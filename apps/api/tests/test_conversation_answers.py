import json
import re
from unittest.mock import AsyncMock

import pytest
from test_ai_conversation import ai_settings as ai_settings
from test_ai_conversation import body, client_for, fact, proposal, snapshot, sse

from bc_api.conversation import (
    ConversationService,
    StoredConversation,
    _navigation_supported,
    _personal_supported,
)
from bc_api.conversation_contract import ProposedFact
from bc_api.conversation_policy import GOALS, QUESTIONS, SERVICE_QUESTIONS, decode_answer
from bc_api.discovery_store import PageStateStore
from bc_api.input import validate_run

CHOICES = [
    (key, value, label)
    for key, spec in QUESTIONS.items()
    for value, label in [*spec.values.items(), (None, "Not sure")]
]


@pytest.mark.parametrize("key,value,label", CHOICES)
async def test_every_rendered_answer_is_consumed_without_model_reinterpretation(
    ai_settings, repository, key, value, label
):
    service = ConversationService(
        ai_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    start = await service.prepare(
        "choice-owner",
        "choice-page-token-00000001",
        validate_run(body("start", share=True), ai_settings),
    )
    start.summary.goal = next(
        goal for goal, spec in GOALS.items() if key in spec.essential + spec.optional
    )
    start.summary.subject = "you"
    service._ask(start, key, [])
    old_question = start.summary.question
    assert label in old_question.choices
    stored = StoredConversation(
        summary=start.summary,
        counts=start.counts,
        previous_revision=0,
        input_hash=start.input_hash,
    )
    assert await service.store.save(start.ref, 0, stored)
    answer = await service.prepare(
        "choice-owner",
        "choice-page-token-00000001",
        validate_run(body(label, start.summary.model_dump(by_alias=True), share=True), ai_settings),
    )
    decide = AsyncMock(side_effect=AssertionError("Explicit choices do not need a model."))
    assert not answer.needs_model
    await service.advance(answer, decide)
    await service.commit(answer)
    saved = await service.store.get(start.ref)
    result = next(item for item in saved.summary.facts if item.key == key)
    assert result.value == value
    assert result.status == ("provided" if value is not None else "unknown")
    assert saved.summary.question is None or saved.summary.question.fact_key != key
    update = ProposedFact(key=key, value=value, status=result.status, quote=label)
    validator = _personal_supported if QUESTIONS[key].personal else _navigation_supported
    assert validator(update, old_question)
    decide.assert_not_awaited()


@pytest.mark.parametrize("label", ["Issued somewhere else", "No", "somewhere else"])
def test_reported_non_bc_answer_leads_to_a_different_question(ai_settings, repository, label):
    client, runtime = client_for(ai_settings, repository, [proposal()])
    with client:
        first = snapshot(
            sse(client.post("/api/agent", json=body("hi please help me renew my drivers license")))
        )
        events = sse(client.post("/api/agent", json=body(label, first)))
        second = snapshot(events)
        assert second["facts"][0]["value"] == "other"
        assert second["question"]["id"] != first["question"]["id"]
        assert "place that issued it" in second["question"]["text"]
        assert "Is it a B.C.-issued licence?" not in "".join(
            item.get("delta", "") for item in events
        )
        assert second["journeyId"] is None
        events = sse(client.post("/api/agent", json=body("how do i renrew?", second)))
        third = snapshot(events)
        assert third["question"] is None
        assert third["facts"][0]["value"] == "other"
        assert third["journeyId"] is None
        text = "".join(item.get("delta", "") for item in events)
        assert "original issuer" in text and "won't substitute B.C." in text
        assert len(runtime.inputs) == 1


@pytest.mark.parametrize(
    "label", list(SERVICE_QUESTIONS["licence-route"].values.values()) + ["Not sure", "skip"]
)
def test_all_licence_route_answers_consume_the_pending_question(ai_settings, repository, label):
    client, runtime = client_for(ai_settings, repository, [proposal()])
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("renew licence"))))
        summary = snapshot(
            sse(client.post("/api/agent", json=body("Issued somewhere else", summary)))
        )
        request = body(label, summary)
        events = sse(client.post("/api/agent", json=request))
        final = snapshot(events)
        assert final["question"] is None and final["journeyId"] is None
        assert final["facts"][0]["value"] == "other"
        text = "".join(item.get("delta", "") for item in events)
        if label == "Get a B.C. licence":
            assert "moving-to-B.C." in text and "accepted identification" in text
            assert "Renew-your-licence-or-ID" not in text
        # Exact replay is idempotent; different input cannot reuse the old question/revision.
        repeated = snapshot(sse(client.post("/api/agent", json=body(label, summary))))
        assert repeated["revision"] == final["revision"]
        assert (
            client.post("/api/agent", json=body("a different answer", summary)).status_code == 409
        )
        assert len(runtime.inputs) == 1


@pytest.mark.parametrize("answer", ["Not sure", "skip"])
def test_unknown_issuer_does_not_become_a_bc_renewal_task(ai_settings, repository, answer):
    client, _ = client_for(ai_settings, repository, [proposal()])
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("renew licence"))))
        events = sse(client.post("/api/agent", json=body(answer, summary)))
        summary = snapshot(events)
        assert summary["journeyId"] is None
        assert summary["question"] is None
        assert summary["facts"][0]["value"] is None
        assert "haven't assumed" in "".join(item.get("delta", "") for item in events)


