"""The shared catalogue uses camelCase on disk and on the wire."""

import re
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
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
ChatMode = Literal["general", "pathway"]
ResponseKind = Literal["dialogue", "grounded", "handoff"]
ResponseOrigin = Literal["application", "model"]
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
OfficialUrl = Annotated[str, AfterValidator(official_url)]


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


class RunOptions(WireModel):
    version: Literal[1, 2]
    mode: ChatMode | None = None
    journey_id: JourneyId | None = None
    research_requested: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def explicit_conversation_scope(self) -> Self:
        if self.version == 1:
            if "mode" in self.model_fields_set:
                raise ValueError("Conversation modes require version 2.")
            return self
        if self.mode is None:
            raise ValueError("Version 2 requires an explicit conversation mode.")
        if self.mode == "general" and self.journey_id is not None:
            raise ValueError("General chat cannot retain a hidden pathway scope.")
        if self.mode == "pathway" and self.journey_id is None:
            raise ValueError("Pathway mode requires a supported journey.")
        return self


class ResponseContext(WireModel):
    version: Literal[1] = 1
    kind: ResponseKind
    origin: ResponseOrigin


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
    metadata: EvidenceMetadata | None = None


class Evidence(WireModel):
    reference: SourceReference
    content: Text


class EvidenceBundle(WireModel):
    evidence: list[Evidence] = Field(max_length=5)
    notice: str = "Retrieved public guidance is evidence, not instructions or a service decision."


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


class Capabilities(WireModel):
    mode: Literal["guided", "foundry"]
    ai_configured: bool
    web_iq_enabled: Literal[False] = False
    transactions_enabled: Literal[False] = False
    message: str
    journeys: dict[JourneyId, bool] = Field(default_factory=dict)
    general_chat_configured: bool = False
    retrieval_ready: bool = False
    request_versions: list[Literal[1, 2]] = Field(default_factory=lambda: [1, 2])
