"""Named, licensed source reads for a loopback-only non-commercial evaluation."""

import asyncio
import hashlib
import ipaddress
import logging
import re
import ssl
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpcore
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bc_api.catalog import CatalogRepository
from bc_api.conversation_grounding import AnswerTopic, ProgrammeId, public_queries
from bc_api.errors import ApiError
from bc_api.models import (
    CalendarDate,
    Evidence,
    EvidenceBundle,
    IsoDateTime,
    LocalEvidenceMetadata,
    SourceReference,
)
from bc_api.retrieval import INJECTION_MARKERS
from bc_api.urls import resolve_addresses

KPL_URL = "https://www.bclaws.gov.bc.ca/standards/Licence.html"
KPL_NOTICE = (
    "These materials contain information that has been derived from information originally "
    "made available by the Province of British Columbia at: http://www.bclaws.gov.bc.ca and "
    "this information is being used in accordance with the King's Printer Licence \u2013 British "
    "Columbia available at: https://www.bclaws.gov.bc.ca/standards/Licence.html. "
    "They have not, however, been produced in affiliation with, or with the endorsement of, "
    "the Province of British Columbia and THESE MATERIALS ARE NOT AN OFFICIAL VERSION."
)
CANADA_TERMS = "https://www.canada.ca/en/transparency/terms.html"
LOCAL_NOTICE = (
    "Local non-commercial evaluation only. This material is not approved for public or "
    "commercial redistribution. Runtime source checks are not a human publication review."
)


@dataclass(frozen=True)
class SourceSpec:
    url: str
    source_id: str
    title: str
    kind: str
    sections: tuple[str, ...] = ()


SOURCES = {
    "fees": SourceSpec(
        "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/334_91",
        "bc-laws",
        "Motor Vehicle Fees Regulation",
        "fees",
    ),
    "adult": SourceSpec(
        "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/96349_01",
        "bc-laws",
        "Patients Property Act",
        "legal",
        ("1", "2", "3", "6"),
    ),
    "child": SourceSpec(
        "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/11025_04",
        "bc-laws",
        "Family Law Act",
        "legal",
        ("39", "51", "52"),
    ),
    "pwd-act": SourceSpec(
        "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/02041_01",
        "bc-laws",
        "Employment and Assistance for Persons with Disabilities Act",
        "legal",
        ("2",),
    ),
    "pwd-application": SourceSpec(
        "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/265_2002",
        "bc-laws",
        "Employment and Assistance for Persons with Disabilities Regulation",
        "legal",
        ("4.1", "4.2"),
    ),
    "ei-overview": SourceSpec(
        "https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit.html",
        "employment-insurance",
        "EI regular benefits",
        "canada",
    ),
    "ei-apply": SourceSpec(
        "https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/apply.html",
        "employment-insurance",
        "EI regular benefits",
        "canada",
    ),
    "ei-eligibility": SourceSpec(
        "https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/eligibility.html",
        "employment-insurance",
        "EI regular benefits",
        "canada",
    ),
    "ei-after": SourceSpec(
        "https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/after-applying.html",
        "employment-insurance",
        "EI regular benefits",
        "canada",
    ),
    "ei-temporary": SourceSpec(
        "https://www.canada.ca/en/services/benefits/ei/"
        "temporary-measures-for-major-economic-conditions.html",
        "employment-insurance",
        "Temporary Employment Insurance measures to respond to "
        "major changes in economic conditions",
        "canada",
    ),
}
ALLOWED_URLS = frozenset(source.url for source in SOURCES.values())
LOCAL_PROGRAMMES: tuple[ProgrammeId, ...] = (
    "licence-renewal",
    "ei-regular",
    "guardianship-adult",
    "guardianship-child",
    "disability-assistance",
    "pwd-designation",
)


class SnapshotSection(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    heading: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=11000)


class SnapshotDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    key: str = Field(min_length=1, max_length=40)
    url: str = Field(max_length=2048)
    title: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=200)
    acquired_at: IsoDateTime
    publisher_updated_at: CalendarDate | None
    sections: list[SnapshotSection] = Field(min_length=1, max_length=12)


