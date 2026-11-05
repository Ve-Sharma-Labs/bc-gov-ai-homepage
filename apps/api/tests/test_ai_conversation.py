import json
import uuid
from unittest.mock import AsyncMock

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
from pydantic import ValidationError

from bc_api.agents import conversation_agent_definition
from bc_api.conversation import ConversationService, StoredConversation
from bc_api.conversation_contract import ConversationProposal, ProposedFact
from bc_api.conversation_policy import CONVERSATION_INSTRUCTIONS, GOALS, QUESTIONS, decision_schema
from bc_api.discovery_store import PageStateStore
from bc_api.errors import ApiError
from bc_api.foundry import FoundryRuntime
from bc_api.input import validate_run
from bc_api.main import create_app
from bc_api.model_budget import ModelBudget
from bc_api.models import AgentBinding
from bc_api.retrieval import EvidenceLedger
from bc_api.tools import ToolContext

PAGE = "conversation-test-page-00001"
HEADERS = {"Origin": "http://localhost:3000", "x-bc-conversation-page": PAGE}


def proposal(goal="licence-renewal", **changes):
    return ConversationProposal.model_validate(
        {
            "goal": goal,
            "intent": "task",
            "subject": "you",
            "action": "guide",
            "questionKey": None,
            "candidates": [],
            "updates": [],
            "focus": "application",
            "tone": "warm",
            **changes,
        }
    )


def fact(key, value, quote, status="provided"):
    return {"key": key, "value": value, "quote": quote, "status": status}


def body(text, snapshot=None, *, action="respond", key=None, share=False):
    command = {
        "action": action,
        "revision": snapshot["revision"] if snapshot else 0,
        "noticeVersion": "ai-conversation-v1",
        "shareContext": share,
    }
    if snapshot and snapshot["question"] and action in ("respond", "skip"):
        command["questionId"] = snapshot["question"]["id"]
    if key:
        command["factKey"] = key
    return {
        "threadId": "conversation-test-thread",
        "runId": str(uuid.uuid4()),
        "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": text}],
        "tools": [],
        "context": [],
        "state": {},
        "forwardedProps": {"bc": {"version": 5, "mode": "general", "conversation": command}},
    }


def sse(response):
    assert response.status_code == 200, response.text
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def snapshot(events):
    assert not [item for item in events if item["type"] == "RUN_ERROR"], events
    assert events[-1]["type"] == "RUN_FINISHED"
    return next(item["value"] for item in events if item.get("name") == "bc.conversation")


@pytest.fixture
def ai_settings(settings):
    return settings.model_copy(
        update={
            "ai_conversation_enabled": True,
            "api_agent_runs_per_minute": 30,
            "foundry_project_endpoint": "https://test.services.ai.azure.com/api/projects/test",
            "foundry_conversation_agent": AgentBinding(
                name="test-isolated-conversation", version="1", model_deployment="test-model"
            ),
        }
    )


class FixtureRuntime(FoundryRuntime):
    decisions = ()
    inputs = None

    async def warm(self):
        return None

    async def decide_conversation(self, data, context):
        self.inputs.append(data)
        context.model_budget = context.model_budget or ModelBudget(self.settings, context, 100)
        context.model_budget.reserve(len(data.encode()))
        context.decision_tokens = 50
        return self.decisions.pop(0)


def client_for(settings, repository, decisions):
    runtime = FixtureRuntime(settings, repository)
    runtime.decisions = list(decisions)
    runtime.inputs = []
    app = create_app(settings, runtime=runtime)
    return TestClient(app, headers=HEADERS), runtime


