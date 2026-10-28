"""Dedicated BC Laws CiviX/legal XML parsing; this is never sitemap discovery."""

import hashlib
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from .extract import Document, Section
from .fetch import Response
from .metadata import LEGAL_XML_EXTRACTION_METHOD, extraction_digest, iso_datetime, legal_date
from .policy import AcquisitionError, canonicalize
from .source_adapters import AdaptedDocument


STATUS_NAMES = {"status", "legislationstatus", "inforcestatus", "documentstatus"}
IDENTITY_NAMES = {"documentid", "documentidentifier", "identifier", "civixid", "id"}
TITLE_NAMES = {"documenttitle", "acttitle", "regulationtitle", "title"}
CONSOLIDATION_NAMES = {"consolidationdate", "consolidatedto", "currentto"}
EFFECTIVE_FROM_NAMES = {"effectivefrom", "effectivefromdate", "inforcedate"}
EFFECTIVE_TO_NAMES = {"effectiveto", "effectivetodate", "expirydate"}
REPEALED_NAMES = {"repealedat", "repealdate"}
HISTORICAL_NAMES = {"ishistorical", "historical"}
CANONICAL_NAMES = {"canonicalurl", "documenturl"}
SECTION_NAMES = {"section", "provision"}
SECTION_ID_NAMES = {"sectionid", "sectionnumber", "num", "number"}
SECTION_HEADING_NAMES = {"marginalnote", "heading", "sectiontitle", "title"}
AMENDMENT_NAMES = {"amendmentid", "amendingdocument", "amendment"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _root_value(root: ET.Element, names: set[str]) -> str | None:
    for key, value in root.attrib.items():
        if _local(key) in names and _clean(value):
            return _clean(value)
    for child in list(root):
        if _local(child.tag) in names and _clean(" ".join(child.itertext())):
            return _clean(" ".join(child.itertext()))
        if _local(child.tag) in {"metadata", "meta", "documentmetadata", "properties"}:
            for key, value in child.attrib.items():
                if _local(key) in names and _clean(value):
                    return _clean(value)
            for item in list(child):
                if _local(item.tag) in names and _clean(" ".join(item.itertext())):
                    return _clean(" ".join(item.itertext()))
    return None


def _required(value: str | None, field: str) -> str:
    if not value:
        raise AcquisitionError(f"BC Laws CiviX XML requires explicit {field}")
    return value


def _status(value: str | None) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", _required(value, "in-force status").casefold()).strip("-")
    if token in {"in-force", "inforce", "current", "active", "consolidated-current"}:
        return "in-force"
    if token in {"not-yet-in-force", "not-in-force", "future", "pending"}:
        return "not-yet-in-force"
    if token in {"repealed", "revoked"}:
        return "repealed"
    if token in {"historical", "archived", "point-in-time"}:
        return "historical"
    raise AcquisitionError("BC Laws CiviX XML does not establish a recognized legal status")


def _boolean(value: str | None, field: str) -> bool | None:
    if value is None:
        return None
    token = value.strip().casefold()
    if token in {"true", "1", "yes"}:
        return True
    if token in {"false", "0", "no"}:
        return False
    raise AcquisitionError(f"BC Laws CiviX XML {field} must be an explicit boolean")


def _date(root: ET.Element, names: set[str], field: str) -> str | None:
    value = _root_value(root, names)
    if value is None:
        return None
    try:
        legal_date(value)
    except AcquisitionError as exc:
        raise AcquisitionError(f"BC Laws CiviX XML {field} must be an ISO calendar date") from exc
    return value


def _amendments(root: ET.Element) -> list[str]:
    result = []
    for node in root.iter():
        if _local(node.tag) not in AMENDMENT_NAMES:
            continue
        value = next((
            _clean(item)
            for key, item in node.attrib.items()
            if _local(key) in {"id", "identifier", "documentid", "amendmentid"} and _clean(item)
        ), None)
        value = value or _clean(" ".join(node.itertext()))
        if value:
            result.append(value)
    return sorted(set(result))


def _section_locator(node: ET.Element) -> str:
    for key, value in node.attrib.items():
        if _local(key) in {"id", "identifier", "sectionid", "number"} and _clean(value):
            return _clean(value)
    for child in list(node):
        if _local(child.tag) in SECTION_ID_NAMES:
            value = _clean(" ".join(child.itertext()))
            if value:
                return value
    raise AcquisitionError("BC Laws CiviX XML section lacks an explicit locator")


def _section_heading(node: ET.Element, locator: str) -> str:
    title = None
    for child in list(node):
        if _local(child.tag) in SECTION_HEADING_NAMES:
            title = _clean(" ".join(child.itertext()))
            if title:
                break
    return f"Section {locator}" + (f" — {title}" if title else "")


def _sections(root: ET.Element) -> list[Section]:
    parents = {child: parent for parent in root.iter() for child in list(parent)}
    nodes = []
    for node in root.iter():
        if _local(node.tag) not in SECTION_NAMES:
            continue
        parent = parents.get(node)
        if parent is not None and _local(parent.tag) in SECTION_NAMES:
            continue
        nodes.append(node)
    if not nodes:
        raise AcquisitionError("BC Laws CiviX XML contains no legal sections")
    if len(nodes) > 20_000:
        raise AcquisitionError("BC Laws CiviX XML exceeds the bounded section count")
    result, locators = [], set()
    for node in nodes:
        locator = _section_locator(node)
        if locator in locators:
            raise AcquisitionError("BC Laws CiviX XML contains duplicate section locators")
        locators.add(locator)
        text = _clean(" ".join(node.itertext()))
        if not text:
            raise AcquisitionError("BC Laws CiviX XML contains an empty legal section")
        result.append(Section(
            heading=_section_heading(node, locator),
            text=text,
            locator=locator,
            contains_exceptions=bool(re.search(
                r"\b(?:except|excluding|unless|however|must not|does not apply)\b",
                text,
                re.I,
            )),
            blocks=[{"kind": "text", "text": text}],
        ))
    return result


def parse_bc_laws_civix(
    response: Response,
    *,
    evidence_url: str,
    require_current: bool = True,
    metadata: dict | None = None,
) -> AdaptedDocument:
    """Parse one approved legal XML document and fail closed on ambiguous currency."""
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if response.status != 200 or media_type not in ("application/xml", "text/xml"):
        raise AcquisitionError("BC Laws CiviX adapter requires a successful XML response")
    if not response.body or len(response.body) > 8_000_000:
        raise AcquisitionError("BC Laws CiviX XML is empty or exceeds the 8 MB bound")
    if b"<!DOCTYPE" in response.body.upper() or b"<!ENTITY" in response.body.upper():
        raise AcquisitionError("BC Laws CiviX XML DTDs/entities are forbidden")
    try:
        root = ET.fromstring(response.body)
    except ET.ParseError as exc:
        raise AcquisitionError("Malformed BC Laws CiviX XML") from exc
    if _local(root.tag) in {"urlset", "sitemapindex"}:
        raise AcquisitionError("BC Laws legal XML parser does not accept discovery sitemaps")

    source_url = canonicalize(response.url)
    evidence = canonicalize(evidence_url)
    if (
        urlsplit(source_url).hostname != "www.bclaws.gov.bc.ca"
        or urlsplit(evidence).hostname != "www.bclaws.gov.bc.ca"
    ):
        raise AcquisitionError("BC Laws CiviX provenance must remain on the official host")
    canonical_value = _root_value(root, CANONICAL_NAMES)
    document_url = canonicalize(canonical_value) if canonical_value else source_url
    if urlsplit(document_url).hostname != "www.bclaws.gov.bc.ca":
        raise AcquisitionError("BC Laws CiviX canonical document host is invalid")

    identity = _required(_root_value(root, IDENTITY_NAMES), "document identity")
    title = _required(_root_value(root, TITLE_NAMES), "document title")
    legal_status = _status(_root_value(root, STATUS_NAMES))
    historical_value = _boolean(
        _root_value(root, HISTORICAL_NAMES), "historical status"
    )
    if historical_value is None and legal_status == "in-force":
        raise AcquisitionError("BC Laws CiviX current XML requires explicit nonhistorical status")
    is_historical = historical_value if historical_value is not None else (
        legal_status in {"historical", "repealed"}
    )
    if legal_status == "in-force" and is_historical:
        raise AcquisitionError("BC Laws CiviX current status conflicts with historical metadata")
    if require_current and (legal_status != "in-force" or is_historical):
        raise AcquisitionError("BC Laws CiviX XML does not establish a current in-force version")

    consolidation = _required(
        _date(root, CONSOLIDATION_NAMES, "consolidation date"),
        "consolidation date",
    )
    effective_from = _date(root, EFFECTIVE_FROM_NAMES, "effective-from date")
    effective_to = _date(root, EFFECTIVE_TO_NAMES, "effective-to date")
    repealed_at = _date(root, REPEALED_NAMES, "repeal date")
    if legal_status == "repealed" and repealed_at is None:
        raise AcquisitionError("BC Laws repealed XML requires an explicit repeal date")
    if legal_status == "in-force" and repealed_at is not None:
        raise AcquisitionError("BC Laws current XML cannot also carry a repeal date")
    if legal_status == "in-force" and effective_to is not None:
        checked_day = iso_datetime(response.checked_at).date()
        if legal_date(effective_to) <= checked_day:
            raise AcquisitionError("BC Laws current XML has an already-ended effective interval")
    sections = _sections(root)
    rendered = "\n".join(section.heading + "\n" + section.text for section in sections)
    legal = {
        "status": legal_status,
        "effectiveFrom": effective_from,
        "effectiveTo": effective_to,
        "consolidationDate": consolidation,
        "repealedAt": repealed_at,
        "sectionId": sections[0].locator if len(sections) == 1 else None,
        "amendmentIds": _amendments(root),
        "isHistorical": is_historical,
        "evidenceUrl": evidence,
    }
    provenance = {
        "schemaVersion": 1,
        "canonicalUrl": document_url,
        "sourceUrl": source_url,
        "sourceIds": ["bc-laws"],
        "topics": ["effective-versions", "legislation", "regulations", "statutes"],
        "language": next((
            value for key, value in root.attrib.items() if _local(key) in {"lang", "language"}
        ), "en-CA"),
        "documentType": "legal",
        "mediaType": media_type,
        "rights": None,
        "legal": legal,
        **(metadata or {}),
    }
    provenance["sourceIds"] = sorted(set(provenance.get("sourceIds", ())) | {"bc-laws"})
    provenance["topics"] = sorted(set(provenance.get("topics", ())) | {
        "effective-versions", "legislation", "regulations", "statutes",
    })
    provenance["canonicalUrl"] = document_url
    provenance["sourceUrl"] = source_url
    provenance["documentType"] = "legal"
    provenance["mediaType"] = media_type
    provenance["legal"] = legal
    document = Document(
        url=document_url,
        title=f"{title} [{identity}]",
        checked_at=response.checked_at,
        publisher_updated_at=consolidation,
        content_hash=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        response_hash=response.digest,
        quality="review-required",
        flags=[],
        sections=sections,
        links=[],
        extraction_method=LEGAL_XML_EXTRACTION_METHOD,
        metadata=provenance,
    )
    document.extraction_hash = extraction_digest(document)
    return AdaptedDocument(
        "bc-laws-civix-xml-v1",
        "bc-laws",
        "Government of British Columbia",
        response,
        document,
        evidence,
        source_identity=identity,
    )
