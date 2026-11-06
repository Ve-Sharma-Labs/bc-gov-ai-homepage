import asyncio
import io
import json
import logging
from datetime import UTC, datetime, timedelta

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from bc_api.catalog import CatalogRepository
from bc_api.context_audit import (
    AUDIT_TELEMETRY_FIELDS,
    ContextAuditRecord,
    ContextAuditTrail,
    InMemoryContextAuditRepository,
    RedisContextAuditRepository,
)
from bc_api.context_sessions import InMemoryContextSessionRepository
from bc_api.context_tools import (
    FLOW_SCOPES,
    ContextAgentService,
    ContextToolContext,
    create_context_tools,
)
from bc_api.demo_personas import DemoPersonaRepository
from bc_api.demo_rules import default_demo_catalog_path
from bc_api.errors import ApiError
from bc_api.main import create_app
from bc_api.models import AgentBinding, AuditReceiptArtifact
from bc_api.retrieval import EvidenceLedger
from bc_api.synthetic_context import ConsentChangeRequest, SyntheticContextService

ORIGIN = "http://localhost:3000"
NOW = datetime(2026, 11, 6, 7, 0, tzinfo=UTC)
PAGE_TOKEN = "context-audit-page-00000001"


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def context_settings(settings, **updates):
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
            **updates,
        }
    )


def audit_logger() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    logger = logging.Logger("test.context.audit")
    logger.addHandler(logging.StreamHandler(stream))
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger, stream


def context_service(settings, repository, *, clock=None, logger=None):
    return SyntheticContextService(
        settings,
        DemoPersonaRepository(),
        InMemoryContextSessionRepository(settings.api_max_sessions),
        clock=clock or MutableClock(),
        audit=ContextAuditTrail(repository, logger=logger),
    )


async def authorized(settings, repository, *, owner="owner", run_id="run-a", logger=None):
    service = context_service(settings, repository, logger=logger)
    _, token = await service.create_session(owner, PAGE_TOKEN, None, "sam-job-loss")
    await service.change_consent(
        owner,
        PAGE_TOKEN,
        token,
        ConsentChangeRequest(action="grant", scopes=list(FLOW_SCOPES["job-loss"])),
    )
    agent = ContextAgentService(CatalogRepository(settings.catalog_path), service)
    plan = await agent.authorize(owner, PAGE_TOKEN, token, run_id=run_id)
    return service, agent, plan, token


async def test_value_free_receipt_is_ordered_strict_and_contains_no_context_values(settings):
    configured = context_settings(settings)
    repository = InMemoryContextAuditRepository(100, 65536)
    logger, stream = audit_logger()
    service, agent, plan, token = await authorized(
        configured,
        repository,
        owner="raw-owner-reference",
        run_id="raw-run-reference",
        logger=logger,
    )

    artifact_event = await agent.complete_run(plan, "finished")
    artifact = AuditReceiptArtifact.model_validate(artifact_event.value)
    events = await repository.events(plan.authorization.session_ref, now=NOW)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert [event.event_id for event in events] == [
        event.event_id for event in artifact.payload.events
    ]
    assert artifact.payload.contains_raw_context_values is False
    assert {
        "consent-granted",
        "context-category-accessed",
        "rule-evaluated",
        "preview-generated",
        "handoff-offered",
        "context-run-completed",
    } <= {event.action for event in artifact.payload.events}

    serialized = json.dumps(
        {
            "events": [event.model_dump(mode="json", by_alias=True) for event in events],
            "artifact": artifact.model_dump(mode="json", by_alias=True),
            "telemetry": stream.getvalue(),
        }
    )
    for forbidden in (
        "recently-ended",
        "material-decrease",
        "employment.status",
        "raw-owner-reference",
        "raw-run-reference",
        token,
        "prompt",
        "total_token_count",
        "applicationPreview",
    ):
        assert forbidden not in serialized

    telemetry = [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if line.strip()
    ]
    assert telemetry
    assert all(set(item) <= AUDIT_TELEMETRY_FIELDS for item in telemetry)
    assert all(item["sessionRef"] == plan.authorization.session_ref for item in telemetry)
    assert service.audit is not None


