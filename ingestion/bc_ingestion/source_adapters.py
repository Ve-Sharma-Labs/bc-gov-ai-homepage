"""Composable source contracts layered on the section-aware extractor."""

from dataclasses import dataclass
from datetime import datetime
from html import escape
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .extract import Document, extract
from .fetch import Response
from .metadata import (
    EXTRACTION_METHOD,
    LEGAL_XML_EXTRACTION_METHOD,
    PUBLISHER_FEED_EXTRACTION_METHOD,
    RENDERED_HTML_EXTRACTION_METHOD,
    SERVICE_DIRECTORY_EXTRACTION_METHOD,
    extraction_digest,
    iso_datetime,
    legal_date,
)
from .policy import AcquisitionError, SERVICE_BC, canonicalize


SERVICE_BC_DATASET_URL = (
    "https://catalogue.data.gov.bc.ca/dataset/"
    "2b44d212-5438-47a9-ad23-20eb8ada9709"
)

PROVINCE_ROUTE_TOPICS = {
    "bc-content": (
        "benefits", "contacts", "eligibility-guidance", "fees",
        "government", "government-programmes", "services",
    ),
    "service-bc": (
        "identification", "in-person-help", "locations",
        "office-capabilities", "service-navigation",
    ),
    "housing-tenancy": (
        "dispute-resolution", "housing", "renting", "tenancy",
    ),
    "health": (
        "accessing-care", "health", "msp", "pharmacare", "public-health",
    ),
    "family-social-supports": (
        "childcare", "disability", "disability-support", "families",
        "family-services", "income-assistance",
    ),
    "employment-business": (
        "business", "business-guidance", "employer-responsibilities",
        "employment", "employment-standards",
    ),
    "taxes": (
        "credits", "exemptions", "payment-guidance", "tax-credits", "taxes",
    ),
}

PROVINCE_ROUTES = (
    ("service-bc", SERVICE_BC),
    ("housing-tenancy", "/gov/content/housing-tenancy"),
    ("health", "/gov/content/health"),
    ("family-social-supports", "/gov/content/family-social-supports"),
    ("employment-business", "/gov/content/employment-business"),
    ("taxes", "/gov/content/taxes"),
)

ICBC_SENSITIVE_PATH = re.compile(
    r"(?:^|/)(?:account|accounts|login|log-in|signin|sign-in|register|"
    r"booking|book-appointment|appointments?|payment|payments|pay|personal|"
    r"profile|my-icbc|claims?)(?:/|$)",
    re.I,
)
WORKBC_JOB_PATH = re.compile(
    r"(?:^|/)(?:job-board|jobboard|job-search|find-jobs|jobs|job-postings?|"
    r"vacancies|employer-job-posting)(?:/|$)",
    re.I,
)
WORKBC_STATIC_ROUTES = (
    ("/plan-career", "career-guidance", ("careers",)),
    ("/career-profiles", "career-guidance", ("careers",)),
    ("/explore-training-and-education", "training-guidance", ("training", "education")),
    ("/search-and-prepare-for-a-job", "employment-guidance", ("employment-services",)),
    ("/discover-employment-services", "employment-guidance", ("employment-services",)),
    ("/access-employer-resources", "employer-guidance", ("employer-guidance",)),
)
OFFLINE_OR_MAINTENANCE = re.compile(
    r"\b(?:workbc\s*[-–—:]?\s*offline|temporarily unavailable|"
    r"under maintenance|down for maintenance|scheduled maintenance|"
    r"service unavailable|website maintenance)\b",
    re.I,
)
INCOMPLETE_TEXT = re.compile(
    r"\b(?:enable javascript|please wait while we load|loading[.\u2026 ]*$|"
    r"checking your browser|verify (?:that )?you are human)\b",
    re.I,
)
HEALTHLINK_THIRD_PARTY = re.compile(
    r"\b(?:healthwise(?:,\s*incorporated)?|ignite healthwise|webmd ignite)\b",
    re.I,
)


@dataclass(frozen=True)
class RouteClassification:
    content_class: str
    source_ids: tuple[str, ...]
    topics: tuple[str, ...]


@dataclass
class AdaptedDocument:
    adapter_id: str
    source_id: str
    publisher: str
    response: Response
    document: Document
    evidence_url: str
    review_notes: tuple[str, ...] = ()
    source_identity: str | None = None


@dataclass
class WorkBcFeedResult:
    documents: list[AdaptedDocument]
    excluded: list[dict]


