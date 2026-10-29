"""Strict, flow-owned policy for the synthetic Sam job-loss demonstration."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bc_api.models import (
    SCREENING_NOTICE,
    ApplicationPreview,
    ApplicationPreviewArtifact,
    ConsentScope,
    ContextCategory,
    ContextFact,
    FactSensitivity,
    PreviewField,
    ProgramMatch,
    ProgramMatchesArtifact,
    ProgramSourceVersion,
)

FLOW_ID = "job-loss"
PERSONA_ID = "sam-job-loss"
PERSONA_NAME = "Sam"

REQUIRED_SCOPES: tuple[ConsentScope, ...] = (
    "identity.read",
    "household.read",
    "employment.read",
    "existing-programs.read",
    "region-preferences.read",
)
OPTIONAL_SCOPES: tuple[ConsentScope, ...] = ()

PROGRAM_ORDER = (
    "employment-business-navigation",
    "provincial-income-assistance-navigation",
    "housing-tenancy-navigation",
)
JURISDICTION_ORDER = ("federal", "provincial", "municipal", "crown")

Jurisdiction = Literal["federal", "provincial", "municipal", "crown"]
SourceRequirement = Literal["none", "rule-output", "reviewed-official-source"]
ProgramRole = Literal["primary-navigation", "related-navigation"]
RecommendationStatus = Literal["potential-match", "already-enrolled"]
PublicMissingFactKey = Literal[
    "immediate-housing-risk-status",
    "employment-end-category",
    "employment-status",
    "record-of-employment-availability",
    "bc-residency-status",
    "adult-status",
    "household-income-change",
    "current-income-assistance-status",
    "housing-tenure",
    "dependant-count",
    "service-region",
    "preferred-service-channel",
    "employment-separation-reason",
    "insurable-hours-category",
    "employment-insurance-status",
]

_Identifier = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
_Text = Annotated[str, Field(min_length=1, max_length=800)]

_INTERNAL_FACT_KEY = re.compile(
    r"\b(?:applications|employment|household|housing|identity|income|preferences|programs|"
    r"region|residency)\.[a-z0-9-]+",
    re.IGNORECASE,
)
_UNSAFE_PUBLIC_CLAIMS = (
    re.compile(
        r"\b(?:you|sam|the applicant|they)\s+(?:are|is|will be|has been|have been)\s+"
        r"(?:eligible|approved|entitled|qualified)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:qualifies|qualified|approved|eligible|entitled)\s+(?:for|to)\s+"
        r"(?:EI|Employment Insurance|income assistance)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:EI|Employment Insurance)\b.{0,80}"
        r"(?:\$\s*\d|\b\d+(?:\.\d+)?\s*(?:dollars?|%))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:EI|Employment Insurance)\b.{0,80}"
        r"\b(?:deadline|apply by|apply within|must file by)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:we|this app|the assistant)\s+(?:have\s+)?"
        r"(?:submitted|filed|sent|applied)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:confirmation (?:number|code)|submission (?:complete|successful)|"
        r"application (?:was|has been) submitted)\b",
        re.IGNORECASE,
    ),
)


def _assert_public_text(text: str) -> str:
    if type(text) is not str or not text.strip() or len(text) > 2_000:
        raise ValueError("Public job-loss text failed its safety contract.")
    if _INTERNAL_FACT_KEY.search(text) or any(
        pattern.search(text) for pattern in _UNSAFE_PUBLIC_CLAIMS
    ):
        raise ValueError("Public job-loss text failed its safety contract.")
    return text


class _PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class JurisdictionLabel(_PolicyModel):
    code: Jurisdiction
    label: _Text
    authority_label: _Text
    boundary: _Text
    app_can_access: Literal[False] = False
    app_can_submit: Literal[False] = False


class PriorityStep(_PolicyModel):
    order: Annotated[int, Field(ge=1, le=10)]
    key: _Identifier
    title: _Text
    instruction: _Text
    jurisdictions: tuple[Jurisdiction, ...]
    source_requirement: SourceRequirement

    @model_validator(mode="after")
    def coherent_step(self) -> Self:
        if not self.jurisdictions or len(self.jurisdictions) != len(set(self.jurisdictions)):
            raise ValueError("Priority jurisdictions must be present and unique.")
        _assert_public_text(self.title)
        _assert_public_text(self.instruction)
        return self


class MissingFactPrompt(_PolicyModel):
    key: PublicMissingFactKey
    question: _Text
    reason: _Text

    @model_validator(mode="after")
    def one_question(self) -> Self:
        if not self.question.endswith("?") or self.question.count("?") != 1:
            raise ValueError("A clarification prompt must contain exactly one question.")
        _assert_public_text(self.question)
        _assert_public_text(self.reason)
        return self


class PreviewFieldPolicy(_PolicyModel):
    field: _Identifier
    label: _Text
    fact_key: Annotated[
        str,
        Field(
            min_length=3,
            max_length=100,
            pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$",
        ),
    ]
    public_missing_key: PublicMissingFactKey
    category: ContextCategory
    consent_scope: ConsentScope
    sensitivity: FactSensitivity
    missing_item: _Text
    official_service_fact: bool = False


class ProgramNavigationPolicy(_PolicyModel):
    order: Annotated[int, Field(ge=1, le=10)]
    program_id: _Identifier
    label: _Text
    role: ProgramRole
    jurisdiction: Jurisdiction
    source_ids: tuple[_Identifier, ...]
    potential_summary: _Text
    already_enrolled_summary: _Text | None = None

    @model_validator(mode="after")
    def coherent_program(self) -> Self:
        if not self.source_ids or len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("Program sources must be present and unique.")
        _assert_public_text(self.label)
        _assert_public_text(self.potential_summary)
        if self.already_enrolled_summary is not None:
            _assert_public_text(self.already_enrolled_summary)
        return self


class ProgramNavigationItem(_PolicyModel):
    program_id: _Identifier
    status: RecommendationStatus
    label: _Text
    jurisdiction: Jurisdiction
    jurisdiction_label: _Text
    summary: _Text
    source_ids: tuple[_Identifier, ...]
    source_versions: tuple[ProgramSourceVersion, ...]
    notice: Literal["This is a screening indicator, not an eligibility decision."]
    app_can_access: Literal[False] = False
    app_can_submit: Literal[False] = False

    @model_validator(mode="after")
    def safe_item(self) -> Self:
        _assert_public_text(self.label)
        _assert_public_text(self.summary)
        return self


class JobLossFlowDefinition(_PolicyModel):
    flow_id: Literal["job-loss"]
    persona_id: Literal["sam-job-loss"]
    persona_name: Literal["Sam"]
    required_scopes: tuple[ConsentScope, ...]
    optional_scopes: tuple[ConsentScope, ...]
    immediate_priorities: tuple[PriorityStep, ...]
    jurisdictions: tuple[JurisdictionLabel, ...]
    clarifications: tuple[MissingFactPrompt, ...]
    preview_fields: tuple[PreviewFieldPolicy, ...]
    programs: tuple[ProgramNavigationPolicy, ...]
    boundaries: tuple[_Text, ...]

    @model_validator(mode="after")
    def exact_flow_contract(self) -> Self:
        if self.required_scopes != REQUIRED_SCOPES or self.optional_scopes != OPTIONAL_SCOPES:
            raise ValueError("The job-loss consent scope contract changed.")
        if tuple(item.order for item in self.immediate_priorities) != tuple(
            range(1, len(self.immediate_priorities) + 1)
        ):
            raise ValueError("Immediate priorities must use contiguous deterministic ordering.")
        if tuple(item.code for item in self.jurisdictions) != JURISDICTION_ORDER:
            raise ValueError("The jurisdiction label contract changed.")
        if tuple(item.program_id for item in self.programs) != PROGRAM_ORDER:
            raise ValueError("The job-loss program order changed.")
        if tuple(item.order for item in self.programs) != tuple(range(1, len(self.programs) + 1)):
            raise ValueError("Programs must use contiguous deterministic ordering.")
        for values, label in (
            ((item.key for item in self.immediate_priorities), "priority keys"),
            ((item.key for item in self.clarifications), "clarification keys"),
            ((item.field for item in self.preview_fields), "preview fields"),
            ((item.fact_key for item in self.preview_fields), "preview fact keys"),
            ((item.public_missing_key for item in self.preview_fields), "preview missing keys"),
        ):
            materialized = tuple(values)
            if len(materialized) != len(set(materialized)):
                raise ValueError(f"Job-loss {label} must be unique.")
        prompt_keys = {item.key for item in self.clarifications}
        if any(item.public_missing_key not in prompt_keys for item in self.preview_fields):
            raise ValueError("Every preview field requires a public-safe clarification key.")
        for boundary in self.boundaries:
            _assert_public_text(boundary)
        return self

    def jurisdiction(self, code: Jurisdiction) -> JurisdictionLabel:
        for item in self.jurisdictions:
            if item.code == code:
                return item
        raise ValueError("The jurisdiction is outside the job-loss flow.")

    def validate_public_text(self, text: str) -> str:
        return _assert_public_text(text)

    def ordered_matches(self, matches: Iterable[ProgramMatch]) -> tuple[ProgramMatch, ...]:
        materialized = tuple(matches)
        if any(not isinstance(item, ProgramMatch) for item in materialized):
            raise TypeError("Job-loss matches must use the strict program-match contract.")
        by_program: dict[str, ProgramMatch] = {}
        policies = {item.program_id: item for item in self.programs}
        for match in materialized:
            if match.program_id in by_program:
                raise ValueError("Job-loss program matches must be unique.")
            policy = policies.get(match.program_id)
            if policy is None:
                raise ValueError("A program match is outside the job-loss flow.")
            if (
                tuple(match.source_ids) != policy.source_ids
                or tuple(item.source_id for item in match.source_versions) != policy.source_ids
            ):
                raise ValueError("A program match lacks its reviewed source contract.")
            if any(
                key not in {item.key for item in self.clarifications} for key in match.missing_facts
            ):
                raise ValueError("A program match used a non-public missing-fact key.")
            by_program[match.program_id] = match
        return tuple(
            by_program[program_id] for program_id in PROGRAM_ORDER if program_id in by_program
        )

    def match_missing_keys(
        self,
        matches: Iterable[ProgramMatch],
    ) -> tuple[PublicMissingFactKey, ...]:
        ordered = self.ordered_matches(matches)
        missing = {key for match in ordered for key in match.missing_facts}
        return tuple(item.key for item in self.clarifications if item.key in missing)

    def next_clarification(
        self,
        public_missing_keys: Iterable[str],
    ) -> MissingFactPrompt | None:
        supplied = tuple(public_missing_keys)
        prompts = {item.key: item for item in self.clarifications}
        if any(type(key) is not str or key not in prompts for key in supplied):
            raise ValueError("Clarification keys must use the public job-loss contract.")
        missing = set(supplied)
        return next((item for item in self.clarifications if item.key in missing), None)

    def next_match_clarification(
        self,
        matches: Iterable[ProgramMatch],
    ) -> MissingFactPrompt | None:
        return self.next_clarification(self.match_missing_keys(matches))

    def build_preview(
        self,
        facts: Iterable[ContextFact],
        *,
        preview_id: str,
        expires_at: str,
    ) -> ApplicationPreview:
        by_key: dict[str, ContextFact] = {}
        for fact in facts:
            if not isinstance(fact, ContextFact):
                raise TypeError("Job-loss preview facts must use the strict context contract.")
            if fact.key in by_key:
                raise ValueError("Job-loss preview facts must be unique.")
            by_key[fact.key] = fact

        fields: list[PreviewField] = []
        missing_items: list[str] = []
        for spec in self.preview_fields:
            fact = by_key.get(spec.fact_key)
            public_value = _MISSING if fact is None else _public_preview_value(fact)
            if fact is None or public_value is _MISSING:
                fields.append(
                    PreviewField(
                        field=spec.field,
                        label=spec.label,
                        value=None,
                        source="missing",
                        source_fact_key=None,
                        editable=True,
                        sensitivity=spec.sensitivity,
                        requires_confirmation=True,
                    )
                )
                missing_items.append(spec.missing_item)
                continue
            if (
                fact.category != spec.category
                or fact.consent_scope != spec.consent_scope
                or fact.sensitivity != spec.sensitivity
            ):
                raise ValueError("A job-loss preview fact failed its flow contract.")
            fields.append(
                PreviewField(
                    field=spec.field,
                    label=spec.label,
                    value=public_value,
                    source=(
                        "synthetic-record"
                        if fact.provenance == "synthetic-government-record"
                        else "citizen-answer"
                    ),
                    source_fact_key=fact.key,
                    editable=fact.mutable_by_citizen,
                    sensitivity=spec.sensitivity,
                    requires_confirmation=True,
                )
            )
        return ApplicationPreview(
            preview_id=preview_id,
            flow_id=FLOW_ID,
            schema_version=1,
            fields=fields,
            missing_items=missing_items,
            submission_enabled=False,
            requires_human_review=True,
            expires_at=expires_at,
        )

    def build_preview_artifact(
        self,
        facts: Iterable[ContextFact],
        *,
        artifact_id: str,
        preview_id: str,
        expires_at: str,
    ) -> ApplicationPreviewArtifact:
        return ApplicationPreviewArtifact(
            id=artifact_id,
            payload=self.build_preview(
                facts,
                preview_id=preview_id,
                expires_at=expires_at,
            ),
        )

    def preview_missing_keys(
        self,
        preview: ApplicationPreview,
    ) -> tuple[PublicMissingFactKey, ...]:
        if preview.flow_id != FLOW_ID:
            raise ValueError("The preview is outside the job-loss flow.")
        policy_by_field = {item.field: item for item in self.preview_fields}
        unknown = {item.field for item in preview.fields} - set(policy_by_field)
        if unknown:
            raise ValueError("The preview contains a field outside the job-loss flow.")
        missing = {
            policy_by_field[item.field].public_missing_key
            for item in preview.fields
            if item.source == "missing"
        }
        return tuple(item.key for item in self.clarifications if item.key in missing)

    def next_preview_clarification(
        self,
        preview: ApplicationPreview,
    ) -> MissingFactPrompt | None:
        return self.next_clarification(self.preview_missing_keys(preview))

    def build_matches_artifact(
        self,
        matches: Iterable[ProgramMatch],
        *,
        artifact_id: str,
    ) -> ProgramMatchesArtifact:
        return ProgramMatchesArtifact(
            id=artifact_id,
            payload=list(self.ordered_matches(matches)),
        )

    def navigation_items(
        self,
        matches: Iterable[ProgramMatch],
    ) -> tuple[ProgramNavigationItem, ...]:
        policies = {item.program_id: item for item in self.programs}
        jurisdiction_labels = {item.code: item.label for item in self.jurisdictions}
        items: list[ProgramNavigationItem] = []
        for match in self.ordered_matches(matches):
            if match.status not in ("potential-match", "already-enrolled"):
                continue
            policy = policies[match.program_id]
            summary = (
                policy.already_enrolled_summary
                if match.status == "already-enrolled"
                else policy.potential_summary
            )
            if summary is None:
                raise ValueError("The job-loss navigation status is not supported.")
            items.append(
                ProgramNavigationItem(
                    program_id=match.program_id,
                    status=match.status,
                    label=policy.label,
                    jurisdiction=policy.jurisdiction,
                    jurisdiction_label=jurisdiction_labels[policy.jurisdiction],
                    summary=summary,
                    source_ids=tuple(match.source_ids),
                    source_versions=tuple(match.source_versions),
                    notice=SCREENING_NOTICE,
                )
            )
        return tuple(items)

    def related_recommendations(
        self,
        matches: Iterable[ProgramMatch],
    ) -> tuple[ProgramNavigationItem, ...]:
        roles = {item.program_id: item.role for item in self.programs}
        return tuple(
            item
            for item in self.navigation_items(matches)
            if roles[item.program_id] == "related-navigation"
        )


_MISSING = object()

_PUBLIC_VALUE_LABELS: dict[str, tuple[tuple[object, str], ...]] = {
    "employment.status": (
        ("recently-ended", "Employment recently ended"),
        ("hours-reduced", "Employment hours reduced"),
    ),
    "employment.end-date-band": (
        ("within-last-four-weeks", "Within the last four weeks"),
        ("recent", "Recently"),
        ("more-than-four-weeks", "More than four weeks ago"),
        ("unknown", "Unknown"),
    ),
    "employment.record-of-employment": (
        ("available", "Available"),
        ("not-available", "Not available"),
        ("unknown", "Unknown"),
    ),
    "income.change": (
        ("material-decrease", "Material decrease"),
        ("no-material-decrease", "No material decrease reported"),
    ),
    "programs.provincial-income-assistance": (
        ("not-receiving", "Not receiving"),
        ("application-in-progress", "Application in progress"),
        ("receiving", "Receiving"),
    ),
    "housing.tenure": (
        ("renter", "Renter"),
        ("owner", "Owner"),
        ("other", "Other"),
    ),
    "housing.immediate-risk-status": (
        (True, "Immediate housing risk reported"),
        (False, "No immediate housing risk reported"),
    ),
    "region.service-area": (
        ("Interior service region", "Interior service region"),
        ("Victoria service region", "Victoria service region"),
    ),
    "preferences.service-channel": (
        ("online-and-phone", "Online and phone"),
        ("online-with-assisted-option", "Online with an assisted option"),
    ),
    "employment.separation-reason": (
        ("shortage-of-work", "Shortage of work"),
        ("dismissed", "Dismissed"),
        ("resigned", "Resigned"),
        ("other", "Other"),
        ("unknown", "Unknown"),
    ),
    "employment.insurable-hours-band": (
        ("official-service-review-needed", "Official service review needed"),
        ("unknown", "Unknown"),
    ),
    "applications.employment-insurance-status": (
        ("not-started", "Not started"),
        ("in-progress", "In progress"),
        ("unknown", "Unknown"),
    ),
}


def _public_preview_value(fact: ContextFact) -> object:
    if fact.key == "household.dependant-count":
        if type(fact.value) is int and 0 <= fact.value <= 20:
            return fact.value
        return _MISSING
    for expected, public_value in _PUBLIC_VALUE_LABELS.get(fact.key, ()):
        if type(fact.value) is type(expected) and fact.value == expected:
            return public_value
    return _MISSING


_JURISDICTION_BOUNDARY = (
    "External official service. This app may label the jurisdiction, but it cannot access "
    "an account, submit information, or confirm an outcome."
)

JOB_LOSS_FLOW = JobLossFlowDefinition(
    flow_id=FLOW_ID,
    persona_id=PERSONA_ID,
    persona_name=PERSONA_NAME,
    required_scopes=REQUIRED_SCOPES,
    optional_scopes=OPTIONAL_SCOPES,
    immediate_priorities=(
        PriorityStep(
            order=1,
            key="stabilize-immediate-needs",
            title="Check immediate household and housing stability",
            instruction=(
                "Address urgent food, safety, and housing needs first through an appropriate "
                "official service used directly by the citizen."
            ),
            jurisdictions=("municipal", "provincial", "crown"),
            source_requirement="reviewed-official-source",
        ),
        PriorityStep(
            order=2,
            key="prepare-federal-navigation",
            title="Prepare for federal Employment Insurance navigation",
            instruction=(
                "Gather the employment-end category and Record of Employment availability, "
                "then use a reviewed official federal source for any substantive guidance."
            ),
            jurisdictions=("federal",),
            source_requirement="reviewed-official-source",
        ),
        PriorityStep(
            order=3,
            key="review-employment-navigation",
            title="Review employment navigation",
            instruction=(
                "Use only the employment navigation result returned by the deterministic rule "
                "engine and its reviewed source."
            ),
            jurisdictions=("provincial",),
            source_requirement="rule-output",
        ),
        PriorityStep(
            order=4,
            key="review-related-supports",
            title="Review related income and housing navigation",
            instruction=(
                "Show income-assistance or housing navigation only when returned by the rule "
                "engine with the expected reviewed source."
            ),
            jurisdictions=("provincial", "municipal", "crown"),
            source_requirement="rule-output",
        ),
    ),
    jurisdictions=(
        JurisdictionLabel(
            code="federal",
            label="Federal service",
            authority_label="Government of Canada or federal delivery organization",
            boundary=_JURISDICTION_BOUNDARY,
        ),
        JurisdictionLabel(
            code="provincial",
            label="Provincial service",
            authority_label="Government of British Columbia",
            boundary=_JURISDICTION_BOUNDARY,
        ),
        JurisdictionLabel(
            code="municipal",
            label="Municipal service",
            authority_label="Local government",
            boundary=_JURISDICTION_BOUNDARY,
        ),
        JurisdictionLabel(
            code="crown",
            label="Crown service",
            authority_label="B.C. Crown corporation or agency",
            boundary=_JURISDICTION_BOUNDARY,
        ),
    ),
    clarifications=(
        MissingFactPrompt(
            key="immediate-housing-risk-status",
            question="Are you at immediate risk of losing housing or without a safe place to stay?",
            reason="This distinguishes urgent direct-service navigation from later planning.",
        ),
        MissingFactPrompt(
            key="employment-end-category",
            question=(
                "Did the employment end within the last four weeks, earlier, or are you unsure?"
            ),
            reason="The rule-backed employment navigation requires a broad end-date category.",
        ),
        MissingFactPrompt(
            key="employment-status",
            question="Has the employment ended, or have the hours only been reduced?",
            reason="This distinguishes the supported employment-change branches.",
        ),
        MissingFactPrompt(
            key="record-of-employment-availability",
            question="Do you know whether your Record of Employment is available?",
            reason=(
                "This prepares an official-service handoff without claiming access to the record."
            ),
        ),
        MissingFactPrompt(
            key="bc-residency-status",
            question="Do you currently live in British Columbia?",
            reason="The provincial rule outputs require a B.C. residency answer.",
        ),
        MissingFactPrompt(
            key="adult-status",
            question="Are you an adult?",
            reason="The employment navigation rule requires an adult-status answer.",
        ),
        MissingFactPrompt(
            key="household-income-change",
            question="Has household income materially decreased since the employment ended?",
            reason="This distinguishes the income and housing navigation branches.",
        ),
        MissingFactPrompt(
            key="current-income-assistance-status",
            question="Are you receiving provincial income assistance, applying for it, or neither?",
            reason=(
                "This prevents recommending a new application when an existing service is present."
            ),
        ),
        MissingFactPrompt(
            key="housing-tenure",
            question="Do you rent, own, or have another housing arrangement?",
            reason="The housing navigation rule requires a broad tenure category.",
        ),
        MissingFactPrompt(
            key="dependant-count",
            question="How many dependants are in the household?",
            reason="This completes the household summary without inferring family details.",
        ),
        MissingFactPrompt(
            key="service-region",
            question="Which B.C. service region should be used for official navigation?",
            reason=(
                "This narrows the handoff region without choosing a service on the citizen's "
                "behalf."
            ),
        ),
        MissingFactPrompt(
            key="preferred-service-channel",
            question="Would you prefer online, phone, or an assisted service channel?",
            reason="This records a channel preference without contacting a service.",
        ),
        MissingFactPrompt(
            key="employment-separation-reason",
            question="Which broad category best describes why the employment ended?",
            reason=(
                "The official service must confirm this fact; the app does not decide its effect."
            ),
        ),
        MissingFactPrompt(
            key="insurable-hours-category",
            question=(
                "Do you know the official insurable-hours category, or should it remain unknown?"
            ),
            reason="The official federal service must confirm this fact.",
        ),
        MissingFactPrompt(
            key="employment-insurance-status",
            question=(
                "Have you started an Employment Insurance application, or is that status unknown?"
            ),
            reason=(
                "The answer is citizen-provided only; the app cannot access or confirm an "
                "application."
            ),
        ),
    ),
    preview_fields=(
        PreviewFieldPolicy(
            field="employment-status",
            label="Employment status",
            fact_key="employment.status",
            public_missing_key="employment-status",
            category="employment-income",
            consent_scope="employment.read",
            sensitivity="protected-b",
            missing_item="Confirm the current employment status.",
        ),
        PreviewFieldPolicy(
            field="employment-end-category",
            label="Employment end date category",
            fact_key="employment.end-date-band",
            public_missing_key="employment-end-category",
            category="employment-income",
            consent_scope="employment.read",
            sensitivity="protected-b",
            missing_item="Confirm the broad employment end-date category.",
        ),
        PreviewFieldPolicy(
            field="record-of-employment",
            label="Record of Employment availability",
            fact_key="employment.record-of-employment",
            public_missing_key="record-of-employment-availability",
            category="employment-income",
            consent_scope="employment.read",
            sensitivity="protected-b",
            missing_item=(
                "Confirm Record of Employment availability directly with the official service."
            ),
            official_service_fact=True,
        ),
        PreviewFieldPolicy(
            field="dependant-count",
            label="Number of dependants",
            fact_key="household.dependant-count",
            public_missing_key="dependant-count",
            category="household-dependants",
            consent_scope="household.read",
            sensitivity="protected-a",
            missing_item="Confirm the number of dependants.",
        ),
        PreviewFieldPolicy(
            field="income-change",
            label="Household income change",
            fact_key="income.change",
            public_missing_key="household-income-change",
            category="employment-income",
            consent_scope="employment.read",
            sensitivity="protected-b",
            missing_item="Confirm the household income-change category.",
        ),
        PreviewFieldPolicy(
            field="current-income-assistance",
            label="Current provincial income assistance",
            fact_key="programs.provincial-income-assistance",
            public_missing_key="current-income-assistance-status",
            category="existing-programs",
            consent_scope="existing-programs.read",
            sensitivity="protected-b",
            missing_item="Confirm the current provincial income-assistance status.",
        ),
        PreviewFieldPolicy(
            field="housing-tenure",
            label="Housing tenure",
            fact_key="housing.tenure",
            public_missing_key="housing-tenure",
            category="household-dependants",
            consent_scope="household.read",
            sensitivity="protected-a",
            missing_item="Confirm the housing tenure category.",
        ),
        PreviewFieldPolicy(
            field="housing-immediate-risk-status",
            label="Immediate housing risk",
            fact_key="housing.immediate-risk-status",
            public_missing_key="immediate-housing-risk-status",
            category="household-dependants",
            consent_scope="household.read",
            sensitivity="protected-b",
            missing_item="Confirm any immediate housing risk directly with an appropriate service.",
            official_service_fact=True,
        ),
        PreviewFieldPolicy(
            field="service-region",
            label="Preferred service region",
            fact_key="region.service-area",
            public_missing_key="service-region",
            category="region-preferences",
            consent_scope="region-preferences.read",
            sensitivity="personal",
            missing_item="Confirm the preferred service region.",
        ),
        PreviewFieldPolicy(
            field="preferred-service-channel",
            label="Preferred service channel",
            fact_key="preferences.service-channel",
            public_missing_key="preferred-service-channel",
            category="region-preferences",
            consent_scope="region-preferences.read",
            sensitivity="personal",
            missing_item="Confirm the preferred service channel.",
        ),
        PreviewFieldPolicy(
            field="employment-separation-reason",
            label="Employment separation reason",
            fact_key="employment.separation-reason",
            public_missing_key="employment-separation-reason",
            category="employment-income",
            consent_scope="employment.read",
            sensitivity="protected-b",
            missing_item="Confirm the employment separation reason at the official service.",
            official_service_fact=True,
        ),
        PreviewFieldPolicy(
            field="insurable-hours-band",
            label="Insurable hours category",
            fact_key="employment.insurable-hours-band",
            public_missing_key="insurable-hours-category",
            category="employment-income",
            consent_scope="employment.read",
            sensitivity="protected-b",
            missing_item="Confirm the insurable-hours category at the official federal service.",
            official_service_fact=True,
        ),
        PreviewFieldPolicy(
            field="employment-insurance-status",
            label="Employment Insurance application status",
            fact_key="applications.employment-insurance-status",
            public_missing_key="employment-insurance-status",
            category="existing-programs",
            consent_scope="existing-programs.read",
            sensitivity="protected-b",
            missing_item=(
                "Confirm any application status directly with the official federal service."
            ),
            official_service_fact=True,
        ),
    ),
    programs=(
        ProgramNavigationPolicy(
            order=1,
            program_id="employment-business-navigation",
            label="Employment navigation",
            role="primary-navigation",
            jurisdiction="provincial",
            source_ids=("employment-business",),
            potential_summary=(
                "Review the rule-backed provincial employment navigation result in its reviewed "
                "official source. This app cannot access or submit to that service."
            ),
        ),
        ProgramNavigationPolicy(
            order=2,
            program_id="provincial-income-assistance-navigation",
            label="Provincial income-assistance navigation",
            role="related-navigation",
            jurisdiction="provincial",
            source_ids=("family-social-supports",),
            potential_summary=(
                "Review the rule-backed provincial income-assistance navigation result in its "
                "reviewed official source. This app cannot access or submit to that service."
            ),
            already_enrolled_summary=(
                "Review the existing provincial income-assistance service directly. This app "
                "cannot access, change, or submit information to that service."
            ),
        ),
        ProgramNavigationPolicy(
            order=3,
            program_id="housing-tenancy-navigation",
            label="Housing and tenancy navigation",
            role="related-navigation",
            jurisdiction="provincial",
            source_ids=("housing-tenancy",),
            potential_summary=(
                "Review the rule-backed housing and tenancy navigation result in its reviewed "
                "official source. This app cannot access or submit to that service."
            ),
        ),
    ),
    boundaries=(
        (
            "This flow provides navigation only. It does not determine Employment Insurance or "
            "provincial assistance eligibility, approval, entitlement, benefit amounts, or "
            "deadlines."
        ),
        (
            "This app cannot access an official account, submit a form, transfer preview values, "
            "or issue an official confirmation."
        ),
        (
            "Every preview field requires citizen review, and every official-service fact must be "
            "confirmed directly with that service."
        ),
        (
            "Related navigation may be shown only when it is returned by the deterministic rule "
            "engine with the expected reviewed source."
        ),
    ),
)

FLOW_DEFINITION = JOB_LOSS_FLOW

__all__ = [
    "FLOW_DEFINITION",
    "FLOW_ID",
    "JOB_LOSS_FLOW",
    "JURISDICTION_ORDER",
    "OPTIONAL_SCOPES",
    "PERSONA_ID",
    "PERSONA_NAME",
    "PROGRAM_ORDER",
    "REQUIRED_SCOPES",
    "JobLossFlowDefinition",
    "JurisdictionLabel",
    "MissingFactPrompt",
    "PreviewFieldPolicy",
    "PriorityStep",
    "ProgramNavigationItem",
    "ProgramNavigationPolicy",
]
