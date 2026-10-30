"""Strict, flow-local policy for the synthetic Alex disability-support demo."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from bc_api.models import (
    SCREENING_NOTICE,
    ApplicationPreview,
    ApplicationPreviewArtifact,
    ConsentRequest,
    ConsentRequestArtifact,
    ConsentScope,
    ContextCategory,
    ContextFact,
    FactSensitivity,
    PreviewField,
    ProgramMatch,
    ProgramMatchesArtifact,
)

DisabilityIntent = Literal[
    "provincial-assistance",
    "provincial-designation",
    "federal-benefits",
    "workplace-accommodation",
    "other",
]
DisabilityRoute = Literal["provincial-navigation", "official-source-handoff"]
ProgramRole = Literal["primary-navigation", "related-navigation"]
PublicMissingKey = Literal[
    "adult-status",
    "bc-residency-status",
    "employment-status",
    "current-income-band",
    "financial-evidence-status",
    "disability-duration-category",
    "functional-capacity-category",
    "practitioner-access",
    "practitioner-section-status",
    "current-disability-support-status",
    "designation-application-status",
    "preferred-service-channel",
    "service-area",
]
BoundaryId = Literal[
    "diagnosis",
    "functional-capacity-judgment",
    "practitioner-impersonation",
    "eligibility-decision",
    "benefit-amount",
    "submission-claim",
    "approval-claim",
]

EXPECTED_FLOW_SCOPES: tuple[ConsentScope, ...] = (
    "identity.read",
    "employment.read",
    "disability-caregiving.read",
    "existing-programs.read",
    "region-preferences.read",
)
SYNTHETIC_LABEL = "Synthetic demo — Alex; no real government records were accessed."
MEDICAL_BOUNDARY = (
    "Only a qualified practitioner can complete the practitioner section. "
    "This preview does not include a diagnosis or a functional-capacity decision."
)


class UnsafeDisabilityFlowInput(ValueError):
    """Untrusted flow input did not match a reviewed allowlist."""


class _StrictFlowModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class ClarificationChoice(_StrictFlowModel):
    intent: DisabilityIntent
    label: Annotated[str, Field(min_length=3, max_length=100)]
    route: DisabilityRoute


class ClarificationContract(_StrictFlowModel):
    question: Annotated[str, Field(min_length=10, max_length=200)]
    choices: tuple[ClarificationChoice, ...]

    @model_validator(mode="after")
    def reviewed_choices(self) -> Self:
        expected = (
            "provincial-assistance",
            "provincial-designation",
            "federal-benefits",
            "workplace-accommodation",
            "other",
        )
        if tuple(choice.intent for choice in self.choices) != expected:
            raise ValueError("Disability clarification choices must use reviewed order.")
        if self.question.count("?") != 1 or not self.question.endswith("?"):
            raise ValueError("The clarification contract must ask exactly one question.")
        if any(
            choice.route != "provincial-navigation"
            for choice in self.choices[:2]
        ) or any(
            choice.route != "official-source-handoff"
            for choice in self.choices[2:]
        ):
            raise ValueError("Only provincial choices may enter the demo flow.")
        return self


class ClarificationDecision(_StrictFlowModel):
    requires_clarification: StrictBool
    question: str | None
    choices: tuple[ClarificationChoice, ...]
    selected_intent: DisabilityIntent | None
    route: DisabilityRoute | None

    @model_validator(mode="after")
    def coherent_decision(self) -> Self:
        if self.requires_clarification:
            if (
                self.question is None
                or not self.choices
                or self.selected_intent is not None
                or self.route is not None
            ):
                raise ValueError("Ambiguous requests must return only the reviewed question.")
        elif (
            self.question is not None
            or self.choices
            or self.selected_intent is None
            or self.route is None
        ):
            raise ValueError("Resolved requests must return only the selected route.")
        return self


class ConsentScopePolicy(_StrictFlowModel):
    required: tuple[ConsentScope, ...]
    optional: tuple[ConsentScope, ...]

    @model_validator(mode="after")
    def exact_flow_scopes(self) -> Self:
        combined = self.required + self.optional
        if combined != EXPECTED_FLOW_SCOPES or len(set(combined)) != len(combined):
            raise ValueError("Consent policy must exactly match the reviewed flow scopes.")
        return self


class MissingFactPrompt(_StrictFlowModel):
    key: PublicMissingKey
    question: Annotated[str, Field(min_length=10, max_length=220)]
    evidence_item: Annotated[str, Field(min_length=10, max_length=220)]

    @model_validator(mode="after")
    def one_question(self) -> Self:
        if self.question.count("?") != 1 or not self.question.endswith("?"):
            raise ValueError("Missing-fact prompts must ask exactly one question.")
        return self


class ProgramPresentationSpec(_StrictFlowModel):
    program_id: Literal[
        "provincial-disability-support-navigation",
        "service-bc-assisted-navigation",
    ]
    rule_id: Literal[
        "disability-support-navigation-v1",
        "disability-service-bc-navigation-v1",
    ]
    title: Annotated[str, Field(min_length=3, max_length=120)]
    role: ProgramRole
    source_id: Literal["family-social-supports", "service-bc"]


class PreviewFieldPolicy(_StrictFlowModel):
    section_id: Literal[
        "identity-residency",
        "employment-income",
        "existing-benefits",
        "qualified-practitioner",
    ]
    field: Literal[
        "adult-status",
        "bc-residency",
        "employment-status",
        "income-band",
        "current-disability-support",
        "practitioner-access",
        "practitioner-section",
    ]
    label: Annotated[str, Field(min_length=3, max_length=120)]
    fact_key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]+$", max_length=100)]
    category: ContextCategory
    scope: ConsentScope
    sensitivity: FactSensitivity
    missing_item: Annotated[str, Field(min_length=10, max_length=220)]


class PreviewSection(_StrictFlowModel):
    section_id: Literal[
        "identity-residency",
        "employment-income",
        "existing-benefits",
        "qualified-practitioner",
    ]
    title: Annotated[str, Field(min_length=3, max_length=120)]
    field_names: tuple[str, ...]


class CitizenReviewCheckpoint(_StrictFlowModel):
    heading: Literal["Citizen review required"] = "Citizen review required"
    instruction: Literal[
        "Review every field and missing-evidence item before opening the official service. "
        "This preview has not been submitted."
    ] = (
        "Review every field and missing-evidence item before opening the official service. "
        "This preview has not been submitted."
    )
    reviewed_by_citizen: Literal[False] = False
    submission_enabled: Literal[False] = False


class OfficialHandoffPolicy(_StrictFlowModel):
    action_label: Literal["Continue to official B.C. disability assistance information"]
    destination_name: Literal["B.C. disability assistance information"]
    destination_url: Literal["https://www2.gov.bc.ca/gov/content/family-social-supports"]
    notice: Literal[
        "This opens the official B.C. website. No preview values are sent, and this demo "
        "does not submit or approve an application."
    ]
    transfer_mode: Literal["none"] = "none"
    submission_enabled: Literal[False] = False


class DisabilityFlowDefinition(_StrictFlowModel):
    flow_id: Literal["disability-support"]
    persona_id: Literal["alex-disability-support"]
    persona_display_name: Literal["Alex"]
    purpose: Literal["personalize-disability-support"]
    synthetic_label: Literal[
        "Synthetic demo — Alex; no real government records were accessed."
    ]
    clarification: ClarificationContract
    consent: ConsentScopePolicy
    boundaries: tuple[BoundaryId, ...]
    medical_boundary: Literal[
        "Only a qualified practitioner can complete the practitioner section. "
        "This preview does not include a diagnosis or a functional-capacity decision."
    ]
    missing_fact_prompts: tuple[MissingFactPrompt, ...]
    programs: tuple[ProgramPresentationSpec, ...]
    preview_fields: tuple[PreviewFieldPolicy, ...]
    preview_sections: tuple[PreviewSection, ...]
    handoff: OfficialHandoffPolicy

    @model_validator(mode="after")
    def reviewed_definition(self) -> Self:
        expected_boundaries = (
            "diagnosis",
            "functional-capacity-judgment",
            "practitioner-impersonation",
            "eligibility-decision",
            "benefit-amount",
            "submission-claim",
            "approval-claim",
        )
        if self.boundaries != expected_boundaries:
            raise ValueError("The disability boundary set must be complete and ordered.")
        if tuple(program.role for program in self.programs) != (
            "primary-navigation",
            "related-navigation",
        ):
            raise ValueError("Primary navigation must precede related support.")
        if len({program.program_id for program in self.programs}) != len(self.programs):
            raise ValueError("Program presentation IDs must be unique.")
        prompt_keys = tuple(prompt.key for prompt in self.missing_fact_prompts)
        if len(set(prompt_keys)) != len(prompt_keys):
            raise ValueError("Public missing-fact keys must be unique.")
        field_names = tuple(field.field for field in self.preview_fields)
        if len(set(field_names)) != len(field_names):
            raise ValueError("Preview field names must be unique.")
        section_fields = tuple(
            field_name
            for section in self.preview_sections
            for field_name in section.field_names
        )
        if section_fields != field_names:
            raise ValueError("Preview sections must cover fields in deterministic order.")
        if any(
            field.section_id != section.section_id
            for section in self.preview_sections
            for field in self.preview_fields
            if field.field in section.field_names
        ):
            raise ValueError("Preview fields must belong to their declared section.")
        return self


DISABILITY_FLOW = DisabilityFlowDefinition(
    flow_id="disability-support",
    persona_id="alex-disability-support",
    persona_display_name="Alex",
    purpose="personalize-disability-support",
    synthetic_label=SYNTHETIC_LABEL,
    clarification=ClarificationContract(
        question="Which kind of disability support are you looking for?",
        choices=(
            ClarificationChoice(
                intent="provincial-assistance",
                label="Provincial disability assistance",
                route="provincial-navigation",
            ),
            ClarificationChoice(
                intent="provincial-designation",
                label="Provincial disability designation",
                route="provincial-navigation",
            ),
            ClarificationChoice(
                intent="federal-benefits",
                label="Federal disability benefit navigation",
                route="official-source-handoff",
            ),
            ClarificationChoice(
                intent="workplace-accommodation",
                label="Workplace accommodation",
                route="official-source-handoff",
            ),
            ClarificationChoice(
                intent="other",
                label="Mobility support or another request",
                route="official-source-handoff",
            ),
        ),
    ),
    consent=ConsentScopePolicy(
        required=(
            "identity.read",
            "employment.read",
            "disability-caregiving.read",
            "existing-programs.read",
        ),
        optional=("region-preferences.read",),
    ),
    boundaries=(
        "diagnosis",
        "functional-capacity-judgment",
        "practitioner-impersonation",
        "eligibility-decision",
        "benefit-amount",
        "submission-claim",
        "approval-claim",
    ),
    medical_boundary=MEDICAL_BOUNDARY,
    missing_fact_prompts=(
        MissingFactPrompt(
            key="adult-status",
            question="Are you 18 or older?",
            evidence_item="Confirm adult status.",
        ),
        MissingFactPrompt(
            key="bc-residency-status",
            question="Do you currently live in British Columbia?",
            evidence_item="Confirm current B.C. residency.",
        ),
        MissingFactPrompt(
            key="employment-status",
            question="Which broad employment status should appear in the preview?",
            evidence_item="Confirm current employment status.",
        ),
        MissingFactPrompt(
            key="current-income-band",
            question="Would you like to add a broad income range for the preview?",
            evidence_item="Review the broad income range with the official service.",
        ),
        MissingFactPrompt(
            key="financial-evidence-status",
            question="Do you have the financial evidence requested by the official service?",
            evidence_item="Financial evidence must be reviewed with the official service.",
        ),
        MissingFactPrompt(
            key="disability-duration-category",
            question=(
                "Has a qualified practitioner provided the required duration information, "
                "or is it still missing?"
            ),
            evidence_item=(
                "A qualified practitioner must provide any required duration information."
            ),
        ),
        MissingFactPrompt(
            key="functional-capacity-category",
            question=(
                "Has a qualified practitioner provided the required functional-impact "
                "information, or is it still missing?"
            ),
            evidence_item=(
                "A qualified practitioner must provide any required functional-impact "
                "information."
            ),
        ),
        MissingFactPrompt(
            key="practitioner-access",
            question=(
                "Do you have access to a qualified practitioner who can complete the "
                "practitioner section?"
            ),
            evidence_item="Confirm access to a qualified practitioner.",
        ),
        MissingFactPrompt(
            key="practitioner-section-status",
            question="Has a qualified practitioner completed the practitioner section?",
            evidence_item="A qualified practitioner must complete the practitioner section.",
        ),
        MissingFactPrompt(
            key="current-disability-support-status",
            question="Are you already receiving provincial disability assistance?",
            evidence_item=(
                "Confirm whether provincial disability assistance is already being received."
            ),
        ),
        MissingFactPrompt(
            key="designation-application-status",
            question="Is a provincial disability designation application already in progress?",
            evidence_item=(
                "Confirm whether a provincial disability designation application is in "
                "progress."
            ),
        ),
        MissingFactPrompt(
            key="preferred-service-channel",
            question="Would you prefer online, phone, or in-person help?",
            evidence_item="Choose a preferred service channel.",
        ),
        MissingFactPrompt(
            key="service-area",
            question="Which B.C. service area would you like help finding?",
            evidence_item="Choose a B.C. service area if in-person help is needed.",
        ),
    ),
    programs=(
        ProgramPresentationSpec(
            program_id="provincial-disability-support-navigation",
            rule_id="disability-support-navigation-v1",
            title="Provincial disability-support navigation",
            role="primary-navigation",
            source_id="family-social-supports",
        ),
        ProgramPresentationSpec(
            program_id="service-bc-assisted-navigation",
            rule_id="disability-service-bc-navigation-v1",
            title="Service BC assisted navigation",
            role="related-navigation",
            source_id="service-bc",
        ),
    ),
    preview_fields=(
        PreviewFieldPolicy(
            section_id="identity-residency",
            field="adult-status",
            label="Adult status",
            fact_key="identity.is-adult",
            category="identity-residency",
            scope="identity.read",
            sensitivity="personal",
            missing_item="Confirm adult status.",
        ),
        PreviewFieldPolicy(
            section_id="identity-residency",
            field="bc-residency",
            label="B.C. residency",
            fact_key="residency.bc-status",
            category="identity-residency",
            scope="identity.read",
            sensitivity="protected-a",
            missing_item="Confirm current B.C. residency.",
        ),
        PreviewFieldPolicy(
            section_id="employment-income",
            field="employment-status",
            label="Employment status",
            fact_key="employment.status",
            category="employment-income",
            scope="employment.read",
            sensitivity="protected-b",
            missing_item="Confirm current employment status.",
        ),
        PreviewFieldPolicy(
            section_id="employment-income",
            field="income-band",
            label="Current income range",
            fact_key="income.current-band",
            category="employment-income",
            scope="employment.read",
            sensitivity="protected-b",
            missing_item="Review the broad income range with the official service.",
        ),
        PreviewFieldPolicy(
            section_id="existing-benefits",
            field="current-disability-support",
            label="Current provincial disability assistance",
            fact_key="programs.provincial-disability-assistance",
            category="existing-programs",
            scope="existing-programs.read",
            sensitivity="protected-b",
            missing_item=(
                "Confirm whether provincial disability assistance is already being received."
            ),
        ),
        PreviewFieldPolicy(
            section_id="qualified-practitioner",
            field="practitioner-access",
            label="Qualified practitioner access",
            fact_key="disability.practitioner-access",
            category="disability-caregiving",
            scope="disability-caregiving.read",
            sensitivity="protected-b",
            missing_item="Confirm access to a qualified practitioner.",
        ),
        PreviewFieldPolicy(
            section_id="qualified-practitioner",
            field="practitioner-section",
            label="Qualified practitioner section",
            fact_key="disability.practitioner-section-completed",
            category="disability-caregiving",
            scope="disability-caregiving.read",
            sensitivity="protected-b",
            missing_item="A qualified practitioner must complete the practitioner section.",
        ),
    ),
    preview_sections=(
        PreviewSection(
            section_id="identity-residency",
            title="Identity and residency",
            field_names=("adult-status", "bc-residency"),
        ),
        PreviewSection(
            section_id="employment-income",
            title="Employment and income summary",
            field_names=("employment-status", "income-band"),
        ),
        PreviewSection(
            section_id="existing-benefits",
            title="Existing benefits",
            field_names=("current-disability-support",),
        ),
        PreviewSection(
            section_id="qualified-practitioner",
            title="Qualified practitioner-completed section",
            field_names=("practitioner-access", "practitioner-section"),
        ),
    ),
    handoff=OfficialHandoffPolicy(
        action_label="Continue to official B.C. disability assistance information",
        destination_name="B.C. disability assistance information",
        destination_url="https://www2.gov.bc.ca/gov/content/family-social-supports",
        notice=(
            "This opens the official B.C. website. No preview values are sent, and this "
            "demo does not submit or approve an application."
        ),
    ),
)

PERSONA_FLOW: dict[str, Literal["disability-support"]] = {
    DISABILITY_FLOW.persona_id: DISABILITY_FLOW.flow_id,
}

_PROMPT_BY_KEY = {prompt.key: prompt for prompt in DISABILITY_FLOW.missing_fact_prompts}
_PROMPT_ORDER = tuple(_PROMPT_BY_KEY)
_PUBLIC_KEY_BY_FACT: dict[str, PublicMissingKey] = {
    "identity.is-adult": "adult-status",
    "residency.bc-status": "bc-residency-status",
    "employment.status": "employment-status",
    "income.current-band": "current-income-band",
    "income.liquid-assets-band": "financial-evidence-status",
    "disability.duration-band": "disability-duration-category",
    "disability.functional-capacity": "functional-capacity-category",
    "disability.practitioner-access": "practitioner-access",
    "disability.practitioner-section-completed": "practitioner-section-status",
    "programs.provincial-disability-assistance": "current-disability-support-status",
    "applications.disability-designation-status": "designation-application-status",
    "preferences.service-channel": "preferred-service-channel",
    "region.service-area": "service-area",
}
_PROGRAM_BY_ID = {program.program_id: program for program in DISABILITY_FLOW.programs}
_PROGRAM_ORDER = {
    program.program_id: index for index, program in enumerate(DISABILITY_FLOW.programs)
}
_PREVIEW_POLICY_BY_FACT = {
    policy.fact_key: policy for policy in DISABILITY_FLOW.preview_fields
}

_VALUE_LABELS: dict[str, dict[tuple[type[object], object], str]] = {
    "identity.is-adult": {
        (bool, True): "18 or older",
        (bool, False): "Under 18",
    },
    "residency.bc-status": {
        (str, "resident"): "B.C. resident",
        (str, "not-resident"): "Not currently a B.C. resident",
    },
    "employment.status": {
        (str, "part-time"): "Part-time employment",
        (str, "full-time"): "Full-time employment",
        (str, "not-employed"): "Not currently employed",
        (str, "self-employed"): "Self-employed",
        (str, "recently-ended"): "Employment recently ended",
    },
    "income.current-band": {
        (str, "low"): "Low range",
        (str, "low-to-moderate"): "Low-to-moderate range",
        (str, "moderate"): "Moderate range",
        (str, "above-demo-range"): "Above the demo range",
    },
    "programs.provincial-disability-assistance": {
        (str, "not-receiving"): "Not currently receiving",
        (str, "application-in-progress"): "Application in progress",
        (str, "receiving"): "Currently receiving",
    },
    "disability.practitioner-access": {
        (bool, True): "Access recorded",
        (bool, False): "Access not recorded",
    },
    "disability.practitioner-section-completed": {
        (bool, True): "Completion recorded for citizen review",
        (bool, False): "Not completed",
    },
}

_STATUS_SUMMARIES: dict[str, dict[str, str]] = {
    "provincial-disability-support-navigation": {
        "potential-match": (
            "The reviewed provincial navigation pathway may be relevant to this synthetic "
            "scenario. This is not an eligibility decision."
        ),
        "needs-information": (
            "More information is needed before showing the reviewed provincial navigation "
            "pathway."
        ),
        "already-enrolled": (
            "The synthetic demo record shows current provincial disability assistance. "
            "Use the official service to review existing support or related services; this "
            "is not a new approval."
        ),
        "not-indicated": (
            "The reviewed rule does not indicate this provincial pathway from the available "
            "synthetic facts. An official service can review other options."
        ),
    },
    "service-bc-assisted-navigation": {
        "potential-match": (
            "Service BC assisted navigation may be useful for the selected service channel."
        ),
        "needs-information": (
            "A preferred service channel is needed before showing Service BC assisted "
            "navigation."
        ),
        "already-enrolled": (
            "Service BC remains an official navigation option; no enrolment or approval is "
            "created by this demo."
        ),
        "not-indicated": (
            "The reviewed rule does not indicate Service BC assisted navigation from the "
            "available synthetic facts."
        ),
    },
}


class ProgramMatchPresentation(_StrictFlowModel):
    program_id: str
    title: str
    role: ProgramRole
    status: Literal[
        "potential-match",
        "needs-information",
        "already-enrolled",
        "not-indicated",
    ]
    summary: Annotated[str, Field(min_length=10, max_length=500)]
    notice: Literal["This is a screening indicator, not an eligibility decision."]
    missing_fact_keys: tuple[PublicMissingKey, ...]
    next_question: str | None


class DisabilityApplicationPackage(_StrictFlowModel):
    synthetic_label: Literal[
        "Synthetic demo — Alex; no real government records were accessed."
    ]
    preview: ApplicationPreview
    sections: tuple[PreviewSection, ...]
    missing_evidence: tuple[str, ...]
    medical_boundary: Literal[
        "Only a qualified practitioner can complete the practitioner section. "
        "This preview does not include a diagnosis or a functional-capacity decision."
    ]
    citizen_review: CitizenReviewCheckpoint

    @model_validator(mode="after")
    def safe_package(self) -> Self:
        if self.preview.flow_id != DISABILITY_FLOW.flow_id:
            raise ValueError("The preview must belong to the disability-support flow.")
        section_fields = tuple(
            field_name for section in self.sections for field_name in section.field_names
        )
        if section_fields != tuple(field.field for field in self.preview.fields):
            raise ValueError("Preview sections must match the validated preview field order.")
        if self.missing_evidence != tuple(self.preview.missing_items):
            raise ValueError("Missing evidence must match the validated preview contract.")
        forbidden_medical_keys = {
            "disability.duration-band",
            "disability.functional-capacity",
        }
        if any(
            field.source_fact_key in forbidden_medical_keys for field in self.preview.fields
        ):
            raise ValueError("The preview cannot expose medical judgment fields.")
        return self


def clarify_request(intent: str | None = None) -> ClarificationDecision:
    """Return one reviewed clarification question or the selected safe route."""

    if intent is None:
        return ClarificationDecision(
            requires_clarification=True,
            question=DISABILITY_FLOW.clarification.question,
            choices=DISABILITY_FLOW.clarification.choices,
            selected_intent=None,
            route=None,
        )
    choice = next(
        (item for item in DISABILITY_FLOW.clarification.choices if item.intent == intent),
        None,
    )
    if choice is None:
        raise UnsafeDisabilityFlowInput(
            "Choose one of the reviewed disability-support clarification options."
        )
    return ClarificationDecision(
        requires_clarification=False,
        question=None,
        choices=(),
        selected_intent=choice.intent,
        route=choice.route,
    )


def public_missing_keys(keys: Iterable[str]) -> tuple[PublicMissingKey, ...]:
    """Map reviewed internal fact keys to ordered public-safe missing keys."""

    selected: set[PublicMissingKey] = set()
    try:
        for key in keys:
            if type(key) is not str:
                raise UnsafeDisabilityFlowInput(
                    "Missing facts must use reviewed public-safe keys."
                )
            public_key = (
                cast(PublicMissingKey, key)
                if key in _PROMPT_BY_KEY
                else _PUBLIC_KEY_BY_FACT.get(key)
            )
            if public_key is None:
                raise UnsafeDisabilityFlowInput(
                    "Missing facts must use reviewed public-safe keys."
                )
            selected.add(public_key)
    except TypeError:
        raise UnsafeDisabilityFlowInput(
            "Missing facts must use reviewed public-safe keys."
        ) from None
    return tuple(cast(PublicMissingKey, key) for key in _PROMPT_ORDER if key in selected)


def next_missing_prompt(keys: Iterable[str]) -> MissingFactPrompt | None:
    """Return at most one deterministic question for the next missing fact."""

    ordered = public_missing_keys(keys)
    return _PROMPT_BY_KEY[ordered[0]] if ordered else None


def ordered_program_matches(matches: Sequence[ProgramMatch]) -> tuple[ProgramMatch, ...]:
    """Validate and order only the reviewed primary and related program results."""

    items = tuple(matches)
    if not items:
        raise UnsafeDisabilityFlowInput("At least one reviewed program result is required.")
    if any(not isinstance(item, ProgramMatch) for item in items):
        raise UnsafeDisabilityFlowInput("Program results must use the strict shared contract.")
    program_ids = tuple(item.program_id for item in items)
    if len(set(program_ids)) != len(program_ids) or not set(program_ids) <= set(_PROGRAM_BY_ID):
        raise UnsafeDisabilityFlowInput("Program results are outside the reviewed flow.")
    for item in items:
        spec = _PROGRAM_BY_ID[item.program_id]
        if (
            item.rule_id != spec.rule_id
            or item.source_ids != [spec.source_id]
            or item.notice != SCREENING_NOTICE
            or (
                item.status == "already-enrolled"
                and spec.role != "primary-navigation"
            )
        ):
            raise UnsafeDisabilityFlowInput("Program results are outside the reviewed flow.")
        if any(key not in _PROMPT_BY_KEY for key in item.missing_facts):
            raise UnsafeDisabilityFlowInput(
                "Program results must use public-safe missing-fact keys."
            )
    return tuple(sorted(items, key=lambda item: _PROGRAM_ORDER[item.program_id]))


def present_program_matches(
    matches: Sequence[ProgramMatch],
) -> tuple[ProgramMatchPresentation, ...]:
    """Create deterministic, public-safe presentation text without raw fact values."""

    presentations: list[ProgramMatchPresentation] = []
    for match in ordered_program_matches(matches):
        spec = _PROGRAM_BY_ID[match.program_id]
        missing_keys = public_missing_keys(match.missing_facts)
        prompt = next_missing_prompt(missing_keys)
        presentations.append(
            ProgramMatchPresentation(
                program_id=match.program_id,
                title=spec.title,
                role=spec.role,
                status=match.status,
                summary=_STATUS_SUMMARIES[match.program_id][match.status],
                notice=SCREENING_NOTICE,
                missing_fact_keys=missing_keys,
                next_question=prompt.question if prompt is not None else None,
            )
        )
    return tuple(presentations)


def build_program_matches_artifact(
    matches: Sequence[ProgramMatch],
    *,
    artifact_id: str,
) -> ProgramMatchesArtifact:
    """Return a shared-contract artifact with deterministic match ordering."""

    return ProgramMatchesArtifact(
        id=artifact_id,
        payload=list(ordered_program_matches(matches)),
    )


def _collect_preview_facts(
    context_facts: Iterable[ContextFact],
    citizen_answers: Iterable[ContextFact],
) -> dict[str, ContextFact]:
    known: dict[str, ContextFact] = {}
    for facts, answer_mode in ((context_facts, False), (citizen_answers, True)):
        seen: set[str] = set()
        try:
            for fact in facts:
                if not isinstance(fact, ContextFact):
                    raise UnsafeDisabilityFlowInput(
                        "Preview facts must use the strict shared contract."
                    )
                if fact.key not in _PREVIEW_POLICY_BY_FACT:
                    continue
                if fact.key in seen:
                    raise UnsafeDisabilityFlowInput(
                        "Preview facts must be unique within each source."
                    )
                seen.add(fact.key)
                policy = _PREVIEW_POLICY_BY_FACT[fact.key]
                if (
                    fact.category != policy.category
                    or fact.consent_scope != policy.scope
                    or fact.sensitivity != policy.sensitivity
                    or (answer_mode and fact.provenance != "citizen-answer")
                    or (not answer_mode and fact.provenance == "citizen-answer")
                ):
                    raise UnsafeDisabilityFlowInput(
                        "Preview facts do not match the reviewed flow contract."
                    )
                known[fact.key] = fact
        except TypeError:
            raise UnsafeDisabilityFlowInput(
                "Preview facts must use the strict shared contract."
            ) from None
    return known


def _display_value(fact: ContextFact) -> str | None:
    return _VALUE_LABELS[fact.key].get((type(fact.value), fact.value))


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def build_application_package(
    context_facts: Iterable[ContextFact],
    *,
    preview_id: str,
    expires_at: str,
    citizen_answers: Iterable[ContextFact] = (),
    missing_fact_keys: Iterable[str] = (),
) -> DisabilityApplicationPackage:
    """Build the review-only Alex preview without copying raw medical text."""

    facts = _collect_preview_facts(context_facts, citizen_answers)
    public_missing = public_missing_keys(missing_fact_keys)
    fields: list[PreviewField] = []
    missing_evidence: list[str] = []

    for policy in DISABILITY_FLOW.preview_fields:
        fact = facts.get(policy.fact_key)
        display_value = _display_value(fact) if fact is not None else None
        if fact is None or display_value is None:
            fields.append(
                PreviewField(
                    field=policy.field,
                    label=policy.label,
                    value=None,
                    source="missing",
                    source_fact_key=None,
                    editable=True,
                    sensitivity=policy.sensitivity,
                    requires_confirmation=True,
                )
            )
            _append_unique(missing_evidence, policy.missing_item)
            continue
        fields.append(
            PreviewField(
                field=policy.field,
                label=policy.label,
                value=display_value,
                source=(
                    "citizen-answer"
                    if fact.provenance == "citizen-answer"
                    else "synthetic-record"
                ),
                source_fact_key=fact.key,
                editable=fact.mutable_by_citizen,
                sensitivity=policy.sensitivity,
                requires_confirmation=True,
            )
        )

    for key in public_missing:
        _append_unique(missing_evidence, _PROMPT_BY_KEY[key].evidence_item)

    preview = ApplicationPreview(
        preview_id=preview_id,
        flow_id=DISABILITY_FLOW.flow_id,
        schema_version=1,
        fields=fields,
        missing_items=missing_evidence,
        submission_enabled=False,
        requires_human_review=True,
        expires_at=expires_at,
    )
    return DisabilityApplicationPackage(
        synthetic_label=SYNTHETIC_LABEL,
        preview=preview,
        sections=DISABILITY_FLOW.preview_sections,
        missing_evidence=tuple(missing_evidence),
        medical_boundary=MEDICAL_BOUNDARY,
        citizen_review=CitizenReviewCheckpoint(),
    )


def build_application_artifacts(
    package: DisabilityApplicationPackage,
    *,
    preview_artifact_id: str,
    consent_artifact_id: str,
    checkpoint_id: str,
) -> tuple[ApplicationPreviewArtifact, ConsentRequestArtifact]:
    """Build validated preview and no-transfer official-handoff artifacts."""

    if not isinstance(package, DisabilityApplicationPackage):
        raise UnsafeDisabilityFlowInput(
            "Application artifacts require the validated disability package."
        )
    populated_fields = [
        field.field for field in package.preview.fields if field.source != "missing"
    ]
    categories: list[ContextCategory] = []
    for policy in DISABILITY_FLOW.preview_fields:
        if (
            policy.field in populated_fields
            and policy.category not in categories
        ):
            categories.append(policy.category)
    preview_artifact = ApplicationPreviewArtifact(
        id=preview_artifact_id,
        payload=package.preview,
    )
    handoff = ConsentRequest(
        checkpoint_id=checkpoint_id,
        preview_id=package.preview.preview_id,
        purpose=DISABILITY_FLOW.purpose,
        destination_name=DISABILITY_FLOW.handoff.destination_name,
        destination_url=DISABILITY_FLOW.handoff.destination_url,
        categories_to_share=categories,
        field_names_to_share=populated_fields,
        transfer_mode="none",
        reviewed_by_citizen=False,
        submission_enabled=False,
    )
    return (
        preview_artifact,
        ConsentRequestArtifact(id=consent_artifact_id, payload=handoff),
    )


__all__ = [
    "DISABILITY_FLOW",
    "EXPECTED_FLOW_SCOPES",
    "MEDICAL_BOUNDARY",
    "PERSONA_FLOW",
    "SYNTHETIC_LABEL",
    "ClarificationDecision",
    "DisabilityApplicationPackage",
    "DisabilityFlowDefinition",
    "MissingFactPrompt",
    "ProgramMatchPresentation",
    "UnsafeDisabilityFlowInput",
    "build_application_artifacts",
    "build_application_package",
    "build_program_matches_artifact",
    "clarify_request",
    "next_missing_prompt",
    "ordered_program_matches",
    "present_program_matches",
    "public_missing_keys",
]