def _beneath(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def classify_province_route(url: str) -> RouteClassification:
    """Classify a canonical Province route while retaining the broad parent tag."""
    normalized = canonicalize(url)
    parts = urlsplit(normalized)
    if parts.hostname != "www2.gov.bc.ca" or not _beneath(parts.path, "/gov/content"):
        raise AcquisitionError("Province HTML adapter only accepts canonical /gov/content routes")
    source_ids = ["bc-content"]
    content_class = "province-content"
    for source_id, prefix in PROVINCE_ROUTES:
        if _beneath(parts.path, prefix):
            source_ids.append(source_id)
            content_class = source_id
            break
    topics = sorted({
        topic for source_id in source_ids for topic in PROVINCE_ROUTE_TOPICS[source_id]
    })
    return RouteClassification(content_class, tuple(sorted(source_ids)), tuple(topics))


def classify_healthlink_route(url: str, html: bytes | str = b"") -> RouteClassification:
    normalized = canonicalize(url)
    parts = urlsplit(normalized)
    if parts.hostname != "www.healthlinkbc.ca":
        raise AcquisitionError("HealthLink adapter requires the canonical HealthLink BC host")
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True) if html else ""
    if HEALTHLINK_THIRD_PARTY.search(text):
        return RouteClassification(
            "third-party-clinical",
            ("healthlink-bc",),
            ("clinical-content", "public-health-information"),
        )
    if _beneath(parts.path, "/find-care") or _beneath(parts.path, "/health-services"):
        topics = {"health-navigation", "public-health-information"}
        if "health-connect-registry" in parts.path.casefold():
            topics.add("health-connect-registry")
        return RouteClassification(
            "government-service-navigation", ("healthlink-bc",), tuple(sorted(topics))
        )
    return RouteClassification(
        "authorship-review-required",
        ("healthlink-bc",),
        ("public-health-information",),
    )


def classify_workbc_route(url: str) -> RouteClassification:
    normalized = canonicalize(url)
    parts = urlsplit(normalized)
    if parts.hostname != "www.workbc.ca":
        raise AcquisitionError("WorkBC adapter requires the canonical WorkBC host")
    if WORKBC_JOB_PATH.search(parts.path):
        return RouteClassification("live-job-board", ("workbc",), ("job-listings",))
    if parts.path == "/":
        return RouteClassification(
            "static-navigation", ("workbc",), ("careers", "employment-services", "training")
        )
    for prefix, content_class, topics in WORKBC_STATIC_ROUTES:
        if _beneath(parts.path, prefix):
            return RouteClassification(content_class, ("workbc",), tuple(sorted(topics)))
    return RouteClassification("unapproved-static-route", ("workbc",), ())


def classify_workbc_record(record: dict) -> str:
    """Separate static publisher records from prohibited live job-board records."""
    if not isinstance(record, dict):
        raise AcquisitionError("WorkBC feed records must be objects")
    value = record.get("contentType", record.get("recordType"))
    if not isinstance(value, str):
        raise AcquisitionError("WorkBC feed records require an explicit content type")
    kind = value.strip().casefold().replace("_", "-")
    if kind in {"job", "job-record", "job-posting", "job-board", "vacancy"}:
        return "live-job-board"
    if kind in {"guidance", "training", "career", "career-guidance", "training-guidance"}:
        return "approved-static"
    raise AcquisitionError("WorkBC feed content type is outside the approved static contract")


def _approved_workbc_link(url: str) -> bool:
    try:
        return classify_workbc_route(url).content_class not in {
            "live-job-board", "unapproved-static-route",
        }
    except AcquisitionError:
        return False


def _merge_tags(metadata: dict | None, classification: RouteClassification) -> dict:
    value = dict(metadata or {})
    value["sourceIds"] = sorted(set(value.get("sourceIds", ())) | set(classification.source_ids))
    value["topics"] = sorted(set(value.get("topics", ())) | set(classification.topics))
    return value


