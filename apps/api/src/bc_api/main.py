import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from bc_api.agents import binding_for_request, route_journey
from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.context_audit import (
    ContextAuditTrail,
    InMemoryContextAuditRepository,
    RedisContextAuditRepository,
)
from bc_api.context_sessions import (
    CONTEXT_COOKIE,
    CONTEXT_PAGE_HEADER,
    InMemoryContextSessionRepository,
    RedisContextSessionRepository,
)
from bc_api.context_tools import ContextAgentService, ContextRunPlan, ContextRunTracker
from bc_api.controls import SharedControls
from bc_api.conversation import CONVERSATION_PAGE_HEADER, ConversationService, StoredConversation
from bc_api.conversation_contract import ConversationControlResponse, ConversationSummary
from bc_api.demo_personas import DemoPersonaRepository
from bc_api.dialogue import dialogue_reply
from bc_api.discovery import DiscoveryService
from bc_api.discovery_store import DISCOVERY_PAGE_HEADER, DiscoveryStore, PageStateStore
from bc_api.errors import ApiError, unavailable
from bc_api.foundry import FoundryRuntime, configure_safe_logging
from bc_api.input import RUN_ID, parse_options, validate_run
from bc_api.models import (
    Capabilities,
    Catalog,
    ConsentReceipt,
    ContextSummary,
    DemoPersonaSummary,
    DiscoverySummary,
    Journey,
    LocationsResponse,
)
from bc_api.research import page_hash, research_capabilities
from bc_api.research_contract import RESEARCH_PAGE_HEADER, ResearchRequest
from bc_api.research_runs import ResearchService
from bc_api.security import PreviewControls, RunRegistry, SecurityMiddleware
from bc_api.streaming import RunStreamingResponse, stream_run
from bc_api.synthetic_context import (
    ConsentChangeRequest,
    DemoSessionRequest,
    DemoSessionResponse,
    SyntheticContextService,
    clear_context_cookie,
    set_context_cookie,
)
from bc_api.task_assistance import ConversationControl
from bc_api.telemetry import Telemetry


async def monitor_sources(runtime: FoundryRuntime, telemetry: Telemetry) -> None:
    while True:
        try:
            await runtime.ensure_sources_ready()
        except ApiError as exc:
            logging.getLogger("bc_api.operations").warning("Source check failed: %s", exc.code)
        telemetry.sources(runtime.source_health)
        await asyncio.sleep(300)


