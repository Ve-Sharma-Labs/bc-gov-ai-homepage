"""The shared catalogue and conversation contracts use camelCase on the wire."""

import math
import re
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)
from pydantic.alias_generators import to_camel

from bc_api.urls import official_url

JourneyId = Literal[
    "licence-renewal",
    "road-test-booking",
    "rental-assistance",
    "health-coverage",
    "pharmacare-registration",
    "primary-care",
    "service-bc",
]
ChatMode = Literal["general", "pathway", "contextual-demo"]
ResponseKind = Literal["dialogue", "grounded", "handoff"]
ResponseOrigin = Literal["application", "model"]
DiscoveryGoalId = Literal[
    "motorcycle",
    "licence",
    "road-test",
    "rent",
    "health",
    "pharmacare",
    "primary-care",
    "service-bc",
    "job-loss",
    "caregiving",
    "disability",
]
DiscoveryFactKey = Literal[
    "age",
    "licence-experience",
    "timeframe",
    "priority",
    "bc-residency",
    "phn-status",
    "support-for",
]
ConversationFactKey = Literal[
    "licence-jurisdiction",
    "road-test-kind",
    "housing-need",
    "coverage-need",
    "primary-care-need",
    "service-need",
    "age-range",
    "phn-status",
    "bc-residency",
    "care-recipient",
    "priority",
]
DemoPersonaId = Literal["maya-caregiver", "alex-disability-support", "sam-job-loss"]
ContextCategory = Literal[
    "identity-residency",
    "household-dependants",
    "employment-income",
    "disability-caregiving",
    "existing-programs",
    "region-preferences",
]
FactProvenance = Literal["synthetic-government-record", "citizen-answer"]
FactSensitivity = Literal["personal", "protected-a", "protected-b"]
ConsentScope = Literal[
    "identity.read",
    "household.read",
    "employment.read",
    "disability-caregiving.read",
    "existing-programs.read",
    "region-preferences.read",
]
ContextFlowId = Literal["guardianship-intake", "disability-support", "job-loss"]
ProgramMatchStatus = Literal[
    "potential-match",
    "needs-information",
    "already-enrolled",
    "not-indicated",
]
PreviewFieldSource = Literal["synthetic-record", "citizen-answer", "missing"]
AuditAction = Literal[
    "consent-granted",
    "consent-revoked",
    "context-category-accessed",
    "rule-evaluated",
    "preview-generated",
    "approved-source-accessed",
    "handoff-offered",
    "handoff-opened",
    "access-denied",
    "session-cleared",
    "context-run-completed",
]
ContextAuditTool = Literal[
    "context-authorization",
    "change-consent",
    "clear-context",
    "read_consented_context",
    "evaluate_program_rules",
    "build_application_preview",
    "search_approved_sources",
    "context-run",
]
AuditOutcome = Literal[
    "active-consent",
    "active-minimum-consent",
    "accessed",
    "potential-match",
    "needs-information",
    "already-enrolled",
    "not-indicated",
    "review-required",
    "no-transfer",
    "denied",
    "revoked-partial",
    "revoked-complete",
    "citizen-request",
    "session-reset",
    "persona-changed",
    "finished",
    "cancelled",
    "failed",
]
LEGACY_JOURNEY_IDS = frozenset(
    {
        "licence-renewal",
        "rental-assistance",
        "health-coverage",
        "primary-care",
        "service-bc",
    }
)
JOURNEY_IDS = LEGACY_JOURNEY_IDS | {"road-test-booking", "pharmacare-registration"}
ServiceKey = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)]
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$", max_length=100)]
Text = Annotated[str, Field(min_length=1, max_length=8000)]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
OfficialUrl = Annotated[str, AfterValidator(official_url)]
ContextValue = StrictStr | StrictInt | StrictFloat | StrictBool
PreviewValue = ContextValue | None
SCREENING_NOTICE = "This is a screening indicator, not an eligibility decision."
CONTEXT_SCOPE_BY_CATEGORY: dict[ContextCategory, ConsentScope] = {
    "identity-residency": "identity.read",
    "household-dependants": "household.read",
    "employment-income": "employment.read",
    "disability-caregiving": "disability-caregiving.read",
    "existing-programs": "existing-programs.read",
    "region-preferences": "region-preferences.read",
}