async def test_audit_is_cross_session_isolated_and_cleared_with_context(settings):
    configured = context_settings(settings)
    repository = InMemoryContextAuditRepository(100, 65536)
    logger, stream = audit_logger()
    service = context_service(configured, repository, logger=logger)
    agent = ContextAgentService(CatalogRepository(configured.catalog_path), service)

    _, first_token = await service.create_session(
        "first-owner",
        PAGE_TOKEN,
        None,
        "sam-job-loss",
    )
    await service.change_consent(
        "first-owner",
        PAGE_TOKEN,
        first_token,
        ConsentChangeRequest(action="grant", scopes=list(FLOW_SCOPES["job-loss"])),
    )
    first = await agent.authorize(
        "first-owner",
        PAGE_TOKEN,
        first_token,
        run_id="first-run",
    )

    _, second_token = await service.create_session(
        "second-owner",
        PAGE_TOKEN,
        None,
        "sam-job-loss",
    )
    await service.change_consent(
        "second-owner",
        PAGE_TOKEN,
        second_token,
        ConsentChangeRequest(action="grant", scopes=list(FLOW_SCOPES["job-loss"])),
    )
    second = await agent.authorize(
        "second-owner",
        PAGE_TOKEN,
        second_token,
        run_id="second-run",
    )
    await agent.complete_run(first, "finished")
    await agent.complete_run(second, "finished")

    first_events = await repository.events(first.authorization.session_ref, now=NOW)
    second_events = await repository.events(second.authorization.session_ref, now=NOW)
    assert first_events and second_events
    assert {event.event_id for event in first_events}.isdisjoint(
        event.event_id for event in second_events
    )
    with pytest.raises(ApiError, match="CONTEXT_SESSION_REQUIRED"):
        await agent.authorize(
            "second-owner",
            PAGE_TOKEN,
            first_token,
            run_id="stolen-run",
        )

    first_ref = first.authorization.session_ref
    await service.clear_session("first-owner", PAGE_TOKEN, first_token)
    assert await repository.events(first_ref, now=NOW) == ()
    assert await repository.events(second.authorization.session_ref, now=NOW)
    assert '"action":"session-cleared"' in stream.getvalue()
    assert first_token not in stream.getvalue()


async def test_audit_bounds_expiry_and_idempotency_are_enforced():
    ref = "a" * 64
    record = ContextAuditRecord(
        occurred_at="2026-10-29T07:00:00Z",
        session_ref=ref,
        subject_ref=ref,
        persona_id="sam-job-loss",
        consent_id="consent-test",
        consent_scopes=["employment.read"],
        actor_label="test-contextual:1",
        tool="change-consent",
        action="consent-granted",
        flow_id="job-loss",
        outcome="active-consent",
    )
    repository = InMemoryContextAuditRepository(2, 65536)
    expiry = NOW + timedelta(seconds=10)
    first = await repository.append(
        record,
        expires_at=expiry,
        idempotency_key="one",
        now=NOW,
    )
    duplicate = await repository.append(
        record,
        expires_at=expiry,
        idempotency_key="one",
        now=NOW,
    )
    assert duplicate.inserted is False
    assert duplicate.event == first.event
    await repository.append(
        record.model_copy(
            update={
                "action": "preview-generated",
                "tool": "build_application_preview",
                "outcome": "review-required",
            }
        ),
        expires_at=expiry,
        idempotency_key="two",
        now=NOW,
    )
    with pytest.raises(ApiError, match="AUDIT_LIMIT_REACHED"):
        await repository.append(
            record,
            expires_at=expiry,
            idempotency_key="three",
            now=NOW,
        )
    assert len(await repository.events(ref, now=NOW)) == 2
    assert await repository.events(ref, now=NOW + timedelta(seconds=11)) == ()

    size_limited = InMemoryContextAuditRepository(10, 1)
    with pytest.raises(ApiError, match="AUDIT_LIMIT_REACHED"):
        await size_limited.append(
            record,
            expires_at=expiry,
            idempotency_key="size",
            now=NOW,
        )


