import json
from unittest.mock import AsyncMock

import pytest
from test_ai_conversation import ai_settings as ai_settings
from test_ai_conversation import body, fact, proposal

from bc_api.catalog import CatalogRepository
from bc_api.config import default_catalog_path
from bc_api.conversation import ConversationService, StoredConversation
from bc_api.conversation_contract import GroundedConversationProposal
from bc_api.conversation_grounding import explicit_ei_request, public_queries, resolve_municipality
from bc_api.discovery_store import PageStateStore
from bc_api.errors import ApiError
from bc_api.input import validate_run


def grounded_proposal(**changes):
    return GroundedConversationProposal.model_validate(
        {
            **proposal().model_dump(by_alias=True),
            **changes,
        }
    )


@pytest.fixture
def grounded_settings(ai_settings):
    return ai_settings.model_copy(
        update={
            "grounded_conversation_enabled": True,
            "task_assistance_enabled": True,
        }
    )


@pytest.fixture
def repository():
    return CatalogRepository(default_catalog_path())


async def turn(service, settings, text, summary=None, decision=None):
    request = body(text, summary.model_dump(by_alias=True) if summary else None)
    request["forwardedProps"]["bc"]["version"] = 6
    plan = await service.prepare(
        "owner", "grounded-conversation-page-0001", validate_run(request, settings)
    )
    await service.advance(plan, AsyncMock(return_value=decision or grounded_proposal()))
    await service.commit(plan)
    return plan