def iso_date(value: str) -> str:
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?", value
    ):
        raise ValueError("Use an ISO date or date-time.")
    try:
        if "T" in value:
            datetime.fromisoformat(value)
        else:
            date.fromisoformat(value)
    except ValueError:
        raise ValueError("Use a valid ISO date or date-time.") from None
    return value


IsoDate = Annotated[str, AfterValidator(iso_date)]
CalendarDate = Annotated[IsoDate, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def iso_datetime(value: str) -> str:
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        value,
    ):
        raise ValueError("Use an ISO date-time with a timezone.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Use a valid ISO date-time with a timezone.") from None
    if parsed.tzinfo is None:
        raise ValueError("Use an ISO date-time with a timezone.")
    return value


IsoDateTime = Annotated[str, AfterValidator(iso_datetime)]


def parsed_datetime(value: IsoDateTime) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def require_unique(values: list[Any], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique.")


def validate_scalar(value: ContextValue | None) -> None:
    if isinstance(value, str) and not 1 <= len(value) <= 1000:
        raise ValueError("Context string values must contain 1 to 1000 characters.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Context numeric values must be finite.")


class WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class AgentBinding(WireModel):
    journey_id: JourneyId | None = None
    name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")]
    version: Identifier
    model_deployment: Identifier | None = None


class DiscoveryCommand(WireModel):
    action: Literal["respond", "skip", "general", "correct", "remove", "explore", "refine"] = (
        "respond"
    )
    revision: Annotated[StrictInt, Field(ge=0)]
    question_id: Identifier | None = None
    fact_key: DiscoveryFactKey | None = None

    @model_validator(mode="after")
    def bounded_command(self) -> Self:
        if (self.action in ("correct", "remove")) != (self.fact_key is not None):
            raise ValueError("Only a correction or removal may name an existing fact.")
        if self.action == "skip" and self.question_id is None:
            raise ValueError("Skipping requires the current server-owned question.")
        if self.action not in ("respond", "skip") and self.question_id is not None:
            raise ValueError("This command cannot answer a question.")
        return self


class DiscoveryFact(WireModel):
    key: DiscoveryFactKey
    label: Annotated[str, Field(min_length=1, max_length=100)]
    value: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    status: Literal["provided", "unknown", "declined", "disputed"]
    provenance: Literal["citizen-answer"] = "citizen-answer"

    @model_validator(mode="after")
    def explicit_value(self) -> Self:
        if (self.status == "provided") != (self.value is not None):
            raise ValueError("Only an explicit answer may supply a fact value.")
        return self


class DiscoveryQuestion(WireModel):
    id: Identifier
    fact_key: DiscoveryFactKey
    text: Annotated[str, Field(min_length=1, max_length=500)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    choices: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=6
    )


class PathwaySuggestion(WireModel):
    journey_id: JourneyId
    reason: Annotated[str, Field(min_length=1, max_length=300)]


class PageSummary(WireModel):
    thread_id: Identifier
    revision: Annotated[StrictInt, Field(ge=1)]
    expires_at: IsoDateTime


class DiscoverySummary(PageSummary):
    version: Literal[1] = 1
    phase: Literal["understand", "plan"]
    goal_id: DiscoveryGoalId | None = None
    goal_label: Annotated[str, Field(min_length=1, max_length=100)]
    about: Literal["you", "someone-else", "unspecified"] = "unspecified"
    question_count: Annotated[StrictInt, Field(ge=0, le=3)]
    facts: list[DiscoveryFact] = Field(default_factory=list, max_length=7)
    question: DiscoveryQuestion | None = None
    suggestions: list[PathwaySuggestion] = Field(default_factory=list, max_length=3)
    suggested_demo_id: DemoPersonaId | None = None

    @model_validator(mode="after")
    def coherent_discovery(self) -> Self:
        require_unique([fact.key for fact in self.facts], "Discovery facts")
        require_unique([item.journey_id for item in self.suggestions], "Pathway suggestions")
        if self.question is not None and (self.phase != "understand" or self.goal_id is None):
            raise ValueError("A discovery question requires a current goal.")
        if self.phase != "plan" and (self.suggestions or self.suggested_demo_id):
            raise ValueError("Recommendations follow discovery.")
        return self


class ConversationCommand(WireModel):
    action: Literal["respond", "skip", "general", "correct", "remove", "explore", "sharing"]
    revision: Annotated[StrictInt, Field(ge=0)]
    question_id: Identifier | None = None
    fact_key: ConversationFactKey | None = None
    notice_version: Literal["ai-conversation-v1"]
    share_context: StrictBool

    @model_validator(mode="after")
    def narrow_command(self) -> Self:
        if (self.action in ("correct", "remove")) != (self.fact_key is not None):
            raise ValueError("Only corrections and removals may name an existing fact.")
        if self.action == "skip" and self.question_id is None:
            raise ValueError("Skipping requires a pending question.")
        if self.action not in ("respond", "skip") and self.question_id is not None:
            raise ValueError("This command does not answer a question.")
        return self


class RunOptions(WireModel):
    version: Literal[1, 2, 3, 4, 5, 6]
    mode: ChatMode | None = None
    journey_id: JourneyId | None = None
    research_requested: bool = Field(default=False, strict=True)
    discovery: DiscoveryCommand | None = None
    conversation: ConversationCommand | None = None

    @model_validator(mode="after")
    def explicit_conversation_scope(self) -> Self:
        if self.version not in (5, 6) and "conversation" in self.model_fields_set:
            raise ValueError("AI conversation requires version 5 or 6.")
        if self.version != 4 and "discovery" in self.model_fields_set:
            raise ValueError("Discovery requires version 4.")
        if self.version in (5, 6):
            if (
                self.mode != "general"
                or self.journey_id is not None
                or self.research_requested
                or self.conversation is None
            ):
                raise ValueError("Conversation versions require a general command and notice.")
            return self
        if self.version == 4:
            if (
                self.mode != "general"
                or self.journey_id is not None
                or self.research_requested
                or self.discovery is None
            ):
                raise ValueError("Version 4 requires an explicit, general discovery command.")
            return self
        if self.version == 1:
            if "mode" in self.model_fields_set:
                raise ValueError("Conversation modes require version 2 or 3.")
            return self
        if self.version == 2 and self.mode is None:
            raise ValueError("Version 2 requires an explicit conversation mode.")
        if self.version == 2 and self.mode not in ("general", "pathway"):
            raise ValueError("Version 2 supports only general or pathway mode.")
        if self.version == 2 and self.mode == "general" and self.journey_id is not None:
            raise ValueError("General chat cannot retain a hidden pathway scope.")
        if self.version == 2 and self.mode == "pathway" and self.journey_id is None:
            raise ValueError("Pathway mode requires a supported journey.")
        if self.version == 3 and (
            self.mode != "contextual-demo" or self.journey_id is not None or self.research_requested
        ):
            raise ValueError("Version 3 is reserved for server-owned contextual-demo sessions.")
        return self


class ResponseContext(WireModel):
    version: Literal[1] = 1
    kind: ResponseKind
    origin: ResponseOrigin
    decision_origin: ResponseOrigin | None = None


class Source(WireModel):
    id: Identifier
    title: Text
    publisher: Text
    url: OfficialUrl
    description: Text
    checked_at: IsoDate | None
    publisher_updated_at: IsoDate | None
    status: Literal["available", "limited", "pending", "blocked"]
    topics: list[Text] = Field(max_length=30)


class Step(WireModel):
    id: Identifier
    title: Text
    description: Text
    source_ids: list[Identifier] = Field(min_length=1, max_length=30)


class Handoff(WireModel):
    label: Text
    url: OfficialUrl
    description: Text
    source_ids: list[Identifier] = Field(min_length=1, max_length=30)


class Journey(WireModel):
    id: JourneyId
    title: Text
    prompt: Text
    summary: Text
    category: Text
    notice: Text
    source_ids: list[Identifier] = Field(min_length=1, max_length=30)
    steps: list[Step] = Field(min_length=1, max_length=30)
    handoffs: list[Handoff] = Field(min_length=1, max_length=10)


class Location(WireModel):
    id: Identifier
    name: Text
    municipality: Text
    address: Text
    hours: Text
    services: list[ServiceKey] = Field(max_length=50)
    excluded_services: list[ServiceKey] = Field(max_length=50)
    source_ids: list[Identifier] = Field(min_length=1, max_length=30)
    checked_at: IsoDate | None


class Catalog(WireModel):
    schema_version: Literal[1]
    as_of: IsoDate
    sources: list[Source] = Field(min_length=1, max_length=1000)
    journeys: list[Journey] = Field(min_length=7, max_length=7)
    locations: list[Location] = Field(max_length=500)

    @model_validator(mode="after")
    def references_resolve(self) -> Self:
        for collection in (self.sources, self.journeys, self.locations):
            if len({item.id for item in collection}) != len(collection):
                raise ValueError("Catalogue IDs must be unique within each collection.")
        if {journey.id for journey in self.journeys} != JOURNEY_IDS:
            raise ValueError("The seven approved journeys are required.")
        source_ids = {source.id for source in self.sources}
        references = [item.source_ids for item in (*self.journeys, *self.locations)]
        for journey in self.journeys:
            if len({step.id for step in journey.steps}) != len(journey.steps):
                raise ValueError("Step IDs must be unique within a journey.")
            references.extend(step.source_ids for step in journey.steps)
            references.extend(handoff.source_ids for handoff in journey.handoffs)
        if any(not set(refs) <= source_ids or len(refs) != len(set(refs)) for refs in references):
            raise ValueError("Every source reference must resolve and must be unique.")
        return self


class LocationsResponse(WireModel):
    locations: list[Location]


class EvidenceMetadata(WireModel):
    version: Literal[1] = 1
    source_ids: list[Identifier] = Field(min_length=1, max_length=30)
    document_type: Literal["guidance", "legal", "service-directory", "notice"]
    language: str | None = Field(default=None, max_length=80)
    content_hash: Sha256
    extraction_hash: Sha256
    review_hash: Sha256
    rights_review_id: str = Field(min_length=1, max_length=200)
    rights_hash: Sha256
    legal_status: (
        Literal["in-force", "not-yet-in-force", "repealed", "historical", "unknown"] | None
    ) = None
    effective_from: CalendarDate | None = None
    effective_to: CalendarDate | None = None
    consolidation_date: CalendarDate | None = None
    repealed_at: CalendarDate | None = None
    legal_section_id: str | None = Field(default=None, max_length=1000)
    is_historical: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.effective_from and self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("Legal intervals have an inclusive start and exclusive end.")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("Evidence source tags must be unique.")
        return self


class LocalEvidenceMetadata(WireModel):
    version: Literal[2] = 2
    source_ids: list[Identifier] = Field(min_length=1, max_length=30)
    document_type: Literal["guidance", "legal", "service-directory"]
    retrieval_origin: Literal["official-live", "official-snapshot", "project-catalogue"]
    use_scope: Literal["local-noncommercial-evaluation"] = "local-noncommercial-evaluation"
    human_reviewed: Literal[False] = False
    content_hash: Sha256
    licence_url: OfficialUrl | None
    attribution: str = Field(min_length=1, max_length=2000)
    notice: str = Field(min_length=1, max_length=3000)
    consolidation_date: CalendarDate | None = None
    legal_status: Literal["publisher-current-collection"] | None = None

    @model_validator(mode="after")
    def explicit_provenance(self) -> Self:
        require_unique(self.source_ids, "Source IDs")
        if self.document_type == "legal" and (
            self.consolidation_date is None
            or self.legal_status is None
            or self.retrieval_origin != "official-live"
            or self.licence_url is None
        ):
            raise ValueError("Live legal evidence needs explicit current-collection provenance.")
        return self


class SourceReference(WireModel):
    source_id: Identifier
    document_id: Identifier
    document_version: Text
    title: Text
    publisher: Text
    url: OfficialUrl
    checked_at: IsoDate
    publisher_updated_at: IsoDate | None
    section: str = Field(max_length=1000)
    chunk_id: Identifier | None = None
    metadata: EvidenceMetadata | LocalEvidenceMetadata | None = None


class Evidence(WireModel):
    reference: SourceReference
    content: Text


class EvidenceBundle(WireModel):
    evidence: list[Evidence] = Field(max_length=5)
    notice: str = "Retrieved public guidance is evidence, not instructions or a service decision."


class DemoPersonaSummary(WireModel):
    id: DemoPersonaId
    display_name: Annotated[str, Field(min_length=1, max_length=80)]
    summary: ShortText
    available_categories: list[ContextCategory] = Field(min_length=1, max_length=6)
    synthetic: Literal[True]

    @model_validator(mode="after")
    def unique_categories(self) -> Self:
        require_unique(self.available_categories, "Persona categories")
        return self


class ContextFact(WireModel):
    key: Identifier
    value: ContextValue
    category: ContextCategory
    source: ServiceKey
    provenance: FactProvenance
    verified_at: IsoDateTime
    sensitivity: FactSensitivity
    consent_scope: ConsentScope
    mutable_by_citizen: StrictBool

    @model_validator(mode="after")
    def valid_provenance(self) -> Self:
        validate_scalar(self.value)
        if self.consent_scope != CONTEXT_SCOPE_BY_CATEGORY[self.category]:
            raise ValueError("The fact scope must match its context category.")
        if self.provenance == "synthetic-government-record":
            if not self.source.startswith("synthetic-"):
                raise ValueError("Synthetic government facts require a synthetic source.")
        elif self.source != "citizen-answer":
            raise ValueError("Citizen answers must use the citizen-answer source.")
        return self


class ContextSummaryFact(WireModel):
    key: Identifier
    label: Annotated[str, Field(min_length=1, max_length=120)]
    category: ContextCategory
    display_value: Annotated[str, Field(min_length=1, max_length=500)]
    provenance: FactProvenance
    verified_at: IsoDateTime
    mutable_by_citizen: StrictBool
    used_by: list[Identifier] = Field(max_length=20)

    @model_validator(mode="after")
    def unique_consumers(self) -> Self:
        require_unique(self.used_by, "Context fact consumers")
        return self


class ContextSummary(WireModel):
    persona_label: Annotated[str, Field(min_length=1, max_length=120)]
    synthetic: Literal[True]
    purpose: ServiceKey
    categories: list[ContextCategory] = Field(min_length=1, max_length=6)
    facts: list[ContextSummaryFact] = Field(max_length=50)
    missing_facts: list[Identifier] = Field(max_length=30)
    consent_expires_at: IsoDateTime

    @model_validator(mode="after")
    def coherent_summary(self) -> Self:
        require_unique(self.categories, "Context summary categories")
        require_unique([fact.key for fact in self.facts], "Context summary fact keys")
        require_unique(self.missing_facts, "Missing context facts")
        if any(fact.category not in self.categories for fact in self.facts):
            raise ValueError("Every displayed fact must belong to a disclosed category.")
        if {fact.key for fact in self.facts} & set(self.missing_facts):
            raise ValueError("A context fact cannot be both present and missing.")
        return self


class ConsentScopeProposal(WireModel):
    scope: ConsentScope
    category: ContextCategory
    reason: Annotated[str, Field(min_length=1, max_length=300)]
    required: StrictBool

    @model_validator(mode="after")
    def scope_matches_category(self) -> Self:
        if self.scope != CONTEXT_SCOPE_BY_CATEGORY[self.category]:
            raise ValueError("The proposed scope must match its context category.")
        return self


class ConsentProposal(WireModel):
    proposal_id: Identifier
    persona_id: DemoPersonaId
    purpose: ServiceKey
    notice_version: Identifier
    scopes: list[ConsentScopeProposal] = Field(min_length=1, max_length=6)
    expires_at: IsoDateTime
    synthetic: Literal[True]

    @model_validator(mode="after")
    def unique_scopes(self) -> Self:
        require_unique([item.scope for item in self.scopes], "Proposed consent scopes")
        require_unique([item.category for item in self.scopes], "Proposed consent categories")
        return self


class ConsentReceipt(WireModel):
    consent_id: Identifier
    purpose: ServiceKey
    scopes: list[ConsentScope] = Field(min_length=1, max_length=6)
    subject_hash: Annotated[
        str,
        Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$"),
    ]
    notice_version: Identifier
    granted_at: IsoDateTime
    expires_at: IsoDateTime
    revoked_at: IsoDateTime | None

    @model_validator(mode="after")
    def valid_receipt_window(self) -> Self:
        require_unique(self.scopes, "Consent scopes")
        granted = parsed_datetime(self.granted_at)
        expires = parsed_datetime(self.expires_at)
        if expires <= granted:
            raise ValueError("Consent expiry must be after the grant time.")
        if self.revoked_at is not None:
            revoked = parsed_datetime(self.revoked_at)
            if revoked < granted or revoked > expires:
                raise ValueError("Consent revocation must fall within the receipt lifetime.")
        return self


class ConsentRevocation(WireModel):
    revocation_id: Identifier
    consent_id: Identifier
    revoked_scopes: list[ConsentScope] = Field(min_length=1, max_length=6)
    revoked_at: IsoDateTime
    reason: Literal[
        "citizen-request",
        "session-reset",
        "session-expired",
        "persona-changed",
    ]

    @model_validator(mode="after")
    def unique_revoked_scopes(self) -> Self:
        require_unique(self.revoked_scopes, "Revoked consent scopes")
        return self


class ProgramSourceVersion(WireModel):
    source_id: Identifier
    version: Identifier


class ProgramMatch(WireModel):
    program_id: Identifier
    status: ProgramMatchStatus
    rule_id: Identifier | None = None
    rule_version: Identifier
    policy_effective_date: CalendarDate
    satisfied_conditions: list[Identifier] = Field(max_length=30)
    missing_facts: list[Identifier] = Field(max_length=30)
    disqualifying_facts: list[Identifier] = Field(max_length=30)
    source_ids: list[Identifier] = Field(min_length=1, max_length=20)
    source_versions: list[ProgramSourceVersion] = Field(min_length=1, max_length=20)
    notice: Literal["This is a screening indicator, not an eligibility decision."]

    @model_validator(mode="after")
    def coherent_match(self) -> Self:
        fact_groups = (
            self.satisfied_conditions,
            self.missing_facts,
            self.disqualifying_facts,
        )
        for label, values in zip(
            ("Satisfied conditions", "Missing facts", "Disqualifying facts"),
            fact_groups,
            strict=True,
        ):
            require_unique(values, label)
        if any(
            set(left) & set(right)
            for left, right in (
                (fact_groups[0], fact_groups[1]),
                (
                    fact_groups[0],
                    fact_groups[2],
                ),
                (fact_groups[1], fact_groups[2]),
            )
        ):
            raise ValueError("Satisfied, missing and disqualifying facts must not overlap.")
        require_unique(self.source_ids, "Program match source IDs")
        version_ids = [item.source_id for item in self.source_versions]
        require_unique(version_ids, "Program match source versions")
        if version_ids != self.source_ids:
            raise ValueError("Every source ID must have one matching source version.")
        return self


def unique_program_matches(matches: list[ProgramMatch]) -> list[ProgramMatch]:
    require_unique([match.program_id for match in matches], "Program match IDs")
    return matches


ProgramMatches = Annotated[
    list[ProgramMatch],
    Field(min_length=1, max_length=20),
    AfterValidator(unique_program_matches),
]


class PreviewField(WireModel):
    field: Identifier
    label: Annotated[str, Field(min_length=1, max_length=120)]
    value: PreviewValue
    source: PreviewFieldSource
    source_fact_key: Identifier | None
    editable: StrictBool
    sensitivity: FactSensitivity
    requires_confirmation: StrictBool

    @model_validator(mode="after")
    def valid_field_provenance(self) -> Self:
        validate_scalar(self.value)
        if self.source == "missing":
            if self.value is not None or self.source_fact_key is not None:
                raise ValueError("Missing preview fields cannot carry values or provenance.")
        elif self.value is None or self.source_fact_key is None:
            raise ValueError("Populated preview fields require a source fact key.")
        return self


class ApplicationPreview(WireModel):
    preview_id: Identifier
    flow_id: ContextFlowId
    schema_version: Literal[1]
    fields: list[PreviewField] = Field(min_length=1, max_length=50)
    missing_items: list[ShortText] = Field(max_length=30)
    submission_enabled: Literal[False]
    requires_human_review: Literal[True]
    expires_at: IsoDateTime

    @model_validator(mode="after")
    def unique_preview_fields(self) -> Self:
        require_unique([field.field for field in self.fields], "Preview field names")
        require_unique(self.missing_items, "Preview missing items")
        return self


class ConsentRequest(WireModel):
    checkpoint_id: Identifier
    preview_id: Identifier
    purpose: ServiceKey
    destination_name: Annotated[str, Field(min_length=1, max_length=160)]
    destination_url: OfficialUrl
    categories_to_share: list[ContextCategory] = Field(max_length=6)
    field_names_to_share: list[Identifier] = Field(max_length=50)
    transfer_mode: Literal["none"]
    reviewed_by_citizen: StrictBool
    submission_enabled: Literal[False]

    @model_validator(mode="after")
    def unique_handoff_scope(self) -> Self:
        require_unique(self.categories_to_share, "Handoff categories")
        require_unique(self.field_names_to_share, "Handoff field names")
        return self


class AuditReceiptEvent(WireModel):
    event_id: Identifier
    sequence: StrictInt = Field(ge=1)
    occurred_at: IsoDateTime
    action: AuditAction
    trace_ref: Annotated[
        str | None,
        Field(
            min_length=16,
            max_length=128,
            pattern=r"^[a-f0-9]+$",
        ),
    ] = None
    run_ref: Annotated[
        str | None,
        Field(
            min_length=64,
            max_length=64,
            pattern=r"^[a-f0-9]{64}$",
        ),
    ] = None
    actor_label: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=160,
            pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:@-]*$",
        ),
    ] = None
    tool: ContextAuditTool | None = None
    consent_scopes: list[ConsentScope] = Field(default_factory=list, max_length=6)
    flow_id: ContextFlowId | None = None
    rule_set_version: Identifier | None = None
    category: ContextCategory | None = None
    rule_id: Identifier | None = None
    rule_version: Identifier | None = None
    source_ids: list[Identifier] = Field(default_factory=list, max_length=20)
    source_versions: list[ProgramSourceVersion] = Field(default_factory=list, max_length=20)
    outcome: AuditOutcome
    error_code: Annotated[
        str | None,
        Field(max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$"),
    ] = None

    @model_validator(mode="after")
    def required_event_evidence(self) -> Self:
        require_unique(self.consent_scopes, "Audit consent scopes")
        require_unique(self.source_ids, "Audit source IDs")
        source_ids = [item.source_id for item in self.source_versions]
        require_unique(source_ids, "Audit source versions")
        if source_ids and source_ids != self.source_ids:
            raise ValueError("Every audit source ID must have one matching version.")
        if self.action == "context-category-accessed" and self.category is None:
            raise ValueError("Context access events require a category.")
        if self.action == "rule-evaluated" and (
            self.rule_id is None
            or self.rule_version is None
            or not self.source_ids
            or not self.source_versions
        ):
            raise ValueError("Rule evaluation events require rule and source versions.")
        if self.action == "access-denied" and self.error_code is None:
            raise ValueError("Denied audit events require an error code.")
        if self.action == "context-run-completed" and (
            self.trace_ref is None or self.run_ref is None
        ):
            raise ValueError("Run completion audit events require opaque run and trace references.")
        return self


class AuditReceipt(WireModel):
    receipt_id: Identifier
    session_ref: Identifier
    persona_label: Annotated[str, Field(min_length=1, max_length=120)]
    synthetic: Literal[True]
    events: list[AuditReceiptEvent] = Field(min_length=1, max_length=100)
    contains_raw_context_values: Literal[False]

    @model_validator(mode="after")
    def unique_events(self) -> Self:
        require_unique([event.event_id for event in self.events], "Audit event IDs")
        if [event.sequence for event in self.events] != list(range(1, len(self.events) + 1)):
            raise ValueError("Audit receipt events must use contiguous deterministic ordering.")
        return self


class GuidedPlan(WireModel):
    mode: Literal["guided"] = "guided"
    journey: Journey
    sources: list[Source]
    transactions_enabled: Literal[False] = False


class ProgressUpdate(WireModel):
    version: Literal[1] = 1
    phase: Literal["connecting", "retrieving", "thinking", "preparing", "locations", "validating"]
    message: str = Field(max_length=300)


class PreparationArtifact(WireModel):
    version: Literal[1] = 1
    id: Identifier
    kind: Literal["preparation"] = "preparation"
    journey: Journey
    sources: list[Source] = Field(max_length=100)
    transactions_enabled: Literal[False] = False


class LocationsArtifact(WireModel):
    version: Literal[1] = 1
    id: Identifier
    kind: Literal["locations"] = "locations"
    locations: list[Location] = Field(max_length=100)
    sources: list[Source] = Field(max_length=100)
    notice: str = Field(max_length=500)


class ContextSummaryArtifact(WireModel):
    version: Literal[1] = 1
    id: Identifier
    kind: Literal["context-summary"] = "context-summary"
    payload: ContextSummary


class ProgramMatchesArtifact(WireModel):
    version: Literal[1] = 1
    id: Identifier
    kind: Literal["program-matches"] = "program-matches"
    payload: ProgramMatches


class ApplicationPreviewArtifact(WireModel):
    version: Literal[1] = 1
    id: Identifier
    kind: Literal["application-preview"] = "application-preview"
    payload: ApplicationPreview


class ConsentRequestArtifact(WireModel):
    version: Literal[1] = 1
    id: Identifier
    kind: Literal["consent-request"] = "consent-request"
    payload: ConsentRequest


class AuditReceiptArtifact(WireModel):
    version: Literal[1] = 1
    id: Identifier
    kind: Literal["audit-receipt"] = "audit-receipt"
    payload: AuditReceipt


ContextArtifact = Annotated[
    ContextSummaryArtifact
    | ProgramMatchesArtifact
    | ApplicationPreviewArtifact
    | ConsentRequestArtifact
    | AuditReceiptArtifact,
    Field(discriminator="kind"),
]
Artifact = Annotated[
    PreparationArtifact
    | LocationsArtifact
    | ContextSummaryArtifact
    | ProgramMatchesArtifact
    | ApplicationPreviewArtifact
    | ConsentRequestArtifact
    | AuditReceiptArtifact,
    Field(discriminator="kind"),
]


def unique_artifacts(artifacts: list[Artifact]) -> list[Artifact]:
    require_unique([artifact.id for artifact in artifacts], "Artifact IDs")
    return artifacts


ArtifactList = Annotated[
    list[Artifact],
    Field(max_length=10),
    AfterValidator(unique_artifacts),
]


class SourceHealth(WireModel):
    status: Literal[
        "unknown", "ready", "expiring", "expired", "empty", "unusable", "unavailable"
    ] = "unknown"
    checked_at: IsoDateTime | None = None
    usable_documents: int = Field(default=0, ge=0)
    expired_documents: int = Field(default=0, ge=0)
    rejected_chunks: int = Field(default=0, ge=0)
    next_expiry_at: IsoDateTime | None = None
    covered_source_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    missing_source_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    error_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")] | None = None


class Capabilities(WireModel):
    mode: Literal["guided", "foundry"]
    ai_configured: bool
    web_iq_enabled: Literal[False] = False
    transactions_enabled: Literal[False] = False
    message: str
    journeys: dict[JourneyId, bool] = Field(default_factory=dict)
    general_chat_configured: bool = False
    retrieval_ready: bool = False
    source_health: SourceHealth = Field(default_factory=SourceHealth)
    request_versions: list[Literal[1, 2, 3, 4, 5, 6]] = Field(
        default_factory=lambda: [1, 2, 3],
        min_length=1,
        max_length=6,
    )
    discovery_available: StrictBool = False
    conversation_available: StrictBool = False
    conversation_agent_ready: StrictBool = False
    task_assistance_available: StrictBool = False
    local_evidence_evaluation: StrictBool = False
    synthetic_context_available: StrictBool = False
    real_identity_integrated: Literal[False] = False
    real_citizen_identity_configured: Literal[False] = False

    @model_validator(mode="after")
    def coherent_capabilities(self) -> Self:
        require_unique(self.request_versions, "Request versions")
        if self.synthetic_context_available and 3 not in self.request_versions:
            raise ValueError("Synthetic context requires request version 3.")
        if self.discovery_available != (4 in self.request_versions):
            raise ValueError("Discovery availability must match request version 4.")
        if self.conversation_available != (5 in self.request_versions):
            raise ValueError("AI conversation availability must match request version 5.")
        if 6 in self.request_versions and not (
            self.conversation_available and self.task_assistance_available
        ):
            raise ValueError("Grounded conversation requires AI conversation and task support.")
        return self