class SnapshotFile(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    version: Literal[1]
    use_scope: Literal["local-noncommercial-evaluation"]
    acquisition_method: Literal["read-only-web-fetch"]
    documents: list[SnapshotDocument] = Field(min_length=1, max_length=5)


def load_snapshots(path: Path | None, expected_hash: str | None) -> dict[str, SnapshotDocument]:
    if path is None and expected_hash is None:
        return {}
    if path is None or not expected_hash:
        raise ApiError(503, "SOURCE_SNAPSHOT_INVALID", "A local snapshot needs its pinned digest.")
    try:
        with path.open("rb") as source:
            body = source.read(131073)
        if len(body) > 131072 or hashlib.sha256(body).hexdigest() != expected_hash:
            raise ValueError("Snapshot digest or size mismatch.")
        manifest = SnapshotFile.model_validate_json(body)
        result: dict[str, SnapshotDocument] = {}
        for item in manifest.documents:
            spec = SOURCES.get(item.key)
            if (
                spec is None
                or spec.kind != "canada"
                or item.url != spec.url
                or spec.title.casefold() not in item.title.casefold()
                or item.key in result
                or item.publisher
                not in ("Employment and Social Development Canada", "Service Canada")
            ):
                raise ValueError("Snapshot identity mismatch.")
            result[item.key] = item
        return result
    except OSError, ValueError, ValidationError:
        raise ApiError(
            503,
            "SOURCE_SNAPSHOT_INVALID",
            "The pinned local source snapshot could not be verified.",
        ) from None


class PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, hostname: str, address: str):
        self.hostname, self.address = hostname, address
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host,
        port,
        timeout=None,  # noqa: ASYNC109 -- required by httpcore's backend protocol.
        local_address=None,
        socket_options=None,
    ):
        if host != self.hostname or port != 443:
            raise OSError("Unapproved connection target.")
        return await self.backend.connect_tcp(
            self.address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


async def _fetch_named_source(url: str, read_timeout: float) -> bytes:
    if url not in ALLOWED_URLS:
        raise ApiError(403, "SOURCE_NOT_PERMITTED", "That source is not in the local registry.")
    host = urlsplit(url).hostname
    assert host is not None
    async with asyncio.timeout(read_timeout):
        addresses = await resolve_addresses(host)
        if not addresses or any(
            not ipaddress.ip_address(address).is_global for address in addresses
        ):
            raise ApiError(403, "SOURCE_ADDRESS_DENIED", "The source did not resolve publicly.")
        addresses.sort(key=lambda address: (ipaddress.ip_address(address).version, address))
        async with httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PinnedBackend(host, addresses[0]),
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
        ) as pool:
            async with pool.stream(
                "GET",
                url,
                headers={
                    "User-Agent": "BCPilotLocalEvaluation/1.0",
                    "Accept-Encoding": "identity",
                    "Accept": "text/html,application/xhtml+xml",
                },
                extensions={"timeout": {"connect": min(read_timeout, 5), "read": read_timeout}},
            ) as response:
                headers = {key.decode().lower(): value.decode() for key, value in response.headers}
                media = headers.get("content-type", "").split(";")[0].strip().lower()
                if response.status != 200 or media not in ("text/html", "application/xhtml+xml"):
                    raise ApiError(
                        503, "SOURCE_RESPONSE_INVALID", "The official source is unavailable."
                    )
                if headers.get("content-encoding", "identity").lower() != "identity":
                    raise ApiError(502, "SOURCE_ENCODING_INVALID", "Unsupported source encoding.")
                chunks, size = [], 0
                async for chunk in response.aiter_stream():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise ApiError(
                            502, "SOURCE_SIZE_LIMIT", "The source exceeds the read limit."
                        )
                    chunks.append(chunk)
                return b"".join(chunks)


