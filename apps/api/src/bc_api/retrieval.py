import asyncio
import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import QueryType, VectorizedQuery
from pydantic import ValidationError

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.dialogue import source_topics
from bc_api.embeddings import AzureEmbeddings
from bc_api.errors import ApiError
from bc_api.grounded_quotes import mark_source_quotes, quote_registry
from bc_api.models import (
    JOURNEY_IDS,
    Evidence,
    EvidenceBundle,
    EvidenceMetadata,
    Source,
    SourceHealth,
    SourceReference,
)

SELECT_FIELDS = [
    "id",
    "documentId",
    "sourceId",
    "title",
    "publisher",
    "url",
    "content",
    "section",
    "checkedAt",
    "publisherUpdatedAt",
    "status",
    "documentVersion",
    "journeyIds",
]
METADATA_FIELDS = [
    "metadataVersion",
    "sourceIds",
    "documentType",
    "language",
    "contentHash",
    "extractionHash",
    "reviewHash",
    "rightsStatus",
    "rightsReviewId",
    "rightsHash",
    "legalStatus",
    "effectiveFrom",
    "effectiveTo",
    "consolidationDate",
    "repealedAt",
    "legalSectionId",
    "isHistorical",
]
INJECTION_MARKERS = re.compile(
    r"(?:ignore|override|disregard).{0,50}(?:instructions|system|developer)"
    r"|<script\b|javascript:|(?:system|developer)\s+prompt"
    r"|(?:^|[\r\n])[ \t]*(?:system|developer|assistant)[ \t]*:"
    r"|<\s*(?:/\s*)?(?:system|developer|assistant)\b[^<>]*>",
    re.IGNORECASE | re.DOTALL,
)


def _reject_instruction_markers(value: Any) -> None:
    """Screen known markers without rewriting source text; this does not establish trust."""
    if isinstance(value, str):
        if INJECTION_MARKERS.search(value):
            raise ApiError(
                502, "SOURCE_CONTENT_REJECTED", "Unexpected instruction-like source content."
            )
    elif isinstance(value, dict):
        for item in value.values():
            _reject_instruction_markers(item)
    elif isinstance(value, list):
        for item in value:
            _reject_instruction_markers(item)


def iso_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def journey_matches(query: str) -> list[str]:
    patterns = (
        ("road-test-booking", r"\broad test\b|\bdriving test\b|\bbook(?:ing)? (?:a )?test\b"),
        ("licence-renewal", r"\blicen[cs]e\b|\bicbc\b|\bbcid\b"),
        ("rental-assistance", r"\brent(?:al)?\b|\bhousing\b|\bshelter\b|\bsafer\b"),
        ("pharmacare-registration", r"\bpharmacare\b|\bdrug coverage\b|\bdrug plan\b"),
        ("health-coverage", r"\bmsp\b|\bmedical services plan\b|\bhealth coverage\b"),
        ("primary-care", r"\bdoctor\b|\bprimary care\b|\bhealth connect\b|\bnurse practitioner\b"),
        ("service-bc", r"\bservice ?bc\b|\boffice\b"),
    )
    matches = [journey for journey, pattern in patterns if re.search(pattern, query, re.I)]
    if "road-test-booking" in matches and "licence-renewal" in matches:
        matches.remove("licence-renewal")
    if "pharmacare-registration" in matches and "health-coverage" in matches:
        matches.remove("health-coverage")
    return matches


def choose_journey(query: str) -> str | None:
    return next(iter(journey_matches(query)), None)


@lru_cache(maxsize=1)
def bc_timezone() -> ZoneInfo:
    # Use the pinned database on every platform, not a potentially older host tzdb.
    with files("tzdata.zoneinfo").joinpath("America", "Vancouver").open("rb") as zone:
        return ZoneInfo.from_file(zone, key="America/Vancouver")


def legal_day(now: datetime) -> str:
    return now.astimezone(bc_timezone()).date().isoformat()


