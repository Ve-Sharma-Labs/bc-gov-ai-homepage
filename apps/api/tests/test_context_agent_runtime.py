import asyncio
import io
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from ag_ui.core import (
    CustomEvent,
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bc_api.agents import (
    binding_for_request,
    contextual_agent_definition,
    route_journey,
)
from bc_api.catalog import CatalogRepository
from bc_api.context_sessions import InMemoryContextSessionRepository
from bc_api.context_tools import (
    CONTEXT_TOOL_NAMES,
    FLOW_REQUIRED_SCOPES,
    FLOW_SCOPES,
    ContextAgentService,
    ContextRunPlan,
    ContextToolContext,
    create_context_tools,
)
from bc_api.demo_personas import DemoPersonaRepository
from bc_api.demo_rules import default_demo_catalog_path
from bc_api.errors import ApiError
from bc_api.foundry import FoundryRuntime
from bc_api.main import create_app
from bc_api.models import AgentBinding
from bc_api.output import OutputGate
from bc_api.protocol import ContextArtifactValidator, validate_artifact
from bc_api.retrieval import EvidenceLedger
from bc_api.security import Run
from bc_api.synthetic_context import ConsentChangeRequest, SyntheticContextService
from bc_api.telemetry import Telemetry
from bc_api.tools import function_declarations

ORIGIN = "http://localhost:3000"
NOW = datetime(2026, 11, 6, 3, 0, tzinfo=UTC)
PAGE_TOKEN = "context-runtime-page-00000001"
HEADERS = {"Origin": ORIGIN, "X-BC-Context-Page": PAGE_TOKEN}


def decode_sse(text: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def contextual_settings(settings):
    return settings.model_copy(
        update={
            "content_catalog_path": default_demo_catalog_path(),
            "synthetic_context_enabled": True,
            "synthetic_context_session_ttl_seconds": 300,
            "synthetic_context_consent_ttl_seconds": 180,
            "foundry_project_endpoint": "https://test.services.ai.azure.com/api/projects/test",
            "foundry_contextual_agent": AgentBinding(
                name="test-contextual",
                version="1",
                model_deployment="test-model",
            ),
            "azure_search_endpoint": "https://test.search.windows.net",
            "azure_search_index": "approved-test-index",
        }
    )


def make_context_service(settings) -> SyntheticContextService:
    return SyntheticContextService(
        settings,
        DemoPersonaRepository(),
        InMemoryContextSessionRepository(settings.api_max_sessions),
        clock=lambda: NOW,
    )


async def authorized_plan(
    settings,
    *,
    persona_id: str = "sam-job-loss",
    scopes: list[str] | None = None,
) -> tuple[SyntheticContextService, ContextAgentService, ContextRunPlan, str]:
    service = make_context_service(settings)
    _, token = await service.create_session("owner", PAGE_TOKEN, None, persona_id)
    flow_id = {
        "maya-caregiver": "guardianship-intake",
        "alex-disability-support": "disability-support",
        "sam-job-loss": "job-loss",
    }[persona_id]
    await service.change_consent(
        "owner",
        PAGE_TOKEN,
        token,
        ConsentChangeRequest(
            action="grant",
            scopes=scopes or list(FLOW_SCOPES[flow_id]),
        ),
    )
    agent = ContextAgentService(CatalogRepository(settings.catalog_path), service)
    return service, agent, await agent.authorize("owner", PAGE_TOKEN, token), token


async def test_context_discovery_never_expands_a_fictional_purpose(settings):
    settings = contextual_settings(settings)
    _, agent, _, token = await authorized_plan(settings)
    with pytest.raises(ApiError) as error:
        await agent.authorize(
            "owner", PAGE_TOKEN, token, question="I'm buying a motorcycle next year."
        )
    assert error.value.code == "CONTEXT_PURPOSE_CHANGED"
    plan = await agent.authorize(
        "owner", PAGE_TOKEN, token, question="I lost my job and need help with rent."
    )
    assert plan.authorization.persona_id == "sam-job-loss"


class FixtureContextRuntime(FoundryRuntime):
    def __init__(self, settings, catalog, evidence):
        super().__init__(settings, catalog)
        self.evidence = evidence
        self.received_plan = None

    async def warm(self):
        return None

    async def events(self, request, context, *, context_plan=None):
        assert isinstance(context, ContextToolContext)
        assert context_plan is not None
        self.received_plan = context_plan
        context.model_work_started = True
        context.ledger.add(self.evidence)
        url = self.evidence.evidence[0].reference.url
        yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
        yield TextMessageStartEvent(message_id="context-answer", role="assistant")
        yield TextMessageContentEvent(
            message_id="context-answer",
            delta=(
                "Review the server-owned screening package and confirm every field with a "
                f"qualified person. [Official source]({url})"
            ),
        )
        yield TextMessageEndEvent(message_id="context-answer")
        assert context.coordinator is not None
        await context.coordinator.assert_current(context_plan)
        for event in context.coordinator.artifact_events(context_plan):
            yield event
        yield RunFinishedEvent(run_id=request.run_id, thread_id=request.thread_id)


class SlowContextRuntime(FoundryRuntime):
    def __init__(self, settings, catalog):
        super().__init__(settings, catalog)
        self.started = asyncio.Event()

    async def warm(self):
        return None

    async def events(self, request, context, *, context_plan=None):
        assert context_plan is not None
        context.model_work_started = False
        yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
        yield TextMessageStartEvent(message_id="stale-context", role="assistant")
        yield TextMessageContentEvent(
            message_id="stale-context",
            delta="Employment recently ended.\n\n",
        )
        self.started.set()
        await asyncio.Event().wait()


def select_and_grant(client, persona_id="sam-job-loss"):
    selected = client.post("/api/demo/session", json={"personaId": persona_id})
    assert selected.status_code == 201
    flow_id = {
        "maya-caregiver": "guardianship-intake",
        "alex-disability-support": "disability-support",
        "sam-job-loss": "job-loss",
    }[persona_id]
    granted = client.post(
        "/api/context/consents",
        json={"action": "grant", "scopes": list(FLOW_SCOPES[flow_id])},
    )
    assert granted.status_code == 200


def contextual_request(run_input) -> dict:
    return {
        **run_input,
        "forwardedProps": {"bc": {"version": 3, "mode": "contextual-demo"}},
    }


def test_contextual_routing_requires_feature_session_and_minimum_consent(
    settings,
    run_input,
    evidence,
):
    request = RunAgentInput.model_validate(contextual_request(run_input))
    with pytest.raises(ApiError, match="CONTEXTUAL_DEMO_UNAVAILABLE"):
        route_journey(request)
    assert route_journey(request, contextual_enabled=True) is None

    context_settings = contextual_settings(settings)
    runtime = FixtureContextRuntime(
        context_settings,
        CatalogRepository(context_settings.catalog_path),
        evidence,
    )
    service = make_context_service(context_settings)
    with TestClient(
        create_app(context_settings, runtime=runtime, context_service=service),
        headers=HEADERS,
    ) as client:
        missing_session = client.post("/api/agent", json=contextual_request(run_input))
        assert missing_session.status_code == 401
        assert missing_session.json()["error"]["code"] == "CONTEXT_SESSION_REQUIRED"

        assert (
            client.post(
                "/api/demo/session",
                json={"personaId": "sam-job-loss"},
            ).status_code
            == 201
        )
        missing_consent = client.post("/api/agent", json=contextual_request(run_input))
        assert missing_consent.status_code == 403
        assert missing_consent.json()["error"]["code"] == "CONSENT_REQUIRED"

        partial = client.post(
            "/api/context/consents",
            json={"action": "grant", "scopes": ["employment.read"]},
        )
        assert partial.status_code == 200
        insufficient = client.post("/api/agent", json=contextual_request(run_input))
        assert insufficient.status_code == 403
        assert insufficient.json()["error"]["code"] == "CONSENT_INSUFFICIENT"

        remaining = [scope for scope in FLOW_SCOPES["job-loss"] if scope != "employment.read"]
        assert (
            client.post(
                "/api/context/consents",
                json={"action": "grant", "scopes": remaining},
            ).status_code
            == 200
        )
        response = client.post("/api/agent", json=contextual_request(run_input))
        assert response.status_code == 200
        events = decode_sse(response.text)
        assert events[-1]["type"] == "RUN_FINISHED"
        assert binding_for_request(context_settings, request).name == "test-contextual"
        assert runtime.received_plan.authorization.flow_id == "job-loss"


async def test_context_tools_bind_server_persona_and_deny_cross_persona_or_revoked_state(
    settings,
):
    context_settings = contextual_settings(settings)
    service, agent, plan, token = await authorized_plan(context_settings)
    result = await agent.read_context(
        plan.authorization,
        FLOW_SCOPES["job-loss"],
    )
    payload = result.model_dump_json(by_alias=True)
    assert "recently-ended" in payload
    assert plan.authorization.persona_id not in payload
    assert plan.authorization.consent_id not in payload
    assert plan.authorization.session_ref not in payload
    assert "@" not in payload
    source_query = agent.source_query(plan, "recently-ended material-decrease")
    assert "recently-ended" not in source_query
    assert "material-decrease" not in source_query

    forged = replace(plan.authorization, persona_id="maya-caregiver")
    with pytest.raises(ApiError, match="CONTEXT_CHANGED"):
        await agent.evaluate(forged, "job-loss")
    with pytest.raises(ApiError, match="TOOL_SCOPE_DENIED"):
        await agent.evaluate(plan.authorization, "disability-support")

    await service.change_consent(
        "owner",
        PAGE_TOKEN,
        token,
        ConsentChangeRequest(action="revoke", scopes=["employment.read"]),
    )
    with pytest.raises(ApiError) as revoked:
        await agent.preview(plan.authorization, "job-loss")
    assert revoked.value.code in {"CONSENT_INSUFFICIENT", "CONTEXT_CHANGED"}
    assert "recently-ended" not in revoked.value.message


async def test_context_tool_access_rechecks_consent_expiry(settings):
    context_settings = contextual_settings(settings)
    service, agent, plan, _ = await authorized_plan(context_settings)
    service.clock = lambda: NOW + timedelta(seconds=181)
    with pytest.raises(ApiError, match="CONSENT_REQUIRED"):
        await agent.read_context(
            plan.authorization,
            FLOW_SCOPES["job-loss"],
        )


def test_contextual_agent_definition_is_distinct_strict_and_has_no_action_tool(
    settings,
):
    context_settings = contextual_settings(settings)
    catalog = CatalogRepository(context_settings.catalog_path)
    exported = contextual_agent_definition(
        catalog,
        prefix="test-bc",
        model_deployment="test-model",
    )
    assert exported["mode"] == "contextual-demo"
    assert exported["name"] == "test-bc-contextual-demo"
    declarations = exported["definition"]["tools"]
    assert {item["name"] for item in declarations} == CONTEXT_TOOL_NAMES
    assert all(item["type"] == "function" and item["strict"] is True for item in declarations)
    assert declarations[1]["parameters"]["properties"]["flow_id"]["enum"] == [
        "guardianship-intake",
        "disability-support",
        "job-loss",
    ]
    search = next(item for item in declarations if item["name"] == "search_approved_sources")
    assert search["parameters"]["properties"] == {}
    assert search["parameters"].get("required", []) == []
    assert not any(
        word in item["name"]
        for item in declarations
        for word in ("submit", "sign", "pay", "book", "confirm")
    )

    version = SimpleNamespace(
        name=exported["name"],
        version="1",
        status="active",
        draft=False,
        definition=PromptAgentDefinition(
            model=exported["definition"]["model"],
            instructions=exported["definition"]["instructions"],
            tools=[FunctionTool(**item) for item in declarations],
        ),
    )
    runtime = FoundryRuntime(context_settings, catalog)
    runtime._verify_version(
        version,
        AgentBinding(
            name=exported["name"],
            version="1",
            model_deployment="test-model",
        ),
        mode="contextual-demo",
    )
    altered = json.loads(json.dumps(declarations))
    altered[0]["parameters"]["properties"]["scopes"]["maxItems"] = 99
    version.definition.tools = [FunctionTool(**item) for item in altered]
    with pytest.raises(ApiError, match="AGENT_POLICY_MISMATCH"):
        runtime._verify_version(
            version,
            AgentBinding(
                name=exported["name"],
                version="1",
                model_deployment="test-model",
            ),
            mode="contextual-demo",
        )
    with pytest.raises(ValidationError):
        context_settings.__class__.model_validate(
            {
                **context_settings.model_dump(),
                "foundry_general_agent": {
                    "name": "same-agent",
                    "version": "1",
                    "model_deployment": "test-model",
                },
                "foundry_contextual_agent": {
                    "name": "same-agent",
                    "version": "1",
                    "model_deployment": "test-model",
                },
            }
        )


async def test_contextual_readiness_verifies_only_the_distinct_binding(settings):
    context_settings = contextual_settings(settings)
    catalog = CatalogRepository(context_settings.catalog_path)
    exported = contextual_agent_definition(
        catalog,
        prefix="test",
        model_deployment="test-model",
    )
    binding = context_settings.foundry_contextual_agent
    assert binding is not None
    exported["name"] = binding.name
    version = SimpleNamespace(
        name=binding.name,
        version=binding.version,
        status="active",
        draft=False,
        definition=PromptAgentDefinition(
            model=exported["definition"]["model"],
            instructions=exported["definition"]["instructions"],
            tools=[FunctionTool(**item) for item in exported["definition"]["tools"]],
        ),
    )
    project = SimpleNamespace(agents=SimpleNamespace(get_version=AsyncMock(return_value=version)))
    runtime = FoundryRuntime(
        context_settings,
        catalog,
        project=project,
        search=SimpleNamespace(),
    )
    await runtime.ensure_contextual_ready()
    await runtime.ensure_contextual_ready()
    project.agents.get_version.assert_awaited_once_with(binding.name, binding.version)
    assert runtime.contextual_available
    assert not runtime.general_available
    assert not any(runtime.journey_availability().values())


@pytest.mark.parametrize(
    ("persona_id", "flow_id"),
    [
        ("maya-caregiver", "guardianship-intake"),
        ("alex-disability-support", "disability-support"),
        ("sam-job-loss", "job-loss"),
    ],
)
async def test_previews_and_rules_are_deterministic_server_owned_and_review_only(
    settings,
    persona_id,
    flow_id,
):
    context_settings = contextual_settings(settings)
    _, agent, plan, _ = await authorized_plan(
        context_settings,
        persona_id=persona_id,
    )
    first = await agent.preview(plan.authorization, flow_id)
    second = await agent.preview(plan.authorization, flow_id)
    assert first == second
    assert first.flow_id == flow_id
    assert first.submission_enabled is False
    assert first.requires_human_review is True
    assert all(field.requires_confirmation for field in first.fields)
    assert all(
        (field.source == "missing" and field.value is None and field.source_fact_key is None)
        or (
            field.source in ("synthetic-record", "citizen-answer")
            and field.value is not None
            and field.source_fact_key is not None
        )
        for field in first.fields
    )
    evaluated = await agent.evaluate(plan.authorization, flow_id)
    artifact = plan.artifacts[1]
    assert artifact.kind == "program-matches"
    assert artifact.payload == evaluated.matches
    assert all(match.rule_version == plan.rule_set_version for match in evaluated.matches)


async def test_context_artifact_authority_rejects_reordering_and_model_rule_changes(
    settings,
    evidence,
):
    context_settings = contextual_settings(settings)
    _, _, plan, _ = await authorized_plan(context_settings)
    catalog = CatalogRepository(context_settings.catalog_path)
    validator = ContextArtifactValidator(plan.artifacts)
    for artifact in plan.artifacts:
        validate_artifact(artifact.model_dump(by_alias=True), catalog, validator)
    validator.ensure_complete()

    reordered = ContextArtifactValidator(plan.artifacts)
    with pytest.raises(ApiError, match="OUTPUT_INVALID"):
        validate_artifact(
            plan.artifacts[1].model_dump(by_alias=True),
            catalog,
            reordered,
        )

    forged = plan.artifacts[1].model_dump(by_alias=True)
    forged["payload"][0]["status"] = "already-enrolled"
    changed = ContextArtifactValidator(plan.artifacts)
    validate_artifact(plan.artifacts[0].model_dump(by_alias=True), catalog, changed)
    with pytest.raises(ApiError, match="OUTPUT_INVALID"):
        validate_artifact(forged, catalog, changed)

    ledger = EvidenceLedger()
    ledger.add(evidence)
    gate = OutputGate(
        catalog,
        ledger,
        tool_names=CONTEXT_TOOL_NAMES,
        context_artifacts=plan.artifacts,
    )
    url = evidence.evidence[0].reference.url
    gate.hold(TextMessageStartEvent(message_id="forged-status", role="assistant"))
    gate.hold(
        TextMessageContentEvent(
            message_id="forged-status",
            delta=f"The screening result says already enrolled. [Source]({url})",
        )
    )
    gate.hold(TextMessageEndEvent(message_id="forged-status"))
    for artifact in plan.artifacts:
        gate.hold(
            CustomEvent(
                name="bc.artifact",
                value=artifact.model_dump(by_alias=True),
            )
        )
    with pytest.raises(ApiError, match="RULE_RESULT_MISMATCH"):
        gate.finish()


def test_context_stream_emits_strict_server_artifact_order_and_no_submission_route(
    settings,
    run_input,
    evidence,
):
    context_settings = contextual_settings(settings)
    runtime = FixtureContextRuntime(
        context_settings,
        CatalogRepository(context_settings.catalog_path),
        evidence,
    )
    with TestClient(
        create_app(
            context_settings,
            runtime=runtime,
            context_service=make_context_service(context_settings),
        ),
        headers=HEADERS,
    ) as client:
        select_and_grant(client)
        response = client.post("/api/agent", json=contextual_request(run_input))
        events = decode_sse(response.text)
        artifacts = [
            event["value"]["kind"] for event in events if event.get("name") == "bc.artifact"
        ]
        assert artifacts == [
            "context-summary",
            "program-matches",
            "application-preview",
            "consent-request",
            "audit-receipt",
        ]
        preview = next(
            event["value"]["payload"]
            for event in events
            if event.get("name") == "bc.artifact"
            and event["value"]["kind"] == "application-preview"
        )
        assert preview["submissionEnabled"] is False
        assert preview["requiresHumanReview"] is True
        assert client.post("/api/submit", json={}).status_code == 404


async def test_persona_switch_cancels_an_in_flight_contextual_run(
    settings,
    run_input,
):
    context_settings = contextual_settings(settings)
    catalog = CatalogRepository(context_settings.catalog_path)
    runtime = SlowContextRuntime(context_settings, catalog)
    app = create_app(
        context_settings,
        runtime=runtime,
        context_service=make_context_service(context_settings),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://testserver",
        headers=HEADERS,
    ) as client:
        assert (
            await client.post(
                "/api/demo/session",
                json={"personaId": "sam-job-loss"},
            )
        ).status_code == 201
        assert (
            await client.post(
                "/api/context/consents",
                json={"action": "grant", "scopes": list(FLOW_SCOPES["job-loss"])},
            )
        ).status_code == 200
        pending = asyncio.create_task(client.post("/api/agent", json=contextual_request(run_input)))
        async with asyncio.timeout(5):
            await runtime.started.wait()
            switched = await client.post(
                "/api/demo/session",
                json={"personaId": "maya-caregiver"},
            )
            assert switched.status_code == 201
            response = await pending
        events = decode_sse(response.text)
        assert events[-1]["type"] == "RUN_ERROR"
        assert events[-1]["code"] == "CANCELLED"
        assert "Employment recently ended" not in response.text
        assert app.state.runs.runs[run_input["runId"]].status == "cancelled"


def test_context_values_do_not_enter_telemetry_or_safe_errors(settings):
    context_settings = contextual_settings(settings)
    telemetry = Telemetry(context_settings)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    telemetry.logger.handlers = [handler]
    run = Run("run-context", "thread-context", "owner")
    run.status = "finished"
    run.response_kind = "grounded"
    run.response_origin = "model"
    run.usage_tokens = 12345
    telemetry.finish(run)
    output = stream.getvalue()
    assert "recently-ended" not in output
    assert "material-decrease" not in output
    assert "employment.status" not in output
    assert "context_token" not in output
    assert '"tokens"' not in output
    assert "12345" not in output


def test_anonymous_general_regression_with_context_feature_enabled(
    settings,
    run_input,
):
    context_settings = contextual_settings(settings).model_copy(
        update={
            "foundry_general_agent": None,
            "foundry_contextual_agent": None,
            "foundry_project_endpoint": "",
            "azure_search_endpoint": "",
            "azure_search_index": "",
        }
    )
    app = create_app(
        context_settings,
        context_service=make_context_service(context_settings),
    )
    run_input["messages"][-1]["content"] = "Hi"
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        response = client.post("/api/agent", json=run_input)
        assert response.status_code == 200
        events = decode_sse(response.text)
        assert events[0]["type"] == "RUN_STARTED"
        assert events[-1]["type"] == "RUN_FINISHED"
        assert not any(event.get("name") == "bc.artifact" for event in events)


async def test_context_source_version_mismatch_fails_closed(settings, evidence):
    context_settings = contextual_settings(settings)
    service, agent, plan, token = await authorized_plan(context_settings)
    catalog = CatalogRepository(context_settings.catalog_path)
    expected_version = plan.artifacts[1].payload[0].source_versions[0].version
    equivalent_evidence = evidence.model_copy(
        update={
            "evidence": [
                evidence.evidence[0].model_copy(
                    update={
                        "reference": evidence.evidence[0].reference.model_copy(
                            update={
                                "source_id": plan.artifacts[1].payload[0].source_ids[0],
                                "checked_at": expected_version.replace("Z", "+00:00"),
                            }
                        )
                    }
                )
            ]
        }
    )
    completed = agent.complete_navigation_evidence(plan.source_ids, equivalent_evidence)
    assert {item.reference.source_id for item in completed.evidence} == set(plan.source_ids)
    assert all(
        "navigation only" in item.content
        for item in completed.evidence
        if item.reference.document_id.startswith("catalog-")
    )
    stale_evidence = evidence.model_copy(
        update={
            "evidence": [
                evidence.evidence[0].model_copy(
                    update={
                        "reference": evidence.evidence[0].reference.model_copy(
                            update={
                                "source_id": plan.source_ids[0],
                                "checked_at": "2026-10-27T00:00:00Z",
                            }
                        )
                    }
                )
            ]
        }
    )
    with pytest.raises(ApiError, match="SOURCE_VERSION_UNAVAILABLE"):
        agent.validate_evidence(plan.source_ids, stale_evidence)

    class StaleCatalog:
        def get(self):
            return catalog.get().model_copy(update={"as_of": "2026-10-27T00:00:00Z"})

    stale = ContextAgentService(StaleCatalog(), service)
    with pytest.raises(ApiError, match="SOURCE_VERSION_UNAVAILABLE"):
        await stale.authorize("owner", PAGE_TOKEN, token)


@pytest.mark.parametrize(
    "persona_id,flow_id",
    [
        ("maya-caregiver", "guardianship-intake"),
        ("alex-disability-support", "disability-support"),
    ],
)
async def test_contextual_authorization_allows_optional_scope_to_be_withheld(
    settings,
    persona_id,
    flow_id,
):
    context_settings = contextual_settings(settings)
    _, _, plan, _ = await authorized_plan(
        context_settings,
        persona_id=persona_id,
        scopes=list(FLOW_REQUIRED_SCOPES[flow_id]),
    )
    assert plan.authorization.scopes == FLOW_REQUIRED_SCOPES[flow_id]
    assert "region-preferences.read" not in plan.authorization.scopes


def test_context_tool_schema_context_cannot_execute_without_server_state(settings):
    context_settings = contextual_settings(settings)
    context = ContextToolContext(
        CatalogRepository(context_settings.catalog_path),
        EvidenceLedger(),
    )
    declarations = function_declarations(create_context_tools(context))
    assert {item["name"] for item in declarations} == CONTEXT_TOOL_NAMES