async def fetch_named_source(url: str, read_timeout: float = 15) -> bytes:
    try:
        return await _fetch_named_source(url, read_timeout)
    except TimeoutError, httpcore.TimeoutException:
        raise ApiError(504, "SOURCE_READ_TIMEOUT", "The official source read timed out.") from None
    except OSError, httpcore.NetworkError, httpcore.ProtocolError:
        raise ApiError(
            503, "SOURCE_READ_FAILED", "The official source could not be read."
        ) from None


def text_of(node: Tag) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _legal_section(soup: BeautifulSoup, number: str) -> tuple[str, str]:
    marker = soup.find(id=f"section{number}") or soup.find("a", attrs={"name": f"section{number}"})
    if not isinstance(marker, Tag):
        raise ApiError(502, "SOURCE_SECTION_MISSING", "The requested statutory section is missing.")
    node = marker if marker.name == "div" else marker.find_parent("div", class_="section")
    if not isinstance(node, Tag):
        raise ApiError(502, "SOURCE_SECTION_MISSING", "The statutory section has no complete body.")
    blocks = node.find_all(["h4", "p"], recursive=False)
    if not blocks:
        raise ApiError(502, "SOURCE_SECTION_INVALID", "The statutory paragraph structure changed.")
    paragraphs = []
    for block in blocks:
        copy = deepcopy(block)
        for marker in copy.select("span.secnum, span.num"):
            paragraphs.append(text_of(marker))
            marker.decompose()
        paragraphs.append(text_of(copy))
    value = "\n".join(paragraph for paragraph in paragraphs if paragraph)
    if len(value) < 50 or len(value) > 10000 or re.search(r"\bRepealed\b", value[:120]):
        raise ApiError(
            502, "SOURCE_SECTION_INVALID", "The statutory section is incomplete or unsuitable."
        )
    return f"Section {number}", value


def _fee_section(soup: BeautifulSoup) -> tuple[str, str]:
    rows = soup.find_all("tr")
    selected = []
    started = False
    ended = False
    for row in rows:
        text = text_of(row)
        if len(text) < 200 and "DRIVERS' LICENCES AND DRIVERS' TESTS" in text:
            started = True
        if started and ("LICENCES WITH INDICATION" in text or "DRIVERS' TEST AND MISSED" in text):
            ended = True
            break
        if started:
            if text == "The fee for a driver's licence is as follows:":
                continue
            cells = [text_of(cell) for cell in row.find_all(["td", "th"], recursive=False)]
            if len(cells) > 1 and re.fullmatch(r"\d+(?:,\d{3})*(?:\.\d{1,2})?", cells[-1]):
                labels = [cell for cell in cells[:-1] if re.fullmatch(r"\([ivx]+\)", cell)]
                matter = " ".join(cell for cell in cells[:-1] if cell and cell not in labels)
                if not matter:
                    raise ApiError(502, "SOURCE_TABLE_INCOMPLETE", "A fee row has no description.")
                selected.extend([*labels, f"{matter}: ${cells[-1]}."])
            else:
                selected.append(text)
    if (
        not started
        or not ended
        or len(selected) < 7
        or not re.search(r"\bFee\s*\$", text_of(soup), re.I)
    ):
        raise ApiError(
            502, "SOURCE_TABLE_INCOMPLETE", "The complete driver-licence fee group is missing."
        )
    return (
        "Schedule, item 4(a): driver licences; normalized rows from the FEE $ column",
        "\n".join(selected),
    )