def evidence_metadata(row: dict, source_ids: set[str], day: str) -> EvidenceMetadata:
    version = row.get("metadataVersion")
    if version is None:
        raise ValueError("Metadata-aware evidence needs explicit provenance metadata.")
    if type(version) is not int or version != 1:
        raise ValueError("Unsupported evidence metadata version.")
    if row.get("rightsStatus") != "candidate-acquisition-permitted":
        raise ValueError("The acquired evidence has no verified rights provenance.")
    rights_review_id = row.get("rightsReviewId")
    if (
        not isinstance(rights_review_id, str)
        or not rights_review_id.strip()
        or rights_review_id != rights_review_id.strip()
    ):
        raise ValueError("The acquired evidence has no valid rights review identifier.")
    metadata = EvidenceMetadata(
        source_ids=row.get("sourceIds"),
        document_type=row.get("documentType"),
        language=row.get("language"),
        content_hash=row.get("contentHash"),
        extraction_hash=row.get("extractionHash"),
        review_hash=row.get("reviewHash"),
        rights_review_id=row.get("rightsReviewId"),
        rights_hash=row.get("rightsHash"),
        legal_status=row.get("legalStatus"),
        effective_from=row.get("effectiveFrom"),
        effective_to=row.get("effectiveTo"),
        consolidation_date=row.get("consolidationDate"),
        repealed_at=row.get("repealedAt"),
        legal_section_id=row.get("legalSectionId"),
        is_historical=row.get("isHistorical"),
    )
    if not set(metadata.source_ids) <= source_ids or row["sourceId"] not in metadata.source_ids:
        raise ValueError("Evidence source tags must resolve to the approved catalogue.")
    if row["sourceId"] == "bc-laws" and metadata.document_type != "legal":
        raise ValueError("Statutory evidence needs legal version metadata.")
    if metadata.document_type == "legal" and (
        metadata.legal_status != "in-force"
        or metadata.is_historical is not False
        or metadata.effective_from is None
        or metadata.effective_from > day
        or (metadata.effective_to is not None and metadata.effective_to <= day)
        or (metadata.repealed_at is not None and metadata.repealed_at <= day)
    ):
        raise ValueError("This legal version is not verified as currently in force.")
    return metadata


def validate_evidence_row(
    row: dict,
    allowed: dict[str, Source],
    source_ids: set[str],
    settings: Settings,
    now: datetime,
    day: str | None,
) -> tuple[Evidence | None, Literal["expired", "invalid"] | None]:
    source = allowed.get(row.get("sourceId"))
    if source is None or row.get("status") != "active":
        return None, "invalid"
    try:
        ref = SourceReference(
            source_id=source.id,
            document_id=row["documentId"],
            document_version=row["documentVersion"],
            title=row["title"],
            publisher=row["publisher"],
            url=row["url"],
            checked_at=iso_value(row["checkedAt"]),
            publisher_updated_at=iso_value(row.get("publisherUpdatedAt")),
            section=row.get("section", ""),
            chunk_id=row.get("id"),
            metadata=evidence_metadata(row, source_ids, day) if day is not None else None,
        )
        if (
            urlsplit(ref.url).hostname != urlsplit(source.url).hostname
            or ref.publisher != source.publisher
        ):
            return None, "invalid"
        text = row["content"]
        if not isinstance(text, str) or len(text) > 8000 or INJECTION_MARKERS.search(text):
            return None, "invalid"
        evidence = Evidence(reference=ref, content=text)
        checked = datetime.fromisoformat(ref.checked_at)
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=UTC)
        if checked > now:
            return None, "invalid"
        if checked < now - timedelta(days=settings.search_max_age_days):
            return None, "expired"
        return evidence, None
    except KeyError, TypeError, ValueError, ValidationError:
        return None, "invalid"


def add_metadata_filter(filters: str, day: str | None) -> str:
    if day is not None:
        filters += (
            " and metadataVersion eq 1"
            " and rightsStatus eq 'candidate-acquisition-permitted'"
            " and rightsReviewId ne null and rightsHash ne null and reviewHash ne null"
            " and (documentType ne 'legal' or (legalStatus eq 'in-force'"
            " and isHistorical eq false and effectiveFrom ne null"
            f" and effectiveFrom le '{day}'"
            f" and (effectiveTo eq null or effectiveTo gt '{day}')"
            f" and (repealedAt eq null or repealedAt gt '{day}')))"
        )
    return filters


