"""Server-owned progress and canonical tool-result presentation."""

from dataclasses import dataclass
from typing import Any

from ag_ui.core import CustomEvent
from pydantic import TypeAdapter, ValidationError

from bc_api.catalog import CatalogRepository
from bc_api.errors import ApiError
from bc_api.models import (
    Artifact,
    ContextArtifact,
    LocationsArtifact,
    PreparationArtifact,
    ProgressUpdate,
    ResponseContext,
    ResponseKind,
    ResponseOrigin,
)

PROGRESS = {
    "connecting": "Connecting to the assistant...",
    "retrieving": "Checking official BC sources...",
    "thinking": "Thinking...",
    "preparing": "Preparing your next steps...",
    "locations": "Checking published service locations...",
    "validating": "Checking the answer against its sources...",
}
TOOL_PHASES = {
    "search_approved_sources": "retrieving",
    "build_preparation_plan": "preparing",
    "find_service_locations": "locations",
    "read_consented_context": "thinking",
    "evaluate_program_rules": "validating",
    "build_application_preview": "preparing",
}
LOCATION_NOTICE = (
    "These are reviewed office snapshots. Published hours are not live appointment availability."
)
ARTIFACT = TypeAdapter(Artifact)
CONTEXT_ARTIFACT = TypeAdapter(ContextArtifact)


@dataclass
class ContextArtifactValidator:
    expected: tuple[ContextArtifact, ...]
    position: int = 0

    def accept(self, artifact: ContextArtifact) -> bool:
        if self.position >= len(self.expected) or artifact != self.expected[self.position]:
            return False
        self.position += 1
        return True

    def ensure_complete(self) -> None:
        if self.position != len(self.expected):
            raise ApiError(
                502,
                "OUTPUT_INVALID",
                "The server-owned contextual artifacts were incomplete.",
            )


def response_context_event(kind: ResponseKind, origin: ResponseOrigin) -> CustomEvent:
    value = ResponseContext(kind=kind, origin=origin)
    return CustomEvent(name="bc.response", value=value.model_dump(by_alias=True))


def progress_event(phase: str) -> CustomEvent:
    if not isinstance(phase, str) or phase not in PROGRESS:
        raise ApiError(502, "OUTPUT_INVALID", "Unsupported assistant progress was withheld.")
    value = ProgressUpdate.model_validate({"phase": phase, "message": PROGRESS[phase]})
    return CustomEvent(name="status", value=value.model_dump(by_alias=True))


def validate_artifact(
    value: Any,
    catalog: CatalogRepository,
    contextual: ContextArtifactValidator | None = None,
) -> CustomEvent:
    try:
        artifact = ARTIFACT.validate_python(value)
        if isinstance(artifact, PreparationArtifact):
            plan = catalog.plan(artifact.journey.id)
            valid = artifact.journey == plan.journey and artifact.sources == plan.sources
        else:
            if isinstance(artifact, LocationsArtifact):
                snapshot = catalog.get()
                known = {location.id: location for location in snapshot.locations}
                ids = [location.id for location in artifact.locations]
                source_ids = {key for location in artifact.locations for key in location.source_ids}
                sources = [source for source in snapshot.sources if source.id in source_ids]
                valid = (
                    len(ids) == len(set(ids))
                    and all(known.get(location.id) == location for location in artifact.locations)
                    and artifact.sources == sources
                    and artifact.notice == LOCATION_NOTICE
                )
            else:
                context_artifact = CONTEXT_ARTIFACT.validate_python(
                    artifact.model_dump(by_alias=True)
                )
                valid = contextual is not None and contextual.accept(context_artifact)
        if not valid:
            raise ValueError("The result does not match the reviewed catalogue.")
    except ValidationError, ValueError:
        raise ApiError(
            502,
            "OUTPUT_INVALID",
            "An unverified server-owned artifact was withheld.",
        ) from None
    return CustomEvent(name="bc.artifact", value=artifact.model_dump(by_alias=True))