def parse_source(spec: SourceSpec, body: bytes, now: datetime) -> EvidenceBundle:
    soup = BeautifulSoup(body, "html.parser")
    title = text_of(soup.title) if soup.title else ""
    if spec.title.casefold() not in title.casefold():
        raise ApiError(
            502, "SOURCE_IDENTITY_INVALID", "The source title did not match the registry."
        )
    content_hash = hashlib.sha256(body).hexdigest()
    checked = now.isoformat()
    consolidated = None
    publisher_updated = None
    if spec.kind != "canada":
        currency_node = soup.find(id="act:currency") or soup.select_one(
            ".currencysingle, .regCurrency"
        )
        currency = re.search(
            r"(?:current to|current as of)\s+([A-Z][a-z]+ \d{1,2}, \d{4})",
            text_of(currency_node) if isinstance(currency_node, Tag) else "",
            re.I,
        )
        if not currency:
            raise ApiError(
                502, "LEGAL_CURRENCY_MISSING", "The consolidation date was not supplied."
            )
        consolidated = datetime.strptime(currency[1], "%B %d, %Y").date()
        if not now.date() - timedelta(days=7) <= consolidated <= now.date():
            raise ApiError(
                503, "LEGAL_SOURCE_STALE", "The consolidation needs a currentness review."
            )
        if not soup.find("a", href="/standards/Licence.html"):
            raise ApiError(
                502, "SOURCE_LICENCE_MISSING", "The source licence reference is missing."
            )
        pieces = (
            [_legal_section(soup, "2"), _fee_section(soup)]
            if spec.kind == "fees"
            else [_legal_section(soup, section) for section in spec.sections]
        )
        publisher = "Province of British Columbia, King's Printer"
        notice = KPL_NOTICE
        licence = KPL_URL
    else:
        author = soup.find("meta", attrs={"name": "author"})
        publisher = (
            str(author.get("content"))
            if author and author.get("content")
            else "Government of Canada"
        )
        modified = soup.find("meta", attrs={"name": "dcterms.modified"})
        if modified and modified.get("content"):
            value = str(modified["content"])
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                publisher_updated = value
        main = soup.find("main")
        if not isinstance(main, Tag):
            raise ApiError(502, "SOURCE_REGION_MISSING", "The official content region is missing.")
        for node in main.find_all(["script", "style", "nav", "footer", "input", "button"]):
            node.decompose()
        for node in main.select(".success-message, .pagedetails"):
            node.decompose()
        value = text_of(main)
        if len(value) < 300 or len(value) > 11000:
            raise ApiError(
                502, "SOURCE_CONTENT_INCOMPLETE", "The complete guidance could not be retained."
            )
        if spec.url.endswith("/apply.html") and not all(
            phrase in value.casefold()
            for phrase in ("social insurance number", "records of employment")
        ):
            raise ApiError(
                502, "SOURCE_LIST_MISSING", "Application preparation content is incomplete."
            )
        pieces = [("Complete main guidance", value)]
        notice = f"This is a copy of the version available at {spec.url}. {LOCAL_NOTICE}"
        licence = CANADA_TERMS
    evidence = []
    for section, content in pieces:
        if INJECTION_MARKERS.search(content):
            raise ApiError(
                502, "SOURCE_CONTENT_REJECTED", "Unexpected instruction-like source content."
            )
        if len(content) > 11000:
            raise ApiError(
                502, "SOURCE_SECTION_LIMIT", "The complete source section exceeds the limit."
            )
        key = hashlib.sha256(f"{spec.url}#{section}".encode()).hexdigest()[:24]
        legal = spec.kind != "canada"
        metadata = LocalEvidenceMetadata(
            source_ids=[spec.source_id],
            document_type="legal" if legal else "guidance",
            retrieval_origin="official-live",
            content_hash=content_hash,
            licence_url=licence,
            attribution=f"{title}. Author/publisher: {publisher}. Source: {spec.url}.",
            notice=notice,
            consolidation_date=consolidated.isoformat() if consolidated else None,
            legal_status="publisher-current-collection" if legal else None,
        )
        evidence.append(
            Evidence(
                reference=SourceReference(
                    source_id=spec.source_id,
                    document_id=f"local-{key}",
                    document_version=content_hash,
                    chunk_id=f"local-{key}",
                    title=title,
                    publisher=publisher,
                    url=spec.url,
                    checked_at=checked,
                    publisher_updated_at=publisher_updated,
                    section=section,
                    metadata=metadata,
                ),
                content=content,
            )
        )
    return EvidenceBundle(evidence=evidence)


