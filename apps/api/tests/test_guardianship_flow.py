import json
import re
from dataclasses import FrozenInstanceError, asdict
from datetime import date

import pytest
from pydantic import TypeAdapter

from bc_api.context_flows.guardianship import (
    ALL_SCOPES,
    APPLICATION_PREVIEW_REVIEW_TEXT,
    CONSENT_CHECKPOINT_TEXT,
    FLOW_ID,
    GUARDIANSHIP_AGENT_INSTRUCTIONS,
    GUARDIANSHIP_FLOW,
    MAYA_PERSONA_ID,
    REQUIRED_SCOPES,
    SYNTHETIC_LABEL,
    GuardianshipPolicyError,
    build_guardianship_consent_checkpoint,
    build_guardianship_intake_summary,
    build_guardianship_preview,
    next_guardianship_question,
    ordered_guardianship_matches,
    related_guardianship_supports,
    resolve_guardianship_intent,
)
from bc_api.context_tools import FLOW_SCOPES
from bc_api.demo_personas import DemoPersonaRepository
from bc_api.demo_rules import (
    DemoProgramRuleEngine,
    DemoProgramRuleRepository,
    RuleEvaluationEvidence,
    reviewed_source_versions,
)
from bc_api.models import (
    ApplicationPreviewArtifact,
    ConsentRequestArtifact,
    ContextArtifact,
    ContextFact,
)


def maya_facts() -> list[ContextFact]:
    persona = DemoPersonaRepository().get(MAYA_PERSONA_ID)
    return [
        ContextFact(
            key=fact.key,
            value=fact.value,
            category=fact.category,
            source=fact.source,
            provenance=fact.provenance,
            verified_at=fact.verified_at,
            sensitivity=fact.sensitivity,
            consent_scope=fact.consent_scope,
            mutable_by_citizen=fact.mutable_by_citizen,
        )
        for group in persona.category_facts
        for fact in group.facts
    ]


def rule_matches(facts: list[ContextFact]):
    repository = DemoProgramRuleRepository()
    rule_set = repository.get()
    return DemoProgramRuleEngine(repository).evaluate(
        flow_id=FLOW_ID,
        context_facts=[fact for fact in facts if fact.provenance == "synthetic-government-record"],
        citizen_answers=[fact for fact in facts if fact.provenance == "citizen-answer"],
        evidence=RuleEvaluationEvidence(
            rule_set_version=rule_set.rule_set_version,
            policy_effective_date=date(2026, 11, 5),
            evaluated_at=date(2026, 11, 5),
            source_versions=reviewed_source_versions(rule_set),
        ),
    )


def replace_fact(
    facts: list[ContextFact],
    key: str,
    value: object,
) -> list[ContextFact]:
    return [fact.model_copy(update={"value": value}) if fact.key == key else fact for fact in facts]


def citizen_authority_answer(value: bool) -> ContextFact:
    return ContextFact(
        key="authority.other-legal-orders",
        value=value,
        category="existing-programs",
        source="citizen-answer",
        provenance="citizen-answer",
        verified_at="2026-10-28T00:00:00Z",
        sensitivity="protected-b",
        consent_scope="existing-programs.read",
        mutable_by_citizen=True,
    )


def summary_text(summary) -> str:
    return json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True)


def test_guardianship_definition_is_strict_and_aligned_to_current_flow_scopes():
    assert GUARDIANSHIP_FLOW.flow_id == "guardianship-intake"
    assert GUARDIANSHIP_FLOW.persona_branches[0].persona_id == "maya-caregiver"
    assert GUARDIANSHIP_FLOW.persona_branches[0].branch == "adult"
    assert GUARDIANSHIP_FLOW.required_scopes == REQUIRED_SCOPES
    assert GUARDIANSHIP_FLOW.optional_scopes == ("region-preferences.read",)
    assert GUARDIANSHIP_FLOW.all_scopes == FLOW_SCOPES["guardianship-intake"]
    assert GUARDIANSHIP_FLOW.all_scopes == ALL_SCOPES
    assert [item.program_id for item in GUARDIANSHIP_FLOW.programs] == [
        "family-social-supports-navigation",
        "service-bc-assisted-navigation",
    ]
    assert [item.required_source_ids for item in GUARDIANSHIP_FLOW.programs] == [
        ("family-social-supports",),
        ("service-bc",),
    ]
    with pytest.raises(FrozenInstanceError):
        GUARDIANSHIP_FLOW.flow_id = "changed"


def test_adult_child_intent_contract_and_maya_mapping():
    unclear = resolve_guardianship_intent("I need to apply for guardianship.")
    assert unclear.branch == "clarify"
    assert unclear.clarification_question == (
        "Is this request about an adult, including an older parent, or a child?"
    )

    maya = resolve_guardianship_intent(
        "I need to apply for guardianship.",
        persona_id=MAYA_PERSONA_ID,
    )
    assert maya.branch == "adult"
    assert maya.source == "persona-mapping"
    assert maya.supported is True

    adult = resolve_guardianship_intent("This is for my older parent.")
    assert adult.branch == "adult"
    assert adult.supported is True

    child = resolve_guardianship_intent("This is about a child under 19.")
    assert child.branch == "child"
    assert child.supported is False
    assert "adult rules" in child.guidance

    mixed = resolve_guardianship_intent("My adult son needs help.")
    assert mixed.branch == "clarify"


