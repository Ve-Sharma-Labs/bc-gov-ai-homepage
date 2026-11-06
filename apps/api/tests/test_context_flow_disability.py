import json
import re
from datetime import date

import pytest
from pydantic import TypeAdapter

from bc_api.context_flows.disability import (
    DISABILITY_FLOW,
    EXPECTED_FLOW_SCOPES,
    PERSONA_FLOW,
    UnsafeDisabilityFlowInput,
    build_application_artifacts,
    build_application_package,
    build_program_matches_artifact,
    clarify_request,
    next_missing_prompt,
    present_program_matches,
    public_missing_keys,
)
from bc_api.context_tools import FLOW_SCOPES
from bc_api.demo_personas import CONSENT_SCOPE_BY_CATEGORY, DemoPersonaRepository
from bc_api.demo_rules import (
    DemoProgramRuleEngine,
    RuleEvaluationEvidence,
    load_demo_program_rule_set,
    reviewed_source_versions,
)
from bc_api.models import ContextArtifact, ContextFact

NOW = date(2026, 11, 5)
EXPIRES_AT = "2026-11-05T20:30:00Z"


def _alex() -> tuple[list[ContextFact], tuple[str, ...]]:
    persona = DemoPersonaRepository().get("alex-disability-support")
    facts = [
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
    raw_missing = [
        key
        for group in persona.category_facts
        if CONSENT_SCOPE_BY_CATEGORY[group.category] in EXPECTED_FLOW_SCOPES
        for key in group.missing_fact_keys
    ]
    return facts, public_missing_keys(raw_missing)


def _evidence() -> RuleEvaluationEvidence:
    rule_set = load_demo_program_rule_set()
    return RuleEvaluationEvidence(
        rule_set_version=rule_set.rule_set_version,
        policy_effective_date=NOW,
        evaluated_at=NOW,
        source_versions=reviewed_source_versions(rule_set),
    )


def _evaluate(facts: list[ContextFact]):
    return DemoProgramRuleEngine().evaluate(
        flow_id=DISABILITY_FLOW.flow_id,
        context_facts=facts,
        evidence=_evidence(),
    )


def _replace_fact(
    facts: list[ContextFact],
    key: str,
    value: str | bool,
) -> list[ContextFact]:
    return [
        ContextFact.model_validate({**fact.model_dump(), "value": value})
        if fact.key == key
        else fact
        for fact in facts
    ]


def test_definition_maps_alex_and_partitions_exact_shared_flow_scopes():
    assert DISABILITY_FLOW.flow_id == "disability-support"
    assert DISABILITY_FLOW.persona_id == "alex-disability-support"
    assert PERSONA_FLOW == {"alex-disability-support": "disability-support"}
    assert DISABILITY_FLOW.consent.required == (
        "identity.read",
        "employment.read",
        "disability-caregiving.read",
        "existing-programs.read",
    )
    assert DISABILITY_FLOW.consent.optional == ("region-preferences.read",)
    assert DISABILITY_FLOW.consent.required + DISABILITY_FLOW.consent.optional == tuple(
        FLOW_SCOPES["disability-support"]
    )
    assert DISABILITY_FLOW.consent.required + DISABILITY_FLOW.consent.optional == (
        EXPECTED_FLOW_SCOPES
    )


def test_ambiguous_request_asks_one_question_and_only_provincial_choices_enter_demo():
    ambiguous = clarify_request()
    assert ambiguous.requires_clarification is True
    assert ambiguous.question == "Which kind of disability support are you looking for?"
    assert ambiguous.question.count("?") == 1
    assert [choice.intent for choice in ambiguous.choices] == [
        "provincial-assistance",
        "provincial-designation",
        "federal-benefits",
        "workplace-accommodation",
        "other",
    ]

    assert clarify_request("provincial-assistance").route == "provincial-navigation"
    assert clarify_request("provincial-designation").route == "provincial-navigation"
    for intent in ("federal-benefits", "workplace-accommodation", "other"):
        assert clarify_request(intent).route == "official-source-handoff"
    with pytest.raises(UnsafeDisabilityFlowInput, match="reviewed"):
        clarify_request("diagnose-me")


def test_alex_known_and_missing_rule_branches_use_public_safe_single_questions():
    facts, _ = _alex()
    known = _evaluate(facts)
    assert [match.status for match in known] == ["potential-match", "potential-match"]

    missing_function = [
        fact for fact in facts if fact.key != "disability.functional-capacity"
    ]
    missing = _evaluate(missing_function)
    primary = next(
        match
        for match in missing
        if match.program_id == "provincial-disability-support-navigation"
    )
    assert primary.status == "needs-information"
    assert primary.missing_facts == ["functional-capacity-category"]
    prompt = next_missing_prompt(primary.missing_facts)
    assert prompt is not None
    assert prompt.key == "functional-capacity-category"
    assert prompt.question.count("?") == 1
    assert "qualified practitioner" in prompt.question.casefold()
    assert "reduced" not in prompt.question.casefold()


def test_alex_preview_has_required_sections_and_practitioner_missing_branch():
    facts, missing_keys = _alex()
    package = build_application_package(
        facts,
        preview_id="preview-alex-disability",
        expires_at=EXPIRES_AT,
        missing_fact_keys=missing_keys,
    )
    fields = {field.field: field for field in package.preview.fields}

    assert [section.title for section in package.sections] == [
        "Identity and residency",
        "Employment and income summary",
        "Existing benefits",
        "Qualified practitioner-completed section",
    ]
    assert fields["adult-status"].value == "18 or older"
    assert fields["bc-residency"].value == "B.C. resident"
    assert fields["employment-status"].value == "Part-time employment"
    assert fields["income-band"].value == "Low-to-moderate range"
    assert fields["current-disability-support"].value == "Not currently receiving"
    assert fields["practitioner-access"].value == "Access recorded"
    assert fields["practitioner-section"].source == "missing"
    assert fields["practitioner-section"].value is None
    assert (
        "A qualified practitioner must complete the practitioner section."
        in package.missing_evidence
    )
    prompt = next_missing_prompt(["practitioner-section-status"])
    assert prompt is not None
    assert prompt.question == (
        "Has a qualified practitioner completed the practitioner section?"
    )


def test_match_and_related_support_presentation_order_is_deterministic():
    facts, _ = _alex()
    matches = _evaluate(facts)
    first = present_program_matches(list(reversed(matches)))
    second = present_program_matches(matches)

    assert first == second
    assert [(item.program_id, item.role) for item in first] == [
        ("provincial-disability-support-navigation", "primary-navigation"),
        ("service-bc-assisted-navigation", "related-navigation"),
    ]
    assert all(item.notice.endswith("not an eligibility decision.") for item in first)


def test_already_enrolled_result_does_not_claim_new_approval():
    facts, _ = _alex()
    enrolled = _replace_fact(
        facts,
        "programs.provincial-disability-assistance",
        "receiving",
    )
    result = DemoProgramRuleEngine().evaluate(
        flow_id=DISABILITY_FLOW.flow_id,
        context_facts=enrolled,
        evidence=_evidence(),
        program_ids=["provincial-disability-support-navigation"],
    )
    presentation = present_program_matches(result)[0]

    assert presentation.status == "already-enrolled"
    assert "synthetic demo record" in presentation.summary.casefold()
    assert "existing support" in presentation.summary.casefold()
    assert "not a new approval" in presentation.summary.casefold()
    assert not re.search(
        r"\byou (?:are|have been) (?:eligible|approved|enrolled)\b",
        presentation.summary,
        re.IGNORECASE,
    )


def test_medical_and_handoff_language_stays_within_review_only_boundaries():
    facts, missing_keys = _alex()
    package = build_application_package(
        facts,
        preview_id="preview-alex-boundaries",
        expires_at=EXPIRES_AT,
        missing_fact_keys=missing_keys,
    )
    text = " ".join(
        (
            package.medical_boundary,
            package.citizen_review.instruction,
            DISABILITY_FLOW.handoff.notice,
        )
    )

    assert set(DISABILITY_FLOW.boundaries) == {
        "diagnosis",
        "functional-capacity-judgment",
        "practitioner-impersonation",
        "eligibility-decision",
        "benefit-amount",
        "submission-claim",
        "approval-claim",
    }
    assert "qualified practitioner" in text.casefold()
    assert "does not include a diagnosis" in text.casefold()
    assert "has not been submitted" in text.casefold()
    assert "no preview values are sent" in text.casefold()
    assert package.preview.submission_enabled is False
    assert package.preview.requires_human_review is True
    assert package.citizen_review.reviewed_by_citizen is False
    assert DISABILITY_FLOW.handoff.transfer_mode == "none"
    assert DISABILITY_FLOW.handoff.submission_enabled is False
    assert not re.search(r"\byou (?:qualify|are eligible|are approved)\b", text, re.IGNORECASE)


def test_unreviewed_raw_context_and_rule_labels_never_leak_to_public_output():
    facts, missing_keys = _alex()
    secret = "PRIVATE_PROMPT_INJECTION_MARKER"
    poisoned = _replace_fact(facts, "employment.status", secret)
    poisoned.append(
        ContextFact(
            key="context.private-note",
            value=secret,
            category="identity-residency",
            source="synthetic-demo-identity-registry",
            provenance="synthetic-government-record",
            verified_at="2026-10-28T00:00:00Z",
            sensitivity="protected-b",
            consent_scope="identity.read",
            mutable_by_citizen=False,
        )
    )
    package = build_application_package(
        poisoned,
        preview_id="preview-alex-redacted",
        expires_at=EXPIRES_AT,
        missing_fact_keys=missing_keys,
    )
    serialized = package.model_dump_json(by_alias=True)
    employment = next(
        field for field in package.preview.fields if field.field == "employment-status"
    )
    assert employment.source == "missing"
    assert secret not in serialized
    assert "disability.functional-capacity" not in serialized
    assert "disability.duration-band" not in serialized

    match = _evaluate(facts)[0]
    injected = match.model_validate(
        {
            **match.model_dump(by_alias=True),
            "satisfiedConditions": [secret.lower()],
        }
    )
    assert secret.lower() not in present_program_matches([injected])[0].model_dump_json()

    with pytest.raises(UnsafeDisabilityFlowInput) as failure:
        public_missing_keys(["private.raw.context.key"])
    assert "private.raw.context.key" not in str(failure.value)


def test_preview_match_and_handoff_artifacts_validate_shared_contracts():
    facts, missing_keys = _alex()
    matches = _evaluate(facts)
    package = build_application_package(
        facts,
        preview_id="preview-alex-contract",
        expires_at=EXPIRES_AT,
        missing_fact_keys=missing_keys,
    )
    match_artifact = build_program_matches_artifact(
        list(reversed(matches)),
        artifact_id="program-matches-alex",
    )
    preview_artifact, handoff_artifact = build_application_artifacts(
        package,
        preview_artifact_id="application-preview-alex",
        consent_artifact_id="consent-request-alex",
        checkpoint_id="checkpoint-alex",
    )
    adapter = TypeAdapter(ContextArtifact)

    parsed = [
        adapter.validate_python(artifact.model_dump(by_alias=True))
        for artifact in (match_artifact, preview_artifact, handoff_artifact)
    ]
    assert [artifact.kind for artifact in parsed] == [
        "program-matches",
        "application-preview",
        "consent-request",
    ]
    assert [match.program_id for match in match_artifact.payload] == [
        "provincial-disability-support-navigation",
        "service-bc-assisted-navigation",
    ]
    assert preview_artifact.payload.flow_id == "disability-support"
    assert handoff_artifact.payload.transfer_mode == "none"
    assert handoff_artifact.payload.submission_enabled is False
    assert handoff_artifact.payload.reviewed_by_citizen is False
    serialized = json.dumps(
        [artifact.model_dump(mode="json", by_alias=True) for artifact in parsed]
    )
    assert "no real government records" not in serialized.casefold()
    assert "PRIVATE_PROMPT_INJECTION_MARKER" not in serialized
