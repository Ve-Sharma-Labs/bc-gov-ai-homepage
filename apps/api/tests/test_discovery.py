import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from ag_ui.core import (
    CustomEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from fastapi.testclient import TestClient

from bc_api.agents import route_journey
from bc_api.discovery import DiscoveryService
from bc_api.discovery_content import GOALS, question_copy
from bc_api.discovery_store import DiscoveryStore, discovery_ref
from bc_api.errors import ApiError
from bc_api.foundry import FoundryRuntime
from bc_api.input import parse_options, validate_run
from bc_api.main import create_app
from bc_api.models import AgentBinding, DiscoverySummary
from bc_api.output import OutputGate
from bc_api.retrieval import EvidenceLedger

PAGE = "fixture-page-discovery-0001"
OWNER = "fixture-anonymous-owner"
HEADERS = {"Origin": "http://localhost:3000", "x-bc-discovery-page": PAGE}


def request(text, summary=None, *, action="respond", fact_key=None, revision=None):
    command = {
        "action": action,
        "revision": revision if revision is not None else summary["revision"] if summary else 0,
    }
    if summary and summary.get("question") and action in ("respond", "skip"):
        command["questionId"] = summary["question"]["id"]
    if fact_key:
        command["factKey"] = fact_key
    return {
        "threadId": "fixture-discovery-thread",
        "runId": "run-" + uuid.uuid4().hex,
        "state": {},
        "tools": [],
        "context": [],
        "messages": [{"id": "message-" + uuid.uuid4().hex, "role": "user", "content": text}],
        "forwardedProps": {"bc": {"version": 4, "mode": "general", "discovery": command}},
    }


def events(response):
    assert response.status_code == 200, response.text
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def answer(client, text, summary=None, **options):
    stream = events(client.post("/api/agent", json=request(text, summary, **options)))
    assert not [item for item in stream if item["type"] == "RUN_ERROR"], stream
    assert stream[-1]["type"] == "RUN_FINISHED"
    snapshot = next(item["value"] for item in stream if item.get("name") == "bc.discovery")
    prose = "".join(item["delta"] for item in stream if item["type"] == "TEXT_MESSAGE_CONTENT")
    return snapshot, prose, stream


@pytest.fixture
def discovery_settings(settings):
    return settings.model_copy(
        update={
            "conversation_discovery_enabled": True,
            "api_agent_runs_per_minute": 30,
        }
    )


@pytest.fixture
def discovery_client(discovery_settings):
    with TestClient(create_app(discovery_settings), headers=HEADERS) as client:
        yield client


@pytest.fixture
def service(discovery_settings, repository):
    return DiscoveryService(discovery_settings, repository, DiscoveryStore(20))


def test_motorcycle_is_warm_bounded_and_not_a_renewal(discovery_client):
    first, text, _ = answer(
        discovery_client, "I'm thinking of buying a motorcycle next year - what should I think of?"
    )
    assert text.startswith("That sounds exciting")
    assert text.count("?") == 1
    assert first["question"]["factKey"] == "age"
    assert first["questionCount"] == 1
    assert first["facts"][0]["value"] == "Next year"
    assert "phn" not in text.lower() and "immigration" not in text.lower()

    second, _, _ = answer(discovery_client, "I'll be 18.", first)
    assert second["question"]["factKey"] == "licence-experience"
    final, text, stream = answer(discovery_client, "My first.", second)
    assert final["phase"] == "plan"
    assert final["questionCount"] == 2
    assert final["suggestions"] == []
    assert final["suggestedDemoId"] is None
    assert "won't guess" in text
    assert "licence-renewal" not in json.dumps(stream)
    assert not [item for item in stream if item["type"] == "TOOL_CALL_START"]
    assert final["facts"][1]["value"] == "18"


def test_volunteered_answers_are_not_asked_again(discovery_client):
    summary, _, _ = answer(
        discovery_client,
        "I'll be 18. My first motorcycle licence is planned for next year.",
    )
    assert summary["phase"] == "plan"
    assert summary["questionCount"] == 0
    assert len(summary["facts"]) == 3


def test_buying_a_first_motorcycle_is_not_proof_of_a_first_licence(discovery_client):
    summary, _, _ = answer(discovery_client, "I'm 30 and buying my first motorcycle next year.")
    assert summary["question"]["factKey"] == "licence-experience"


def test_decline_gives_general_guidance_without_pressure(discovery_client):
    summary, _, _ = answer(discovery_client, "I'm planning to buy a motorcycle.")
    summary, text, _ = answer(discovery_client, "I'd rather not give my age.", summary)
    assert summary["phase"] == "plan"
    assert summary["question"] is None
    assert summary["facts"][0]["status"] == "declined"
    assert "No problem" in text


def test_skip_and_unknown_do_not_become_negative_facts(discovery_client):
    summary, _, _ = answer(discovery_client, "I need health coverage.")
    summary, _, _ = answer(discovery_client, "Skip this question.", summary, action="skip")
    assert summary["question"]["factKey"] == "phn-status"
    summary, _, _ = answer(discovery_client, "Not sure", summary)
    assert summary["phase"] == "plan"
    assert [(item["status"], item["value"]) for item in summary["facts"]] == [
        ("declined", None),
        ("unknown", None),
    ]


def test_no_more_than_three_questions_and_no_loop_on_unrecognized_answer(discovery_client):
    summary, _, _ = answer(discovery_client, "I'd like a motorcycle.")
    for _ in range(3):
        summary, _, _ = answer(discovery_client, "A complicated story I cannot summarize.", summary)
    assert summary["phase"] == "plan"
    assert summary["questionCount"] == 3
    assert all(fact["status"] == "unknown" for fact in summary["facts"])


def test_multiple_needs_prioritize_without_activating_a_fictional_persona(discovery_client):
    summary, _, _ = answer(discovery_client, "I lost my job and need help.")
    assert summary["question"]["factKey"] == "priority"
    summary, text, _ = answer(discovery_client, "Both", summary)
    assert summary["suggestions"][0]["journeyId"] == "rental-assistance"
    assert summary["suggestedDemoId"] == "sam-job-loss"
    assert "eligible" not in text
    assert not discovery_client.app.state.context_service.sessions._states


def test_context_can_be_corrected_removed_and_not_reconstructed_from_history(discovery_client):
    summary, _, _ = answer(discovery_client, "I'm 30 and planning for a motorcycle next year.")
    summary, _, _ = answer(discovery_client, "My first one", summary)
    summary, _, _ = answer(discovery_client, "40", summary, action="correct", fact_key="age")
    assert next(f["value"] for f in summary["facts"] if f["key"] == "age") == "40"
    summary, _, _ = answer(
        discovery_client, "Stop using my age.", summary, action="remove", fact_key="age"
    )
    removed = next(f for f in summary["facts"] if f["key"] == "age")
    assert removed["value"] is None and removed["status"] == "declined"
    body = request("Keep it general.", summary, action="general")
    body["messages"].insert(0, {"id": "old-input", "role": "user", "content": "I'm 30."})
    stream = events(discovery_client.post("/api/agent", json=body))
    snapshot = next(item["value"] for item in stream if item.get("name") == "bc.discovery")
    assert next(f for f in snapshot["facts"] if f["key"] == "age")["value"] is None
    assert not [item for item in stream if item["type"] == "RUN_ERROR"]


def test_topic_change_does_not_keep_a_hidden_pathway(discovery_client):
    summary, _, _ = answer(discovery_client, "I'm 30 and planning for a motorcycle next year.")
    summary, _, _ = answer(discovery_client, "Actually I need help with rent.", summary)
    assert summary["goalId"] == "rent"
    assert not any(f["key"] == "age" for f in summary["facts"])
    assert "motorcycle" not in summary["goalLabel"].lower()


def test_other_person_age_is_not_taken_from_the_speaker(discovery_client):
    summary, text, _ = answer(
        discovery_client, "I'm 40 and buying a motorcycle for my son next year."
    )
    assert summary["about"] == "someone-else"
    assert not any(f["key"] == "age" for f in summary["facts"])
    assert "they" in text


def test_phn_number_is_never_an_answer(discovery_client):
    summary, _, _ = answer(discovery_client, "I need PharmaCare registration help.")
    assert summary["question"]["factKey"] == "phn-status"
    response = discovery_client.post("/api/agent", json=request("1234567890", summary))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PERSONAL_DATA_NOT_SUPPORTED"
    assert "1234567890" not in response.text


def test_social_reply_does_not_consume_a_discovery_question(discovery_client):
    summary, _, _ = answer(discovery_client, "I want a motorcycle.")
    question = summary["question"]
    summary, text, _ = answer(discovery_client, "Thanks", summary)
    assert summary["question"] == question and summary["questionCount"] == 1
    assert "welcome" in text


def test_model_and_retrieval_receive_public_intent_not_personal_answers(
    configured, repository, evidence
):
    settings = configured.model_copy(
        update={
            "conversation_discovery_enabled": True,
            "foundry_general_agent": AgentBinding(
                name="fixture-general", version="1", model_deployment="fixture-model"
            ),
        }
    )

    class IntentRuntime(FoundryRuntime):
        received = None
        query = None

        async def warm(self):
            return None

        async def events(self, request, context):
            self.received = request.model_dump_json(by_alias=True)
            self.query = context.public_query
            context.model_work_started = True
            context.ledger.add(evidence)
            yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
            yield TextMessageStartEvent(message_id="fixture-factual", role="assistant")
            yield TextMessageContentEvent(
                message_id="fixture-factual",
                delta="Bring accepted identification to the office. "
                f"[Official source]({evidence.evidence[0].reference.url})",
            )
            yield TextMessageEndEvent(message_id="fixture-factual")
            yield RunFinishedEvent(run_id=request.run_id, thread_id=request.thread_id)

    runtime = IntentRuntime(settings, repository)
    with TestClient(create_app(settings, runtime=runtime), headers=HEADERS) as client:
        summary, _, _ = answer(
            client, "I'll be 37. My first motorcycle licence is planned for next year."
        )
        assert summary["phase"] == "plan"
        _, _, stream = answer(client, "What are the costs?", summary)
        assert "published fees" in runtime.query
        assert "37" not in runtime.query
        messages = json.loads(runtime.received)["messages"]
        assert len(messages) == 1
        assert "37" not in messages[0]["content"]
        assert "Age when" not in messages[0]["content"]
        assert next(item["value"] for item in stream if item.get("name") == "bc.response") == {
            "version": 1,
            "kind": "grounded",
            "origin": "model",
        }


def test_discovery_is_capability_gated_and_legacy_modes_unchanged(client, settings):
    response = client.post("/api/agent", json=request("I want a motorcycle."))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DISCOVERY_DISABLED"
    caps = client.get("/api/capabilities").json()
    assert caps["discoveryAvailable"] is False
    assert caps["requestVersions"] == [1, 2, 3]
    valid = validate_run(request("I want a motorcycle."), settings)
    assert route_journey(valid) is None
    assert parse_options(valid.forwarded_props).discovery.revision == 0


def test_active_question_and_owner_are_enforced(discovery_client):
    summary, _, _ = answer(discovery_client, "I want a motorcycle.")
    body = request("18", summary)
    body["forwardedProps"]["bc"]["discovery"]["questionId"] = "invented-question"
    response = discovery_client.post("/api/agent", json=body)
    assert response.status_code == 409
    response = discovery_client.get(
        "/api/discovery", headers={"x-bc-discovery-page": "different-fixture-page-0002"}
    )
    assert response.json() is None
    response = discovery_client.post(
        "/api/agent",
        json=request("18", summary),
        headers={"x-bc-discovery-page": "different-fixture-page-0002"},
    )
    assert response.status_code == 410


def test_urgent_safety_bypasses_discovery(discovery_client):
    summary, text, _ = answer(discovery_client, "I'm in immediate danger right now.")
    assert summary["question"] is None and summary["questionCount"] == 0
    assert "emergency support" in text
    assert "age" not in text


async def test_fact_questions_bypass_discovery_and_use_only_public_intent(
    service, discovery_settings
):
    body = request("What is MSP?")
    plan = await service.prepare(OWNER, PAGE, validate_run(body, discovery_settings))
    assert plan.reply is None
    assert plan.summary.question is None
    assert plan.summary.question_count == 0
    assert "overview and purpose" in plan.public_query


async def test_new_public_topic_clears_old_personal_scope_and_keeps_safe_followups(
    service, discovery_settings
):
    plan = await service.prepare(
        OWNER, PAGE, validate_run(request("I'm 30 and want a motorcycle."), discovery_settings)
    )
    await service.commit(plan)
    tax = await service.prepare(
        OWNER,
        PAGE,
        validate_run(
            request("What is a tax credit?", plan.summary.model_dump(by_alias=True)),
            discovery_settings,
        ),
    )
    assert tax.summary.goal_id is None and not tax.summary.facts
    assert "taxes" in tax.public_query and "motorcycle" not in tax.public_query
    await service.commit(tax)
    followup = await service.prepare(
        OWNER,
        PAGE,
        validate_run(
            request("How do I apply?", tax.summary.model_dump(by_alias=True)), discovery_settings
        ),
    )
    assert "taxes" in followup.public_query
    assert "application preparation" in followup.public_query
    assert "30" not in followup.public_query


def test_model_cannot_emit_a_discovery_event_to_bypass_source_verification(repository):
    gate = OutputGate(repository, EvidenceLedger())
    with pytest.raises(ApiError) as error:
        gate.hold(CustomEvent(name="bc.discovery", value={"unverified": "profile"}))
    assert error.value.code == "OUTPUT_INVALID"


def test_public_discovery_requires_a_privacy_review(settings):
    with pytest.raises(ValueError, match="privacy review"):
        type(settings)(
            app_env="production",
            conversation_discovery_enabled=True,
            conversation_discovery_privacy_reviewed=False,
        )


def test_ambiguous_age_and_other_licence_are_not_invented(discovery_client):
    summary, _, _ = answer(
        discovery_client, "I'm 18 and I'm 30. I have a car licence and want a motorcycle next year."
    )
    age = next(fact for fact in summary["facts"] if fact["key"] == "age")
    assert age["status"] == "disputed" and age["value"] is None
    assert summary["question"]["factKey"] == "licence-experience"


async def test_retries_do_not_consume_another_question(service, discovery_settings):
    body = request("I'm buying a motorcycle next year.")
    plan = await service.prepare(OWNER, PAGE, validate_run(body, discovery_settings))
    await service.commit(plan)
    body["runId"] = "retry-" + uuid.uuid4().hex
    replay = await service.prepare(OWNER, PAGE, validate_run(body, discovery_settings))
    assert replay.summary.question.id == plan.summary.question.id
    assert replay.summary.question_count == 1
    assert replay.summary.revision == 1
    assert replay.state is None
    await service.commit(replay)


@pytest.mark.parametrize("with_redis", [False, True])
async def test_clear_blocks_a_late_first_commit(discovery_settings, repository, with_redis):
    if with_redis:
        from fakeredis.aioredis import FakeRedis

        store = DiscoveryStore(20, redis=FakeRedis())
    else:
        store = DiscoveryStore(20)
    service = DiscoveryService(discovery_settings, repository, store)
    plan = await service.prepare(
        OWNER, PAGE, validate_run(request("I want a motorcycle."), discovery_settings)
    )
    await service.clear(OWNER, PAGE)
    with pytest.raises(ApiError, match="cleared"):
        await service.commit(plan)


@pytest.mark.parametrize("with_redis", [False, True])
async def test_atomic_revision_and_expiry(discovery_settings, repository, with_redis):
    if with_redis:
        from fakeredis.aioredis import FakeRedis

        store = DiscoveryStore(20, redis=FakeRedis())
    else:
        store = DiscoveryStore(20)
    service = DiscoveryService(discovery_settings, repository, store)
    first = await service.prepare(
        OWNER, PAGE, validate_run(request("I want a motorcycle."), discovery_settings)
    )
    second = await service.prepare(
        OWNER, PAGE, validate_run(request("I need health coverage."), discovery_settings)
    )
    await service.commit(first)
    with pytest.raises(ApiError, match="changed"):
        await service.commit(second)
    summary = first.summary.model_dump(by_alias=True)
    plan = await service.prepare(
        OWNER, PAGE, validate_run(request("18", summary), discovery_settings)
    )
    plan.state.summary.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert not await store.save(discovery_ref(OWNER, PAGE), 1, plan.state)


def test_reviewed_questions_ask_one_thing_and_contract_rejects_fake_facts():
    for goal_id, goal in GOALS.items():
        assert len(goal.questions) <= 3
        for key in goal.questions:
            assert question_copy(goal_id, key).text.count("?") == 1
    with pytest.raises(ValueError):
        DiscoverySummary.model_validate(
            {
                "version": 1,
                "threadId": "fixture-thread",
                "revision": 1,
                "phase": "plan",
                "goalId": "motorcycle",
                "goalLabel": "Fixture",
                "about": "you",
                "questionCount": 4,
                "facts": [],
                "question": None,
                "suggestions": [],
                "suggestedDemoId": None,
                "expiresAt": datetime.now(UTC).isoformat(),
            }
        )