async def test_revocation_tool_denial_and_terminal_races_are_value_free(settings):
    configured = context_settings(settings)
    repository = InMemoryContextAuditRepository(100, 65536)
    service, agent, plan, token = await authorized(configured, repository)
    tool_context = ContextToolContext(
        CatalogRepository(configured.catalog_path),
        EvidenceLedger(),
        coordinator=agent,
        authorization=plan.authorization,
    )
    evaluate = next(
        item for item in create_context_tools(tool_context) if item.name == "evaluate_program_rules"
    )
    with pytest.raises(RuntimeError, match="did not succeed"):
        await evaluate.func(flow_id="disability-support")
    assert tool_context.failure is not None
    assert tool_context.failure.code == "TOOL_SCOPE_DENIED"

    await service.change_consent(
        "owner",
        PAGE_TOKEN,
        token,
        ConsentChangeRequest(action="revoke", scopes=["employment.read"]),
    )
    await asyncio.gather(
        *(agent.record_terminal(plan, "cancelled", "CANCELLED") for _ in range(12))
    )
    await agent.record_terminal(plan, "failed", "AGENT_UNAVAILABLE")
    events = await repository.events(plan.authorization.session_ref, now=NOW)
    denied = [event for event in events if event.action == "access-denied"]
    revoked = [event for event in events if event.action == "consent-revoked"]
    terminal = [event for event in events if event.action == "context-run-completed"]
    assert len(denied) == 1
    assert denied[0].tool == "evaluate_program_rules"
    assert denied[0].error_code == "TOOL_SCOPE_DENIED"
    assert len(revoked) == 1
    assert revoked[0].consent_scopes == ["employment.read"]
    assert len(terminal) == 1
    assert terminal[0].outcome == "cancelled"
    assert terminal[0].error_code == "CANCELLED"
    payload = json.dumps([event.model_dump(by_alias=True) for event in events])
    assert "recently-ended" not in payload
    assert "employment.status" not in payload


async def test_preview_and_redis_audit_repositories_have_equivalent_behavior():
    now = datetime.now(UTC).replace(microsecond=0)
    expiry = now + timedelta(minutes=5)
    ref = "b" * 64
    record = ContextAuditRecord(
        occurred_at=now.isoformat().replace("+00:00", "Z"),
        trace_ref="c" * 32,
        run_ref="d" * 64,
        session_ref=ref,
        subject_ref=ref,
        persona_id="alex-disability-support",
        consent_id="consent-shared",
        consent_scopes=["identity.read", "employment.read"],
        actor_label="shared-contextual:1",
        tool="context-run",
        action="context-run-completed",
        flow_id="disability-support",
        outcome="finished",
    )
    preview = InMemoryContextAuditRepository(10, 8192)
    server = fakeredis.FakeServer()
    first_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    second_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    redis_first = RedisContextAuditRepository(first_client, "bc:{audit-test}:", 10, 8192)
    redis_second = RedisContextAuditRepository(second_client, "bc:{audit-test}:", 10, 8192)

    try:
        await preview.append(record, expires_at=expiry, idempotency_key="terminal", now=now)
        await redis_first.append(record, expires_at=expiry, idempotency_key="terminal", now=now)
        await asyncio.gather(
            redis_first.append(
                record,
                expires_at=expiry,
                idempotency_key="terminal",
                now=now,
            ),
            redis_second.append(
                record,
                expires_at=expiry,
                idempotency_key="terminal",
                now=now,
            ),
        )
        preview_events = await preview.events(ref, now=now)
        redis_events = await redis_second.events(ref, now=now)
        assert [item.model_dump(mode="json") for item in redis_events] == [
            item.model_dump(mode="json") for item in preview_events
        ]
        await preview.clear(ref)
        await redis_first.clear(ref)
        assert await preview.events(ref, now=now) == ()
        assert await redis_second.events(ref, now=now) == ()
    finally:
        await first_client.aclose()
        await second_client.aclose()


def test_anonymous_chat_does_not_create_context_audit_events(settings, run_input):
    configured = context_settings(settings).model_copy(
        update={
            "foundry_project_endpoint": "",
            "foundry_contextual_agent": None,
            "azure_search_endpoint": "",
            "azure_search_index": "",
        }
    )
    repository = InMemoryContextAuditRepository(100, 65536)
    logger, stream = audit_logger()
    service = context_service(configured, repository, logger=logger)
    run_input["messages"][-1]["content"] = "Hi"
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
    with TestClient(
        create_app(configured, context_service=service),
        headers={"Origin": ORIGIN},
    ) as client:
        response = client.post("/api/agent", json=run_input)
        assert response.status_code == 200
    assert stream.getvalue() == ""
