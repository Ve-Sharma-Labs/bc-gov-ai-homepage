"""Server-owned progress and canonical tool-result presentation."""

from typing import Any

from ag_ui.core import CustomEvent
from pydantic import TypeAdapter, ValidationError

from bc_api.catalog import CatalogRepository
from bc_api.errors import ApiError
from bc_api.models import (
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
}
LOCATION_NOTICE = (
    "These are reviewed office snapshots. Published hours are not live appointment availability."
)
ARTIFACT = TypeAdapter(PreparationArtifact | LocationsArtifact)


def response_context_event(kind: ResponseKind, origin: ResponseOrigin) -> CustomEvent:
    value = ResponseContext(kind=kind, origin=origin)
    return CustomEvent(name="bc.response", value=value.model_dump(by_alias=True))


def progress_event(phase: str) -> CustomEvent:
    if not isinstance(phase, str) or phase not in PROGRESS:
        raise ApiError(502, "OUTPUT_INVALID", "Unsupported assistant progress was withheld.")
    value = ProgressUpdate.model_validate({"phase": phase, "message": PROGRESS[phase]})
    return CustomEvent(name="status", value=value.model_dump(by_alias=True))


def validate_artifact(value: Any, catalog: CatalogRepository) -> CustomEvent:
    try:
        artifact = ARTIFACT.validate_python(value)
        if isinstance(artifact, PreparationArtifact):
            plan = catalog.plan(artifact.journey.id)
            valid = artifact.journey == plan.journey and artifact.sources == plan.sources
        else:
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
        if not valid:
            raise ValueError("The result does not match the reviewed catalogue.")
    except ValidationError, ValueError:
        raise ApiError(
            502, "OUTPUT_INVALID", "An unverified preparation or location result was withheld."
        ) from None
    return CustomEvent(name="bc.artifact", value=artifact.model_dump(by_alias=True))
