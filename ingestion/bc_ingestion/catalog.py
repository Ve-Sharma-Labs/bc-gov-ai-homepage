"""Validate, but do not implement an alternate backend for, the shared contract."""

from datetime import date, datetime
import json
from pathlib import Path
from urllib.parse import urlsplit

from .policy import AcquisitionError, PUBLISHERS, canonicalize
from .locations import SERVICE_KEYS


JOURNEY_IDS = {
    "licence-renewal",
    "road-test-booking",
    "rental-assistance",
    "health-coverage",
    "pharmacare-registration",
    "primary-care",
    "service-bc",
}
SOURCE_IDS = {
    "bc-content", "service-bc", "housing-tenancy", "health", "family-social-supports",
    "employment-business", "taxes", "bc-housing", "icbc", "workbc", "healthlink-bc", "bc-laws",
}
OFFICIAL_DOMAINS = ("gov.bc.ca", "icbc.com", "bchousing.org", "workbc.ca", "healthlinkbc.ca")


def _publisher_domain(host: str | None) -> str | None:
    if not host:
        return None
    return next(
        (domain for domain in OFFICIAL_DOMAINS if host == domain or host.endswith("." + domain)),
        None,
    )


def _keys(record, names: str) -> None:
    if not isinstance(record, dict) or set(record) != set(names.split()):
        raise AcquisitionError(f"Catalogue fields do not match contract: expected {names}")


def _text(value) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AcquisitionError("Catalogue text fields must be non-empty strings")


def _strings(value) -> None:
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise AcquisitionError("Expected a string array")
    if len(value) != len(set(value)):
        raise AcquisitionError("Duplicate array entries")


def _date(value, nullable=True) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise AcquisitionError("Expected an ISO date or date-time")
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Date-time needs an offset")
    except ValueError as exc:
        raise AcquisitionError("Invalid catalogue ISO date") from exc


def validate_catalog(catalog: dict) -> dict:
    _keys(catalog, "schemaVersion asOf sources journeys locations")
    if type(catalog["schemaVersion"]) is not int or catalog["schemaVersion"] != 1:
        raise AcquisitionError("Unsupported catalogue schemaVersion")
    _date(catalog["asOf"], nullable=False)
    for name in ("sources", "journeys", "locations"):
        if not isinstance(catalog[name], list):
            raise AcquisitionError(f"{name} must be an array")
    sources = {}
    for source in catalog["sources"]:
        _keys(source, "id title publisher url description checkedAt publisherUpdatedAt status topics")
        for key in ("id", "title", "publisher", "url", "description"):
            _text(source[key])
        if source["id"] in sources:
            raise AcquisitionError("Duplicate source id")
        sources[source["id"]] = source
        if source["status"] not in ("available", "limited", "pending", "blocked"):
            raise AcquisitionError("Invalid source status")
        _strings(source["topics"])
        _date(source["checkedAt"])
        _date(source["publisherUpdatedAt"])
        if urlsplit(canonicalize(source["url"])).hostname not in PUBLISHERS:
            raise AcquisitionError("Source URL must identify an approved publisher")
    if set(sources) != SOURCE_IDS:
        raise AcquisitionError("Catalogue must contain exactly the twelve prescribed sources")

    def refs(values, within=None):
        _strings(values)
        if not values or not set(values) <= set(sources):
            raise AcquisitionError("Missing or unknown source reference")
        if within is not None and not set(values) <= set(within):
            raise AcquisitionError("Step/handoff references must also belong to the journey")
        if any(sources[s]["status"] in ("blocked", "pending") for s in values):
            raise AcquisitionError("Blocked/pending content cannot substantiate a published claim")

    journey_ids = []
    for journey in catalog["journeys"]:
        _keys(journey, "id title prompt summary category notice sourceIds steps handoffs")
        for key in ("id", "title", "prompt", "summary", "category", "notice"):
            _text(journey[key])
        journey_ids.append(journey["id"])
        refs(journey["sourceIds"])
        if not isinstance(journey["steps"], list) or not journey["steps"]:
            raise AcquisitionError("Every journey needs preparation steps")
        if not isinstance(journey["handoffs"], list) or not journey["handoffs"]:
            raise AcquisitionError("Every journey needs an official handoff")
        step_ids = set()
        for step in journey["steps"]:
            _keys(step, "id title description sourceIds")
            for key in ("id", "title", "description"):
                _text(step[key])
            if step["id"] in step_ids:
                raise AcquisitionError("Duplicate step id")
            step_ids.add(step["id"])
            refs(step["sourceIds"], journey["sourceIds"])
        for handoff in journey["handoffs"]:
            _keys(handoff, "label url description sourceIds")
            for key in ("label", "url", "description"):
                _text(handoff[key])
            refs(handoff["sourceIds"], journey["sourceIds"])
            host = urlsplit(canonicalize(handoff["url"])).hostname
            if _publisher_domain(host) not in {
                _publisher_domain(urlsplit(sources[s]["url"]).hostname)
                for s in handoff["sourceIds"]
            }:
                raise AcquisitionError("Handoff publisher does not match its cited source")
    if len(journey_ids) != 7 or set(journey_ids) != JOURNEY_IDS:
        raise AcquisitionError("Expected the seven prescribed journey IDs")
    location_ids = set()
    for location in catalog["locations"]:
        _keys(location, "id name municipality address hours services excludedServices sourceIds checkedAt")
        for key in ("id", "name", "municipality", "address", "hours"):
            _text(location[key])
        if location["id"] in location_ids:
            raise AcquisitionError("Duplicate location id")
        location_ids.add(location["id"])
        refs(location["sourceIds"])
        _date(location["checkedAt"])
        _strings(location["services"])
        _strings(location["excludedServices"])
        if not (set(location["services"]) | set(location["excludedServices"])) <= set(SERVICE_KEYS):
            raise AcquisitionError("Unreviewed location service key")
        if set(location["services"]) & set(location["excludedServices"]):
            raise AcquisitionError("Remove excluded services from the published inclusions")
    return catalog


def load_catalog(path: str | Path) -> dict:
    return validate_catalog(json.loads(Path(path).read_text(encoding="utf-8")))