def _publisher_date(text: str) -> str | None:
    patterns = (
        r"(?:content\s+(?:is\s+)?current\s+(?:as of|to)|last\s+(?:updated|reviewed|modified))"
        r"\s*:?\s*(\d{4}-\d{2}-\d{2})",
        r"(?:content\s+(?:is\s+)?current\s+(?:as of|to)|last\s+(?:updated|reviewed|modified))"
        r"\s*:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        candidate = match.group(1)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
            legal_date(candidate)
            return candidate
        for form in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(candidate, form).date().isoformat()
            except ValueError:
                pass
        raise AcquisitionError("Publisher freshness notice contains an invalid date")
    return None


def _finish(
    document: Document,
    *,
    add_flags=(),
    remove_flags=(),
    extraction_method: str | None = None,
) -> Document:
    document.flags = sorted((set(document.flags) | set(add_flags)) - set(remove_flags))
    document.quality = "quarantined" if document.flags else "review-required"
    if extraction_method is not None:
        document.extraction_method = extraction_method
    document.extraction_hash = extraction_digest(document)
    return document


def adapt_province_html(response: Response, **kwargs) -> Document:
    classification = classify_province_route(response.url)
    kwargs["metadata"] = _merge_tags(kwargs.get("metadata"), classification)
    return extract(response, **kwargs)


def adapt_bc_housing_html(response: Response, **kwargs) -> Document:
    metadata = dict(kwargs.get("metadata") or {})
    metadata["sourceIds"] = sorted(set(metadata.get("sourceIds", ())) | {"bc-housing"})
    metadata["topics"] = sorted(set(metadata.get("topics", ())) | {
        "application-requirements", "housing-assistance", "rental-assistance",
    })
    kwargs["metadata"] = metadata
    document = extract(response, **kwargs)
    text = BeautifulSoup(response.body, "html.parser").get_text(" ", strip=True)
    explicit_date = _publisher_date(text)
    if explicit_date and document.publisher_updated_at is None:
        document.publisher_updated_at = explicit_date
    flags = {"publisher-freshness-review-required"}
    if re.search(
        r"(?:\b(?:updates?|content updates?)\b.{0,80}\b(?:paused|suspended|suspending)\b|"
        r"\b(?:paused|suspended|suspending)\b.{0,80}\b(?:updates?|content updates?)\b)",
        text,
        re.I,
    ):
        flags.update({"publisher-updates-paused", "publisher-freshness-notice"})
    if document.publisher_updated_at is None:
        flags.add("publisher-freshness-date-missing")
    return _finish(document, add_flags=flags)


def adapt_healthlink_html(response: Response, **kwargs) -> Document:
    classification = classify_healthlink_route(response.url, response.body)
    kwargs["metadata"] = _merge_tags(kwargs.get("metadata"), classification)
    document = extract(response, **kwargs)
    text = BeautifulSoup(response.body, "html.parser").get_text(" ", strip=True)
    explicit_date = _publisher_date(text)
    if explicit_date and document.publisher_updated_at is None:
        document.publisher_updated_at = explicit_date
    flags = set()
    if classification.content_class == "third-party-clinical":
        flags.update({
            "healthlink-third-party-clinical-content",
            "healthlink-third-party-rights-review-required",
        })
    elif classification.content_class == "authorship-review-required":
        flags.add("healthlink-authorship-review-required")
    if document.publisher_updated_at is None:
        flags.update({
            "publisher-freshness-review-required",
            "healthlink-publisher-date-missing",
        })
    return _finish(document, add_flags=flags)


def _assert_complete_main(response: Response, publisher: str) -> BeautifulSoup:
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if response.status != 200 or media_type not in ("text/html", "application/xhtml+xml"):
        raise AcquisitionError(f"{publisher} adapter requires a successful HTML response")
    if not response.body or len(response.body) > 8_000_000:
        raise AcquisitionError(f"{publisher} adapter response is empty or exceeds the 8 MB bound")
    soup = BeautifulSoup(response.body, "html.parser")
    root = soup.select_one("main, [role=main]")
    if root is None:
        raise AcquisitionError(f"{publisher} adapter requires a complete main content region")
    text = " ".join(root.get_text(" ", strip=True).split())
    whole = " ".join(soup.get_text(" ", strip=True).split())
    if len(text) < 300 or not root.find(["h1", "h2"]):
        raise AcquisitionError(f"{publisher} adapter received incomplete main content")
    if OFFLINE_OR_MAINTENANCE.search(whole) or INCOMPLETE_TEXT.search(text):
        raise AcquisitionError(f"{publisher} adapter rejected an offline, maintenance or partial page")
    return soup


def _assert_icbc_url(url: str) -> str:
    normalized = canonicalize(url)
    parts = urlsplit(normalized)
    if parts.hostname != "www.icbc.com":
        raise AcquisitionError("ICBC adapter requires the approved canonical www.icbc.com host")
    if ICBC_SENSITIVE_PATH.search(parts.path):
        raise AcquisitionError("ICBC account, booking, payment, claims and personal paths are excluded")
    return normalized


def adapt_icbc_rendered_html(
    response: Response,
    *,
    complete_main: bool,
    metadata: dict | None = None,
) -> AdaptedDocument:
    """Accept an explicitly controlled complete render, never ordinary fetched shell HTML."""
    if complete_main is not True:
        raise AcquisitionError("ICBC rendered HTML needs an explicit complete-main attestation")
    normalized = _assert_icbc_url(response.url)
    soup = _assert_complete_main(response, "ICBC")
    canonicals = soup.select("link[rel~=canonical]")
    if len(canonicals) != 1 or not canonicals[0].get("href"):
        raise AcquisitionError("ICBC rendered HTML requires exactly one canonical link")
    canonical = _assert_icbc_url(urljoin(normalized, canonicals[0]["href"]))
    if canonical != normalized:
        raise AcquisitionError("ICBC rendered HTML URL must already be its canonical URL")
    classification = RouteClassification(
        "controlled-rendered-guidance",
        ("icbc",),
        ("driver-licensing", "identification", "insurance", "vehicle-registration"),
    )
    document = extract(
        response,
        metadata=_merge_tags(metadata, classification),
        url_validator=_assert_icbc_url,
        canonical_validator=lambda target: _assert_icbc_url(target),
    )
    unsafe = {
        "dynamic-or-incomplete", "footer-only", "incomplete-structured-extraction",
        "maintenance-or-access-page", "missing-main-region", "missing-title-or-headings",
        "too-little-guidance", "unapproved-canonical",
    }
    if unsafe & set(document.flags):
        raise AcquisitionError("ICBC rendered HTML did not preserve complete main content")
    document.links = [
        link for link in document.links
        if urlsplit(link["url"]).hostname == "www.icbc.com"
        and not ICBC_SENSITIVE_PATH.search(urlsplit(link["url"]).path)
    ]
    _finish(
        document,
        remove_flags={"icbc-rendering-review-required"},
        extraction_method=RENDERED_HTML_EXTRACTION_METHOD,
    )
    return AdaptedDocument(
        "icbc-rendered-html-v1",
        "icbc",
        "ICBC",
        response,
        document,
        canonical,
    )


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AcquisitionError("Publisher feed JSON contains duplicate object keys")
        value[key] = item
    return value


def _feed_json(response: Response, publisher: str) -> dict:
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if response.status != 200 or media_type not in (
        "application/json", "application/feed+json", "text/json",
    ):
        raise AcquisitionError(f"{publisher} feed requires a successful JSON response")
    try:
        value = json.loads(response.body, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcquisitionError(f"{publisher} feed returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise AcquisitionError(f"{publisher} feed root must be an object")
    return value


def _feed_date(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AcquisitionError("Publisher feed dates must be explicit ISO strings")
    legal_date(value) if len(value) == 10 else iso_datetime(value)
    return value


def adapt_icbc_publisher_feed(
    response: Response,
    *,
    metadata: dict | None = None,
) -> list[AdaptedDocument]:
    """Adapt a bounded complete-content JSON feed supplied by ICBC."""
    feed_url = _assert_icbc_url(response.url)
    value = _feed_json(response, "ICBC")
    items = value.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise AcquisitionError("ICBC feed must contain between 1 and 100 bounded items")
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise AcquisitionError("ICBC feed items must be objects")
        canonical_value = item.get("canonicalUrl", item.get("url"))
        title = item.get("title")
        content = item.get("contentHtml", item.get("content_html"))
        complete = item.get("contentComplete", item.get("content_complete"))
        if (
            not isinstance(canonical_value, str)
            or not isinstance(title, str) or not title.strip()
            or not isinstance(content, str) or not content.strip()
            or complete is not True
        ):
            raise AcquisitionError("ICBC feed items require canonical URL, title and complete HTML")
        canonical = _assert_icbc_url(canonical_value)
        if canonical in seen:
            raise AcquisitionError("ICBC feed contains duplicate canonical documents")
        seen.add(canonical)
        updated = _feed_date(item.get("publisherUpdatedAt", item.get("date_modified")))
        rendered = (
            "<html lang='en-CA'><head><title>"
            + escape(BeautifulSoup(title, "html.parser").get_text(" ", strip=True))
            + f"</title><link rel='canonical' href='{canonical}'></head>"
            + f"<body><main><h1>{escape(title)}</h1>{content}</main></body></html>"
        ).encode("utf-8")
        synthetic = Response(
            canonical,
            200,
            {"content-type": "text/html; charset=utf-8"},
            rendered,
            response.checked_at,
        )
        adapted = adapt_icbc_rendered_html(
            synthetic, complete_main=True, metadata=metadata
        )
        adapted.adapter_id = "icbc-publisher-feed-v1"
        adapted.evidence_url = feed_url
        adapted.response = Response(
            canonical,
            response.status,
            dict(response.headers),
            response.body,
            response.checked_at,
        )
        adapted.document.response_hash = response.digest
        adapted.document.publisher_updated_at = updated
        _finish(
            adapted.document,
            extraction_method=PUBLISHER_FEED_EXTRACTION_METHOD,
        )
        result.append(adapted)
    return result


def adapt_workbc_static_html(
    response: Response,
    *,
    metadata: dict | None = None,
    **kwargs,
) -> AdaptedDocument:
    classification = classify_workbc_route(response.url)
    if classification.content_class == "live-job-board":
        raise AcquisitionError("WorkBC live job-board records are excluded")
    if classification.content_class == "unapproved-static-route":
        raise AcquisitionError("WorkBC route is outside approved static guidance/training/career content")
    _assert_complete_main(response, "WorkBC")
    document = extract(
        response,
        metadata=_merge_tags(metadata, classification),
        **kwargs,
    )
    if {
        "maintenance-or-access-page", "dynamic-or-incomplete", "footer-only",
        "missing-main-region", "too-little-guidance",
    } & set(document.flags):
        raise AcquisitionError("WorkBC adapter rejected an offline, maintenance or partial page")
    document.links = [link for link in document.links if _approved_workbc_link(link["url"])]
    return AdaptedDocument(
        "workbc-static-html-v1",
        "workbc",
        "WorkBC",
        response,
        document,
        canonicalize(response.url),
    )


def adapt_workbc_publisher_feed(
    response: Response,
    *,
    metadata: dict | None = None,
) -> WorkBcFeedResult:
    """Adapt only static guidance records and report every live job record excluded."""
    feed_url = canonicalize(response.url)
    if urlsplit(feed_url).hostname != "www.workbc.ca":
        raise AcquisitionError("WorkBC publisher feed must stay on the official host")
    value = _feed_json(response, "WorkBC")
    items = value.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise AcquisitionError("WorkBC feed must contain between 1 and 100 bounded items")
    documents, excluded, seen = [], [], set()
    for index, item in enumerate(items):
        content_class = classify_workbc_record(item)
        record_id = item.get("id", f"record-{index + 1}")
        if content_class == "live-job-board":
            excluded.append({
                "id": str(record_id),
                "reason": "live-job-board-record",
            })
            continue
        canonical_value = item.get("canonicalUrl", item.get("url"))
        title = item.get("title")
        content = item.get("contentHtml", item.get("content_html"))
        complete = item.get("contentComplete", item.get("content_complete"))
        if (
            not isinstance(canonical_value, str)
            or not isinstance(title, str) or not title.strip()
            or not isinstance(content, str) or not content.strip()
            or complete is not True
        ):
            raise AcquisitionError(
                "WorkBC static feed records require canonical URL, title and complete HTML"
            )
        canonical = canonicalize(canonical_value)
        route = classify_workbc_route(canonical)
        if route.content_class in {"live-job-board", "unapproved-static-route"}:
            raise AcquisitionError("WorkBC feed record URL is not approved static content")
        if canonical in seen:
            raise AcquisitionError("WorkBC feed contains duplicate canonical documents")
        seen.add(canonical)
        updated = _feed_date(item.get("publisherUpdatedAt", item.get("date_modified")))
        rendered = (
            "<html lang='en-CA'><head><title>"
            + escape(BeautifulSoup(title, "html.parser").get_text(" ", strip=True))
            + f"</title><link rel='canonical' href='{canonical}'></head>"
            + f"<body><main><h1>{escape(title)}</h1>{content}</main></body></html>"
        ).encode("utf-8")
        synthetic = Response(
            canonical,
            200,
            {"content-type": "text/html; charset=utf-8"},
            rendered,
            response.checked_at,
        )
        _assert_complete_main(synthetic, "WorkBC")
        document = extract(
            synthetic,
            metadata=_merge_tags(metadata, route),
            url_validator=lambda target: canonicalize(target),
            canonical_validator=lambda target: canonicalize(target),
        )
        document.response_hash = response.digest
        document.publisher_updated_at = updated
        _finish(
            document,
            add_flags={"publisher-freshness-review-required"} if updated is None else (),
            extraction_method=PUBLISHER_FEED_EXTRACTION_METHOD,
        )
        documents.append(AdaptedDocument(
            "workbc-publisher-feed-v1",
            "workbc",
            "WorkBC",
            Response(
                canonical,
                response.status,
                dict(response.headers),
                response.body,
                response.checked_at,
            ),
            document,
            feed_url,
        ))
    return WorkBcFeedResult(documents, excluded)


def adapt_programme_html(response: Response, **kwargs) -> Document:
    """Registry hook for ordinary programme HTML without changing default extraction."""
    host = urlsplit(canonicalize(response.url)).hostname
    if host == "www2.gov.bc.ca":
        return adapt_province_html(response, **kwargs)
    if host == "www.bchousing.org":
        return adapt_bc_housing_html(response, **kwargs)
    if host == "www.healthlinkbc.ca":
        return adapt_healthlink_html(response, **kwargs)
    if host == "www.icbc.com":
        raise AcquisitionError(
            "ICBC requires an approved publisher feed or controlled rendered HTML response"
        )
    if host == "www.workbc.ca":
        return adapt_workbc_static_html(
            response,
            metadata=kwargs.pop("metadata", None),
            **kwargs,
        ).document
    return extract(response, **kwargs)


def validate_source_adapter_entry(entry: dict, source: dict) -> None:
    """Validate alternate source provenance without widening policy.py."""
    adapter_id = entry.get("adapterId")
    source_id = entry.get("sourceId")
    url = canonicalize(entry.get("url"))
    host = urlsplit(url).hostname
    if adapter_id == "service-bc-ckan-v1":
        if source_id != "service-bc" or url != SERVICE_BC_DATASET_URL:
            raise AcquisitionError("Service BC directory adapter provenance is invalid")
        expected = (SERVICE_DIRECTORY_EXTRACTION_METHOD, "service-directory", "application/json")
    elif adapter_id in {"icbc-rendered-html-v1", "icbc-publisher-feed-v1"}:
        if source_id != "icbc" or host != "www.icbc.com":
            raise AcquisitionError("ICBC adapter provenance is invalid")
        _assert_icbc_url(url)
        expected = (
            RENDERED_HTML_EXTRACTION_METHOD
            if adapter_id == "icbc-rendered-html-v1"
            else PUBLISHER_FEED_EXTRACTION_METHOD,
            "guidance",
            "text/html",
        )
    elif adapter_id == "workbc-static-html-v1":
        if source_id != "workbc" or host != "www.workbc.ca":
            raise AcquisitionError("WorkBC adapter provenance is invalid")
        if classify_workbc_route(url).content_class in {
            "live-job-board", "unapproved-static-route",
        }:
            raise AcquisitionError("WorkBC adapter route is not approved static content")
        expected = (EXTRACTION_METHOD, "guidance", "text/html")
    elif adapter_id == "workbc-publisher-feed-v1":
        if source_id != "workbc" or host != "www.workbc.ca":
            raise AcquisitionError("WorkBC publisher-feed provenance is invalid")
        if classify_workbc_route(url).content_class in {
            "live-job-board", "unapproved-static-route",
        }:
            raise AcquisitionError("WorkBC publisher-feed route is not approved static content")
        expected = (PUBLISHER_FEED_EXTRACTION_METHOD, "guidance", "text/html")
    elif adapter_id == "bc-laws-civix-xml-v1":
        if source_id != "bc-laws" or host != "www.bclaws.gov.bc.ca":
            raise AcquisitionError("BC Laws CiviX adapter provenance is invalid")
        expected = (LEGAL_XML_EXTRACTION_METHOD, "legal", None)
    else:
        raise AcquisitionError("Unknown source adapter provenance")
    for version in entry.get("versions", []):
        document = version.get("document", {})
        metadata = document.get("metadata", {})
        if (
            document.get("extraction_method") != expected[0]
            or metadata.get("documentType") != expected[1]
            or (expected[2] is not None and metadata.get("mediaType") != expected[2])
            or (
                adapter_id == "bc-laws-civix-xml-v1"
                and metadata.get("mediaType") not in {"application/xml", "text/xml"}
            )
        ):
            raise AcquisitionError("Source adapter document contract does not match its provenance")
