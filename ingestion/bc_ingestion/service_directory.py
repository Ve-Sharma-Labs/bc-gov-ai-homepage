"""Reviewable Service BC directory documents derived from the licensed CKAN candidate."""

import hashlib
import json
import math
from urllib.parse import urlsplit

from .extract import Document, Section
from .fetch import Response
from .metadata import (
    SERVICE_DIRECTORY_EXTRACTION_METHOD,
    digest,
    extraction_digest,
    iso_datetime,
    legal_date,
)
from .policy import AcquisitionError
from .source_adapters import AdaptedDocument, SERVICE_BC_DATASET_URL


OFFICE_FIELDS = {
    "officeCode",
    "name",
    "address",
    "locality",
    "phone",
    "fax",
    "email",
    "website",
    "latitude",
    "longitude",
}
CANONICAL_LICENCE_URL = (
    "https://www2.gov.bc.ca/gov/content/data/policy-standards/"
    "data-policies/open-data/open-government-licence-bc"
)
DATASET_LICENCE_URL = (
    "https://www2.gov.bc.ca/gov/content?id=A519A56BC2BF44E4A008B33FCF527F61"
)
PACKAGE_ID = "2b44d212-5438-47a9-ad23-20eb8ada9709"
PACKAGE_NAME = "service-bc-office-locations"
RESOURCE_ID = "c7cc9297-220c-4d6c-a9a7-72d0680b2f74"


def _candidate_identity(candidate: dict) -> None:
    if (
        not isinstance(candidate, dict)
        or candidate.get("schemaVersion") != 1
        or candidate.get("mode") != "candidate-only"
        or candidate.get("sourceId") != "service-bc"
        or candidate.get("publicationApproved") is not False
    ):
        raise AcquisitionError("Service BC directory conversion requires the candidate-only CKAN artifact")
    records = candidate.get("records")
    if (
        not isinstance(records, list)
        or not 1 <= len(records) <= 100
        or candidate.get("recordCount") != len(records)
        or candidate.get("contentHash") != digest(records)
    ):
        raise AcquisitionError("Service BC directory candidate record identity is invalid")
    review_hash = candidate.get("reviewHash")
    unsigned = {key: value for key, value in candidate.items() if key != "reviewHash"}
    if not isinstance(review_hash, str) or review_hash != digest(unsigned):
        raise AcquisitionError("Service BC directory candidate review identity is invalid")
    iso_datetime(candidate.get("checkedAt"))
    review_flags = candidate.get("reviewFlags")
    if (
        not isinstance(review_flags, list)
        or any(not isinstance(flag, str) or not flag for flag in review_flags)
    ):
        raise AcquisitionError("Service BC directory candidate review flags are invalid")
    rights = candidate.get("rights")
    dataset = candidate.get("dataset")
    if (
        not isinstance(dataset, dict)
        or dataset.get("id") != PACKAGE_ID
        or dataset.get("name") != PACKAGE_NAME
        or dataset.get("resourceId") != RESOURCE_ID
    ):
        raise AcquisitionError("Service BC directory dataset/resource identity is invalid")
    if (
        not isinstance(rights, dict)
        or rights.get("status") != "dataset-specific-open-licence"
        or rights.get("evidenceUrl") != SERVICE_BC_DATASET_URL
        or rights.get("licenceUrl") != DATASET_LICENCE_URL
    ):
        raise AcquisitionError("Service BC directory candidate licence provenance is invalid")


def _text(value, field: str, *, optional=False, maximum=2000) -> str:
    if value is None and optional:
        return ""
    if not isinstance(value, str):
        raise AcquisitionError(f"Service BC directory {field} must be text")
    if len(value) > maximum or "\x00" in value or (not optional and not value.strip()):
        raise AcquisitionError(f"Service BC directory {field} is empty or out of bounds")
    return value


