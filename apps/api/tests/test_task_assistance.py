import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from test_ai_conversation import HEADERS, FixtureRuntime, body, fact, proposal, snapshot, sse
from test_ai_conversation import ai_settings as ai_settings

from bc_api.catalog import CatalogRepository
from bc_api.config import default_catalog_path
from bc_api.errors import ApiError
from bc_api.foundry import FoundryRuntime
from bc_api.main import create_app
from bc_api.retrieval import EvidenceLedger
from bc_api.task_assistance import ensure_task, move_task
from bc_api.tools import ToolContext


@pytest.fixture
def task_settings(ai_settings):
    return ai_settings.model_copy(
        update={
            "task_assistance_enabled": True,
            "content_catalog_path": default_catalog_path(),
        }
    )


def make_client(settings, decisions):
    runtime = FixtureRuntime(settings, CatalogRepository(settings.catalog_path))
    runtime.decisions, runtime.inputs = list(decisions), []
    return TestClient(create_app(settings, runtime=runtime), headers=HEADERS), runtime


def turn(client, text, summary=None, **kwargs):
    events = sse(client.post("/api/agent", json=body(text, summary, **kwargs)))
    state = snapshot(events)
    task = next(event["value"] for event in events if event.get("name") == "bc.task")
    text = "".join(event.get("delta", "") for event in events)
    return state, task, text


def control(client, summary, task=None, action="sharing", **fields):
    request = {
        "id": str(uuid.uuid4()),
        "revision": summary["revision"],
        "noticeVersion": "ai-conversation-v1",
        "action": action,
        **fields,
    }
    if task:
        request.update({"taskId": task["task"]["id"], "stepId": task["task"]["activeStepId"]})
    response = client.post("/api/conversation/control", json=request)
    assert response.status_code == 200, response.text
    return response.json(), request


def test_reported_exchange_progresses_to_an_official_handoff(task_settings):
    client, runtime = make_client(
        task_settings,
        [
            proposal(),
            proposal(),
            proposal("unknown", intent="social", action="social"),
            proposal(
                taskAction="reviewed", stepId="prepare-identification", progressQuote="I have my ID"
            ),
            proposal(municipality="Nanaimo"),
            proposal(taskAction="reviewed", progressQuote="I have chosen an office"),
        ],
    )
    with client:
        summary, empty, _ = turn(client, "please help me renew my drivers license please")
        assert empty["task"] is None
        summary, task, text = turn(client, "Yes, issued in B.C.", summary)
        task_id = task["task"]["id"]
        assert task["task"]["activeStepId"] == "prepare-identification"
        assert "primary" in text and "secondary" in text
        assert "Accepted-ID" in text
        assert "Work through the checklist below" not in text
        before = len(runtime.inputs)
        changed, request = control(client, summary, shareContext=True)
        assert len(runtime.inputs) == before
        assert changed["task"]["task"]["id"] == task_id
        assert changed["task"]["task"]["activeStepId"] == "prepare-identification"
        assert changed["notice"] == "Optional context sharing is on."
        assert "Removed" not in changed["notice"]
        repeated = client.post("/api/conversation/control", json=request)
        assert repeated.json()["summary"]["revision"] == changed["summary"]["revision"]
        summary, task, text = turn(
            client,
            "so plesae help me renew my BC DL please",
            changed["summary"],
            share=True,
        )
        assert task["task"]["id"] == task_id
        assert "Here's a reviewed preparation guide" not in text
        summary, task, text = turn(client, "halllllo are you helping", summary, share=True)
        assert summary["goal"] == "licence-renewal"
        assert "What would you like help figuring out" not in text
        assert "ID" in text and "Accepted-ID" in text
        summary, task, text = turn(client, "I have my ID", summary, share=True)
        assert task["task"]["reviewedStepIds"] == ["prepare-identification"]
        assert task["task"]["activeStepId"] == "find-licensing-office"
        assert task["task"]["waitingFor"] == "municipality"
        assert "city or town" in text
        summary, task, text = turn(client, "Nanaimo", summary, share=True)
        assert "Nanaimo" in text and "not live availability" in text
        summary, task, _ = turn(client, "I have chosen an office", summary, share=True)
        assert task["task"]["activeStepId"] == "confirm-before-visiting"
        result, _ = control(client, summary, task, "review", reviewed=True)
        assert result["task"]["task"]["phase"] == "ready-for-official-handoff"
        assert "official service" in result["task"]["guidance"]
        assert "nothing has been renewed" in result["task"]["guidance"]
        assert len(runtime.inputs) == 6


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
def test_each_journey_has_persistent_steps_and_free_controls(task_settings, goal):
    client, runtime = make_client(task_settings, [proposal(goal), proposal(goal)])
    with client:
        summary, task, _ = turn(client, "A synthetic service request")
        if task["task"] is None:
            summary, task, _ = turn(
                client,
                "Yes" if goal == "licence-renewal" else "Skip",
                summary,
                action="respond" if goal == "licence-renewal" else "skip",
            )
        first_step = task["task"]["activeStepId"]
        first_id = task["task"]["id"]
        result, _ = control(client, summary, shareContext=True)
        assert result["task"]["task"]["id"] == first_id
        summary, task, text = turn(
            client, "Please keep helping with this", result["summary"], share=True
        )
        assert task["task"]["activeStepId"] == first_step
        assert "](" in text
        next_result, _ = control(client, summary, task, "next")
        assert next_result["task"]["task"]["activeStepId"] != first_step
        assert next_result["task"]["task"]["reviewedStepIds"] == []
        current = next_result
        for _ in range(40):
            if current["task"]["task"]["phase"] == "ready-for-official-handoff":
                break
            current, _ = control(
                client, current["summary"], current["task"], "review", reviewed=True
            )
        assert current["task"]["task"]["phase"] == "ready-for-official-handoff"
        assert "](" in current["task"]["guidance"]
        assert len(runtime.inputs) == 2


