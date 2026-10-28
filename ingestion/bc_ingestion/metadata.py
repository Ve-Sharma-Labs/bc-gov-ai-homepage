"""Versioned, hashable provenance; legal time is never inferred from fetch time."""

from datetime import date, datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit

from .policy import AcquisitionError, PUBLISHERS, canonicalize


MAX_CHUNK_CHARS = 8000
EXTRACTION_METHOD = "direct-publisher-html/section-aware-v2"
LEGACY_EXTRACTION_METHOD = "direct-publisher-html/section-aware-v1"
SERVICE_DIRECTORY_EXTRACTION_METHOD = "bc-data-catalogue/service-directory-v1"
RENDERED_HTML_EXTRACTION_METHOD = "controlled-rendered-html/section-aware-v1"
PUBLISHER_FEED_EXTRACTION_METHOD = "publisher-feed-html/section-aware-v1"
LEGAL_XML_EXTRACTION_METHOD = "bc-laws-civix/legal-section-v1"
EXTRACTION_METHODS = {
    EXTRACTION_METHOD,
    LEGACY_EXTRACTION_METHOD,
    SERVICE_DIRECTORY_EXTRACTION_METHOD,
    RENDERED_HTML_EXTRACTION_METHOD,
    PUBLISHER_FEED_EXTRACTION_METHOD,
    LEGAL_XML_EXTRACTION_METHOD,
}
DOCUMENT_TYPES = {"guidance", "legal", "service-directory", "notice"}
LEGAL_STATUSES = {"in-force", "not-yet-in-force", "repealed", "historical", "unknown"}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def iso_datetime(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise AcquisitionError("An ISO date-time with an explicit offset is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Missing offset")
        return parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise AcquisitionError("Invalid ISO date-time") from exc


def legal_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Not a calendar date")
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AcquisitionError("Legal effective dates must be explicit ISO calendar dates") from exc


def validate_legal(value: dict | None) -> dict | None:
    if value is None:
        return None
    allowed = {
        "status", "effectiveFrom", "effectiveTo", "consolidationDate", "repealedAt",
        "sectionId", "amendmentIds", "isHistorical", "evidenceUrl",
    }
    if not isinstance(value, dict) or set(value) - allowed:
        raise AcquisitionError("Unsupported legal metadata fields")
    if value.get("status", "unknown") not in LEGAL_STATUSES:
        raise AcquisitionError("Invalid legal status")
    start, end = legal_date(value.get("effectiveFrom")), legal_date(value.get("effectiveTo"))
    consolidation = legal_date(value.get("consolidationDate"))
    repealed = legal_date(value.get("repealedAt"))
    if start and end and end <= start:
        raise AcquisitionError("Legal intervals use inclusive start and exclusive end")
    if start and repealed and repealed < start:
        raise AcquisitionError("Repeal predates this legal version's effective interval")
    if value.get("status") == "repealed" and not repealed:
        raise AcquisitionError("A repealed version needs an explicit repeal date")
    if type(value.get("isHistorical", False)) is not bool:
        raise AcquisitionError("Legal historical status must be explicit boolean metadata")
    if value.get("sectionId") is not None and not isinstance(value["sectionId"], str):
        raise AcquisitionError("Legal section identity must be text")
    amendments = value.get("amendmentIds", [])
    if not isinstance(amendments, list) or any(not isinstance(x, str) or not x for x in amendments):
        raise AcquisitionError("Legal amendment references must be a string array")
    if not value.get("evidenceUrl"):
        raise AcquisitionError("Legal metadata requires publisher evidence, not a fetch-date guess")
    if urlsplit(canonicalize(value["evidenceUrl"])).hostname not in PUBLISHERS:
        raise AcquisitionError("Legal metadata evidence must identify an official registered publisher")
    # Consolidation is an editorial date, not an effective-from/to boundary.
    _ = consolidation
    return value


def legal_effective_on(value: dict | None, on: str) -> bool | None:
    """Evaluate a supplied calendar day; None means the interval is not known."""
    validate_legal(value)
    day = legal_date(on)
    if day is None:
        raise AcquisitionError("An explicit legal as-of calendar date is required")
    if value is None:
        return None
    start, end = legal_date(value.get("effectiveFrom")), legal_date(value.get("effectiveTo"))
    repealed = legal_date(value.get("repealedAt"))
    if (end and day >= end) or (repealed and day >= repealed) or (start and day < start):
        return False
    return True if start is not None else None


def validate_metadata(value: dict) -> dict:
    allowed = {
        "schemaVersion", "canonicalUrl", "sourceUrl", "sourceIds", "topics", "language",
        "documentType", "mediaType", "rights", "legal",
    }
    if not value:
        return value  # The shipped v1 snapshots predate additive metadata.
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or set(value) - allowed:
        raise AcquisitionError("Unsupported provenance metadata schema")
    for name in ("canonicalUrl", "sourceUrl"):
        if value.get(name) != canonicalize(value.get(name)):
            raise AcquisitionError("Provenance URLs must be canonical HTTPS URLs")
    for name in ("sourceIds", "topics"):
        tags = value.get(name, [])
        if not isinstance(tags, list) or any(not isinstance(x, str) or not x for x in tags):
            raise AcquisitionError("Provenance tags must be string arrays")
        if tags != sorted(set(tags)):
            raise AcquisitionError("Provenance tags must be sorted and deduplicated")
    language = value.get("language")
    if language is not None and (
        not isinstance(language, str) or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language)
    ):
        raise AcquisitionError("Language must be an explicit language tag or null")
    if value.get("documentType", "guidance") not in DOCUMENT_TYPES:
        raise AcquisitionError("Unsupported document type")
    media_type = value.get("mediaType")
    document_type = value.get("documentType", "guidance")
    if media_type not in (
        "text/html", "application/xhtml+xml", "application/json",
        "application/xml", "text/xml",
    ):
        raise AcquisitionError("This extractor does not support that media type")
    if media_type == "application/json" and document_type != "service-directory":
        raise AcquisitionError("JSON source adapters are limited to service-directory documents")
    if media_type in ("application/xml", "text/xml") and document_type != "legal":
        raise AcquisitionError("XML source adapters are limited to legal documents")
    rights = value.get("rights")
    if rights is not None:
        legacy_keys = {"status", "reviewId", "reviewHash", "licenceUrl", "evidenceUrl"}
        internal_keys = {
            "status", "reviewId", "reviewHash", "approvalEvidenceHash",
            "approvalEvidenceReference", "licenceUrl",
        }
        if not isinstance(rights, dict) or set(rights) not in (legacy_keys, internal_keys):
            raise AcquisitionError("Invalid rights provenance")
        if rights["status"] != "candidate-acquisition-permitted" or not rights["reviewId"]:
            raise AcquisitionError("Rights review authorizes candidates, never publication")
        if not re.fullmatch(r"[0-9a-f]{64}", rights.get("reviewHash", "")):
            raise AcquisitionError("Rights provenance requires the exact review hash")
        if set(rights) == legacy_keys:
            canonicalize(rights["licenceUrl"])
            canonicalize(rights["evidenceUrl"])
        else:
            if not re.fullmatch(r"[0-9a-f]{64}", rights.get("approvalEvidenceHash", "")):
                raise AcquisitionError("Rights provenance requires the internal approval evidence hash")
            reference = rights.get("approvalEvidenceReference")
            if (
                not isinstance(reference, str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]{1,512}", reference)
            ):
                raise AcquisitionError("Rights provenance requires the internal approval reference")
            if rights["licenceUrl"] is not None:
                canonicalize(rights["licenceUrl"])
    validate_legal(value.get("legal"))
    if value.get("legal") and value.get("documentType") != "legal":
        raise AcquisitionError("Legal effective-time metadata requires a legal document type")
    return value


