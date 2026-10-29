"""High-stakes adult guardianship and caregiving policy for the Maya demo flow."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast
from urllib.parse import urlsplit

from bc_api.models import (
    ApplicationPreview,
    ConsentRequest,
    ConsentScope,
    ContextCategory,
    ContextFact,
    PreviewField,
    ProgramMatch,
)

GuardianshipIntentBranch = Literal["adult", "child", "clarify"]
GuardianshipIntentSource = Literal[
    "explicit-message",
    "persona-mapping",
    "clarification-required",
]
DiscoveryRole = Literal["primary-navigation", "related-navigation"]
FactSensitivity = Literal["personal", "protected-a", "protected-b"]

FLOW_ID = "guardianship-intake"
MAYA_PERSONA_ID = "maya-caregiver"
FLOW_PURPOSE = "personalize-guardianship-navigation"
SYNTHETIC_LABEL = "Synthetic demo — no real government records are accessed."
SUPPORTED_FLOW_IDS = (FLOW_ID,)
PERSONA_FLOW_MAPPING = MappingProxyType({MAYA_PERSONA_ID: FLOW_ID})

REQUIRED_SCOPES: tuple[ConsentScope, ...] = (
    "household.read",
    "disability-caregiving.read",
    "existing-programs.read",
)
OPTIONAL_SCOPES: tuple[ConsentScope, ...] = ("region-preferences.read",)
ALL_SCOPES: tuple[ConsentScope, ...] = (*REQUIRED_SCOPES, *OPTIONAL_SCOPES)

LEGAL_BOUNDARIES = (
    "This is general service-navigation information, not legal advice.",
    "The assistant cannot determine incapacity or make a medical or cognitive finding.",
    "The assistant cannot decide or declare that guardianship or committeeship is needed.",
    "The assistant cannot predict a court outcome, prepare a court filing, or submit "
    "anything to a court.",
    "A qualified legal or authorized human reviewer must review the situation and any next step.",
)

APPLICATION_PREVIEW_REVIEW_TEXT = (
    "Review this guardianship intake summary with a qualified legal or authorized human "
    "reviewer. It is not a court form, filing, legal opinion, or capacity decision. Confirm "
    "each item and use it only to prepare for a conversation with the official service."
)

CONSENT_CHECKPOINT_TEXT = (
    "Review the listed categories and fields before continuing. This synthetic demo transfers "
    "and submits nothing. Continue to the reviewed official service yourself, then obtain the "
    "required legal or human review."
)

URGENT_SAFETY_TEXT = (
    "An immediate safety concern is reported. Pause the routine intake and seek urgent human "
    "or emergency support now. Return to the legal-information pathway only after the immediate "
    "safety concern is addressed."
)


class GuardianshipPolicyError(ValueError):
    """A flow input or deterministic result did not satisfy the guardianship policy."""


@dataclass(frozen=True, slots=True)
class PersonaBranchPolicy:
    persona_id: str
    branch: Literal["adult"]
    public_description: str


@dataclass(frozen=True, slots=True)
class MissingFactPrompt:
    public_key: str
    question: str
    purpose: str
    urgent: bool = False


@dataclass(frozen=True, slots=True)
class ProgramPolicy:
    order: int
    program_id: str
    rule_id: str
    role: DiscoveryRole
    display_label: str
    required_source_ids: tuple[str, ...]
    source_label: str


@dataclass(frozen=True, slots=True)
class PreviewFieldPolicy:
    field: str
    label: str
    fact_key: str
    missing_sensitivity: FactSensitivity
    missing_item: str
    populate_from_context: bool = True


@dataclass(frozen=True, slots=True)
class DocumentCategory:
    key: str
    title: str
    guidance: str
    declared_required: Literal[False] = False


@dataclass(frozen=True, slots=True)
class GuardianshipFlowDefinition:
    flow_id: str
    purpose: str
    persona_branches: tuple[PersonaBranchPolicy, ...]
    required_scopes: tuple[ConsentScope, ...]
    optional_scopes: tuple[ConsentScope, ...]
    intent_clarification_question: str
    legal_boundaries: tuple[str, ...]
    missing_fact_prompts: tuple[MissingFactPrompt, ...]
    summary_section_order: tuple[str, ...]
    document_categories: tuple[DocumentCategory, ...]
    programs: tuple[ProgramPolicy, ...]
    preview_fields: tuple[PreviewFieldPolicy, ...]
    application_preview_review_text: str
    consent_checkpoint_text: str
    synthetic_label: str
    agent_instructions: str

    @property
    def all_scopes(self) -> tuple[ConsentScope, ...]:
        return (*self.required_scopes, *self.optional_scopes)


@dataclass(frozen=True, slots=True)
class IntentResolution:
    branch: GuardianshipIntentBranch
    source: GuardianshipIntentSource
    supported: bool
    clarification_question: str | None
    guidance: str


@dataclass(frozen=True, slots=True)
class IntakeSection:
    key: str
    title: str
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NavigationResult:
    label: str
    status_label: str
    explanation: str
    source_label: str
    navigation_ready: bool


@dataclass(frozen=True, slots=True)
class GuardianshipIntakeSummary:
    synthetic_label: str
    title: str
    sections: tuple[IntakeSection, ...]
    document_categories: tuple[DocumentCategory, ...]
    primary_navigation: NavigationResult
    related_supports: tuple[NavigationResult, ...]
    next_question: MissingFactPrompt | None
    next_steps: tuple[str, ...]
    legal_boundaries: tuple[str, ...]
    application_preview_review_text: str
    consent_checkpoint_text: str
    urgent_handoff_required: bool
    requires_human_review: Literal[True] = True
    court_submission_enabled: Literal[False] = False


MISSING_FACT_PROMPTS = (
    MissingFactPrompt(
        public_key="safety-check",
        question="Is anyone in immediate danger or at risk of harm right now?",
        purpose="Establish whether routine intake must pause for urgent human support.",
        urgent=True,
    ),
    MissingFactPrompt(
        public_key="adult-or-child",
        question="Is this request about an adult, including an older parent, or a child?",
        purpose="Select the adult or child information pathway without making a legal decision.",
    ),
    MissingFactPrompt(
        public_key="caregiving-relationship",
        question="What is your relationship to the adult you are supporting?",
        purpose="Describe the caregiving relationship in the review-only intake summary.",
    ),
    MissingFactPrompt(
        public_key="care-recipient-residency",
        question="Does the adult you are supporting live in B.C.?",
        purpose="Select reviewed B.C. service-navigation information.",
    ),
    MissingFactPrompt(
        public_key="existing-authority-records",
        question=(
            "Is there already a power of attorney, representation agreement, court order, "
            "committee order, or other authority record that may apply?"
        ),
        purpose="Flag existing records for qualified review without deciding their legal effect.",
    ),
    MissingFactPrompt(
        public_key="other-authority-record",
        question=(
            "Besides the records already noted, are you aware of any court order or other "
            "legal authority that may apply?"
        ),
        purpose="Avoid assuming the synthetic record is a complete statement of authority.",
    ),
    MissingFactPrompt(
        public_key="service-region",
        question="Which B.C. service region would be easiest for in-person or phone support?",
        purpose="Consider related human-service navigation only when the rule returns it.",
    ),
)

PROGRAM_POLICIES = (
    ProgramPolicy(
        order=1,
        program_id="family-social-supports-navigation",
        rule_id="caregiver-support-navigation-v1",
        role="primary-navigation",
        display_label="Family and social supports navigation",
        required_source_ids=("family-social-supports",),
        source_label="Reviewed B.C. family and social supports source",
    ),
    ProgramPolicy(
        order=2,
        program_id="service-bc-assisted-navigation",
        rule_id="caregiver-service-bc-navigation-v1",
        role="related-navigation",
        display_label="Service BC assisted navigation",
        required_source_ids=("service-bc",),
        source_label="Reviewed Service BC source",
    ),
)

PREVIEW_FIELDS = (
    PreviewFieldPolicy(
        field="relationship",
        label="Relationship to the person receiving care",
        fact_key="household.relationship-to-care-recipient",
        missing_sensitivity="personal",
        missing_item="Confirm the relationship to the adult receiving care.",
    ),
    PreviewFieldPolicy(
        field="care-recipient-residency",
        label="Care recipient B.C. residency",
        fact_key="caregiving.care-recipient-bc-resident",
        missing_sensitivity="personal",
        missing_item="Confirm whether the adult receiving care lives in B.C.",
    ),
    PreviewFieldPolicy(
        field="immediate-safety-event",
        label="Immediate safety concern",
        fact_key="caregiving.immediate-safety-event",
        missing_sensitivity="protected-b",
        missing_item="Confirm immediate safety before routine navigation continues.",
    ),
    PreviewFieldPolicy(
        field="power-of-attorney-record",
        label="Power of attorney record",
        fact_key="authority.power-of-attorney-recorded",
        missing_sensitivity="protected-a",
        missing_item="Confirm whether a power of attorney record may apply.",
    ),
    PreviewFieldPolicy(
        field="representation-agreement-record",
        label="Representation agreement record",
        fact_key="authority.representation-agreement-recorded",
        missing_sensitivity="protected-a",
        missing_item="Confirm whether a representation agreement record may apply.",
    ),
    PreviewFieldPolicy(
        field="service-region",
        label="Preferred service region",
        fact_key="region.service-area",
        missing_sensitivity="personal",
        missing_item="Confirm the preferred service region if related human help is wanted.",
    ),
    PreviewFieldPolicy(
        field="capacity-assessment-status",
        label="Professional capacity information",
        fact_key="caregiving.capacity-assessment-status",
        missing_sensitivity="protected-b",
        missing_item=(
            "If professional capacity information already exists, a qualified reviewer must "
            "decide whether it is relevant."
        ),
        populate_from_context=False,
    ),
)

DOCUMENT_CATEGORIES = (
    DocumentCategory(
        key="existing-authority-records",
        title="Existing authority records",
        guidance=(
            "Locate any existing power of attorney, representation agreement, court or "
            "committee order, or other authority record. Do not assume a record is current "
            "or sufficient."
        ),
    ),
    DocumentCategory(
        key="identity-residency-records",
        title="Identity and residency records",
        guidance=(
            "Locate only the identity or residency records the official service or qualified "
            "reviewer asks to see."
        ),
    ),
    DocumentCategory(
        key="care-safety-information",
        title="Existing care and safety information",
        guidance=(
            "Bring existing notes or records that may help a reviewer understand immediate "
            "needs; do not create medical or cognitive findings."
        ),
    ),
    DocumentCategory(
        key="professional-information",
        title="Existing professional information",
        guidance=(
            "If an assessment or professional note already exists, a qualified reviewer "
            "decides whether it is relevant."
        ),
    ),
)

GUARDIANSHIP_AGENT_INSTRUCTIONS = """Flow: guardianship-intake.
This module supports the Maya synthetic persona on the adult/older-parent branch. If the
conversation does not establish whether the request concerns an adult or a child, ask only:
"Is this request about an adult, including an older parent, or a child?" Do not apply adult
rules to a child request.