@pytest.mark.parametrize(
    "text,quote,reviewed",
    [
        ("yes, what else to bring?", "yes", False),
        ("I have my ID ready, what else to bring?", "I have my ID ready", True),
    ],
)
async def test_mixed_readiness_and_question_selects_grounding_not_the_same_step(
    grounded_settings, repository, text, quote, reviewed
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(
        service,
        grounded_settings,
        "Renew my BC licence",
        decision=grounded_proposal(
            updates=[fact("licence-jurisdiction", "bc", "BC licence")],
        ),
    )
    next_turn = await turn(
        service,
        grounded_settings,
        text,
        first.summary,
        grounded_proposal(
            intent="information",
            focus="documents",
            taskAction="reviewed",
            progressQuote=quote,
            answerQuestion=True,
            answerTopics=["additional-items"],
            programmeId="licence-renewal",
        ),
    )
    assert next_turn.reply is None
    assert "besides accepted identification" in next_turn.public_query
    assert ("prepare-identification" in next_turn.task.reviewed_step_ids) == reviewed
    assert next_turn.summary.question is None


async def test_explicit_ei_retires_the_binary_priority_question(grounded_settings, repository):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(
        service,
        grounded_settings,
        "I just lost my job, what do I do?",
        decision=grounded_proposal(goal="job-loss"),
    )
    assert first.summary.question.fact_key == "priority"
    followup = await turn(
        service,
        grounded_settings,
        "finding work? i want to claim my EI please",
        first.summary,
        grounded_proposal(
            goal="job-loss",
            programmeId="ei-regular",
            answerQuestion=True,
            answerTopics=["application"],
        ),
    )
    assert followup.summary.question is None
    assert followup.programme_id == "ei-regular"
    assert followup.reply is None
    assert "Employment Insurance" in followup.public_query
    assert "WorkBC" not in followup.public_query
    continuing = await turn(
        service,
        grounded_settings,
        "I don't have my ROE yet",
        followup.summary,
        grounded_proposal(
            goal="job-loss",
            programmeId="ei-regular",
            answerQuestion=True,
            answerTopics=["missing-roe"],
        ),
    )
    assert "ROE missing documents" in continuing.public_query
    assert continuing.summary.question is None


async def test_city_typo_and_missing_coverage_do_not_replay_intake(grounded_settings, repository):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(
        service,
        grounded_settings,
        "Renew my BC licence",
        decision=grounded_proposal(updates=[fact("licence-jurisdiction", "bc", "BC licence")]),
    )
    where = await turn(
        service,
        grounded_settings,
        "where do I go?",
        first.summary,
        grounded_proposal(taskAction="explain", focus="locations", stepId="find-licensing-office"),
    )
    assert where.task.waiting_for == "municipality"
    found = await turn(
        service,
        grounded_settings,
        "vancoucver",
        where.summary,
        grounded_proposal(municipality="Vancouver"),
    )
    assert found.task.municipality == "Vancouver"
    assert "locators" in found.reply.text
    assert "another city" not in found.reply.text
    assert "no service" not in found.reply.text


async def test_acknowledgement_keeps_one_step_and_a_conversational_question(
    grounded_settings, repository
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(service, grounded_settings, "Help me renew my drivers licence")
    answer = await turn(service, grounded_settings, "yes", first.summary)
    assert answer.reply is not None and answer.public_query is None
    assert answer.reply.text.endswith("Do you have your ID ready?")
    assert "Filter the seven-office" not in answer.reply.text
    assert answer.answer_topics == ["documents"]


async def test_information_classification_cannot_skip_the_licence_routing_question(
    grounded_settings, repository
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(
        service,
        grounded_settings,
        "help me renew my drivers license",
        decision=grounded_proposal(
            intent="information",
            action="answer",
            answerQuestion=True,
            answerTopics=["application"],
        ),
    )
    assert first.summary.question.fact_key == "licence-jurisdiction"
    assert first.reply is not None and first.public_query is None
    answer = await turn(service, grounded_settings, "yes", first.summary)
    assert answer.summary.facts[0].value == "bc"
    assert answer.reply.text.endswith("Do you have your ID ready?")


@pytest.mark.parametrize(
    "goal,message,key",
    [
        ("caregiving", "I need to apply for guardianship", "guardianship-scope"),
        ("disability", "I need to apply for disability", "disability-kind"),
    ],
)
async def test_information_classification_still_resolves_essential_service_scope(
    grounded_settings, repository, goal, message, key
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    plan = await turn(
        service,
        grounded_settings,
        message,
        decision=grounded_proposal(
            goal=goal,
            intent="information",
            action="answer",
            answerQuestion=True,
            answerTopics=["application"],
        ),
    )
    assert plan.summary.question is not None
    assert plan.pending_service_question == key
    assert plan.public_query is None


@pytest.mark.parametrize("subject", ["you", "unspecified"])
async def test_subject_wording_cannot_erase_the_known_child_service_route(
    grounded_settings, repository, subject
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(
        service,
        grounded_settings,
        "I need guardianship information",
        decision=grounded_proposal(goal="caregiving", subject=subject),
    )
    child = await turn(service, grounded_settings, "A child", first.summary)
    help_turn = await turn(
        service,
        grounded_settings,
        "Not an adult. Where can I get help?",
        child.summary,
        grounded_proposal(
            goal="caregiving",
            subject="someone-else",
            intent="information",
            action="answer",
            focus="contact",
            answerQuestion=True,
            answerTopics=["legal-help"],
        ),
    )
    assert help_turn.service_answers["guardianship-scope"].value == "child"
    assert help_turn.programme_id == "guardianship-child"
    assert help_turn.reply is None


async def test_missing_doctor_is_a_pwd_followup_not_permission_to_switch_programmes(
    grounded_settings, repository
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(
        service,
        grounded_settings,
        "I need to apply for disability",
        decision=grounded_proposal(goal="disability"),
    )
    selected = await turn(
        service, grounded_settings, "Provincial disability assistance", first.summary
    )
    followup = await turn(
        service,
        grounded_settings,
        "I don't have a doctor. Who can help?",
        selected.summary,
        grounded_proposal(
            goal="primary-care",
            intent="information",
            action="answer",
            changeTask=True,
            answerQuestion=True,
            answerTopics=["contact"],
            focus="contact",
        ),
    )
    assert followup.summary.goal == "disability"
    assert followup.programme_id == "disability-assistance"
    assert followup.answer_topics == ["professional-sections"]
    assert followup.reply is None


async def test_after_applying_uses_reporting_even_if_the_model_repeats_application_topic(
    grounded_settings, repository
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(
        service,
        grounded_settings,
        "I want to claim EI",
        decision=grounded_proposal(
            goal="job-loss",
            programmeId="ei-regular",
            intent="information",
            answerQuestion=True,
            answerTopics=["application"],
        ),
    )
    followup = await turn(
        service,
        grounded_settings,
        "What happens after applying?",
        first.summary,
        grounded_proposal(
            goal="job-loss",
            programmeId="ei-regular",
            intent="information",
            answerQuestion=True,
            answerTopics=["application"],
        ),
    )
    assert followup.answer_topics == ["reporting"]
    assert "reports and checking claim" in followup.public_query


async def test_additional_items_and_locations_do_not_depend_on_legacy_focus(
    grounded_settings, repository
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(
        service,
        grounded_settings,
        "Renew my BC licence",
        decision=grounded_proposal(updates=[fact("licence-jurisdiction", "bc", "BC licence")]),
    )
    additional = await turn(
        service,
        grounded_settings,
        "yes, what else to bring?",
        first.summary,
        grounded_proposal(
            intent="information",
            focus="documents",
            answerQuestion=True,
            answerTopics=["documents"],
            programmeId="licence-renewal",
        ),
    )
    assert additional.answer_topics == ["additional-items"]
    assert additional.reply is None
    assert json.loads(service.grounded_input(additional))["nextQuestion"] is None
    where = await turn(
        service,
        grounded_settings,
        "where do I go?",
        additional.summary,
        grounded_proposal(
            intent="information",
            focus="application",
            taskAction="next",
            answerQuestion=True,
            answerTopics=["locations"],
            programmeId="licence-renewal",
        ),
    )
    assert where.reply is not None and "locator" in where.reply.text
    assert where.task.waiting_for == "municipality"
    assert not where.task.reviewed_step_ids


def test_programme_queries_are_typed_and_bounded():
    assert "ROE" in public_queries("ei-regular", ["missing-roe"])[0]
    with pytest.raises(ValueError):
        public_queries("ei-regular", ["professional-sections"])
    assert explicit_ei_request("finding work? i want to claim my EI please")
    assert not explicit_ei_request("I don't want EI, I need a new job")
    assert not explicit_ei_request("I want work rather than EI")
    assert not explicit_ei_request("I'm not asking about EI")
    assert not explicit_ei_request("EIghteen forms")


def test_city_resolution_requires_a_unique_approved_match():
    names = {"Vancouver", "North Vancouver", "West Vancouver", "Victoria", "Nanaimo"}
    assert resolve_municipality("vancoucver", names).name == "Vancouver"
    assert resolve_municipality("Vancouver", names).corrected is False
    assert resolve_municipality("123 Main Street", names).name is None
    assert resolve_municipality("unknown city", names).name is None


def test_grounding_cases_preserve_the_reported_transcripts():
    from bc_api.config import default_catalog_path

    path = default_catalog_path().parent / "evaluations" / "grounded-conversation-cases.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in data["cases"]}
    assert "yes, what else to bring?" in cases["renewal-compound-followup"]["messages"]
    assert "finding work? i want to claim my EI please" in cases["job-loss-to-ei"]["messages"]
    assert all(case["requiredTopics"] and case["expectedBehaviour"] for case in cases.values())


async def test_legacy_ei_handoff_is_honest_and_does_not_repeat_the_priority_menu(
    ai_settings, repository
):
    service = ConversationService(
        ai_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await service.prepare(
        "owner",
        "legacy-ei-page-00000000001",
        validate_run(body("I just lost my job, what do I do?"), ai_settings),
    )
    await service.advance(first, AsyncMock(return_value=proposal("job-loss")))
    await service.commit(first)
    next_turn = await service.prepare(
        "owner",
        "legacy-ei-page-00000000001",
        validate_run(
            body(
                "finding work? i want to claim my EI please",
                first.summary.model_dump(by_alias=True),
            ),
            ai_settings,
        ),
    )
    await service.advance(
        next_turn,
        AsyncMock(
            return_value=proposal(
                "job-loss",
                action="ask",
                questionKey="priority",
            )
        ),
    )
    assert next_turn.summary.question is None
    assert next_turn.programme_id == "ei-regular"
    assert "canada.ca" in next_turn.reply.text
    assert "verified sources yet" in next_turn.reply.text
    assert "Would you like to start" not in next_turn.reply.text


async def test_legacy_missing_evidence_does_not_replay_the_same_id_paragraph(
    grounded_settings, repository
):
    settings = grounded_settings.model_copy(update={"grounded_conversation_enabled": False})
    service = ConversationService(
        settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await service.prepare(
        "owner", "legacy-items-page-00000001", validate_run(body("Renew my BC licence"), settings)
    )
    await service.advance(
        first,
        AsyncMock(
            return_value=proposal(
                updates=[fact("licence-jurisdiction", "bc", "BC licence")],
            )
        ),
    )
    await service.commit(first)
    initial_text = first.reply.text
    followup = await service.prepare(
        "owner",
        "legacy-items-page-00000001",
        validate_run(
            body("yes, what else to bring?", first.summary.model_dump(by_alias=True)),
            settings,
        ),
    )
    await service.advance(
        followup,
        AsyncMock(
            return_value=proposal(
                focus="documents",
                taskAction="explain",
                stepId="prepare-identification",
            )
        ),
    )
    assert followup.reply is None
    assert "besides accepted identification" in followup.public_query
    fallback = service.source_fallback(followup)
    assert fallback.text != initial_text
    assert "isn't available" in fallback.text
    assert "Do you have your ID ready" not in fallback.text


async def test_grounded_canonical_answer_still_reserves_generation_budget(
    grounded_settings, repository
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(service, grounded_settings, "Help me renew a drivers licence")
    request = body("Yes", first.summary.model_dump(by_alias=True))
    request["forwardedProps"]["bc"]["version"] = 6
    next_turn = await service.prepare(
        "owner",
        "grounded-conversation-page-0001",
        validate_run(request, grounded_settings),
    )
    assert next_turn.resolved_fact is not None
    assert next_turn.needs_model


async def test_protocol_cannot_change_under_an_existing_page(grounded_settings, repository):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(service, grounded_settings, "Help with a BC licence")
    with pytest.raises(ApiError) as changed:
        await service.prepare(
            "owner",
            "grounded-conversation-page-0001",
            validate_run(
                body("Yes", first.summary.model_dump(by_alias=True)),
                grounded_settings,
            ),
        )
    assert changed.value.code == "CONVERSATION_CHANGED"


async def test_repeated_question_gets_one_bounded_repair(grounded_settings, repository):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    first = await turn(service, grounded_settings, "Help renew my licence")
    request = body("Please tell me what I should prepare", first.summary.model_dump(by_alias=True))
    request["forwardedProps"]["bc"]["version"] = 6
    next_turn = await service.prepare(
        "owner",
        "grounded-conversation-page-0001",
        validate_run(request, grounded_settings),
    )
    repeated = grounded_proposal(action="ask", questionKey="licence-jurisdiction")
    decide = AsyncMock(return_value=repeated)
    await service.advance(next_turn, decide)
    assert decide.await_count == 2
    assert next_turn.summary.question is None
    assert next_turn.public_query
    assert next_turn.summary.facts == []
    assert json.loads(decide.await_args.args[0])["repair"]["reason"] == "repeated-pending-question"


async def test_source_failure_does_not_claim_the_requested_topic_was_covered(
    grounded_settings, repository
):
    service = ConversationService(
        grounded_settings, repository, PageStateStore(100, state_type=StoredConversation)
    )
    plan = await turn(
        service,
        grounded_settings,
        "I want to claim EI",
        decision=grounded_proposal(
            goal="job-loss",
            programmeId="ei-regular",
            answerQuestion=True,
            answerTopics=["application"],
        ),
    )
    service.source_fallback(plan)
    assert plan.state.recent_topics == []
    assert plan.summary.limitation == "source-coverage"
    assert "canada.ca" in plan.reply.text


@pytest.mark.parametrize("programme", ["ei-regular", "licence-renewal", "guardianship-adult"])
async def test_grounded_agents_do_not_receive_legacy_plan_or_office_tools(repository, programme):
    from bc_api.retrieval import EvidenceLedger
    from bc_api.tools import ToolContext, create_tools

    context = ToolContext(
        repository, EvidenceLedger(), grounded_conversation=True, programme_id=programme
    )
    tools = {tool.name: tool for tool in create_tools(context)}
    assert set(tools) == {"read_programme_sources"}
    assert context.pending_events == []


async def test_private_or_out_of_plan_search_is_not_forwarded(repository):
    from pydantic import ValidationError

    from bc_api.retrieval import EvidenceLedger
    from bc_api.tools import ProgrammeSourceInput, ToolContext, create_tools

    retriever = AsyncMock()
    context = ToolContext(
        repository,
        EvidenceLedger(),
        grounded_conversation=True,
        programme_id="ei-regular",
        public_queries=public_queries("ei-regular", ["application"]),
        retriever=retriever,
    )
    tools = {tool.name: tool for tool in create_tools(context)}
    with pytest.raises(ValidationError):
        ProgrammeSourceInput.model_validate({"query": "private unapproved detail"})
    with pytest.raises(RuntimeError, match="availableSourceTopics"):
        await tools["read_programme_sources"].func(topic="professional-sections")
    retriever.retrieve.assert_not_awaited()


async def test_typed_source_lookup_builds_a_new_public_query_without_private_text(repository):
    from bc_api.models import EvidenceBundle
    from bc_api.retrieval import EvidenceLedger
    from bc_api.tools import ToolContext, create_tools

    retriever = AsyncMock()
    retriever.retrieve.return_value = EvidenceBundle(evidence=[])
    context = ToolContext(
        repository,
        EvidenceLedger(),
        retriever=retriever,
        grounded_conversation=True,
        programme_id="ei-regular",
        source_ids=frozenset({"employment-insurance"}),
        public_queries=public_queries("ei-regular", ["application"]),
        answer_topics=["application"],
    )
    reader = create_tools(context)[0]
    await reader.func(topic="missing-roe")
    retriever.retrieve.assert_awaited_once_with(
        public_queries("ei-regular", ["missing-roe"])[0],
        None,
        source_ids=frozenset({"employment-insurance"}),
    )
    assert context.answer_topics == ["application"]


async def test_repeated_source_lookup_returns_references_not_duplicate_context(
    repository, evidence
):
    from bc_api.retrieval import EvidenceLedger
    from bc_api.tools import ToolContext, create_tools

    retriever = AsyncMock()
    retriever.retrieve.return_value = evidence
    ledger = EvidenceLedger()
    ledger.add(evidence)
    context = ToolContext(
        repository,
        ledger,
        retriever=retriever,
        grounded_conversation=True,
        programme_id="ei-regular",
    )
    result = json.loads(await create_tools(context)[0].func(topic="application"))
    assert result["evidence"] == []
    assert len(result["alreadyInContext"]) == len(evidence.evidence)
    assert len(ledger.items) == len(evidence.evidence)