def test_maya_known_and_missing_branches_ask_one_public_safe_question():
    facts = maya_facts()
    matches = rule_matches(facts)
    assert [match.status for match in matches] == ["potential-match", "potential-match"]

    missing_summary = build_guardianship_intake_summary(facts, matches)
    assert missing_summary.synthetic_label == SYNTHETIC_LABEL
    assert missing_summary.next_question is not None
    assert missing_summary.next_question.public_key == "other-authority-record"
    assert missing_summary.next_question.question.count("?") == 1

    known_summary = build_guardianship_intake_summary(
        [*facts, citizen_authority_answer(False)],
        matches,
    )
    assert known_summary.next_question is None
    assert known_summary.sections[0].items[0] == (
        "Older adult parent in the adult information pathway"
    )
    assert known_summary.sections[1].items == ("Adult child supporting a parent",)
    assert "does not prove" in known_summary.sections[2].items[0]


def test_rule_missing_fact_uses_engine_public_key_and_never_raw_key():
    facts = [fact for fact in maya_facts() if fact.key != "caregiving.immediate-safety-event"]
    matches = rule_matches(facts)
    assert matches[0].status == "needs-information"
    assert matches[0].missing_facts == ["safety-check"]

    summary = build_guardianship_intake_summary(facts, matches)
    assert summary.next_question is not None
    assert summary.next_question.public_key == "safety-check"
    assert summary.next_question.urgent is True
    assert summary.next_question.question == (
        "Is anyone in immediate danger or at risk of harm right now?"
    )

    raw_key = "caregiving.immediate-safety-event"
    with pytest.raises(GuardianshipPolicyError) as error:
        next_guardianship_question([raw_key])
    assert raw_key not in str(error.value)


def test_urgent_safety_branch_pauses_routine_navigation():
    facts = replace_fact(
        maya_facts(),
        "caregiving.immediate-safety-event",
        True,
    )
    matches = rule_matches(facts)
    assert matches[0].status == "not-indicated"
    assert matches[0].disqualifying_facts == ["urgent-human-support-context"]

    summary = build_guardianship_intake_summary(facts, matches)
    assert summary.urgent_handoff_required is True
    assert summary.next_question is None
    assert summary.related_supports == ()
    assert summary.next_steps[0] == (
        "Pause the routine intake and seek urgent human or emergency support now."
    )
    assert "Pause the routine intake" in summary.sections[3].items[0]


def test_existing_authority_record_is_flagged_without_declaring_legal_authority():
    facts = replace_fact(
        maya_facts(),
        "authority.power-of-attorney-recorded",
        True,
    )
    summary = build_guardianship_intake_summary(facts, rule_matches(facts))
    authority_text = summary.sections[2].items[0]
    assert "existing authority records are noted" in authority_text
    assert "confirm whether each record is current and what it covers" in authority_text
    assert "Maya has authority" not in authority_text
    assert "record is valid" not in authority_text
    assert any("Bring the existing authority record" in step for step in summary.next_steps)


def test_legal_boundaries_and_copy_make_no_positive_high_stakes_claims():
    facts = [*maya_facts(), citizen_authority_answer(False)]
    summary = build_guardianship_intake_summary(facts, rule_matches(facts))
    rendered = "\n".join(
        (
            *summary.legal_boundaries,
            summary.application_preview_review_text,
            summary.consent_checkpoint_text,
            GUARDIANSHIP_AGENT_INSTRUCTIONS,
        )
    )
    assert "not legal advice" in rendered
    assert "cannot determine incapacity" in rendered
    assert "cannot decide or declare that guardianship or committeeship is needed" in rendered
    assert "cannot predict a court outcome" in rendered
    assert "qualified legal or authorized human reviewer" in rendered
    assert "transfers and submits nothing" in rendered
    assert summary.requires_human_review is True
    assert summary.court_submission_enabled is False

    positive_claims = (
        r"\b(?:is|are)\s+eligible\b",
        r"\bguardianship\s+is\s+(?:needed|required)\b",
        r"\b(?:Maya|the caregiver)\s+has\s+legal\s+authority\b",
        r"\bthe adult\s+(?:is|has been)\s+incapable\b",
        r"\bthe court\s+will\b",
        r"\bwas submitted\b",
        r"\bhas been diagnosed\b",
    )
    assert not any(re.search(pattern, rendered, re.IGNORECASE) for pattern in positive_claims)