Use only the consent scopes and immutable rule results supplied by the server. Ask at most one
missing-fact question at a time, and only from this flow's public-safe question allowlist. Never
repeat raw fact keys, source-system names, identifiers, or hidden context values in prose.

This is service navigation, not legal advice. Never determine incapacity, make a medical or
cognitive finding, declare that guardianship or committeeship is needed, predict a court
outcome, prepare a court filing, or submit anything. Mandatory qualified legal or authorized
human review is the end state.

Present the output as a review-only guardianship intake summary: person concerned, relationship,
existing authority records, immediate safety, document categories to locate, and questions for
the reviewer. Do not invent court-form fields, evidence requirements, or legal criteria. Keep
the synthetic label visible and use plain language.

Preserve deterministic program order. The family and social supports navigation result is
primary. Service BC is related support and may be mentioned only when its rule result is present
and is not "not indicated." Keep every status and source requirement unchanged.

Describe the application preview as an intake-summary review aid, never as an application or
court document. At the consent checkpoint, state that this demo transfers and submits nothing,
then hand off to the reviewed official service and a qualified human reviewer.
"""
GUARDIANSHIP_POLICY_INSTRUCTIONS = GUARDIANSHIP_AGENT_INSTRUCTIONS

GUARDIANSHIP_FLOW = GuardianshipFlowDefinition(
    flow_id=FLOW_ID,
    purpose=FLOW_PURPOSE,
    persona_branches=(
        PersonaBranchPolicy(
            persona_id=MAYA_PERSONA_ID,
            branch="adult",
            public_description="Synthetic adult/older-parent caregiving branch",
        ),
    ),
    required_scopes=REQUIRED_SCOPES,
    optional_scopes=OPTIONAL_SCOPES,
    intent_clarification_question=MISSING_FACT_PROMPTS[1].question,
    legal_boundaries=LEGAL_BOUNDARIES,
    missing_fact_prompts=MISSING_FACT_PROMPTS,
    summary_section_order=(
        "person-concerned",
        "relationship",
        "existing-authority",
        "immediate-risk",
        "documents-to-locate",
        "questions-for-reviewer",
    ),
    document_categories=DOCUMENT_CATEGORIES,
    programs=PROGRAM_POLICIES,
    preview_fields=PREVIEW_FIELDS,
    application_preview_review_text=APPLICATION_PREVIEW_REVIEW_TEXT,
    consent_checkpoint_text=CONSENT_CHECKPOINT_TEXT,
    synthetic_label=SYNTHETIC_LABEL,
    agent_instructions=GUARDIANSHIP_AGENT_INSTRUCTIONS,
)
GUARDIANSHIP_FLOW_POLICY = GUARDIANSHIP_FLOW

_QUESTION_BY_KEY = {item.public_key: item for item in MISSING_FACT_PROMPTS}
_QUESTION_ORDER = {item.public_key: index for index, item in enumerate(MISSING_FACT_PROMPTS)}
_PROGRAM_BY_ID = {item.program_id: item for item in PROGRAM_POLICIES}
_PREVIEW_BY_FIELD = {item.field: item for item in PREVIEW_FIELDS}

_CHILD_INTENT = re.compile(
    r"\b(?:child|minor|youth|kid|under\s+19|son|daughter)\b",
    re.IGNORECASE,
)
_ADULT_INTENT = re.compile(
    r"\b(?:adult|older\s+parent|aging\s+parent|older\s+person|senior|elder|"
    r"mother|father|mom|dad)\b",
    re.IGNORECASE,
)

_FACT_SCOPE: dict[str, ConsentScope] = {
    "household.relationship-to-care-recipient": "household.read",
    "caregiving.care-recipient-age-years": "disability-caregiving.read",
    "caregiving.care-recipient-bc-resident": "disability-caregiving.read",
    "caregiving.immediate-safety-event": "disability-caregiving.read",
    "authority.power-of-attorney-recorded": "existing-programs.read",
    "authority.representation-agreement-recorded": "existing-programs.read",
    "authority.other-legal-orders": "existing-programs.read",
    "region.service-area": "region-preferences.read",
}

_RELATIONSHIP_LABELS = {
    "adult-child": "Adult child supporting a parent",
    "spouse": "Spouse or partner supporting an adult",
    "other-family": "Family member supporting an adult",
    "friend": "Friend supporting an adult",
}

_STATUS_LABELS = {
    "potential-match": "Potential navigation match",
    "needs-information": "More information needed",
    "already-enrolled": "Existing service record",
    "not-indicated": "Not indicated by current information",
}

_STATUS_EXPLANATIONS = {
    "potential-match": (
        "The deterministic rule returned a possible navigation path. It is not a legal decision."
    ),
    "needs-information": (
        "The deterministic rule needs one or more listed public-safe answers before indicating "
        "this path."
    ),
    "already-enrolled": (
        "The deterministic rule found an existing service record. A human must confirm what "
        "that record covers."
    ),
    "not-indicated": (
        "Current facts did not indicate this navigation path. That is not a legal decision."
    ),
}

_SCOPE_CATEGORY: dict[ConsentScope, ContextCategory] = {
    "household.read": "household-dependants",
    "disability-caregiving.read": "disability-caregiving",
    "existing-programs.read": "existing-programs",
    "region-preferences.read": "region-preferences",
}


def _validate_definition(definition: GuardianshipFlowDefinition) -> None:
    if definition.flow_id != FLOW_ID or definition.purpose != FLOW_PURPOSE:
        raise RuntimeError("The guardianship flow identity is invalid.")
    if definition.persona_branches != (
        PersonaBranchPolicy(
            persona_id=MAYA_PERSONA_ID,
            branch="adult",
            public_description="Synthetic adult/older-parent caregiving branch",
        ),
    ):
        raise RuntimeError("The guardianship persona mapping is invalid.")
    if definition.all_scopes != ALL_SCOPES or len(set(definition.all_scopes)) != len(ALL_SCOPES):
        raise RuntimeError("The guardianship consent policy is invalid.")
    if tuple(item.order for item in definition.programs) != (1, 2):
        raise RuntimeError("The guardianship program order is invalid.")
    if tuple(item.role for item in definition.programs) != (
        "primary-navigation",
        "related-navigation",
    ):
        raise RuntimeError("The guardianship discovery roles are invalid.")
    if tuple(item.required_source_ids for item in definition.programs) != (
        ("family-social-supports",),
        ("service-bc",),
    ):
        raise RuntimeError("The guardianship source policy is invalid.")
    public_keys = tuple(item.public_key for item in definition.missing_fact_prompts)
    if len(set(public_keys)) != len(public_keys) or any("." in key for key in public_keys):
        raise RuntimeError("Guardianship missing-fact prompts must use public-safe keys.")
    if any(not item.question.endswith("?") for item in definition.missing_fact_prompts):
        raise RuntimeError("Guardianship missing-fact prompts must be questions.")
    if len({item.field for item in definition.preview_fields}) != len(definition.preview_fields):
        raise RuntimeError("Guardianship preview fields must be unique.")


_validate_definition(GUARDIANSHIP_FLOW)


def resolve_guardianship_intent(
    message: str,
    *,
    persona_id: str | None = None,
) -> IntentResolution:
    """Resolve only the adult-versus-child branch; make no legal determination."""

    if (
        type(message) is not str
        or not message.strip()
        or len(message) > 2_000
        or not message.isprintable()
    ):
        raise GuardianshipPolicyError("A bounded plain-text request is required.")
    if persona_id not in (None, MAYA_PERSONA_ID):
        raise GuardianshipPolicyError("The persona is not supported by this flow.")

    child = _CHILD_INTENT.search(message) is not None
    adult = _ADULT_INTENT.search(message) is not None
    if child and not adult:
        return IntentResolution(
            branch="child",
            source="explicit-message",
            supported=False,
            clarification_question=None,
            guidance=(
                "This module handles only adult and older-person caregiving. Use reviewed child "
                "guardianship navigation instead; do not reuse the adult rules."
            ),
        )
    if adult and not child:
        return IntentResolution(
            branch="adult",
            source="explicit-message",
            supported=True,
            clarification_question=None,
            guidance=(
                "Use the adult and older-person information pathway, ending with qualified "
                "legal or authorized human review."
            ),
        )
    if not child and not adult and persona_id == MAYA_PERSONA_ID:
        return IntentResolution(
            branch="adult",
            source="persona-mapping",
            supported=True,
            clarification_question=None,
            guidance=(
                "Maya's synthetic demo mapping selects the adult and older-parent information "
                "pathway; it does not decide a legal question."
            ),
        )
    return IntentResolution(
        branch="clarify",
        source="clarification-required",
        supported=False,
        clarification_question=GUARDIANSHIP_FLOW.intent_clarification_question,
        guidance="Ask the single adult-versus-child clarification before using a pathway.",
    )


def next_guardianship_question(
    public_missing_fact_keys: Iterable[str],
) -> MissingFactPrompt | None:
    """Return one deterministic public-safe question and never echo an internal key."""

    if isinstance(public_missing_fact_keys, (str, bytes)):
        raise GuardianshipPolicyError("Public missing-fact keys must be a collection.")
    try:
        keys = tuple(public_missing_fact_keys)
    except TypeError:
        raise GuardianshipPolicyError("Public missing-fact keys must be a collection.") from None
    if any(type(key) is not str or key not in _QUESTION_BY_KEY for key in keys):
        raise GuardianshipPolicyError("A missing-fact key is not public-safe for this flow.")
    if not keys:
        return None
    selected = min(set(keys), key=_QUESTION_ORDER.__getitem__)
    return _QUESTION_BY_KEY[selected]


def _validate_fact_value(key: str, value: object) -> None:
    boolean_keys = {
        "caregiving.care-recipient-bc-resident",
        "caregiving.immediate-safety-event",
        "authority.power-of-attorney-recorded",
        "authority.representation-agreement-recorded",
        "authority.other-legal-orders",
    }
    if key in boolean_keys and type(value) is not bool:
        raise GuardianshipPolicyError("A guardianship context value is invalid.")
    if key == "household.relationship-to-care-recipient" and value not in _RELATIONSHIP_LABELS:
        raise GuardianshipPolicyError("A guardianship context value is invalid.")
    if key == "caregiving.care-recipient-age-years" and (
        type(value) is not int or not 0 <= value <= 120
    ):
        raise GuardianshipPolicyError("A guardianship context value is invalid.")
    if key == "region.service-area" and value not in (
        "Victoria service region",
        "Interior service region",
    ):
        raise GuardianshipPolicyError("A guardianship context value is invalid.")


def _collect_facts(context_facts: Iterable[ContextFact]) -> dict[str, ContextFact]:
    try:
        facts = tuple(context_facts)
    except TypeError:
        raise GuardianshipPolicyError(
            "Guardianship facts must use the typed context contract."
        ) from None
    collected: dict[str, ContextFact] = {}
    for fact in facts:
        if not isinstance(fact, ContextFact):
            raise GuardianshipPolicyError("Guardianship facts must use the typed context contract.")
        expected_scope = _FACT_SCOPE.get(fact.key)
        if expected_scope is None:
            continue
        if fact.key in collected:
            raise GuardianshipPolicyError("A guardianship fact was supplied more than once.")
        if fact.consent_scope != expected_scope or expected_scope not in ALL_SCOPES:
            raise GuardianshipPolicyError("A guardianship fact is outside the flow scope.")
        _validate_fact_value(fact.key, fact.value)
        collected[fact.key] = fact
    return collected


def ordered_guardianship_matches(
    matches: Iterable[ProgramMatch],
    *,
    require_primary: bool = True,
) -> tuple[ProgramMatch, ...]:
    """Validate engine-owned program IDs, rule IDs, sources, and display order."""

    try:
        values = tuple(matches)
    except TypeError:
        raise GuardianshipPolicyError(
            "Guardianship matches must use the typed rule-result contract."
        ) from None
    seen: set[str] = set()
    for match in values:
        if not isinstance(match, ProgramMatch):
            raise GuardianshipPolicyError(
                "Guardianship matches must use the typed rule-result contract."
            )
        policy = _PROGRAM_BY_ID.get(match.program_id)
        if (
            policy is None
            or match.program_id in seen
            or match.rule_id != policy.rule_id
            or tuple(match.source_ids) != policy.required_source_ids
        ):
            raise GuardianshipPolicyError(
                "A guardianship rule result is outside the reviewed flow policy."
            )
        seen.add(match.program_id)
    primary_id = PROGRAM_POLICIES[0].program_id
    if require_primary and primary_id not in seen:
        raise GuardianshipPolicyError("The primary guardianship navigation result is unavailable.")
    return tuple(sorted(values, key=lambda match: _PROGRAM_BY_ID[match.program_id].order))


def _navigation_result(match: ProgramMatch) -> NavigationResult:
    policy = _PROGRAM_BY_ID[match.program_id]
    return NavigationResult(
        label=policy.display_label,
        status_label=_STATUS_LABELS[match.status],
        explanation=_STATUS_EXPLANATIONS[match.status],
        source_label=policy.source_label,
        navigation_ready=match.status in ("potential-match", "already-enrolled"),
    )


def related_guardianship_supports(
    matches: Iterable[ProgramMatch],
) -> tuple[NavigationResult, ...]:
    """Return related navigation only when a reviewed related rule result is present."""

    ordered = ordered_guardianship_matches(matches)
    return tuple(
        _navigation_result(match)
        for match in ordered
        if _PROGRAM_BY_ID[match.program_id].role == "related-navigation"
        and match.status != "not-indicated"
    )


def _derived_missing_public_keys(
    facts: dict[str, ContextFact],
    matches: Sequence[ProgramMatch],
) -> tuple[str, ...]:
    keys: list[str] = [key for match in matches for key in match.missing_facts]
    authority_keys = (
        "authority.power-of-attorney-recorded",
        "authority.representation-agreement-recorded",
    )
    if not any(key in facts for key in authority_keys):
        keys.append("existing-authority-records")
    elif "authority.other-legal-orders" not in facts:
        keys.append("other-authority-record")
    return tuple(
        sorted(
            set(keys),
            key=lambda key: _QUESTION_ORDER.get(key, len(_QUESTION_ORDER)),
        )
    )


def _person_concerned(facts: dict[str, ContextFact]) -> str:
    age_fact = facts.get("caregiving.care-recipient-age-years")
    relationship = facts.get("household.relationship-to-care-recipient")
    if age_fact is not None:
        age = cast(int, age_fact.value)
        if age < 19:
            raise GuardianshipPolicyError("The adult-versus-child pathway requires clarification.")
        if age >= 65 and relationship is not None and relationship.value == "adult-child":
            return "Older adult parent in the adult information pathway"
        return "Adult in the adult information pathway"
    return "Adult pathway selected; age details remain for human confirmation"


def _relationship_summary(facts: dict[str, ContextFact]) -> str:
    fact = facts.get("household.relationship-to-care-recipient")
    if fact is None:
        return "Caregiving relationship needs confirmation"
    return _RELATIONSHIP_LABELS[cast(str, fact.value)]


def _authority_summary(facts: dict[str, ContextFact]) -> str:
    poa = facts.get("authority.power-of-attorney-recorded")
    representation = facts.get("authority.representation-agreement-recorded")
    other = facts.get("authority.other-legal-orders")
    values = tuple(
        cast(bool, fact.value) for fact in (poa, representation, other) if fact is not None
    )
    if any(values):
        return (
            "One or more existing authority records are noted. A qualified legal or "
            "authorized human reviewer must confirm whether each record is current and "
            "what it covers; the assistant does not infer authority."
        )
    if poa is not None and representation is not None and other is not None:
        return (
            "No power of attorney, representation agreement, or other authority record is "
            "recorded or reported for this review. This does not prove that no authority exists."
        )
    if poa is not None and representation is not None:
        return (
            "No power of attorney or representation agreement record is present in the "
            "fictional fixture. Other authority records still need confirmation."
        )
    return "Existing authority records need confirmation by a qualified reviewer."


def _risk_summary(facts: dict[str, ContextFact], urgent: bool) -> str:
    if urgent:
        return URGENT_SAFETY_TEXT
    fact = facts.get("caregiving.immediate-safety-event")
    if fact is None:
        return "Immediate safety needs confirmation before routine navigation continues."
    return (
        "No immediate safety event is recorded in the fictional fixture. Confirm whether "
        "circumstances have changed."
    )


def _next_steps(urgent: bool, authority_present: bool) -> tuple[str, ...]:
    if urgent:
        return (
            "Pause the routine intake and seek urgent human or emergency support now.",
            "Return to the legal-information pathway only after the immediate safety concern "
            "is addressed.",
            "Have a qualified legal or authorized human reviewer handle any later process.",
        )
    steps = [
        "Review the synthetic intake summary and correct any citizen-answer items.",
        "Locate existing records from the document categories; they are not declared requirements.",
        "Use only navigation results returned by the deterministic rules and their reviewed "
        "sources.",
    ]
    if authority_present:
        steps.append(
            "Bring the existing authority record for qualified review of its currency and scope."
        )
    steps.extend(
        (
            "Take the summary to a qualified legal or authorized human reviewer.",
            "Continue to the reviewed official service yourself; the demo transfers and submits "
            "nothing.",
        )
    )
    return tuple(steps)


def build_guardianship_intake_summary(
    context_facts: Iterable[ContextFact],
    matches: Iterable[ProgramMatch],
) -> GuardianshipIntakeSummary:
    """Build plain-language intake copy without making a legal or medical finding."""

    facts = _collect_facts(context_facts)
    ordered_matches = ordered_guardianship_matches(matches)
    primary = next(
        match
        for match in ordered_matches
        if _PROGRAM_BY_ID[match.program_id].role == "primary-navigation"
    )
    safety_fact = facts.get("caregiving.immediate-safety-event")
    urgent = (safety_fact is not None and cast(bool, safety_fact.value)) or (
        "urgent-human-support-context" in primary.disqualifying_facts
    )
    missing_keys = _derived_missing_public_keys(facts, ordered_matches)
    next_question = None if urgent else next_guardianship_question(missing_keys)

    person_items = [_person_concerned(facts)]
    region = facts.get("region.service-area")
    if region is not None:
        person_items.append(f"Preferred human-support area: {region.value}")

    authority_present = any(
        cast(bool, fact.value)
        for key in (
            "authority.power-of-attorney-recorded",
            "authority.representation-agreement-recorded",
            "authority.other-legal-orders",
        )
        if (fact := facts.get(key)) is not None
    )
    reviewer_questions = (
        "What immediate decision or support is being requested?",
        "Which existing authority records apply, and what does a qualified reviewer say "
        "they cover?",
        "Is professional assessment information already available for qualified review?",
        "Which official legal or human service should handle the next step?",
    )
    sections = (
        IntakeSection(
            key="person-concerned",
            title="Person concerned",
            items=tuple(person_items),
        ),
        IntakeSection(
            key="relationship",
            title="Relationship",
            items=(_relationship_summary(facts),),
        ),
        IntakeSection(
            key="existing-authority",
            title="Existing legal authority",
            items=(_authority_summary(facts),),
        ),
        IntakeSection(
            key="immediate-risk",
            title="Immediate safety",
            items=(_risk_summary(facts, urgent),),
        ),
        IntakeSection(
            key="documents-to-locate",
            title="Document categories to locate",
            items=tuple(item.title for item in DOCUMENT_CATEGORIES),
        ),
        IntakeSection(
            key="questions-for-reviewer",
            title="Questions for the qualified reviewer",
            items=reviewer_questions,
        ),
    )
    related = () if urgent else related_guardianship_supports(ordered_matches)
    return GuardianshipIntakeSummary(
        synthetic_label=SYNTHETIC_LABEL,
        title="Guardianship and caregiving intake summary",
        sections=sections,
        document_categories=DOCUMENT_CATEGORIES,
        primary_navigation=_navigation_result(primary),
        related_supports=related,
        next_question=next_question,
        next_steps=_next_steps(urgent, authority_present),
        legal_boundaries=LEGAL_BOUNDARIES,
        application_preview_review_text=APPLICATION_PREVIEW_REVIEW_TEXT,
        consent_checkpoint_text=CONSENT_CHECKPOINT_TEXT,
        urgent_handoff_required=urgent,
    )


def build_guardianship_preview(
    context_facts: Iterable[ContextFact],
    *,
    preview_id: str,
    expires_at: str,
) -> ApplicationPreview:
    """Build the review-only shared preview contract from allowlisted intake fields."""

    facts = _collect_facts(context_facts)
    fields: list[PreviewField] = []
    missing_items: list[str] = []
    for policy in PREVIEW_FIELDS:
        fact = facts.get(policy.fact_key) if policy.populate_from_context else None
        if fact is None:
            fields.append(
                PreviewField(
                    field=policy.field,
                    label=policy.label,
                    value=None,
                    source="missing",
                    source_fact_key=None,
                    editable=True,
                    sensitivity=policy.missing_sensitivity,
                    requires_confirmation=True,
                )
            )
            missing_items.append(policy.missing_item)
            continue
        fields.append(
            PreviewField(
                field=policy.field,
                label=policy.label,
                value=fact.value,
                source=(
                    "synthetic-record"
                    if fact.provenance == "synthetic-government-record"
                    else "citizen-answer"
                ),
                source_fact_key=fact.key,
                editable=fact.mutable_by_citizen,
                sensitivity=fact.sensitivity,
                requires_confirmation=True,
            )
        )
    preview = ApplicationPreview(
        preview_id=preview_id,
        flow_id=FLOW_ID,
        schema_version=1,
        fields=fields,
        missing_items=missing_items,
        submission_enabled=False,
        requires_human_review=True,
        expires_at=expires_at,
    )
    validate_guardianship_preview(preview)
    return preview


def validate_guardianship_preview(preview: ApplicationPreview) -> None:
    if not isinstance(preview, ApplicationPreview) or preview.flow_id != FLOW_ID:
        raise GuardianshipPolicyError("The guardianship preview contract is invalid.")
    if tuple(field.field for field in preview.fields) != tuple(
        item.field for item in PREVIEW_FIELDS
    ):
        raise GuardianshipPolicyError("The guardianship preview field order is invalid.")
    expected_missing: list[str] = []
    for field in preview.fields:
        policy = _PREVIEW_BY_FIELD[field.field]
        if field.label != policy.label or not field.requires_confirmation:
            raise GuardianshipPolicyError("The guardianship preview field policy is invalid.")
        if not policy.populate_from_context and field.source != "missing":
            raise GuardianshipPolicyError(
                "Professional capacity information requires qualified review."
            )
        if field.source == "missing":
            expected_missing.append(policy.missing_item)
        elif field.source_fact_key != policy.fact_key:
            raise GuardianshipPolicyError("The guardianship preview provenance is invalid.")
    if preview.missing_items != expected_missing:
        raise GuardianshipPolicyError("The guardianship preview missing-item list is invalid.")


def build_guardianship_consent_checkpoint(
    preview: ApplicationPreview,
    *,
    granted_scopes: Iterable[ConsentScope],
    destination_name: str,
    destination_url: str,
) -> ConsentRequest:
    """Build a no-transfer checkpoint that ends at an official and human handoff."""

    validate_guardianship_preview(preview)
    if isinstance(granted_scopes, (str, bytes)):
        raise GuardianshipPolicyError("Granted guardianship scopes must be a collection.")
    scopes = tuple(granted_scopes)
    if (
        len(scopes) != len(set(scopes))
        or not set(REQUIRED_SCOPES) <= set(scopes)
        or not set(scopes) <= set(ALL_SCOPES)
    ):
        raise GuardianshipPolicyError("The guardianship consent scopes are invalid.")
    parts = urlsplit(destination_url)
    if parts.query or parts.fragment:
        raise GuardianshipPolicyError("The guardianship handoff URL cannot contain context values.")
    categories = [_SCOPE_CATEGORY[scope] for scope in ALL_SCOPES if scope in set(scopes)]
    populated_fields = [field.field for field in preview.fields if field.source != "missing"]
    return ConsentRequest(
        checkpoint_id=f"checkpoint-{preview.preview_id.removeprefix('preview-')}",
        preview_id=preview.preview_id,
        purpose=FLOW_PURPOSE,
        destination_name=destination_name,
        destination_url=destination_url,
        categories_to_share=categories,
        field_names_to_share=populated_fields,
        transfer_mode="none",
        reviewed_by_citizen=False,
        submission_enabled=False,
    )


__all__ = [
    "ALL_SCOPES",
    "APPLICATION_PREVIEW_REVIEW_TEXT",
    "CONSENT_CHECKPOINT_TEXT",
    "FLOW_ID",
    "FLOW_PURPOSE",
    "GUARDIANSHIP_AGENT_INSTRUCTIONS",
    "GUARDIANSHIP_FLOW",
    "GUARDIANSHIP_FLOW_POLICY",
    "GUARDIANSHIP_POLICY_INSTRUCTIONS",
    "GuardianshipFlowDefinition",
    "GuardianshipIntakeSummary",
    "GuardianshipPolicyError",
    "IntentResolution",
    "MAYA_PERSONA_ID",
    "MissingFactPrompt",
    "OPTIONAL_SCOPES",
    "PERSONA_FLOW_MAPPING",
    "REQUIRED_SCOPES",
    "SUPPORTED_FLOW_IDS",
    "SYNTHETIC_LABEL",
    "build_guardianship_consent_checkpoint",
    "build_guardianship_intake_summary",
    "build_guardianship_preview",
    "next_guardianship_question",
    "ordered_guardianship_matches",
    "related_guardianship_supports",
    "resolve_guardianship_intent",
    "validate_guardianship_preview",
]