def snapshot_evidence(snapshot: SnapshotDocument, now: datetime) -> EvidenceBundle:
    acquired = datetime.fromisoformat(snapshot.acquired_at.replace("Z", "+00:00"))
    if not now - timedelta(days=7) <= acquired <= now:
        raise ApiError(
            503, "SOURCE_SNAPSHOT_STALE", "The evaluation snapshot needs a fresh source read."
        )
    content = "\n\n".join(f"{section.heading}\n{section.content}" for section in snapshot.sections)
    if len(content) < 300 or len(content) > 11000 or INJECTION_MARKERS.search(content):
        raise ApiError(502, "SOURCE_CONTENT_REJECTED", "The source snapshot failed content checks.")
    if snapshot.key == "ei-apply" and not all(
        phrase in content.casefold()
        for phrase in (
            "social insurance number",
            "records of employment",
            "apply online",
        )
    ):
        raise ApiError(502, "SOURCE_LIST_MISSING", "Application preparation content is incomplete.")
    spec = SOURCES[snapshot.key]
    digest = hashlib.sha256(content.encode()).hexdigest()
    key = hashlib.sha256(spec.url.encode()).hexdigest()[:24]
    return EvidenceBundle(
        evidence=[
            Evidence(
                reference=SourceReference(
                    source_id=spec.source_id,
                    document_id=f"snapshot-{key}",
                    chunk_id=f"snapshot-{key}",
                    document_version=digest,
                    title=snapshot.title,
                    publisher=snapshot.publisher,
                    url=spec.url,
                    checked_at=snapshot.acquired_at,
                    publisher_updated_at=snapshot.publisher_updated_at,
                    section="Complete selected sections: "
                    + "; ".join(section.heading for section in snapshot.sections),
                    metadata=LocalEvidenceMetadata(
                        source_ids=[spec.source_id],
                        document_type="guidance",
                        retrieval_origin="official-snapshot",
                        content_hash=digest,
                        licence_url=CANADA_TERMS,
                        attribution=f"{snapshot.title}. Author/publisher: {snapshot.publisher}. "
                        f"Source: {spec.url}.",
                        notice=f"This is a copy of the version available at {spec.url}, "
                        f"read on {acquired.date().isoformat()}. {LOCAL_NOTICE}",
                    ),
                ),
                content=content,
            )
        ]
    )