def _date(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AcquisitionError("Service BC directory publisher date must be text")
    legal_date(value) if len(value) == 10 else iso_datetime(value)
    return value


def _office_section(record: dict, identifiers: set[str]) -> Section:
    if not isinstance(record, dict) or set(record) != OFFICE_FIELDS:
        raise AcquisitionError(
            "Service BC directory records may contain only identity, contact and location fields"
        )
    code = _text(record["officeCode"], "office code", maximum=40)
    if code in identifiers:
        raise AcquisitionError("Service BC directory contains a duplicate office code")
    identifiers.add(code)
    name = _text(record["name"], "office name", maximum=500)
    address = _text(record["address"], "address", maximum=1000)
    locality = _text(record["locality"], "locality", maximum=200)
    phone = _text(record["phone"], "phone", optional=True, maximum=100)
    fax = _text(record["fax"], "fax", optional=True, maximum=100)
    email = _text(record["email"], "email", optional=True, maximum=200)
    website = _text(record["website"], "website", optional=True, maximum=1000)
    if website:
        parts = urlsplit(website)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            raise AcquisitionError("Service BC directory website is not a public HTTP(S) URL")
    latitude, longitude = record["latitude"], record["longitude"]
    if (
        type(latitude) not in (int, float)
        or type(longitude) not in (int, float)
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not 47 <= float(latitude) <= 61
        or not -140 <= float(longitude) <= -110
    ):
        raise AcquisitionError("Service BC directory coordinates are outside reviewed bounds")
    lines = [
        f"Office code: {code}",
        f"Office name: {name}",
        f"Location: {address}, {locality}, British Columbia",
        f"Coordinates: {latitude}, {longitude}",
    ]
    if phone:
        lines.append(f"Phone: {phone}")
    if fax:
        lines.append(f"Fax: {fax}")
    if email:
        lines.append(f"Email: {email}")
    if website:
        # Preserve the publisher value exactly, including reviewed legacy HTTP links.
        lines.append(f"Website: {website}")
    text = "\n".join(lines)
    return Section(
        heading=f"{name} — {locality}",
        text=text,
        locator=f"office-{code}",
        blocks=[{"kind": "text", "text": text}],
    )


def build_service_bc_directory_document(candidate: dict) -> AdaptedDocument:
    """Convert the exact CKAN candidate into one bounded, sectioned directory document."""
    _candidate_identity(candidate)
    identifiers: set[str] = set()
    sections = [_office_section(record, identifiers) for record in candidate["records"]]
    rendered = "\n".join(section.heading + "\n" + section.text for section in sections)
    raw = json.dumps(
        candidate,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    response = Response(
        SERVICE_BC_DATASET_URL,
        200,
        {"content-type": "application/json"},
        raw,
        candidate["checkedAt"],
    )
    metadata = {
        "schemaVersion": 1,
        "canonicalUrl": SERVICE_BC_DATASET_URL,
        "sourceUrl": SERVICE_BC_DATASET_URL,
        "sourceIds": ["service-bc"],
        "topics": ["locations", "office-contact", "office-identity"],
        "language": "en-CA",
        "documentType": "service-directory",
        "mediaType": "application/json",
        "rights": {
            "status": "candidate-acquisition-permitted",
            "reviewId": "bc-data-catalogue:" + candidate["dataset"]["id"],
            "reviewHash": candidate["reviewHash"],
            "licenceUrl": CANONICAL_LICENCE_URL,
            "evidenceUrl": candidate["rights"]["evidenceUrl"],
        },
        "legal": None,
    }
    document = Document(
        url=SERVICE_BC_DATASET_URL,
        title="Service BC office locations",
        checked_at=candidate["checkedAt"],
        publisher_updated_at=_date(candidate["dataset"].get("recordLastModified")),
        content_hash=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        response_hash=response.digest,
        quality="review-required",
        flags=[],
        sections=sections,
        links=[],
        extraction_method=SERVICE_DIRECTORY_EXTRACTION_METHOD,
        metadata=metadata,
    )
    document.extraction_hash = extraction_digest(document)
    return AdaptedDocument(
        "service-bc-ckan-v1",
        "service-bc",
        "Government of British Columbia",
        response,
        document,
        SERVICE_BC_DATASET_URL,
        tuple(sorted(set(candidate.get("reviewFlags", ())))),
        PACKAGE_ID,
    )