@pytest.mark.parametrize(
    "prompt",
    [
        "please help me renew my drivers license",
        "PLEASE HELP ME RENEW MY DRIVERS LICENESE PELASE",
        "please help me renew my driver's licence",
    ],
)
def test_exact_typo_request_gets_essential_question_then_reviewed_guide(
    ai_settings, repository, prompt
):
    client, runtime = client_for(
        ai_settings,
        repository,
        [
            proposal(),
        ],
    )
    with client:
        first = sse(client.post("/api/agent", json=body(prompt)))
        summary = snapshot(first)
        assert summary["question"]["factKey"] == "licence-jurisdiction"
        text = "".join(item.get("delta", "") for item in first)
        assert "B.C.-issued licence" in text and text.count("?") == 1
        assert next(item["value"] for item in first if item.get("name") == "bc.response") == {
            "version": 1,
            "kind": "dialogue",
            "origin": "application",
            "decisionOrigin": "model",
        }
        second = sse(client.post("/api/agent", json=body("Yes", summary)))
        summary = snapshot(second)
        assert summary["phase"] == "guide" and summary["question"] is None
        assert summary["journeyId"] == "licence-renewal"
        assert (
            next(item["value"] for item in second if item.get("name") == "bc.response")[
                "decisionOrigin"
            ]
            == "application"
        )
        assert any(item.get("name") == "bc.artifact" for item in second)
        assert "unsupported" not in json.dumps(second).lower()
        assert "I don't have current, reviewed source information" not in json.dumps(second)
        assert len(runtime.inputs) == 1


@pytest.mark.parametrize(
    "goal",
    [
        "licence-renewal",
        "road-test-booking",
        "rental-assistance",
        "health-coverage",
        "pharmacare-registration",
        "primary-care",
        "service-bc",
    ],
)
def test_every_existing_journey_has_a_usable_guide_without_search(ai_settings, repository, goal):
    client, runtime = client_for(ai_settings, repository, [proposal(goal)])
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("A synthetic service request"))))
        if summary["question"]:
            summary = snapshot(
                sse(
                    client.post(
                        "/api/agent",
                        json=body(
                            "Yes" if goal == "licence-renewal" else "Skip this question",
                            summary,
                            action="respond" if goal == "licence-renewal" else "skip",
                        ),
                    )
                )
            )
        assert summary["journeyId"] == goal
        assert summary["phase"] == "guide"
        assert len(runtime.inputs) == 1


@pytest.mark.parametrize("goal", ["business", "bceid", "motorcycle", "tenancy"])
def test_related_but_different_goals_never_inherit_licence_renewal(ai_settings, repository, goal):
    client, _ = client_for(ai_settings, repository, [proposal(goal)])
    with client:
        summary = snapshot(
            sse(client.post("/api/agent", json=body("An explicitly different goal")))
        )
        assert summary["journeyId"] is None
        assert summary["goal"] == goal


def test_business_goal_cannot_borrow_driver_questions_or_facts(ai_settings, repository):
    client, _ = client_for(
        ai_settings,
        repository,
        [
            proposal(
                "business",
                action="ask",
                questionKey="licence-jurisdiction",
                updates=[fact("licence-jurisdiction", "bc", "business licence")],
            ),
        ],
    )
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("renew my business licence"))))
        assert summary["goal"] == "business"
        assert summary["question"] is None
        assert summary["journeyId"] is None
        assert summary["facts"] == []


def test_already_stated_essential_detail_is_not_repeated(ai_settings, repository):
    client, _ = client_for(
        ai_settings,
        repository,
        [
            proposal(updates=[fact("licence-jurisdiction", "bc", "BC licence")]),
        ],
    )
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("Renew my BC licence"))))
        assert summary["question"] is None
        assert summary["questionCount"] == 0


def test_a_model_guess_cannot_skip_an_essential_question(ai_settings, repository):
    client, _ = client_for(
        ai_settings,
        repository,
        [
            proposal(
                "road-test-booking",
                action="answer",
                updates=[fact("road-test-kind", "car", "drivers test")],
            ),
        ],
    )
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("Book a drivers test"))))
        assert summary["facts"] == []
        assert summary["question"]["factKey"] == "road-test-kind"


def test_known_msp_goal_does_not_repeat_the_type_of_coverage(ai_settings, repository):
    client, _ = client_for(
        ai_settings,
        repository,
        [
            proposal("health-coverage", action="ask", questionKey="coverage-need"),
        ],
    )
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("Help me sign up for MSP"))))
        assert summary["question"] is None
        assert summary["journeyId"] == "health-coverage"


