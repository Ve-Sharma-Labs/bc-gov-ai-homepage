from pathlib import Path

from pydantic import ValidationError

from bc_api.errors import ApiError
from bc_api.models import Catalog, GuidedPlan, Journey, LocationsResponse

KNOWN_SERVICES = frozenset({"icbc-licensing", "income-assistance", "bc-services-card", "bceid"})


class CatalogRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._version: tuple[int, int] | None = None
        self._catalog: Catalog | None = None

    def get(self) -> Catalog:
        try:
            stat = self.path.stat()
            version = (stat.st_mtime_ns, stat.st_size)
            if stat.st_size > 2_000_000:
                raise ValueError("Catalogue size limit.")
            if self._version != version or self._catalog is None:
                # Do not serve a cached catalogue after a failed replacement.
                self._catalog = None
                self._catalog = Catalog.model_validate_json(
                    self.path.read_bytes(), by_alias=True, by_name=False
                )
                self._version = version
            return self._catalog
        except OSError:
            self._catalog = None
            raise ApiError(
                503, "CATALOG_UNAVAILABLE", "The curated service catalogue is unavailable."
            ) from None
        except ValueError, ValidationError:
            self._catalog = None
            raise ApiError(
                503, "CATALOG_INVALID", "The service catalogue did not pass source validation."
            ) from None

    def journey(self, journey_id: str) -> Journey:
        journey = next((item for item in self.get().journeys if item.id == journey_id), None)
        if journey is None:
            raise ApiError(404, "JOURNEY_NOT_FOUND", "That guided journey is not available.")
        usable = {s.id for s in self.get().sources if s.status in ("available", "limited")}
        if not set(journey.source_ids) & usable:
            raise ApiError(
                503, "SOURCES_UNAVAILABLE", "The sources for this journey are unavailable."
            )
        return journey

    def plan(self, journey_id: str) -> GuidedPlan:
        journey = self.journey(journey_id)
        ids = set(journey.source_ids)
        ids.update(source_id for step in journey.steps for source_id in step.source_ids)
        ids.update(source_id for handoff in journey.handoffs for source_id in handoff.source_ids)
        return GuidedPlan(
            journey=journey, sources=[source for source in self.get().sources if source.id in ids]
        )

    def locations(self, service: str | None, municipality: str | None) -> LocationsResponse:
        catalog = self.get()
        known = KNOWN_SERVICES | {
            key for item in catalog.locations for key in (*item.services, *item.excluded_services)
        }
        if service is not None and service not in known:
            raise ApiError(400, "UNKNOWN_SERVICE", "Choose a supported service capability.")
        if municipality is not None:
            municipality = municipality.strip()
            if not municipality or len(municipality) > 100 or not municipality.isprintable():
                raise ApiError(400, "INVALID_MUNICIPALITY", "Use a municipality name only.")
        return LocationsResponse(
            locations=[
                item
                for item in catalog.locations
                if (
                    service is None
                    or (service in item.services and service not in item.excluded_services)
                )
                and (
                    municipality is None or item.municipality.casefold() == municipality.casefold()
                )
            ]
        )