@pytest.mark.parametrize(
    "goal,prompt,key",
    [
        ("caregiving", "I need to apply for guardianship", "guardianship-scope"),
        ("disability", "I need to apply for disability", "disability-kind"),
    ],
)
def test_public_starter_questions_and_all_choices_work_without_personal_sharing(
    ai_settings, repository, goal, prompt, key
):
    for label in [*SERVICE_QUESTIONS[key].values.values(), "Not sure", "skip"]:
        client, runtime = client_for(ai_settings, repository, [proposal(goal)])
        with client:
            summary = snapshot(sse(client.post("/api/agent", json=body(prompt))))
            assert summary["question"]["text"] == SERVICE_QUESTIONS[key].question
            assert not summary["question"]["personal"]
            events = sse(client.post("/api/agent", json=body(label, summary)))
            result = snapshot(events)
            assert result["question"] is None and result["facts"] == []
            assert not result["shareContext"]
            text = "".join(item.get("delta", "") for item in events)
            assert "don't have a reviewed step-by-step guide" not in text
            assert len(runtime.inputs) == 1


def test_free_text_route_uses_known_issuer_without_overwriting_it(ai_settings, repository):
    client, runtime = client_for(
        ai_settings,
        repository,
        [
            proposal(),
            proposal(
                updates=[fact("licence-jurisdiction", "bc", "BC licence")],
                serviceAnswer={
                    "key": "licence-route",
                    "value": "get-bc",
                    "status": "provided",
                    "quote": "get a BC licence",
                },
            ),
        ],
    )
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("renew my drivers license"))))
        summary = snapshot(
            sse(client.post("/api/agent", json=body("Issued somewhere else", summary)))
        )
        events = sse(
            client.post("/api/agent", json=body("I'd like to get a BC licence, please", summary))
        )
        summary = snapshot(events)
        assert summary["facts"][0]["value"] == "other"
        assert summary["goalLabel"] == "Get a B.C. licence"
        assert summary["question"] is None
        assert json.loads(runtime.inputs[-1])["pendingServiceQuestion"] == "licence-route"


def test_canonical_decode_never_treats_another_question_as_a_choice():
    assert (
        decode_answer(QUESTIONS["licence-jurisdiction"], "I need to renew my drivers license")
        is None
    )
    assert (
        decode_answer(QUESTIONS["licence-jurisdiction"], "No, actually I need disability help")
        is None
    )
    assert (
        decode_answer(SERVICE_QUESTIONS["licence-route"], "I don't want to get a BC licence")
        is None
    )


@pytest.mark.parametrize(
    "answer,journey", [("Help with rent", "rental-assistance"), ("Finding work", None)]
)
def test_job_loss_starter_advances_to_the_chosen_priority(ai_settings, repository, answer, journey):
    client, runtime = client_for(ai_settings, repository, [proposal("job-loss")])
    with client:
        summary = snapshot(
            sse(client.post("/api/agent", json=body("I just lost my job, what do I do?")))
        )
        assert summary["question"]["factKey"] == "priority"
        events = sse(client.post("/api/agent", json=body(answer, summary)))
        result = snapshot(events)
        assert result["journeyId"] == journey
        assert result["question"] is None
        assert not result["shareContext"]
        if journey is None:
            text = "".join(item.get("delta", "") for item in events)
            assert re.findall(r"\[WorkBC\]\(([^()\s]+)\)", text) == ["https://www.workbc.ca/"]
        assert len(runtime.inputs) == 1


def test_revoked_personal_answer_is_not_promoted_into_public_service_context(
    ai_settings, repository
):
    client, runtime = client_for(
        ai_settings,
        repository,
        [
            proposal("caregiving", updates=[fact("care-recipient", "adult", "an adult")]),
            proposal("caregiving"),
        ],
    )
    with client:
        summary = snapshot(
            sse(client.post("/api/agent", json=body("Guardianship for an adult", share=True)))
        )
        assert summary["question"] is None
        summary = snapshot(
            sse(client.post("/api/agent", json=body("Stop sharing", summary, action="sharing")))
        )
        assert summary["facts"] == []
        snapshot(sse(client.post("/api/agent", json=body("Please help me continue", summary))))
        context = json.loads(runtime.inputs[-1])
        assert context["context"]["facts"] == []
        assert context["serviceAnswers"] == {}


def test_a_new_starter_is_not_consumed_as_an_answer_to_the_old_question(ai_settings, repository):
    client, _ = client_for(ai_settings, repository, [proposal(), proposal("disability")])
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body("Renew my drivers licence"))))
        summary = snapshot(
            sse(client.post("/api/agent", json=body("I need to apply for disability", summary)))
        )
        assert summary["goal"] == "disability"
        assert summary["facts"] == []
        assert summary["question"]["text"] == SERVICE_QUESTIONS["disability-kind"].question


@pytest.mark.parametrize(
    "goal,key,value,prompt",
    [
        ("caregiving", "guardianship-scope", "adult", "I need to apply for guardianship"),
        ("caregiving", "guardianship-scope", None, "I need to apply for guardianship"),
        (
            "disability",
            "disability-kind",
            "provincial-assistance",
            "I need to apply for disability",
        ),
        ("disability", "disability-kind", None, "I need to apply for disability"),
    ],
)
def test_unstated_service_choice_is_withheld_and_clarified_not_a_dead_end(
    ai_settings, repository, goal, key, value, prompt
):
    client, _ = client_for(
        ai_settings,
        repository,
        [
            proposal(
                goal,
                serviceAnswer={
                    "key": key,
                    "value": value,
                    "status": "provided" if value else "unknown",
                    "quote": prompt,
                },
            ),
        ],
    )
    with client:
        summary = snapshot(sse(client.post("/api/agent", json=body(prompt))))
        assert summary["question"]["text"] == SERVICE_QUESTIONS[key].question
        assert summary["facts"] == []
        assert summary["phase"] == "clarify"