def test_sharing_does_not_answer_a_pending_intake_question(task_settings):
    client, runtime = make_client(task_settings, [proposal()])
    with client:
        summary, _, _ = turn(client, "Help renew my licence")
        question = summary["question"]
        changed, _ = control(client, summary, shareContext=True)
        assert changed["summary"]["question"] == question
        assert changed["summary"]["phase"] == "clarify"
        assert changed["task"]["task"] is None
        assert len(runtime.inputs) == 1


def test_literal_quick_choice_works_with_a_short_evidence_quote(task_settings):
    client, _ = make_client(
        task_settings,
        [
            proposal("rental-assistance"),
            proposal("rental-assistance", updates=[fact("housing-need", "rent", "rent")]),
        ],
    )
    with client:
        summary, _, _ = turn(client, "I need housing help")
        summary, task, _ = turn(client, "Help paying rent", summary)
        assert summary["question"] is None
        assert task["task"]["journeyId"] == "rental-assistance"


def test_control_requires_current_revision_task_and_page(task_settings):
    client, _ = make_client(
        task_settings, [proposal(updates=[fact("licence-jurisdiction", "bc", "BC licence")])]
    )
    with client:
        summary, task, _ = turn(client, "Renew my BC licence")
        result, request = control(client, summary, task, "review", reviewed=True)
        stale = {**request, "id": str(uuid.uuid4())}
        assert client.post("/api/conversation/control", json=stale).status_code == 409
        foreign = {**stale, "revision": result["summary"]["revision"], "taskId": "foreign-task"}
        assert client.post("/api/conversation/control", json=foreign).status_code == 409
        assert (
            client.post(
                "/api/conversation/control",
                json=stale,
                headers={"x-bc-conversation-page": "another-task-page-000001"},
            ).status_code
            == 410
        )
        fresh = client.get("/api/conversation/task").json()
        assert fresh["task"]["task"]["reviewedStepIds"] == ["prepare-identification"]


def test_not_ready_does_not_become_progress(task_settings):
    client, _ = make_client(
        task_settings,
        [
            proposal(updates=[fact("licence-jurisdiction", "bc", "BC licence")]),
            proposal(taskAction="reviewed", progressQuote="I do not have my ID"),
        ],
    )
    with client:
        summary, _, _ = turn(client, "Renew my BC licence")
        _, task, text = turn(client, "I do not have my ID", summary)
        assert task["task"]["activeStepId"] == "prepare-identification"
        assert task["task"]["reviewedStepIds"] == []
        assert "Accepted-ID" in text


def test_repeating_a_known_issuer_does_not_reset_progress(task_settings):
    client, _ = make_client(
        task_settings,
        [
            proposal(updates=[fact("licence-jurisdiction", "bc", "BC licence")]),
            proposal(taskAction="reviewed", progressQuote="I have my ID"),
            proposal(updates=[fact("licence-jurisdiction", "bc", "BC licence")]),
        ],
    )
    with client:
        summary, _, _ = turn(client, "Renew my BC licence")
        summary, task, _ = turn(client, "I have my ID", summary)
        summary, continued, _ = turn(client, "I still need help renewing my BC licence", summary)
        assert continued["task"]["id"] == task["task"]["id"]
        assert continued["task"]["reviewedStepIds"] == ["prepare-identification"]
        assert continued["task"]["activeStepId"] == "find-licensing-office"


def test_next_and_back_never_claim_reviewed(task_settings):
    repository = CatalogRepository(task_settings.catalog_path)
    task = ensure_task(repository, "licence-renewal", None)
    move_task(task, "next")
    assert task.active_step_id == "find-licensing-office"
    assert task.reviewed_step_ids == []
    move_task(task, "back")
    assert task.active_step_id == "prepare-identification"
    assert task.reviewed_step_ids == []


@pytest.mark.parametrize("budget_limit", [1, 2])
async def test_schema_repair_is_bounded_and_charges_both_attempts(task_settings, budget_limit):
    settings = task_settings.model_copy(update={"api_model_calls_per_run": budget_limit})
    valid = proposal().model_dump(by_alias=True)
    malformed = {**valid, "candidates": ["licence-renewal"]}
    responses = [
        SimpleNamespace(
            status="completed",
            usage=SimpleNamespace(total_tokens=tokens),
            output=[
                SimpleNamespace(
                    type="function_call",
                    name="propose_conversation_turn",
                    arguments=json.dumps(value),
                )
            ],
        )
        for value, tokens in [(malformed, 50), (valid, 60)]
    ]
    create = AsyncMock(side_effect=responses)

    class Client:
        def __init__(self):
            self.responses = SimpleNamespace(create=create)

        def with_options(self, **kwargs):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    repository = CatalogRepository(settings.catalog_path)
    runtime = FoundryRuntime(
        settings, repository, project=SimpleNamespace(get_openai_client=Client)
    )
    runtime.conversation_ready_until = time.monotonic() + 60
    context = ToolContext(repository, EvidenceLedger())
    if budget_limit == 1:
        with pytest.raises(ApiError, match="MODEL_BUDGET_EXCEEDED"):
            await runtime.decide_conversation('{"currentMessage":"Synthetic fixture"}', context)
        assert create.await_count == 1
    else:
        result = await runtime.decide_conversation(
            '{"currentMessage":"Synthetic fixture"}', context
        )
        assert result.goal == "licence-renewal"
        assert context.decision_tokens == 110
        assert context.model_budget.calls == 2
        assert create.call_args.kwargs["store"] is False
        assert "validationFeedback" in create.call_args.kwargs["input"][0]["content"]