def test_ambiguity_questions_are_included_in_the_three_question_limit(ai_settings, repository):
    client, _ = client_for(
        ai_settings,
        repository,
        [
            proposal(
                "unknown",
                intent="ambiguous",
                action="ask",
                candidates=["licence-renewal", "business"],
            ),
            proposal(
                "unknown",
                intent="ambiguous",
                action="ask",
                candidates=["licence-renewal", "business"],
            ),
            proposal(),
        ],
    )
    with client:
        summary = None
        for _ in range(3):
            summary = snapshot(sse(client.post("/api/agent", json=body("not clear", summary))))
        assert summary["questionCount"] == 3
        summary = snapshot(
            sse(client.post("/api/agent", json=body("skip", summary, action="skip")))
        )
        assert summary["question"] is None and summary["phase"] == "handoff"
        assert summary["journeyId"] is None


def test_sharing_is_optional_and_revoked_values_are_not_sent_again(ai_settings, repository):
    client, runtime = client_for(
        ai_settings,
        repository,
        [
            proposal(
                "pharmacare-registration", updates=[fact("phn-status", "yes", "I have a PHN")]
            ),
            proposal("pharmacare-registration"),
        ],
    )
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("I have a PHN", share=True))))
        assert summary["facts"][0]["value"] == "yes"
        summary = snapshot(
            sse(
                client.post(
                    "/api/agent",
                    json=body(
                        "Stop using personal details.", summary, action="sharing", share=False
                    ),
                )
            )
        )
        assert summary["facts"] == []
        result = sse(client.post("/api/agent", json=body("What next?", summary)))
        snapshot(result)
        later_input = json.loads(runtime.inputs[-1])
        assert later_input["context"]["facts"] == []
        assert "I have a PHN" not in runtime.inputs[-1]
        assert len(runtime.inputs) == 2


def test_model_cannot_invent_personal_values_or_unshared_context(ai_settings, repository):
    for decision, shared in [
        (proposal("motorcycle", updates=[fact("age-range", "19-or-older", "renew")]), True),
        (
            proposal(
                "pharmacare-registration", updates=[fact("phn-status", "yes", "I have a PHN")]
            ),
            False,
        ),
    ]:
        client, _ = client_for(ai_settings, repository, [decision])
        with client:
            events = sse(client.post("/api/agent", json=body("renew I have a PHN", share=shared)))
            if shared:
                assert any(item.get("code") == "CONVERSATION_DECISION_INVALID" for item in events)
                assert not any(item.get("name") == "bc.conversation" for item in events)
            else:
                result = snapshot(events)
                assert result["facts"] == []
                assert result["question"] is None


def test_remove_is_not_recovered_from_old_browser_transcript(ai_settings, repository):
    client, runtime = client_for(
        ai_settings,
        repository,
        [
            proposal(updates=[fact("licence-jurisdiction", "bc", "BC licence")]),
            proposal(),
        ],
    )
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("My BC licence"))))
        summary = snapshot(
            sse(
                client.post(
                    "/api/agent",
                    json=body(
                        "Remove issuer", summary, action="remove", key="licence-jurisdiction"
                    ),
                )
            )
        )
        request = body("Help me prepare", summary)
        request["messages"].insert(
            0, {"id": "old-message", "role": "user", "content": "My BC licence"}
        )
        summary = snapshot(sse(client.post("/api/agent", json=request)))
        assert summary["facts"][0]["status"] == "declined"
        assert "My BC licence" not in runtime.inputs[-1]


def test_forged_question_or_notice_never_invokes_a_model(ai_settings, repository):
    client, runtime = client_for(ai_settings, repository, [proposal()])
    with client:
        invalid = body("help")
        invalid["forwardedProps"]["bc"]["conversation"]["noticeVersion"] = "old-notice"
        assert client.post("/api/agent", json=invalid).status_code == 422
        summary = snapshot(sse(client.post("/api/agent", json=body("renew licence"))))
        invalid = body("Yes", summary)
        invalid["forwardedProps"]["bc"]["conversation"]["questionId"] = "forged"
        assert client.post("/api/agent", json=invalid).status_code == 409
        assert len(runtime.inputs) == 1


def test_sensitive_inputs_are_rejected_before_model_work(ai_settings, repository):
    client, runtime = client_for(ai_settings, repository, [])
    with client:
        for value in [
            "PHN 1234567890",
            "My password is not-for-the-model",
            "My medical history is private",
        ]:
            assert client.post("/api/agent", json=body(value)).status_code == 422
        assert not runtime.inputs


