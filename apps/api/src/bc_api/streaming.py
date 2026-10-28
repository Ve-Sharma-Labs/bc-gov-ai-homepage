import asyncio
import contextlib
import inspect
import logging
import time
from collections.abc import AsyncGenerator, Iterator

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder
from anyio import CancelScope, move_on_after
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.dialogue import ApplicationReply
from bc_api.errors import ApiError
from bc_api.foundry import FoundryRuntime, local_credential_timeout_error
from bc_api.input import parse_options
from bc_api.output import OutputGate
from bc_api.protocol import TOOL_PHASES, progress_event, response_context_event
from bc_api.retrieval import EvidenceLedger
from bc_api.security import Run
from bc_api.telemetry import Telemetry
from bc_api.tools import ToolContext


class RunStreamingResponse(StreamingResponse):
    def __init__(self, events: AsyncGenerator[str], run: Run):
        super().__init__(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
        self.events = events
        self.run = run

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with CancelScope(shield=True):
                if self.run.status == "running":
                    self.run.cancellation.set()
                    self.run.status = "cancelled"
                never_started = inspect.getasyncgenstate(self.events) == inspect.AGEN_CREATED
                try:
                    await self.events.aclose()
                finally:
                    if self.run.finish is not None and not self.run.finalized:
                        try:
                            await self.run.finish(
                                "not-started" if never_started else self.run.status,
                                0 if never_started else None,
                            )
                            self.run.finalized = True
                        except ApiError as exc:
                            logging.getLogger("bc_api.controls").warning(
                                "Response cleanup failed: %s", exc.code
                            )


async def stream_run(
    request: RunAgentInput,
    run: Run,
    runtime: FoundryRuntime,
    catalog: CatalogRepository,
    settings: Settings,
    *,
    telemetry: Telemetry | None = None,
    reply: ApplicationReply | None = None,
) -> AsyncGenerator[str]:
    encoder = EventEncoder(accept="text/event-stream")
    context = ToolContext(catalog, EvidenceLedger())
    options = parse_options(request.forwarded_props)
    gate = OutputGate(catalog, context.ledger, allow_clarification=options.mode == "general")
    queue: asyncio.Queue[BaseEvent | ApplicationReply | Exception | None] = asyncio.Queue(
        maxsize=16
    )
    response_sent = False
    application_replied = False

    def present(events: list[BaseEvent]) -> Iterator[BaseEvent]:
        nonlocal response_sent
        for validated in events:
            if (
                validated.type in ("TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT")
                and not response_sent
            ):
                response_sent = True
                run.response_kind = gate.response_kind
                run.response_origin = "model"
                if options.version == 2:
                    yield response_context_event(gate.response_kind, "model")
            if validated.type == "TEXT_MESSAGE_CONTENT":
                now = time.monotonic()
                if run.first_response_at is None:
                    run.first_response_at = now
                if gate.response_kind == "grounded" and run.first_content_at is None:
                    run.first_content_at = now
            yield validated

    async def produce() -> None:
        # Keep the entire SDK iterator in one task: its tracing/context tokens
        # cannot be entered in one per-chunk task and reset in another.
        try:
            if reply is not None:
                context.model_work_started = False
                await queue.put(RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id))
                await queue.put(reply)
                await queue.put(
                    RunFinishedEvent(run_id=request.run_id, thread_id=request.thread_id)
                )
                await queue.put(None)
                return
            async with contextlib.aclosing(runtime.events(request, context)) as source:
                async for event in source:
                    await queue.put(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await queue.put(exc)
        else:
            await queue.put(None)

    producer = asyncio.create_task(produce())
    pending: asyncio.Task[BaseEvent | ApplicationReply | Exception | None] | None = None
    cancelled = asyncio.create_task(run.cancellation.wait())
    monitor = asyncio.create_task(run.watch()) if run.watch is not None else None
    deadline = time.monotonic() + settings.api_run_timeout_seconds
    try:
        while True:
            if run.control_failure is not None:
                raise run.control_failure
            if run.cancellation.is_set():
                raise ApiError(499, "CANCELLED", "The response was stopped.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ApiError(504, "RUN_TIMEOUT", "The response timed out. Please try again.")
            if pending is None:
                pending = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {pending, cancelled},
                timeout=min(10, remaining),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done:
                if run.control_failure is not None:
                    raise run.control_failure
                raise ApiError(499, "CANCELLED", "The response was stopped.")
            if not done:
                yield ": keepalive\n\n"
                continue
            event = pending.result()
            pending = None
            if context.failure is not None:
                raise context.failure
            if isinstance(event, Exception):
                raise event
            if event is None:
                raise ApiError(
                    502, "STREAM_INCOMPLETE", "The AI response ended unexpectedly."
                ) from None
            if isinstance(event, ApplicationReply):
                if response_sent or context.model_work_started is True:
                    raise ApiError(502, "OUTPUT_INVALID", "Mixed response authority was withheld.")
                application_replied = True
                response_sent = True
                run.response_kind = event.kind
                run.response_origin = "application"
                message_id = f"{run.run_id}-reply"
                yield encoder.encode(response_context_event(event.kind, "application"))
                yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="assistant"))
                run.first_response_at = time.monotonic()
                yield encoder.encode(
                    TextMessageContentEvent(message_id=message_id, delta=event.text)
                )
                yield encoder.encode(TextMessageEndEvent(message_id=message_id))
                continue
            kind = event.type
            if application_replied and kind != "RUN_FINISHED":
                raise ApiError(502, "OUTPUT_INVALID", "Mixed response authority was withheld.")
            if kind in ("RUN_STARTED", "RUN_FINISHED") and (
                event.run_id != run.run_id or event.thread_id != run.thread_id
            ):
                raise ApiError(502, "RUN_ID_MISMATCH", "The AI response did not match this run.")
            if kind == "RUN_ERROR":
                raise ApiError(
                    502, "AGENT_ERROR", "The AI response failed. Please try a guided journey."
                )
            if kind == "RUN_STARTED":
                yield encoder.encode(event)
            elif kind == "CUSTOM" and getattr(event, "name", None) == "status":
                phase = event.value.get("phase") if isinstance(event.value, dict) else None
                yield encoder.encode(progress_event(phase))
            elif kind == "TOOL_CALL_START":
                gate.hold(event)
                yield encoder.encode(progress_event(TOOL_PHASES[event.tool_call_name]))
            elif kind == "RUN_FINISHED":
                if context.failure is not None:
                    raise context.failure
                for validated in present([] if application_replied else gate.finish()):
                    yield encoder.encode(validated)
                if context.model_work_started is False:
                    run.usage_tokens = 0
                if run.finish is not None:
                    status = await run.finish(
                        "finished", run.usage_tokens if run.usage_valid else None
                    )
                    run.finalized = True
                    if status != "finished":
                        raise ApiError(499, "CANCELLED", "The response was stopped.")
                run.status = "finished"
                yield encoder.encode(event)
                return
            else:
                gate.hold(event)
                if kind == "CUSTOM" and getattr(event, "name", None) == "usage":
                    value = event.value
                    total = value.get("total_token_count")
                    subtotal = (value.get("input_token_count") or 0) + (
                        value.get("output_token_count") or 0
                    )
                    if type(total) is int and total > 0 and total >= subtotal:
                        run.usage_tokens = (run.usage_tokens or 0) + total
                    else:
                        run.usage_valid = False
                for validated in present(gate.flush_sections()):
                    yield encoder.encode(validated)
    except ApiError as exc:
        if (
            exc.code == "CRITICAL_CLAIM_UNVERIFIED"
            and response_sent
            and gate.started
            and not application_replied
        ):
            yield encoder.encode(
                CustomEvent(
                    name="bc.warning",
                    value={"version": 1, "code": "DETAILS_WITHHELD"},
                )
            )
            for message_id in sorted(gate.started):
                yield encoder.encode(TextMessageEndEvent(message_id=message_id))
            if run.finish is not None:
                status = await run.finish(
                    "finished", run.usage_tokens if run.usage_valid else None
                )
                run.finalized = True
                if status != "finished":
                    run.status = "cancelled"
                    yield encoder.encode(
                        RunErrorEvent(code="CANCELLED", message="The response was stopped.")
                    )
                    return
            run.status = "finished"
            yield encoder.encode(
                RunFinishedEvent(run_id=request.run_id, thread_id=request.thread_id)
            )
            return
        run.status = "cancelled" if exc.code == "CANCELLED" else "failed"
        yield encoder.encode(RunErrorEvent(code=exc.code, message=exc.message))
    except asyncio.CancelledError:
        run.cancellation.set()
        run.status = "cancelled"
        raise
    except Exception as exc:
        run.status = "failed"
        runtime.ready_until = 0
        runtime.general_ready_until = 0
        mapped = local_credential_timeout_error(settings, exc)
        yield encoder.encode(
            RunErrorEvent(
                code=mapped.code if mapped else "AGENT_UNAVAILABLE",
                message=mapped.message
                if mapped
                else "The AI response is unavailable. Your guided journeys are still available.",
            )
        )
    finally:
        # ASGI disconnects repeatedly cancel awaits; cleanup must finish before returning.
        with CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                    await pending
            producer.cancel()
            with move_on_after(5) as cleanup:
                try:
                    await producer
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logging.getLogger("bc_api.controls").error(
                        "Native stream cleanup failed: %s", type(exc).__name__
                    )
            if cleanup.cancel_called:
                logging.getLogger("bc_api.controls").error("Native stream cleanup timed out")
            cancelled.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancelled
            if monitor is not None:
                monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor
            if run.status == "running":
                run.status = "cancelled" if run.cancellation.is_set() else "failed"
            if run.finish is not None and not run.finalized:
                try:
                    if context.model_work_started is False:
                        await run.finish("not-started", 0)
                    else:
                        await run.finish(run.status, None)
                    run.finalized = True
                except ApiError as exc:
                    logging.getLogger("bc_api.controls").warning("Run cleanup failed: %s", exc.code)
            run.phase_times.update(context.phase_times)
            if telemetry is not None:
                telemetry.finish(run)
