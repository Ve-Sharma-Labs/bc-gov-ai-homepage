from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from test_ai_conversation import ai_settings as ai_settings
from test_ai_conversation import client_for

from bc_api.agents import grounded_agent_definition
from bc_api.config import Settings
from bc_api.conversation_policy import decision_schema
from bc_api.models import AgentBinding, RunOptions


def test_irrelevant_model_controls_are_dropped_without_changing_facts_or_authority():
    import json

    from test_ai_conversation import proposal

    from bc_api.conversation_contract import GroundedConversationProposal, parse_grounded_proposal

    raw = {
        **proposal().model_dump(by_alias=True),
        "action": "guide",
        "questionKey": "licence-jurisdiction",
        "candidates": ["caregiving"],
        "answerQuestion": False,
        "answerTopics": ["application"],
    }
    result = parse_grounded_proposal(json.dumps(raw))
    assert result.question_key is None and result.candidates == [] and result.answer_topics == []
    assert result.updates == [] and result.answer_question is False
    raw["serviceAnswer"] = {
        "key": "guardianship-scope",
        "status": "provided",
        "value": None,
        "quote": "adult",
    }
    with pytest.raises(ValidationError):
        GroundedConversationProposal.model_validate(raw)
    assert parse_grounded_proposal(json.dumps(raw)).service_answer is None


def test_invalid_or_conflicting_model_facts_are_withheld_not_repaired_into_user_answers():
    import json

    from test_ai_conversation import fact, proposal

    from bc_api.conversation_contract import parse_grounded_proposal

    raw = {
        **proposal().model_dump(by_alias=True),
        "answerQuestion": False,
        "answerTopics": [],
        "updates": [
            fact("licence-jurisdiction", "bc", "BC"),
            fact("licence-jurisdiction", "other", "elsewhere"),
            {"key": "age-range", "value": None, "status": "provided", "quote": "hello"},
        ],
    }
    assert parse_grounded_proposal(json.dumps(raw)).updates == []


def test_v6_never_accepts_client_context_or_arbitrary_research():
    command = {
        "action": "respond",
        "revision": 0,
        "noticeVersion": "ai-conversation-v1",
        "shareContext": False,
    }
    assert (
        RunOptions.model_validate(
            {"version": 6, "mode": "general", "conversation": command}
        ).version
        == 6
    )
    with pytest.raises(ValidationError):
        RunOptions.model_validate(
            {"version": 6, "mode": "general", "conversation": command, "researchRequested": True}
        )
    with pytest.raises(ValidationError):
        RunOptions.model_validate(
            {
                "version": 6,
                "mode": "general",
                "conversation": {**command, "programmeId": "ei-regular"},
            }
        )


def test_old_and_grounded_planner_schemas_are_separate(repository):
    old = decision_schema()["parameters"]["properties"]
    new = decision_schema(grounded=True)["parameters"]["properties"]
    assert "programmeId" not in old and "answerQuestion" not in old
    assert {"programmeId", "answerQuestion", "answerTopics"} <= new.keys()
    planner = grounded_agent_definition(
        repository, prefix="test-local", model_deployment="test", planner=True
    )
    answer = grounded_agent_definition(
        repository, prefix="test-local", model_deployment="test", planner=False
    )
    assert planner["name"] != answer["name"]
    assert planner["definition"]["tools"] == [decision_schema(grounded=True)]
    assert planner["definition"]["tool_choice"] == "required"
    assert answer["mode"] == "grounded-answer"


@pytest.mark.parametrize("configured", [True, False])
def test_new_capabilities_require_explicit_client_negotiation(ai_settings, repository, configured):
    settings = ai_settings.model_copy(
        update={
            "grounded_conversation_enabled": True,
            "task_assistance_enabled": True,
            "foundry_grounded_conversation_agent": AgentBinding(
                name="test-grounded-planner", version="1", model_deployment="test"
            )
            if configured
            else None,
            "foundry_grounded_answer_agent": AgentBinding(
                name="test-grounded-answer", version="1", model_deployment="test"
            )
            if configured
            else None,
        }
    )
    client, runtime = client_for(settings, repository, [])
    for method in (
        "ensure_ready",
        "ensure_general_ready",
        "ensure_sources_ready",
        "ensure_conversation_ready",
        "ensure_grounded_ready",
    ):
        setattr(runtime, method, AsyncMock())
    with client:
        old = client.get("/api/capabilities").json()
        assert 6 not in old["requestVersions"]
        runtime.ensure_grounded_ready.assert_not_awaited()
        new = client.get("/api/capabilities", headers={"x-bc-client-version": "6"}).json()
        assert 6 in new["requestVersions"]
        assert new["conversationAgentReady"] is configured
        assert new["aiConfigured"] is configured
        runtime.ensure_grounded_ready.assert_awaited_once()


def test_isolated_reviewed_index_does_not_repurpose_the_live_index():
    settings = Settings(
        _env_file=None,
        azure_search_index="bc-local-grounded",
        azure_search_metadata_index="bc-local-grounded",
        azure_search_metadata_enabled=True,
        azure_search_metadata_reviewed=True,
    )
    assert settings.azure_search_index == "bc-local-grounded"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, azure_search_metadata_index="bc-pilot-public")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            azure_search_index="bc-local-grounded",
            azure_search_metadata_index="bc-local-grounded",
            azure_search_metadata_enabled=True,
        )


def test_grounded_enablement_does_not_bypass_prerequisites():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, grounded_conversation_enabled=True)


@pytest.mark.asyncio
async def test_v6_model_responses_keep_their_grounded_authority(ai_settings, repository):
    import json

    from ag_ui.core import (
        RunFinishedEvent,
        RunStartedEvent,
        TextMessageContentEvent,
        TextMessageEndEvent,
        TextMessageStartEvent,
    )
    from test_ai_conversation import body

    from bc_api.input import validate_run
    from bc_api.models import Evidence, EvidenceBundle, SourceReference
    from bc_api.security import Run
    from bc_api.streaming import stream_run

    settings = ai_settings.model_copy(
        update={
            "grounded_conversation_enabled": True,
            "task_assistance_enabled": True,
        }
    )
    payload = body("Explain the synthetic source")
    payload["forwardedProps"]["bc"]["version"] = 6
    request = validate_run(payload, settings)
    source = repository.get().sources[0]

    class Runtime:
        async def events(self, request, context):
            context.ledger.add(
                EvidenceBundle(
                    evidence=[
                        Evidence(
                            reference=SourceReference(
                                source_id=source.id,
                                document_id="fixture-document",
                                document_version="fixture-version",
                                title=source.title,
                                publisher=source.publisher,
                                url=source.url,
                                checked_at=source.checked_at,
                                publisher_updated_at=None,
                                section="Fixture",
                            ),
                            content="Synthetic guidance explains the next step.",
                        )
                    ]
                )
            )
            yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
            yield TextMessageStartEvent(message_id="answer", role="assistant")
            yield TextMessageContentEvent(
                message_id="answer",
                delta=f"Synthetic guidance explains the next step. [Source]({source.url})",
            )
            yield TextMessageEndEvent(message_id="answer")
            yield RunFinishedEvent(run_id=request.run_id, thread_id=request.thread_id)

    raw = "".join(
        [
            chunk
            async for chunk in stream_run(
                request,
                Run(request.run_id, request.thread_id, "owner"),
                Runtime(),
                repository,
                settings,
            )
        ]
    )
    events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
    assert not [event for event in events if event["type"] == "RUN_ERROR"]
    response = next(event["value"] for event in events if event.get("name") == "bc.response")
    assert response == {"version": 1, "kind": "grounded", "origin": "model"}