def extraction_digest(document) -> str:
    validate_metadata(document.metadata)
    return digest({
        "method": document.extraction_method, "url": document.url,
        "title": document.title, "contentHash": document.content_hash,
        "publisherUpdatedAt": document.publisher_updated_at,
        "aliases": sorted(set(document.aliases)), "metadata": document.metadata,
        "sections": [
            {
                "heading": section.heading, "text": section.text, "locator": section.locator,
                "containsExceptions": section.contains_exceptions, "blocks": section.blocks,
            }
            for section in document.sections
        ],
    })


def search_metadata(document, entry: dict, version: dict) -> dict:
    metadata = validate_metadata(document.metadata)
    rights, legal = metadata.get("rights") or {}, metadata.get("legal") or {}
    return {
        "metadataVersion": metadata.get("schemaVersion"),
        "canonicalUrl": metadata.get("canonicalUrl", document.url),
        "sourceUrl": metadata.get("sourceUrl"),
        "sourceIds": metadata.get("sourceIds") or entry.get("sourceIds", [entry["sourceId"]]),
        "aliasUrls": sorted(set(document.aliases)),
        "language": metadata.get("language"), "documentType": metadata.get("documentType"),
        "mediaType": metadata.get("mediaType"), "extractionMethod": document.extraction_method,
        "extractionHash": document.extraction_hash, "responseHash": document.response_hash,
        "fetchedAt": version["fetchedAt"],
        "rightsStatus": rights.get("status", "legacy-exact-review" if not metadata else "review-required"),
        "rightsReviewId": rights.get("reviewId"), "rightsHash": rights.get("reviewHash"),
        "licenceUrl": rights.get("licenceUrl"), "legalStatus": legal.get("status"),
        "effectiveFrom": legal.get("effectiveFrom"), "effectiveTo": legal.get("effectiveTo"),
        "consolidationDate": legal.get("consolidationDate"), "repealedAt": legal.get("repealedAt"),
        "legalSectionId": legal.get("sectionId"), "amendmentIds": legal.get("amendmentIds", []),
        "isHistorical": legal.get("isHistorical"),
    }