def create_app(
    settings: Settings | None = None,
    *,
    runtime: FoundryRuntime | None = None,
    control_store: SharedControls | None = None,
    context_service: SyntheticContextService | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_safe_logging()
    catalog = CatalogRepository(settings.catalog_path)
    controls = PreviewControls(settings)
    runs = RunRegistry(settings)
    shared = control_store or (SharedControls(settings) if settings.redis_endpoint else None)
    if context_service is None:
        context_sessions = (
            RedisContextSessionRepository(
                shared.client,
                shared.prefix,
                settings.api_max_sessions,
            )
            if shared is not None
            else InMemoryContextSessionRepository(settings.api_max_sessions)
        )
        context_audit = ContextAuditTrail(
            RedisContextAuditRepository(
                shared.client,
                shared.prefix,
                settings.synthetic_context_audit_max_events,
                settings.synthetic_context_audit_max_bytes,
            )
            if shared is not None
            else InMemoryContextAuditRepository(
                settings.synthetic_context_audit_max_events,
                settings.synthetic_context_audit_max_bytes,
            )
        )
        context_service = SyntheticContextService(
            settings,
            DemoPersonaRepository(),
            context_sessions,
            audit=context_audit,
        )
    context_tracker = ContextRunTracker(context_service.invalidation_hook)
    context_service.invalidation_hook = context_tracker
    context_agent = ContextAgentService(catalog, context_service)
    discovery = DiscoveryService(
        settings,
        catalog,
        DiscoveryStore(
            settings.api_max_sessions,
            redis=shared.client if shared is not None else None,
            prefix=shared.prefix if shared is not None else settings.api_control_namespace,
            ttl_seconds=settings.conversation_context_ttl_seconds,
        ),
    )
    conversation = ConversationService(
        settings,
        catalog,
        PageStateStore(
            settings.api_max_sessions,
            state_type=StoredConversation,
            namespace="conversation",
            redis=shared.client if shared is not None else None,
            prefix=shared.prefix if shared is not None else settings.api_control_namespace,
            ttl_seconds=settings.conversation_context_ttl_seconds,
        ),
    )
    runtime = runtime or FoundryRuntime(settings, catalog)
    runtime.context_agent = context_agent
    telemetry = Telemetry(settings)
    research = ResearchService(settings, catalog, runtime, runs, shared, telemetry)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        warmup = (
            asyncio.create_task(runtime.warm())
            if settings.general_agent_configured
            or settings.contextual_agent_configured
            or settings.conversation_agent_configured
            else None
        )
        source_monitor = (
            asyncio.create_task(monitor_sources(runtime, telemetry))
            if settings.api_metrics_enabled and settings.search_configured
            else None
        )
        try:
            yield
        finally:
            maintenance = [task for task in (warmup, source_monitor) if task is not None]
            for task in maintenance:
                task.cancel()
            await asyncio.gather(*maintenance, return_exceptions=True)
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
    app.state.context_service = context_service
    app.state.context_audit = context_service.audit
    app.state.context_agent = context_agent
    app.state.context_tracker = context_tracker
    app.state.discovery = discovery
    app.state.conversation = conversation
    app.state.research = research
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Content-Type",
            "Accept",
            CONTEXT_PAGE_HEADER,
            DISCOVERY_PAGE_HEADER,
            CONVERSATION_PAGE_HEADER,
            "X-BC-Client-Version",
            "X-BC-Evaluation-Scope",
            RESEARCH_PAGE_HEADER,
        ],
        allow_credentials=True,
    )
    app.add_middleware(SecurityMiddleware, settings=settings, controls=controls, shared=shared)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        headers = {"Retry-After": str(exc.retry_after or 60)} if exc.status == 429 else {}
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
    async def get_capabilities(request: Request) -> Capabilities:
        catalog.get()
        grounded_client = (
            request.headers.get("x-bc-client-version") == "6"
            and settings.grounded_conversation_enabled
        )
        labels = ["pathways"]
        checks = [runtime.ensure_ready()]
        if settings.general_agent_configured:
            labels.append("general")
            checks.append(runtime.ensure_general_ready())
        if settings.contextual_agent_configured:
            labels.append("contextual")
            checks.append(runtime.ensure_contextual_ready())
        if settings.conversation_agent_configured:
            labels.append("conversation")
            checks.append(runtime.ensure_conversation_ready())
        if grounded_client:
            labels.append("grounded")
            checks.append(runtime.ensure_grounded_ready())
        if (
            settings.search_configured
            or settings.general_agent_configured
            or settings.contextual_agent_configured
            or (grounded_client and settings.grounded_agents_configured)
        ):
            labels.append("sources")
            checks.append(
                runtime.ensure_grounded_sources_ready()
                if grounded_client and settings.local_evidence_evaluation_enabled
                else runtime.ensure_sources_ready()
            )
        results = await asyncio.gather(*checks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, ApiError):
                raise result
        outcomes = dict(zip(labels, results, strict=True))
        pathways_ready = not isinstance(outcomes["pathways"], ApiError)
        general_ready = settings.general_agent_configured and not isinstance(
            outcomes.get("general"), ApiError
        )
        sources_ready = "sources" in outcomes and not isinstance(outcomes["sources"], ApiError)
        contextual_ready = (
            settings.contextual_agent_configured
            and not isinstance(outcomes.get("contextual"), ApiError)
            and sources_ready
        )
        connected = pathways_ready or general_ready or contextual_ready
        conversation_ready = settings.conversation_agent_configured and not isinstance(
            outcomes.get("conversation"), ApiError
        )
        if grounded_client:
            conversation_ready = settings.grounded_agents_configured and not isinstance(
                outcomes.get("grounded"), ApiError
            )
        connected = connected or conversation_ready
        if grounded_client:
            connected = conversation_ready
        return Capabilities(
            mode="foundry" if connected else "guided",
            ai_configured=connected,
            general_chat_configured=conversation_ready if grounded_client else general_ready,
            retrieval_ready=sources_ready,
            source_health=runtime.source_health,
            research=research_capabilities(settings) if settings.research_requested else None,
            web_iq_enabled=research_capabilities(settings).web_iq.available,
            message=(
                "Standard answers use approved sources. Optional research is separately gated "
                "and never runs automatically. Transactions remain disabled."
                if settings.research_requested
                else "Local non-commercial evaluation. Named licensed sources and dated snapshots "
                "support the starter flows; runtime checks are not human publication approval. "
                "Public/commercial redistribution and transactions are disabled."
                if settings.local_evidence_evaluation_enabled
                else "Verified Foundry chat is connected. "
                "Answers require available reviewed evidence. "
                "Guided pathways and synthetic context remain separately scoped; "
                "live web research and transactions are disabled."
                if connected and sources_ready
                else "AI assistance is connected. Detailed source answers are currently limited; "
                "reviewed preparation and official next steps remain available. "
                "Live web research and transactions are disabled."
                if connected
                else "Curated guided plans are available. AI answers are not connected. "
                "Live web research and transactions are disabled."
            ),
            journeys=runtime.journey_availability() if connected else {},
            synthetic_context_available=context_service.available(),
            discovery_available=settings.conversation_discovery_enabled,
            conversation_available=settings.ai_conversation_enabled,
            conversation_agent_ready=conversation_ready,
            task_assistance_available=settings.ai_conversation_enabled
            and settings.task_assistance_enabled,
            local_evidence_evaluation=settings.local_evidence_evaluation_enabled,
            request_versions=[1, 2, 3]
            + ([4] if settings.conversation_discovery_enabled else [])
            + ([5] if settings.ai_conversation_enabled else [])
            + ([6] if grounded_client else []),
        )

    @app.get("/api/conversation", response_model=ConversationSummary | None)
    async def get_conversation(request: Request) -> ConversationSummary | None:
        reject_context_query(request)
        return await conversation.summary(
            request.state.session.token, request.headers.get(CONVERSATION_PAGE_HEADER)
        )

    @app.delete("/api/conversation", status_code=204)
    async def clear_conversation(request: Request) -> None:
        reject_context_query(request)
        await conversation.clear(
            request.state.session.token, request.headers.get(CONVERSATION_PAGE_HEADER)
        )

    @app.post("/api/conversation/control", response_model=ConversationControlResponse)
    async def conversation_control(
        data: ConversationControl, request: Request
    ) -> ConversationControlResponse:
        reject_context_query(request)
        return await conversation.control(
            request.state.session.token, request.headers.get(CONVERSATION_PAGE_HEADER), data
        )

    @app.get("/api/conversation/task", response_model=ConversationControlResponse | None)
    async def conversation_task(request: Request) -> ConversationControlResponse | None:
        reject_context_query(request)
        return await conversation.control_snapshot(
            request.state.session.token, request.headers.get(CONVERSATION_PAGE_HEADER)
        )

    @app.get("/api/discovery", response_model=DiscoverySummary | None)
    async def get_discovery(request: Request) -> DiscoverySummary | None:
        reject_context_query(request)
        return await discovery.summary(
            request.state.session.token, request.headers.get(DISCOVERY_PAGE_HEADER)
        )

    @app.delete("/api/discovery", status_code=204)
    async def clear_discovery(request: Request) -> None:
        reject_context_query(request)
        await discovery.clear(
            request.state.session.token, request.headers.get(DISCOVERY_PAGE_HEADER)
        )

    def reject_context_query(request: Request) -> None:
        if request.query_params:
            raise ApiError(
                422,
                "INVALID_REQUEST",
                "Synthetic context routes do not accept query parameters.",
            )

    @app.get("/api/demo/personas", response_model=list[DemoPersonaSummary])
    async def get_demo_personas(request: Request) -> list[DemoPersonaSummary]:
        reject_context_query(request)
        return context_service.public_personas()

    @app.post(
        "/api/demo/session",
        response_model=DemoSessionResponse,
        status_code=201,
    )
    async def create_demo_session(
        data: DemoSessionRequest,
        request: Request,
        response: Response,
    ) -> DemoSessionResponse:
        reject_context_query(request)
        result, token = await context_service.create_session(
            request.state.session.token,
            request.headers.get(CONTEXT_PAGE_HEADER),
            request.cookies.get(CONTEXT_COOKIE),
            data.persona_id,
        )
        set_context_cookie(response, token, settings)
        return result

    @app.delete("/api/demo/session", status_code=204)
    async def delete_demo_session(request: Request, response: Response) -> None:
        reject_context_query(request)
        await context_service.clear_session(
            request.state.session.token,
            request.headers.get(CONTEXT_PAGE_HEADER),
            request.cookies.get(CONTEXT_COOKIE),
        )
        clear_context_cookie(response, settings)

    @app.post("/api/context/consents", response_model=ConsentReceipt)
    async def change_context_consent(
        data: ConsentChangeRequest,
        request: Request,
    ) -> ConsentReceipt:
        reject_context_query(request)
        return await context_service.change_consent(
            request.state.session.token,
            request.headers.get(CONTEXT_PAGE_HEADER),
            request.cookies.get(CONTEXT_COOKIE),
            data,
        )

    @app.get("/api/context/summary", response_model=ContextSummary)
    async def get_context_summary(request: Request) -> ContextSummary:
        reject_context_query(request)
        return await context_service.summary(
            request.state.session.token,
            request.headers.get(CONTEXT_PAGE_HEADER),
            request.cookies.get(CONTEXT_COOKIE),
        )

    @app.post("/api/research")
    async def run_research(data: ResearchRequest, request: Request):
        page = page_hash(request.headers.get(RESEARCH_PAGE_HEADER))
        owner = request.state.session.token
        run = await research.reserve(data, owner, page)
        return RunStreamingResponse(research.stream(data, owner, page, run), run)

    @app.delete("/api/research")
    async def reset_research(request: Request):
        await research.revoke(
            request.state.session.token,
            page_hash(request.headers.get(RESEARCH_PAGE_HEADER)),
        )
        return Response(status_code=204)

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
        research_page = (
            page_hash(request.headers.get(RESEARCH_PAGE_HEADER))
            if settings.research_requested and request.headers.get(RESEARCH_PAGE_HEADER)
            else ""
        )
        discovery_plan = (
            await discovery.prepare(
                request.state.session.token, request.headers.get(DISCOVERY_PAGE_HEADER), data
            )
            if options.version == 4
            else None
        )
        conversation_plan = (
            await conversation.prepare(
                request.state.session.token, request.headers.get(CONVERSATION_PAGE_HEADER), data
            )
            if options.version in (5, 6)
            else None
        )
        context_plan: ContextRunPlan | None = None
        if options.mode == "contextual-demo":
            context_plan = await context_agent.authorize(
                request.state.session.token,
                request.headers.get(CONTEXT_PAGE_HEADER),
                request.cookies.get(CONTEXT_COOKIE),
                run_id=data.run_id,
                question=(
                    data.messages[-1].content if settings.conversation_discovery_enabled else None
                ),
            )
        if options.research_requested:
            raise ApiError(
                503,
                "WEBIQ_DISABLED",
                "Live public-web research is not enabled. "
                "Use the approved sources or official service.",
            )
        reply = (
            discovery_plan.reply
            if discovery_plan is not None
            else dialogue_reply(data.messages[-1].content)
            if options.version == 2
            else None
        )
        if (
            reply is None
            and options.mode not in ("general", "contextual-demo")
            and not settings.foundry_configured
        ):
            raise unavailable()
        catalog.get()
        journey_id = route_journey(
            data,
            contextual_enabled=context_plan is not None,
        )
        model_work = reply is None and (conversation_plan is None or conversation_plan.needs_model)
        if model_work:
            binding_for_request(settings, data)
        if shared is not None:
            run = await shared.reserve(
                data.run_id, data.thread_id, request.state.session.token, model_work=model_work
            )
            runs.runs = {
                key: value for key, value in runs.runs.items() if value.status == "running"
            }
            runs.runs[run.run_id] = run
        else:
            run = runs.reserve(data.run_id, data.thread_id, request.state.session.token)
        run.research_page_hash = research_page
        if context_plan is not None:
            run.trace_ref = context_plan.authorization.trace_ref
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
            stream_run(
                data,
                run,
                runtime,
                catalog,
                settings,
                telemetry=telemetry,
                reply=reply,
                context_plan=context_plan,
                context_agent=context_agent,
                context_tracker=context_tracker,
                discovery_plan=discovery_plan,
                discovery_service=discovery if discovery_plan is not None else None,
                conversation_plan=conversation_plan,
                conversation_service=conversation if conversation_plan is not None else None,
            ),
            run,
            audit_finalize=(
                (
                    lambda status, error_code: context_agent.record_terminal(
                        context_plan,
                        status,
                        error_code,
                    )
                )
                if context_plan is not None
                else None
            ),
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