async def test_replicated_state_rejects_cleared_or_conflicting_turn(ai_settings, repository):
    from fakeredis.aioredis import FakeRedis

    store = PageStateStore(
        10, state_type=StoredConversation, redis=FakeRedis(), namespace="conversation"
    )
    service = ConversationService(ai_settings, repository, store)
    request = validate_run(body("renew licence"), ai_settings)
    plan = await service.prepare("owner", PAGE, request)
    await service.advance(plan, AsyncMock(return_value=proposal()))
    await service.clear("owner", PAGE)
    with pytest.raises(ApiError):
        await service.commit(plan)


async def test_privacy_commands_and_replays_do_not_require_model_admission(ai_settings, repository):
    service = ConversationService(
        ai_settings, repository, PageStateStore(10, state_type=StoredConversation)
    )
    request = validate_run(body("renew licence"), ai_settings)
    plan = await service.prepare("owner", PAGE, request)
    assert plan.needs_model
    await service.advance(plan, AsyncMock(return_value=proposal()))
    await service.commit(plan)
    replay = await service.prepare("owner", PAGE, request)
    assert not replay.needs_model
    snapshot = plan.summary.model_dump(by_alias=True)
    clearing = await service.prepare(
        "owner", PAGE, validate_run(body("Stop sharing", snapshot, action="sharing"), ai_settings)
    )
    assert not clearing.needs_model


def test_planner_and_answer_share_one_budget(ai_settings, repository):
    context = ToolContext(repository, EvidenceLedger())
    budget = ModelBudget(ai_settings.model_copy(update={"api_model_calls_per_run": 1}), context, 10)
    budget.reserve(100)
    with pytest.raises(ApiError, match="MODEL_BUDGET_EXCEEDED"):
        budget.reserve(100)
    assert context.model_work_started is True


@pytest.mark.parametrize("limit", [1, 2])
def test_grounded_generation_preserves_the_planner_budget_and_usage(
    ai_settings, repository, evidence, limit
):
    settings = ai_settings.model_copy(update={"api_model_calls_per_run": limit})

    class GroundedRuntime(FixtureRuntime):
        async def events(self, request, context):
            assert context.model_budget.calls == 1
            assert context.model_work_started is True
            assert (
                context.public_query
                == "Health Connect Registry family doctor nurse practitioner purpose and overview"
            )
            context.model_budget.reserve(80)
            context.ledger.add(evidence)
            yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
            yield CustomEvent(name="usage", value={"total_token_count": 90})
            yield TextMessageStartEvent(message_id="source-answer", role="assistant")
            yield TextMessageContentEvent(
                message_id="source-answer",
                delta="Bring accepted identification to the office. "
                f"[Official source]({evidence.evidence[0].reference.url})",
            )
            yield TextMessageEndEvent(message_id="source-answer")
            yield RunFinishedEvent(run_id=request.run_id, thread_id=request.thread_id)

    runtime = GroundedRuntime(settings, repository)
    runtime.inputs, runtime.decisions = (
        [],
        [proposal("primary-care", intent="information", action="answer", focus="overview")],
    )
    app = create_app(settings, runtime=runtime)
    with TestClient(app, headers=HEADERS) as client:
        request = body("What is the Health Connect Registry?")
        events = sse(client.post("/api/agent", json=request))
        if limit == 1:
            assert any(item.get("code") == "MODEL_BUDGET_EXCEEDED" for item in events)
            assert not any(item["type"] == "RUN_FINISHED" for item in events)
        else:
            assert snapshot(events)["phase"] == "answer"
            assert app.state.runs.runs[request["runId"]].usage_tokens == 140


def test_definition_is_isolated_strict_and_has_no_hosted_tools():
    definition = conversation_agent_definition(prefix="test-isolated", model_deployment="fixture")[
        "definition"
    ]
    assert definition["instructions"] == CONVERSATION_INSTRUCTIONS
    assert definition["tools"] == [decision_schema()]
    assert definition["tool_choice"] == "required"
    for key, goal in GOALS.items():
        for question in goal.essential + goal.optional:
            assert question in QUESTIONS, key
    with pytest.raises(ValidationError):
        ProposedFact.model_validate(fact("phn-status", "yes", "no", "unknown"))