class AzureRetriever:
    def __init__(
        self,
        settings: Settings,
        catalog: CatalogRepository,
        client: SearchClient,
        embeddings: AzureEmbeddings | None = None,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.client = client
        self.embeddings = embeddings

    def allowed_sources(self) -> dict[str, Source]:
        return {
            source.id: source
            for source in self.catalog.get().sources
            if source.status in ("available", "limited")
            and (source.id != "bc-laws" or self.settings.azure_search_metadata_enabled)
        }

    async def inspect_sources(self) -> SourceHealth:
        allowed = self.allowed_sources()
        rows = []
        scanned = 0
        rejected = 0
        if allowed:
            filters = " or ".join(f"sourceId eq '{key}'" for key in sorted(allowed))
            try:
                async with asyncio.timeout(self.settings.api_upstream_timeout_seconds):
                    results = await self.client.search(
                        search_text="*",
                        filter=f"status eq 'active' and ({filters})",
                        select=SELECT_FIELDS
                        + (METADATA_FIELDS if self.settings.azure_search_metadata_enabled else []),
                        query_type=QueryType.SIMPLE,
                        logging_enable=False,
                    )
                    async for row in results:
                        scanned += 1
                        if scanned > 1000:
                            raise ApiError(
                                503,
                                "SOURCE_HEALTH_LIMIT",
                                "The bounded source-health scan could not verify the whole index.",
                            )
                        text = row.get("content")
                        if not isinstance(text, str) or not 1 <= len(text) <= 8000:
                            rejected += 1
                            continue
                        rows.append(row)
            except ApiError:
                raise
            except ResourceNotFoundError:
                raise ApiError(
                    503, "SOURCES_UNAVAILABLE", "The approved source index has not been published."
                ) from None
            except TimeoutError:
                raise ApiError(
                    504, "SEARCH_TIMEOUT", "The source-health check timed out."
                ) from None
            except Exception:
                raise ApiError(
                    503, "SEARCH_UNAVAILABLE", "Official-source health could not be verified."
                ) from None
        now = datetime.now(UTC)
        day = legal_day(now) if self.settings.azure_search_metadata_enabled else None
        source_ids = {source.id for source in self.catalog.get().sources}
        usable: set[tuple[str, str, str]] = set()
        expired: set[tuple[str, str, str]] = set()
        covered: set[str] = set()
        expiry: datetime | None = None
        for row in rows:
            evidence, reason = validate_evidence_row(
                row, allowed, source_ids, self.settings, now, day
            )
            if reason == "expired":
                expired.add((row["sourceId"], row["documentId"], row["documentVersion"]))
            elif evidence is None:
                rejected += 1
            else:
                ref = evidence.reference
                usable.add((ref.source_id, ref.document_id, ref.document_version))
                covered.add(ref.source_id)
                if isinstance(ref.metadata, EvidenceMetadata):
                    covered.update(set(ref.metadata.source_ids) & set(allowed))
                checked = datetime.fromisoformat(ref.checked_at)
                if checked.tzinfo is None:
                    checked = checked.replace(tzinfo=UTC)
                expires = checked + timedelta(days=self.settings.search_max_age_days)
                expiry = min(expiry, expires) if expiry is not None else expires
        return SourceHealth(
            status=(
                "expiring" if expiry is not None and expiry <= now + timedelta(days=1) else "ready"
            )
            if usable
            else "expired"
            if expired
            else "unusable"
            if scanned
            else "empty",
            checked_at=now.isoformat(),
            usable_documents=len(usable),
            expired_documents=len(expired),
            rejected_chunks=rejected,
            next_expiry_at=expiry.isoformat() if expiry is not None else None,
            covered_source_ids=sorted(covered),
            missing_source_ids=sorted(set(allowed) - covered),
        )

    async def retrieve(
        self,
        query: str,
        journey_id: str | None = None,
        *,
        source_ids: frozenset[str] | None = None,
    ) -> EvidenceBundle:
        if not query.strip() or len(query) > 512 or "\x00" in query:
            raise ApiError(422, "INVALID_SEARCH", "Use a short public-service search question.")
        if journey_id is not None and journey_id not in JOURNEY_IDS:
            raise ApiError(422, "INVALID_JOURNEY", "Choose an approved journey.")
        if source_ids is not None and (
            journey_id is not None
            or not source_ids
            or any(type(source_id) is not str for source_id in source_ids)
        ):
            raise ApiError(422, "INVALID_SOURCE_SCOPE", "Choose an approved source scope.")
        catalog = self.catalog.get()
        now = datetime.now(UTC)
        day = legal_day(now) if self.settings.azure_search_metadata_enabled else None
        allowed = self.allowed_sources()
        if journey_id:
            journey = self.catalog.journey(journey_id)
            allowed = {key: source for key, source in allowed.items() if key in journey.source_ids}
        elif source_ids is not None:
            if not source_ids <= set(allowed):
                raise ApiError(422, "INVALID_SOURCE_SCOPE", "Choose an approved source scope.")
            allowed = {key: source for key, source in allowed.items() if key in source_ids}
        requested_topics = (
            set(source_topics(query)) & {source.id for source in catalog.sources}
            if journey_id is None and source_ids is None
            else set()
        )
        if not allowed:
            raise ApiError(503, "SOURCES_UNAVAILABLE", "No approved sources are available.")
        # Only validated catalogue identifiers are interpolated into OData.
        source_filter = " or ".join(f"sourceId eq '{key}'" for key in sorted(allowed))
        filters = f"status eq 'active' and ({source_filter})"
        if journey_id:
            filters += f" and journeyIds/any(j: j eq '{journey_id}')"
        if requested_topics:
            topic_filter = " or ".join(f"sourceId eq '{key}'" for key in sorted(requested_topics))
            if self.settings.azure_search_metadata_enabled:
                topic_filter += " or " + " or ".join(
                    f"sourceIds/any(s: s eq '{key}')" for key in sorted(requested_topics)
                )
            filters += f" and ({topic_filter})"
        filters = add_metadata_filter(filters, day)
        options: dict[str, Any] = {
            "search_text": query,
            "filter": filters,
            "top": 10,
            "select": SELECT_FIELDS + METADATA_FIELDS if day is not None else SELECT_FIELDS,
            "query_type": QueryType.SIMPLE,
            "logging_enable": False,
        }
        if self.settings.azure_search_semantic_config:
            options.update(
                query_type=QueryType.SEMANTIC,
                semantic_configuration_name=self.settings.azure_search_semantic_config,
            )
        try:
            async with asyncio.timeout(self.settings.api_upstream_timeout_seconds):
                if self.settings.azure_search_vector_enabled:
                    if self.embeddings is None or not self.settings.hybrid_configured:
                        raise ApiError(
                            503,
                            "EMBEDDING_NOT_CONFIGURED",
                            "Hybrid retrieval is not fully configured.",
                        )
                    vector = await self.embeddings.embed(query)
                    options["vector_queries"] = [
                        VectorizedQuery(
                            vector=vector, fields="contentVector", k_nearest_neighbors=50
                        )
                    ]
                results = await self.client.search(**options)
                rows = []
                async for row in results:
                    rows.append(row)
                    if len(rows) == 10:
                        break
        except ApiError:
            raise
        except ResourceNotFoundError:
            raise ApiError(
                503, "SOURCES_UNAVAILABLE", "The approved source index has not been published."
            ) from None
        except TimeoutError:
            raise ApiError(504, "SEARCH_TIMEOUT", "Official-source retrieval timed out.") from None
        except Exception:
            raise ApiError(
                503,
                "SEARCH_UNAVAILABLE",
                "Official-source retrieval is unavailable. Try a guided journey.",
            ) from None

        candidates: list[Evidence] = []
        now = datetime.now(UTC)
        for row in rows[:10]:
            source = allowed.get(row.get("sourceId"))
            if source is None or row.get("status") != "active":
                continue
            if journey_id and journey_id not in row.get("journeyIds", []):
                continue
            row_topics = {row.get("sourceId")}
            if (
                self.settings.azure_search_metadata_enabled
                and type(row.get("metadataVersion")) is int
                and row["metadataVersion"] == 1
                and isinstance(row.get("sourceIds"), list)
            ):
                row_topics.update(key for key in row["sourceIds"] if isinstance(key, str))
            if requested_topics and not requested_topics.intersection(row_topics):
                continue
            evidence, _ = validate_evidence_row(
                row, allowed, {source.id for source in catalog.sources}, self.settings, now, day
            )
            if evidence is not None:
                candidates.append(evidence)
        evidence = diversify_evidence(candidates)
        if not evidence:
            raise ApiError(
                503,
                "SOURCES_UNAVAILABLE",
                "No current, approved evidence was found. "
                "Use a guided journey or the official service.",
            )
        return EvidenceBundle(evidence=evidence)


def diversify_evidence(candidates: list[Evidence], limit: int = 5) -> list[Evidence]:
    unique: list[tuple[int, Evidence]] = []
    chunks: set[tuple[str, str]] = set()
    for rank, item in enumerate(candidates):
        ref = item.reference
        chunk = (
            ("id", ref.chunk_id)
            if ref.chunk_id
            else ("content", hashlib.sha256(item.content.encode()).hexdigest())
        )
        if chunk in chunks:
            continue
        chunks.add(chunk)
        unique.append((rank, item))

    selected: set[int] = set()
    sources: set[str] = set()
    documents: set[tuple[str, str]] = set()

    def item_sources(item: Evidence) -> set[str]:
        metadata = item.reference.metadata
        return set(metadata.source_ids) if metadata is not None else {item.reference.source_id}

    def add(rank: int, item: Evidence) -> None:
        selected.add(rank)
        sources.update(item_sources(item))
        documents.add((item.reference.source_id, item.reference.document_id))

    for rank, item in unique:
        if len(selected) == limit:
            break
        if item_sources(item) - sources:
            add(rank, item)
    for rank, item in unique:
        if len(selected) == limit:
            break
        document = (item.reference.source_id, item.reference.document_id)
        if rank not in selected and document not in documents:
            add(rank, item)
    for rank, item in unique:
        if len(selected) == limit:
            break
        if rank not in selected:
            add(rank, item)
    return [item for rank, item in unique if rank in selected]


def model_evidence_json(bundle: EvidenceBundle) -> str:
    payload = bundle.model_dump(mode="json", by_alias=True)
    _reject_instruction_markers(payload)
    quotes = quote_registry(bundle.evidence)
    for item in payload["evidence"]:
        item["content"] = mark_source_quotes(item["content"], item["reference"]["url"], quotes)
        metadata = item["reference"].get("metadata")
        if metadata and metadata["version"] == 2:
            for key in ("notice", "attribution", "licenceUrl", "contentHash"):
                metadata.pop(key, None)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class EvidenceLedger:
    def __init__(self) -> None:
        self.items: dict[str, Evidence] = {}

    def add(self, bundle: EvidenceBundle) -> None:
        _reject_instruction_markers(bundle.model_dump(mode="json", by_alias=True))
        for item in bundle.evidence:
            ref = item.reference
            for previous in self.items.values():
                if (
                    previous.reference.url == ref.url
                    and previous.reference.document_version != ref.document_version
                ):
                    raise ApiError(
                        503,
                        "SOURCE_CONFLICT",
                        "The source changed during this answer. Please retry.",
                    )
            chunk = ref.chunk_id or hashlib.sha256(item.content.encode()).hexdigest()
            key = f"{ref.document_id}:{ref.document_version}:{chunk}"
            previous = self.items.get(key)
            if previous is not None and (
                previous.content != item.content
                or previous.reference.url != ref.url
                or previous.reference.source_id != ref.source_id
            ):
                raise ApiError(
                    503,
                    "SOURCE_CONFLICT",
                    "The indexed evidence is inconsistent. Check the official source.",
                )
            if len(self.items) >= 20 and key not in self.items:
                raise ApiError(502, "EVIDENCE_LIMIT", "The response exceeded the evidence budget.")
            self.items[key] = item

    def bundle(self) -> EvidenceBundle:
        return EvidenceBundle(evidence=list(self.items.values())[:5])