def test_rule_order_source_requirements_and_related_navigation_are_deterministic():
    matches = rule_matches(maya_facts())
    reordered = ordered_guardianship_matches(reversed(matches))
    assert reordered == tuple(matches)
    assert [match.program_id for match in reordered] == [
        "family-social-supports-navigation",
        "service-bc-assisted-navigation",
    ]

    related = related_guardianship_supports(matches)
    assert len(related) == 1
    assert related[0].label == "Service BC assisted navigation"
    assert related[0].source_label == "Reviewed Service BC source"

    assert related_guardianship_supports(matches[:1]) == ()
    not_indicated = matches[1].model_copy(update={"status": "not-indicated"})
    assert related_guardianship_supports([matches[0], not_indicated]) == ()

    forged = matches[1].model_copy(
        update={
            "source_ids": ["family-social-supports"],
            "source_versions": [matches[0].source_versions[0]],
        }
    )
    with pytest.raises(GuardianshipPolicyError):
        ordered_guardianship_matches([matches[0], forged])


def test_summary_is_deterministic_and_does_not_leak_raw_context():
    facts = [*maya_facts(), citizen_authority_answer(False)]
    matches = rule_matches(facts)
    first = build_guardianship_intake_summary(facts, matches)
    second = build_guardianship_intake_summary(facts, matches)
    assert first == second

    rendered = summary_text(first)
    assert "maya-caregiver" not in rendered
    assert "synthetic-demo-" not in rendered
    assert "household.relationship-to-care-recipient" not in rendered
    assert "caregiving.cognitive-impairment-recorded" not in rendered
    assert "authority.power-of-attorney-recorded" not in rendered
    assert "family-social-supports-navigation" not in rendered
    assert "service-bc-assisted-navigation" not in rendered
    assert '"79"' not in rendered
    assert "High-level fictional record present" not in rendered
    assert "Older adult parent" in rendered
    assert "Adult child supporting a parent" in rendered


def test_preview_and_checkpoint_are_shared_contract_valid_and_review_only():
    facts = maya_facts()
    first = build_guardianship_preview(
        facts,
        preview_id="preview-maya-guardianship",
        expires_at="2026-10-28T00:30:00Z",
    )
    second = build_guardianship_preview(
        facts,
        preview_id="preview-maya-guardianship",
        expires_at="2026-10-28T00:30:00Z",
    )
    assert first == second
    assert first.flow_id == FLOW_ID
    assert first.submission_enabled is False
    assert first.requires_human_review is True
    assert [field.field for field in first.fields] == [
        "relationship",
        "care-recipient-residency",
        "immediate-safety-event",
        "power-of-attorney-record",
        "representation-agreement-record",
        "service-region",
        "capacity-assessment-status",
    ]
    capacity = first.fields[-1]
    assert capacity.source == "missing"
    assert capacity.value is None
    assert "qualified reviewer" in first.missing_items[-1]

    checkpoint = build_guardianship_consent_checkpoint(
        first,
        granted_scopes=ALL_SCOPES,
        destination_name="B.C. family and social supports",
        destination_url="https://www2.gov.bc.ca/gov/content/family-social-supports",
    )
    assert checkpoint.transfer_mode == "none"
    assert checkpoint.submission_enabled is False
    assert checkpoint.reviewed_by_citizen is False
    assert checkpoint.categories_to_share == [
        "household-dependants",
        "disability-caregiving",
        "existing-programs",
        "region-preferences",
    ]
    assert checkpoint.destination_url.endswith("/family-social-supports")

    adapter = TypeAdapter(ContextArtifact)
    preview_artifact = ApplicationPreviewArtifact(
        id="guardianship-preview-artifact",
        payload=first,
    )
    consent_artifact = ConsentRequestArtifact(
        id="guardianship-consent-artifact",
        payload=checkpoint,
    )
    assert adapter.validate_python(preview_artifact.model_dump()).kind == "application-preview"
    assert adapter.validate_python(consent_artifact.model_dump()).kind == "consent-request"

    assert "not a court form" in APPLICATION_PREVIEW_REVIEW_TEXT
    assert "transfers and submits nothing" in CONSENT_CHECKPOINT_TEXT


def test_optional_region_scope_can_be_declined_without_broadening_required_access():
    preview = build_guardianship_preview(
        maya_facts(),
        preview_id="preview-maya-required-scopes",
        expires_at="2026-10-28T00:30:00Z",
    )
    checkpoint = build_guardianship_consent_checkpoint(
        preview,
        granted_scopes=REQUIRED_SCOPES,
        destination_name="B.C. family and social supports",
        destination_url="https://www2.gov.bc.ca/gov/content/family-social-supports",
    )
    assert checkpoint.categories_to_share == [
        "household-dependants",
        "disability-caregiving",
        "existing-programs",
    ]

    with pytest.raises(GuardianshipPolicyError):
        build_guardianship_consent_checkpoint(
            preview,
            granted_scopes=("household.read",),
            destination_name="B.C. family and social supports",
            destination_url="https://www2.gov.bc.ca/gov/content/family-social-supports",
        )

    with pytest.raises(GuardianshipPolicyError):
        build_guardianship_consent_checkpoint(
            preview,
            granted_scopes=REQUIRED_SCOPES,
            destination_name="B.C. family and social supports",
            destination_url=(
                "https://www2.gov.bc.ca/gov/content/family-social-supports?person=Maya"
            ),
        )
