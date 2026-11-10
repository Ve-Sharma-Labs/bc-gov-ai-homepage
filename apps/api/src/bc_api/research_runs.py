"""Owned optional runs with independent evidence, metering and presentation."""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx
from ag_ui.core import CustomEvent, RunErrorEvent, RunFinishedEvent, RunStartedEvent
from ag_ui.encoder import EventEncoder
from anyio import CancelScope
from pydantic import ValidationError

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.controls import SharedControls
from bc_api.errors import ApiError
from bc_api.foundry import FoundryRuntime, create_credential
from bc_api.foundry_iq import FoundryIQ
from bc_api.research import require_research, research_query
from bc_api.research_contract import ResearchDescriptor, ResearchRequest, ResearchResult
from bc_api.research_output import verify_research_output
from bc_api.security import Run, RunRegistry
from bc_api.telemetry import Telemetry
from bc_api.webiq import WebIQ


class ResearchService:
    def __init__(
        self,
        settings: Settings,
        catalog: CatalogRepository,
        runtime: FoundryRuntime,
        runs: RunRegistry,
        shared: SharedControls | None,
        telemetry: Telemetry,
    ):
        self.settings, self.catalog, self.runtime = settings, catalog, runtime
        self.runs, self.shared, self.telemetry = runs, shared, telemetry

    async def authorize(
        self,
        request: ResearchRequest,
        owner: str,
        page: str,
    ) -> ResearchDescriptor:
        require_research(self.settings, request.action)
        raw = (
            await self.shared.research_scope(request.parent_run_id, owner, page)
            if self.shared
            else self.runs.research_scope(request.parent_run_id, owner, page)
        )
        try:
            scope = ResearchDescriptor.model_validate_json(raw)
        except ValidationError:
            raise ApiError(
                409, "RESEARCH_EXPIRED", "This research action is no longer available."
            ) from None
        if (
            scope.page_hash != page
            or scope.thread_id != request.thread_id
            or scope.parent_message_id != request.parent_message_id
            or scope.expires_at <= datetime.now(UTC)
        ):
            raise ApiError(409, "RESEARCH_EXPIRED", "Open research from the current answer.")
        expected = {
            source_id
            for topic in scope.topics
            for source_id in self.catalog.journey(topic).source_ids
        }
        available = {
            source.id
            for source in self.catalog.get().sources
            if source.status in ("available", "limited")
        }
        if not set(scope.source_ids) <= expected & available:
            raise ApiError(409, "RESEARCH_SCOPE_CHANGED", "Approved source availability changed.")
        return scope

    async def reserve(self, request: ResearchRequest, owner: str, page: str) -> Run:
        await self.authorize(request, owner, page)
        if self.shared:
            run = await self.shared.reserve(
                request.run_id,
                request.thread_id,
                owner,
                research_action=request.action,
            )
            self.runs.runs = {
                key: value for key, value in self.runs.runs.items() if value.status == "running"
            }
            self.runs.runs[run.run_id] = run
        else:
            run = self.runs.reserve(
                request.run_id,
                request.thread_id,
                owner,
                research_action=request.action,
            )
        return run

    async def revoke(self, owner: str, page: str) -> None:
        if self.shared:
            await self.shared.revoke_research_page(owner, page)
        else:
            self.runs.revoke_research_page(owner, page)

    async def collect(
        self,
        request: ResearchRequest,
        owner: str,
        page: str,
        run: Run,
        progress: asyncio.Queue[CustomEvent],
    ) -> ResearchResult:
        descriptor = await self.authorize(request, owner, page)

        async def authorize() -> None:
            if run.cancellation.is_set():
                raise ApiError(499, "CANCELLED", "Optional research was stopped.")
            await self.authorize(request, owner, page)

        def mark_started() -> None:
            run.research_started = True

        evidence = []
        try:
            async with create_credential(self.settings) as credential:
                async with httpx.AsyncClient(
                    timeout=self.settings.api_upstream_timeout_seconds,
                    follow_redirects=False,
                ) as client:
                    provider = (
                        FoundryIQ(self.settings, self.catalog, credential, client)
                        if request.action == "corpus-explore"
                        else WebIQ(self.settings, self.catalog, credential, client)
                    )
                    run.phase_times["retrieval_started"] = time.monotonic()
                    try:
                        evidence = await provider.retrieve(
                            descriptor,
                            request.geography,
                            authorize,
                            mark_started,
                        )
                    finally:
                        run.research_attempts = provider.attempts
                        if isinstance(provider, FoundryIQ):
                            run.research_reasoning_units = provider.reasoning_units
                            run.research_planning_tokens = provider.planning_tokens
                    run.research_sources = len(evidence)
                    run.phase_times["retrieval_completed"] = time.monotonic()
            await progress.put(
                CustomEvent(
                    name="bc.research.progress",
                    value={"version": 1, "phase": "summarizing"},
                )
            )
            text, tokens = await self.runtime.summarize_research(
                research_query(descriptor, request.geography),
                evidence,
                authorize,
                mark_started,
            )
            run.usage_tokens = tokens
            run.usage_valid = tokens is not None
            references = verify_research_output(text, evidence)
            await authorize()
            return ResearchResult(
                action=request.action,
                run_id=run.run_id,
                parent_run_id=request.parent_run_id,
                parent_message_id=request.parent_message_id,
                text=text,
                citations=references,
                notice=(
                    "Foundry IQ preview. Only existing approved indexed sources were searched; "
                    "coverage may be incomplete. The original answer has not changed."
                    if request.action == "corpus-explore"
                    else "Public-web research, not live verification or reviewed index evidence. "
                    "Crawl and publisher dates may be unknown. The original answer has not changed."
                ),
            )
        finally:
            evidence.clear()

    async def stream(
        self,
        request: ResearchRequest,
        owner: str,
        page: str,
        run: Run,
    ) -> AsyncGenerator[str]:
        encoder = EventEncoder(accept="text/event-stream")
        progress: asyncio.Queue[CustomEvent] = asyncio.Queue(maxsize=1)
        producer = asyncio.create_task(self.collect(request, owner, page, run, progress))
        cancelled = asyncio.create_task(run.cancellation.wait())
        monitor = asyncio.create_task(run.watch()) if run.watch is not None else None
        pending = asyncio.create_task(progress.get())
        try:
            yield encoder.encode(RunStartedEvent(run_id=run.run_id, thread_id=run.thread_id))
            yield encoder.encode(
                CustomEvent(
                    name="bc.research.progress",
                    value={"version": 1, "phase": "retrieving"},
                )
            )
            async with asyncio.timeout(self.settings.api_run_timeout_seconds):
                while True:
                    done, _ = await asyncio.wait(
                        {producer, cancelled, pending},
                        timeout=10,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancelled in done:
                        raise run.control_failure or ApiError(
                            499, "CANCELLED", "Research was stopped."
                        )
                    if producer in done:
                        result = producer.result()
                        if run.finish is not None:
                            status = await run.finish("finished", run.usage_tokens)
                            run.finalized = True
                            if status != "finished":
                                raise ApiError(499, "CANCELLED", "Research was stopped.")
                        run.status = "finished"
                        run.first_content_at = time.monotonic()
                        yield encoder.encode(
                            CustomEvent(
                                name="bc.research.result",
                                value=result.model_dump(mode="json", by_alias=True),
                            )
                        )
                        yield encoder.encode(
                            RunFinishedEvent(run_id=run.run_id, thread_id=run.thread_id)
                        )
                        return
                    if pending in done:
                        yield encoder.encode(pending.result())
                        pending = asyncio.create_task(progress.get())
                    if not done:
                        yield ": keepalive\n\n"
        except ApiError as exc:
            run.status = "cancelled" if exc.code == "CANCELLED" else "failed"
            yield encoder.encode(RunErrorEvent(code=exc.code, message=exc.message))
        except TimeoutError:
            run.status = "failed"
            yield encoder.encode(
                RunErrorEvent(
                    code="RESEARCH_TIMEOUT",
                    message="Optional research timed out. Your answer is unchanged.",
                )
            )
        except asyncio.CancelledError:
            run.status = "cancelled"
            run.cancellation.set()
            raise
        except Exception as exc:
            run.status = "failed"
            logging.getLogger("bc_api.research").warning("Research failed: %s", type(exc).__name__)
            yield encoder.encode(
                RunErrorEvent(
                    code="RESEARCH_UNAVAILABLE",
                    message="Optional research is unavailable. Your original answer is unchanged.",
                )
            )
        finally:
            with CancelScope(shield=True):
                for task in (producer, cancelled, pending, monitor):
                    if task is None:
                        continue
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        try:
                            await task
                        except Exception as exc:
                            logging.getLogger("bc_api.research").warning(
                                "Research task closed: %s", type(exc).__name__
                            )
                if run.status == "running":
                    run.status = "cancelled"
                if run.finish is not None and not run.finalized:
                    await run.finish(
                        run.status if run.research_started else "not-started",
                        None,
                    )
                    run.finalized = True
                self.telemetry.finish(run)
