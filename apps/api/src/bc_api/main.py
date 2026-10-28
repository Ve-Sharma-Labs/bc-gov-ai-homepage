import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from bc_api.agents import binding_for_request, route_journey
from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.controls import SharedControls
from bc_api.dialogue import dialogue_reply
from bc_api.errors import ApiError, unavailable
from bc_api.foundry import FoundryRuntime, configure_safe_logging
from bc_api.input import RUN_ID, parse_options, validate_run
from bc_api.models import Capabilities, Catalog, Journey, LocationsResponse
from bc_api.security import PreviewControls, RunRegistry, SecurityMiddleware
from bc_api.streaming import RunStreamingResponse, stream_run
from bc_api.telemetry import Telemetry


def create_app(
    settings: Settings | None = None,
    *,
    runtime: FoundryRuntime | None = None,
    control_store: SharedControls | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_safe_logging()
    catalog = CatalogRepository(settings.catalog_path)
    runtime = runtime or FoundryRuntime(settings, catalog)
    controls = PreviewControls(settings)
    runs = RunRegistry(settings)
    shared = control_store or (SharedControls(settings) if settings.redis_endpoint else None)
    telemetry = Telemetry(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        warmup = asyncio.create_task(runtime.warm()) if settings.general_agent_configured else None
        try:
            yield
        finally:
            if warmup is not None:
                warmup.cancel()
                await asyncio.gather(warmup, return_exceptions=True)
            for run in runs.runs.values():
                run.cancellation.set()
            await runtime.close()
            if shared is not None:
                await shared.close()
            await asyncio.to_thread(telemetry.close)

    app = FastAPI(
        title="BC Government assistant pilot",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.catalog = catalog
    app.state.runtime = runtime
    app.state.runs = runs
    app.state.controls = controls
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept"],
        allow_credentials=True,
    )
    app.add_middleware(SecurityMiddleware, settings=settings, controls=controls, shared=shared)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        headers = (
            {"Retry-After": str(exc.retry_after or 60)}
            if exc.status == 429
            else {}
        )
        return JSONResponse(exc.payload(), status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            ApiError(422, "INVALID_REQUEST", "The request parameters are not supported.").payload(),
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            ApiError(
                exc.status_code,
                "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
                "That API route or method is not available.",
            ).payload(),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return JSONResponse(
            ApiError(500, "INTERNAL_ERROR", "The request could not be completed.").payload(),
            status_code=500,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/catalog", response_model=Catalog)
    async def get_catalog() -> Catalog:
        return catalog.get()

    @app.get("/api/journeys/{journey_id}", response_model=Journey)
    async def get_journey(journey_id: str) -> Journey:
        return catalog.journey(journey_id)

    @app.get("/api/locations", response_model=LocationsResponse)
    async def get_locations(
        request: Request,
        service: Annotated[str | None, Query(max_length=80)] = None,
        municipality: Annotated[str | None, Query(max_length=100)] = None,
    ) -> LocationsResponse:
        if set(request.query_params) - {"service", "municipality"}:
            raise ApiError(
                422, "INVALID_REQUEST", "Only service and municipality filters are supported."
            )
        if any(len(request.query_params.getlist(key)) > 1 for key in request.query_params):
            raise ApiError(422, "INVALID_REQUEST", "Supply each location filter only once.")
        return catalog.locations(service, municipality)

    @app.get("/api/capabilities", response_model=Capabilities)
    async def get_capabilities() -> Capabilities:
        catalog.get()
        checks = [runtime.ensure_ready()]
        if settings.general_agent_configured:
            checks.extend([runtime.ensure_general_ready(), runtime.ensure_sources_ready()])
        results = await asyncio.gather(*checks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, ApiError):
                raise result
        pathways_ready = not isinstance(results[0], ApiError)
        general_ready = settings.general_agent_configured and not isinstance(results[1], ApiError)
        sources_ready = pathways_ready or (
            settings.general_agent_configured and not isinstance(results[2], ApiError)
        )
        connected = pathways_ready or general_ready
        return Capabilities(
            mode="foundry" if connected else "guided",
            ai_configured=connected,
            general_chat_configured=general_ready,
            retrieval_ready=sources_ready,
            message=(
                "Verified Foundry chat is connected. Answers require available reviewed evidence. "
                "Guided pathways are optional; live web research and transactions are disabled."
                if connected
                else "Curated guided plans are available. AI answers are not connected. "
                "Live web research and transactions are disabled."
            ),
            journeys=runtime.journey_availability() if connected else {},
        )

    @app.post("/api/agent")
    async def run_agent(request: Request):
        dispatched_at = time.monotonic()
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise ApiError(415, "CONTENT_TYPE", "Send a JSON AG-UI request.")
        try:
            raw = await request.json()
        except ValueError, UnicodeDecodeError, json.JSONDecodeError:
            raise ApiError(422, "INVALID_JSON", "The request is not valid JSON.") from None
        data = validate_run(raw, settings)
        options = parse_options(data.forwarded_props)
        if options.research_requested:
            raise ApiError(
                503,
                "WEBIQ_DISABLED",
                "Live public-web research is not enabled. "
                "Use the approved sources or official service.",
            )
        reply = dialogue_reply(data.messages[-1].content) if options.version == 2 else None
        if reply is None and options.mode != "general" and not settings.foundry_configured:
            raise unavailable()
        catalog.get()
        journey_id = route_journey(data)
        if reply is None:
            binding_for_request(settings, data)
        if shared is not None:
            run = await shared.reserve(
                data.run_id, data.thread_id, request.state.session.token, model_work=reply is None
            )
            runs.runs = {
                key: value for key, value in runs.runs.items() if value.status == "running"
            }
            runs.runs[run.run_id] = run
        else:
            run = runs.reserve(data.run_id, data.thread_id, request.state.session.token)
        run.created = dispatched_at
        run.phase_times["admitted"] = time.monotonic()
        try:
            if reply is None and options.version == 1:
                run.phase_times["readiness_started"] = time.monotonic()
                async with asyncio.timeout(settings.api_upstream_timeout_seconds):
                    await runtime.ensure_ready(journey_id)
                run.phase_times["readiness_completed"] = time.monotonic()
            if shared is not None and await shared.cancellation_requested(run.run_id):
                run.cancellation.set()
            if run.cancellation.is_set():
                raise ApiError(409, "CANCELLED", "The response was stopped.")
        except TimeoutError:
            run.status = "failed"
            if run.finish is not None:
                await run.finish("not-started", 0)
                run.finalized = True
            raise ApiError(504, "UPSTREAM_TIMEOUT", "The AI connection check timed out.") from None
        except BaseException:
            run.status = "cancelled" if run.cancellation.is_set() else "failed"
            if run.finish is not None:
                try:
                    await run.finish("not-started", 0)
                    run.finalized = True
                except ApiError as exc:
                    logging.getLogger("bc_api.controls").warning(
                        "Admission cleanup failed: %s", exc.code
                    )
            raise
        return RunStreamingResponse(
            stream_run(data, run, runtime, catalog, settings, telemetry=telemetry, reply=reply),
            run,
        )

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request):
        if not RUN_ID.fullmatch(run_id):
            raise ApiError(422, "INVALID_ID", "Provide a valid run identifier.")
        if shared is not None:
            status = await shared.cancel(run_id, request.state.session.token)
            local = runs.runs.get(run_id)
            if local is not None:
                local.cancellation.set()
            return JSONResponse(
                {"runId": run_id, "status": status},
                status_code=200 if status == "cancelled" else 202,
            )
        run = runs.cancel(run_id, request.state.session.token)
        return JSONResponse(
            {
                "runId": run.run_id,
                "status": "cancelled" if run.status == "cancelled" else "cancelling",
            },
            status_code=200 if run.status == "cancelled" else 202,
        )

    return app


app = create_app()