class LocalEvidenceProvider:
    def __init__(
        self,
        catalog: CatalogRepository,
        *,
        timeout: float = 15,
        fetcher=fetch_named_source,
        snapshot_path: Path | None = None,
        snapshot_sha256: str | None = None,
    ):
        self.catalog, self.timeout, self.fetcher = catalog, timeout, fetcher
        self.snapshots = load_snapshots(snapshot_path, snapshot_sha256)
        self.cache: dict[str, tuple[float, EvidenceBundle]] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    async def source(self, key: str) -> EvidenceBundle:
        async with self.locks.setdefault(key, asyncio.Lock()):
            if key in self.snapshots:
                return snapshot_evidence(self.snapshots[key], datetime.now(UTC))
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            spec = SOURCES[key]
            try:
                body = await self.fetcher(spec.url, self.timeout)
                result = parse_source(spec, body, datetime.now(UTC))
            except ApiError as exc:
                logging.getLogger("bc_api.sources").warning(
                    "Local evaluation source unavailable: %s (%s)",
                    key,
                    exc.code,
                )
                raise
            self.cache[key] = (time.monotonic() + 300, result)
            return result

    def catalogue(self, topics: list[AnswerTopic]) -> list[Evidence]:
        plan = self.catalog.plan("licence-renewal")
        source = next(source for source in plan.sources if source.id == "icbc")
        if source.checked_at is None:
            raise ApiError(
                503, "CATALOGUE_DATE_MISSING", "The preparation guide has no checked date."
            )
        checked = datetime.fromisoformat(source.checked_at.replace("Z", "+00:00"))
        if checked.date() < datetime.now(UTC).date() - timedelta(days=7):
            raise ApiError(
                503, "CATALOGUE_STALE", "The dated preparation guide needs a source review."
            )
        selected = {"check-renewal-guidance", "confirm-before-visiting"}
        if set(topics) - {"additional-items", "fees", "locations", "contact"} or not topics:
            selected.add("prepare-identification")
        content = "\n\n".join(
            [
                plan.journey.notice,
                *[
                    f"{step.title}\n{step.description}"
                    for step in plan.journey.steps
                    if step.id in selected
                ],
            ]
        )
        digest = hashlib.sha256(plan.model_dump_json(by_alias=True).encode()).hexdigest()
        return [
            Evidence(
                reference=SourceReference(
                    source_id="icbc",
                    document_id="reviewed-project-renewal",
                    document_version=digest,
                    title=plan.journey.title,
                    publisher="B.C. service pilot reviewed catalogue",
                    url=plan.journey.handoffs[0].url,
                    checked_at=source.checked_at,
                    publisher_updated_at=source.publisher_updated_at,
                    section="Selected reviewed preparation notes; not an office inventory",
                    metadata=LocalEvidenceMetadata(
                        source_ids=["icbc", "service-bc"],
                        document_type="guidance",
                        retrieval_origin="project-catalogue",
                        content_hash=digest,
                        licence_url=None,
                        attribution="Existing project-reviewed preparation catalogue, "
                        "linked to its official handoff.",
                        notice="Application-curated preparation notes, not a newly acquired "
                        "copy of the publisher website. " + LOCAL_NOTICE,
                    ),
                ),
                content=content,
            )
        ]

    async def retrieve(self, programme: ProgrammeId, topics: list[AnswerTopic]) -> EvidenceBundle:
        requested = set(topics)
        if programme == "licence-renewal":
            items = []
            keys = ["fees"] if requested & {"fees", "additional-items", "requirements"} else []
        elif programme == "ei-regular":
            items = []
            selections = {
                "reporting": ("ei-after", "ei-temporary"),
                "missing-roe": ("ei-overview", "ei-after", "ei-apply", "ei-temporary"),
                "contact": ("ei-after", "ei-apply", "ei-temporary"),
                "requirements": ("ei-eligibility", "ei-temporary", "ei-overview"),
                "existing-claim": ("ei-apply", "ei-temporary"),
            }
            keys = list(
                dict.fromkeys(
                    key
                    for topic in topics or ["overview"]
                    for key in selections.get(topic, ("ei-overview", "ei-apply", "ei-temporary"))
                )
            )
        elif programme == "guardianship-adult":
            items, keys = [], ["adult"]
        elif programme == "guardianship-child":
            items, keys = [], ["child"]
        elif programme in ("disability-assistance", "pwd-designation"):
            items, keys = [], ["pwd-act", "pwd-application"]
        else:
            raise ApiError(
                422, "SOURCE_PROGRAMME_INVALID", "That programme has no local source profile."
            )
        try:
            public_queries(programme, topics)
        except KeyError, ValueError:
            raise ApiError(
                422, "SOURCE_TOPIC_INVALID", "That topic is outside this programme."
            ) from None
        for bundle in await asyncio.gather(*(self.source(key) for key in keys)):
            items.extend(bundle.evidence)
        if requested and requested <= {"legal-help", "contact", "overview", "locations"}:
            if programme == "guardianship-adult":
                items = [
                    item for item in items if item.reference.section in ("Section 1", "Section 6")
                ]
            elif programme == "guardianship-child":
                items = [
                    item for item in items if item.reference.section in ("Section 39", "Section 51")
                ]
        if programme == "licence-renewal":
            items.extend(self.catalogue(topics))
        if not items:
            raise ApiError(
                503, "SOURCES_UNAVAILABLE", "No permitted current evidence was available."
            )
        if len(items) > 5:
            raise ApiError(
                502, "SOURCE_SELECTION_LIMIT", "The complete evidence exceeds the source limit."
            )
        return EvidenceBundle(evidence=items, notice=LOCAL_NOTICE)

    async def ensure_ready(self) -> None:
        await asyncio.gather(
            self.source("ei-apply"),
            self.source("ei-after"),
            *(
                self.retrieve(programme, ["requirements"])
                for programme in LOCAL_PROGRAMMES
                if programme != "pwd-designation"
            ),
        )

    def clear(self) -> None:
        self.cache.clear()
        self.locks.clear()
        self.snapshots.clear()
