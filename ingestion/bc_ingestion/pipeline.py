"""Local version ledger; extraction never implicitly approves publication."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from .extract import (
    ChunkingError,
    Document,
    Section,
    chunk_document,
    extract,
    legacy_chunks,
)
from .fetch import Fetcher, Response, utc_now
from .manifest import (
    JsonManifestStore,
    LocalResponseStore,
    ProgrammeLimits,
    RequestController,
    atomic_json,
)
from .metadata import (
    EXTRACTION_METHOD,
    EXTRACTION_METHODS,
    LEGACY_EXTRACTION_METHOD,
    MAX_CHUNK_CHARS,
    digest,
    extraction_digest,
    search_metadata,
    validate_metadata,
)
from .policy import (
    PUBLICATION_HOLDS,
    PUBLISHERS,
    AcquisitionError,
    canonicalize,
    validate_url,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def document_id(url: str) -> str:
    return hashlib.sha256(canonicalize(url).encode("utf-8")).hexdigest()[:32]


def guarded_output(path: str | Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.is_relative_to(PROJECT_ROOT) or ".generated" not in path.parts:
        raise AcquisitionError("Generated content must stay in a project .generated directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_json(path: Path, value: dict) -> None:
    atomic_json(path, value)


def restore_document(value: dict) -> Document:
    fields = dict(value)
    fields["sections"] = [Section(**section) for section in value["sections"]]
    return Document(**fields)


def snapshot_hash(document: Document) -> str:
    return digest({
        "contentHash": document.content_hash, "extractionHash": document.extraction_hash,
        "responseHash": document.response_hash,
    })


def review_identity(entry: dict, version: dict) -> str:
    document = restore_document(version["document"])
    try:
        chunk_hash = digest(chunk_document(document))
    except ChunkingError as exc:
        chunk_hash = digest({"chunkingHold": exc.reason})
    identity = {
        "documentId": entry["documentId"], "documentVersion": version["documentVersion"],
        "snapshotHash": snapshot_hash(document), "chunkSetHash": chunk_hash,
        "reviewGeneration": version.get("reviewGeneration", 0),
        "maxChunkChars": MAX_CHUNK_CHARS,
    }
    if version.get("derivedFromSnapshot"):
        identity["derivedFromSnapshot"] = version["derivedFromSnapshot"]
    return digest(identity)


def published_ids(version: dict) -> list[str]:
    if "publishedChunkIds" in version:
        return version["publishedChunkIds"]
    document = restore_document(version["document"])
    # Preserve keys of the deployed v1 layout even when an old table exceeds today's cap.
    if document.extraction_method == LEGACY_EXTRACTION_METHOD:
        chunks = legacy_chunks(document)
    else:
        try:
            chunks = chunk_document(document)
        except ChunkingError:
            return []
    return [f"{version['documentVersion']}-{i}" for i in range(len(chunks))]


class Ledger:
    def __init__(self, state: dict | None = None):
        self.state = state if state is not None else {
            "schemaVersion": 1, "documents": {}, "robots": {}, "attempts": [],
        }
        if self.state.get("schemaVersion") != 1:
            raise AcquisitionError("Unsupported ingestion state schema")

    @classmethod
    def load(cls, path: Path):
        return cls(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else cls()

    def find(self, url: str) -> dict | None:
        normalized = canonicalize(url)
        documents = self.state["documents"]
        indexed = hasattr(documents, "find_url")
        direct = documents.get(document_id(normalized))
        if direct is None and indexed:
            direct = documents.find_url(normalized)
        visited = set()
        while direct and direct.get("canonicalMovedTo"):
            if direct["documentId"] in visited:
                raise AcquisitionError("Canonical alias loop in the ledger")
            visited.add(direct["documentId"])
            direct = self.state["documents"].get(direct["canonicalMovedTo"])
        if indexed:
            return direct
        return direct or next((
            entry for entry in self.state["documents"].values()
            if not entry.get("canonicalMovedTo") and (entry["url"] == normalized or any(
                normalized in version["document"]["aliases"] for version in entry["versions"]
            ))
        ), None)

    def fail(self, url: str, source_id: str, reason: str) -> dict:
        attempt = {"url": url, "sourceId": source_id, "checkedAt": utc_now(),
                   "status": "blocked", "reason": reason}
        self.state["attempts"].append(attempt)
        existing = self.find(url)
        if existing:
            for version in existing["versions"]:
                if version["status"] in ("active", "review-required"):
                    version["wasPublished"] = version.get("wasPublished", False) or version["status"] == "active"
                    version["status"] = "quarantined"
                    version["reviewRevoked"] = True
            existing["activeVersion"] = None
            existing["lastFailure"] = attempt
        return attempt

    def record(self, response: Response, source_id: str, publisher: str, *,
               document: Document | None = None, metadata: dict | None = None,
               url_validator=validate_url, canonical_validator=None, quality_flags=(),
               acquisition_mode: str = "sample", origin: str = "direct-publisher",
               adapter_id: str | None = None) -> dict:
        if origin not in {"direct-publisher", "source-adapter"}:
            raise AcquisitionError("Unsupported acquisition origin")
        if (origin == "source-adapter") != bool(adapter_id):
            raise AcquisitionError("Source-adapter origin requires one explicit adapter identity")
        canonical = canonicalize(response.url)
        key = document_id(canonical)
        existing = self.find(canonical) or next(
            (self.find(alias) for alias in response.aliases if self.find(alias)), None,
        )
        attempt = {
            "url": canonical, "sourceId": source_id, "checkedAt": response.checked_at,
            "httpStatus": response.status, "responseHash": response.digest,
            "origin": origin, "status": "checked",
        }
        if adapter_id:
            attempt["adapterId"] = adapter_id
        if response.headers.get("retry-after"):
            attempt["retryAfter"] = response.headers["retry-after"]
        self.state["attempts"].append(attempt)
        if response.status in (404, 410):
            if existing:
                for version in existing["versions"]:
                    version["wasPublished"] = version.get("wasPublished", False) or version["status"] == "active"
                    version["status"] = "withdrawn"
                    version["reviewRevoked"] = True
                existing["activeVersion"] = None
                existing["withdrawnAt"] = response.checked_at
            attempt["status"] = "withdrawn"
            return attempt
        if response.status == 304:
            if not existing or not existing["versions"]:
                raise AcquisitionError("304 without a stored document version")
            if existing["versions"][-1]["status"] in ("withdrawn", "quarantined", "superseded"):
                raise AcquisitionError("304 cannot restore withdrawn or quarantined guidance; complete extraction is required")
            existing["versions"][-1]["document"]["checked_at"] = response.checked_at
            attempt["status"] = "unchanged"
            return attempt
        if response.status != 200:
            return self.fail(canonical, source_id, f"HTTP {response.status}; no automatic retry")
        document = document or extract(
            response, metadata={"sourceIds": [source_id], **(metadata or {})},
            url_validator=url_validator, canonical_validator=canonical_validator,
            quality_flags=quality_flags,
        )
        validate_metadata(document.metadata)
        if (
            document.response_hash != response.digest
            or document.checked_at != response.checked_at
            or document.metadata.get("sourceUrl") != canonicalize(response.url)
        ):
            raise AcquisitionError("Extracted provenance does not match the acquired publisher response")
        key = document_id(document.url)
        if existing and existing["documentId"] == key and (
            existing.get("origin", "direct-publisher") != origin
            or existing.get("acquisitionMode", "sample") != acquisition_mode
            or existing.get("adapterId") != adapter_id
        ):
            raise AcquisitionError("Canonical documents cannot switch publisher, origin or acquisition mode")
        alias_entries = {
            entry["documentId"]: entry for entry in (
                existing, *(self.find(alias) for alias in [*response.aliases, *document.aliases]),
            ) if entry and entry["documentId"] != key
        }
        for alias_entry in alias_entries.values():
            if (
                alias_entry["publisher"] != publisher
                or alias_entry.get("origin", "direct-publisher") != origin
                or alias_entry.get("acquisitionMode", "sample") != acquisition_mode
                or alias_entry.get("adapterId") != adapter_id
            ):
                raise AcquisitionError("A canonical alias cannot switch publisher or adapter provenance")
            for old in alias_entry["versions"]:
                old["wasPublished"] = old.get("wasPublished", False) or old["status"] == "active"
                old["status"], old["reviewRevoked"] = "superseded", True
            alias_entry["activeVersion"] = None
            alias_entry["canonicalMovedTo"] = key
        entry = self.state["documents"].setdefault(key, {
            "documentId": key, "url": document.url, "sourceId": source_id, "publisher": publisher,
            "sourceIds": [source_id], "origin": origin,
            "acquisitionMode": acquisition_mode, "activeVersion": None, "versions": [],
            **({"adapterId": adapter_id} if adapter_id else {}),
        })
        if (
            entry["publisher"] != publisher
            or entry.get("acquisitionMode", "sample") != acquisition_mode
            or entry.get("origin", "direct-publisher") != origin
            or entry.get("adapterId") != adapter_id
        ):
            raise AcquisitionError("Canonical documents cannot switch publisher, origin or acquisition mode")
        entry.pop("canonicalMovedTo", None)
        entry["sourceIds"] = sorted({
            *entry.get("sourceIds", [entry["sourceId"]]), source_id,
            *document.metadata.get("sourceIds", []),
            *(sid for alias_entry in alias_entries.values()
              for sid in alias_entry.get("sourceIds", [alias_entry["sourceId"]])),
        })
        if document.metadata:
            document.metadata["sourceIds"] = entry["sourceIds"]
            document.extraction_hash = extraction_digest(document)
        entry["etag"] = response.headers.get("etag")
        entry["lastModified"] = response.headers.get("last-modified")
        identity = snapshot_hash(document)
        if entry["versions"] and entry["versions"][-1].get("snapshotHash") == identity:
            last = entry["versions"][-1]
            same_quarantine = last["status"] == "quarantined" and document.flags == last["document"]["flags"] and document.flags
            if same_quarantine or (
                not last.get("reviewRevoked") and last["status"] not in ("withdrawn", "quarantined", "superseded")
            ):
                last["document"]["checked_at"] = document.checked_at
                if document.flags:
                    last["wasPublished"] = last.get("wasPublished", False) or last["status"] == "active"
                    last["document"]["flags"] = document.flags
                    last["document"]["quality"] = "quarantined"
                    last["status"] = "quarantined"
                    last["reviewRevoked"] = True
                    entry["activeVersion"] = None
                attempt.update(
                    status="unchanged", documentId=key, documentVersion=last["documentVersion"],
                    contentHash=document.content_hash, extractionHash=document.extraction_hash,
                )
                return attempt
        documents = self.state["documents"]
        duplicate = (documents.find_duplicate(document, key) if hasattr(documents, "find_duplicate") else next((
            other["documentId"]
            for other in self.state["documents"].values()
            if other["documentId"] != key and other["versions"]
            and urlsplit(other["url"]).hostname == urlsplit(document.url).hostname
            and other["versions"][-1]["document"]["content_hash"] == document.content_hash
            and all(other["versions"][-1]["document"].get("metadata", {}).get(field) == document.metadata.get(field)
                    for field in ("language", "documentType", "legal"))
            and other["versions"][-1]["status"] not in ("withdrawn", "quarantined", "duplicate", "superseded")
        ), None)) if not document.flags else None
        for old in entry["versions"]:
            if old["status"] in ("active", "review-required"):
                old["wasPublished"] = old.get("wasPublished", False) or old["status"] == "active"
                old["status"] = "superseded"
        entry["activeVersion"] = None
        generation = len(entry["versions"]) + 1
        version = {
            "documentVersion": f"{key}-{identity[:24]}-{generation}",
            "fetchedAt": response.checked_at,
            "status": "duplicate" if duplicate else document.quality,
            "duplicateOf": duplicate, "snapshotHash": identity, "reviewGeneration": generation,
            "document": asdict(document),
        }
        version["reviewHash"] = review_identity(entry, version)
        entry["versions"].append(version)
        attempt.update(
            status=version["status"], contentHash=document.content_hash, extractionHash=document.extraction_hash,
            documentId=key, documentVersion=version["documentVersion"],
        )
        return attempt

    def review_candidates(self) -> list[dict]:
        return [{
            "documentId": entry["documentId"], "url": entry["url"],
            "sourceIds": entry.get("sourceIds", [entry["sourceId"]]),
            "documentVersion": version["documentVersion"],
            "contentHash": version["document"]["content_hash"],
            "extractionHash": version["document"].get("extraction_hash"),
            "reviewHash": review_identity(entry, version),
            "status": version["status"], "flags": version["document"]["flags"],
            **({"origin": entry["origin"]} if entry.get("origin") != "direct-publisher" else {}),
            **({"adapterId": entry["adapterId"]} if entry.get("adapterId") else {}),
        } for entry in self.state["documents"].values() for version in entry["versions"][-1:]]

    def acknowledge(self, plan: dict) -> None:
        activated = {chunk["documentVersion"] for chunk in plan["uploads"]}
        for entry in self.state["documents"].values():
            for version in entry["versions"]:
                if version["documentVersion"] in activated:
                    version["status"], version["wasPublished"] = "active", True
                    version["publishedChunkIds"] = [
                        chunk["id"] for chunk in plan["uploads"]
                        if chunk["documentVersion"] == version["documentVersion"]
                    ]
                    version["publishedReviewManifestHash"] = plan.get("reviewManifestHash")
                    entry["activeVersion"] = version["documentVersion"]

    def acquire(self, entries: list[tuple[str, str]], catalog: dict, output: Path, fetcher=None) -> dict:
        fetcher = fetcher or Fetcher()
        if fetcher.controller is not None:
            raise AcquisitionError("Manual samples cannot borrow a full-programme request controller")
        historical_requests = sum("httpStatus" in a for a in self.state["attempts"])
        historical_robots = len(self.state["robots"])
        budget = self.state.setdefault("sampleBudget", {
            "requests": historical_requests + historical_robots,
            "documentRequests": historical_requests, "robotsRequests": historical_robots,
            "chargedBytes": historical_requests * 4_000_001 + historical_robots * 512_001,
            "responseBytes": 0, "hosts": {},
        })
        envelope = {"budget": budget, "events": self.state.setdefault("sampleRequestEvents", [])}
        ledger = self
        with JsonManifestStore(output / "state.json") as checkpoint:
            class SampleCheckpoint:
                def save(self, _state):
                    checkpoint.save(ledger.state)

                def pause_requested(self):
                    return False

            fetcher.controller = RequestController(
                envelope, SampleCheckpoint(), ProgrammeLimits(total_requests=100, total_bytes=128_000_000),
                max_document_requests=25, batch_requests=100, run_seconds=3600, sleep=fetcher.sleep,
            )
            try:
                result = self._acquire_entries(entries, catalog, output, fetcher)
                checkpoint.save(self.state)
                return result
            finally:
                fetcher.controller = None

    def _acquire_entries(self, entries: list[tuple[str, str]], catalog: dict, output: Path, fetcher: Fetcher) -> dict:
        sources = {s["id"]: s for s in catalog["sources"]}
        seen = set()
        results = []
        for source_id, url in entries:
            normalized = canonicalize(url)
            if normalized in seen:
                continue
            seen.add(normalized)
            source = sources.get(source_id)
            if source is None or urlsplit(source["url"]).hostname != urlsplit(normalized).hostname:
                raise AcquisitionError("Acquisition source reference must match its publisher host")
            try:
                validate_url(normalized)
                if source["status"] in ("pending", "blocked"):
                    raise AcquisitionError("Source approval/acquisition is on hold")
                previous = self.find(normalized) or {}
                response = fetcher.fetch(
                    normalized, etag=previous.get("etag"), last_modified=previous.get("lastModified"),
                )
                if response.status == 200:
                    (output / (document_id(response.url) + ".html")).write_bytes(response.body)
                result = self.record(
                    response, source_id, source["publisher"], metadata={"topics": sorted(source["topics"])},
                    canonical_validator=lambda target, origin=response.url: (
                        fetcher.validate_canonical(target, origin=origin)
                    ),
                )
            except AcquisitionError as exc:
                result = self.fail(normalized, source_id, str(exc))
            results.append(result)
            save_json(output / "state.json", self.state)
        self.state["robots"].update(fetcher.robots_observations)
        save_json(output / "state.json", self.state)
        return {"requests": fetcher.requests, "results": results}


def build_publish_plan(ledger: Ledger, catalog: dict, review: dict | None = None, *,
                       programme_policy=None) -> dict:
    """A review file authorizes exact direct-source content hashes, not whole hosts."""
    sources = {s["id"]: s for s in catalog["sources"]}
    approvals = {}
    if review is not None:
        if review.get("publisherPermissionConfirmed") is not True or not review.get("reviewer"):
            raise AcquisitionError("Publisher permission and accountable human review are required")
        from .catalog import _date
        _date(review.get("reviewedAt"), nullable=False)
        for approval in review.get("documents", []):
            key = (approval["documentId"], approval["contentHash"])
            if key in approvals:
                raise AcquisitionError("Duplicate or ambiguous document approvals")
            approvals[key] = approval
    uploads, deletes, withheld = [], [], []
    for entry in ledger.state["documents"].values():
        source = sources.get(entry["sourceId"])
        origin = entry.get("origin", "direct-publisher")
        if not source or origin not in {"direct-publisher", "source-adapter"}:
            raise AcquisitionError("Only registered publisher/source-adapter candidates can be reviewed")
        gate_reason = None
        if origin == "source-adapter":
            from .source_adapters import validate_source_adapter_entry
            validate_source_adapter_entry(entry, source)
        elif entry.get("acquisitionMode") == "full-programme":
            if programme_policy is None:
                raise AcquisitionError("Full-programme candidates require their explicit programme and rights policy")
            try:
                programme_policy.validate_url(entry["url"])
            except AcquisitionError as exc:
                gate_reason = str(exc)
        else:
            try:
                validate_url(entry["url"])
            except AcquisitionError:
                publisher = PUBLISHERS.get(urlsplit(canonicalize(entry["url"])).hostname)
                if publisher is None or not publisher.hold:
                    raise
                gate_reason = publisher.hold
        gate_reason = gate_reason or PUBLICATION_HOLDS.get(urlsplit(entry["url"]).hostname)
        if origin == "direct-publisher" and urlsplit(entry["url"]).hostname != urlsplit(source["url"]).hostname:
            raise AcquisitionError("Publisher provenance mismatch")
        if entry.get("publisher") != source["publisher"]:
            raise AcquisitionError("Publisher attribution mismatch")
        for source_id in entry.get("sourceIds", [entry["sourceId"]]):
            if source_id not in sources or (
                origin == "direct-publisher"
                and urlsplit(sources[source_id]["url"]).hostname != urlsplit(entry["url"]).hostname
            ) or (
                origin == "source-adapter" and source_id != entry["sourceId"]
            ):
                raise AcquisitionError("Canonical topic attribution crosses publisher boundaries")
        for version in entry["versions"]:
            doc = restore_document(version["document"])
            metadata = validate_metadata(doc.metadata)
            rendered = "\n".join(s.heading + "\n" + s.text for s in doc.sections)
            if (
                doc.url != entry["url"]
                or document_id(doc.url) != entry["documentId"]
                or hashlib.sha256(rendered.encode("utf-8")).hexdigest() != doc.content_hash
                or doc.extraction_method not in EXTRACTION_METHODS
            ):
                raise AcquisitionError("Document integrity/provenance check failed")
            legacy = doc.extraction_method == LEGACY_EXTRACTION_METHOD and not metadata and not doc.extraction_hash
            if legacy:
                if version["documentVersion"] != f"{entry['documentId']}-{doc.content_hash[:20]}":
                    raise AcquisitionError("Legacy document version integrity check failed")
            elif (
                doc.extraction_hash != extraction_digest(doc)
                or metadata.get("canonicalUrl") != doc.url
                or urlsplit(metadata["sourceUrl"]).hostname != urlsplit(doc.url).hostname
                or version.get("snapshotHash") != snapshot_hash(doc)
                or version["documentVersion"] != (
                    f"{entry['documentId']}-{snapshot_hash(doc)[:24]}-{version.get('reviewGeneration')}"
                )
                or version.get("reviewHash") != review_identity(entry, version)
            ):
                raise AcquisitionError("Extraction/metadata/review integrity check failed")
            was_published = version.get("wasPublished", False) or version["status"] == "active"
            if version["status"] in ("superseded", "withdrawn", "quarantined", "duplicate"):
                if was_published:
                    deletes.extend(published_ids(version))
                withheld.append({"url": doc.url, "reason": version["status"]})
                continue
            if (
                source["status"] in ("blocked", "pending")
                or doc.flags or doc.quality == "quarantined" or gate_reason
                or version.get("reviewRevoked")
            ):
                if was_published:
                    deletes.extend(published_ids(version))
                withheld.append({"url": doc.url, "reason": gate_reason or "Source or quality gate requires withdrawal"})
                continue
            if origin == "direct-publisher" and entry.get("acquisitionMode") == "full-programme":
                rights = metadata.get("rights") or {}
                if rights != programme_policy.metadata(doc.url)["rights"]:
                    raise AcquisitionError("Candidate rights metadata does not match its acquisition review")
                expected_ids, expected_topics = programme_policy.tags(doc.url)
                if not set(expected_ids) <= set(metadata.get("sourceIds", [])) or not set(expected_topics) <= set(metadata.get("topics", [])):
                    raise AcquisitionError("Candidate canonical source/topic provenance is incomplete")
                if programme_policy.extraction_flags(doc.url):
                    if was_published:
                        deletes.extend(published_ids(version))
                    withheld.append({"url": doc.url, "reason": "Publisher extraction/freshness hold"})
                    continue
            try:
                chunks = chunk_document(doc)
            except ChunkingError as exc:
                withheld.append({
                    "url": doc.url, "reason": exc.reason, "retainedPublishedSnapshot": was_published,
                    "action": "Re-extract structured content and review exact new hashes; no table was truncated",
                })
                continue
            identifiers = [f"{version['documentVersion']}-{i}" for i in range(len(chunks))]
            approval = approvals.get((entry["documentId"], doc.content_hash))
            if not approval or (not legacy and (
                approval.get("extractionHash") != doc.extraction_hash
                or approval.get("reviewHash") != review_identity(entry, version)
            )):
                withheld.append({"url": doc.url, "reason": "Exact-hash human/source review missing or quality gate"})
                continue
            source_ids = metadata.get("sourceIds") or entry.get("sourceIds", [source["id"]])
            journeys = [j["id"] for j in catalog["journeys"] if set(source_ids) & set(j["sourceIds"])]
            topics = sorted({t for sid in source_ids for t in sources[sid]["topics"]} | set(metadata.get("topics", [])))
            for i, chunk in enumerate(chunks):
                uploads.append({
                    "id": identifiers[i], "documentId": entry["documentId"],
                    "sourceId": source["id"], "title": doc.title, "publisher": source["publisher"],
                    "url": doc.url, "content": chunk["content"], "section": chunk["section"],
                    "checkedAt": doc.checked_at, "publisherUpdatedAt": doc.publisher_updated_at,
                    "status": "active", "topics": topics, "journeyIds": journeys,
                    "documentVersion": version["documentVersion"], "contentHash": doc.content_hash,
                    **search_metadata(doc, entry, version),
                    "sectionLocators": chunk["locators"],
                    "containsExceptions": chunk["containsExceptions"],
                    "chunkPart": chunk.get("partIndex", 1), "chunkParts": chunk.get("partCount", 1),
                    "reviewHash": review_identity(entry, version) if not legacy else None,
                })
            replacement = version.get("derivedFromSnapshot") or {}
            if replacement.get("publishedChunkIds"):
                old_prefix = replacement.get("documentVersion", "") + "-"
                keys = replacement["publishedChunkIds"]
                if (
                    replacement.get("documentId") != entry["documentId"]
                    or replacement.get("responseHash") != doc.response_hash
                    or not old_prefix.startswith(entry["documentId"] + "-")
                    or not isinstance(keys, list)
                    or any(not isinstance(key, str) or not key.startswith(old_prefix)
                           or not key[len(old_prefix):].isdigit() for key in keys)
                ):
                    raise AcquisitionError("Archived replacement keys do not match the reviewed source snapshot")
                # Re-extraction alone never withdraws the live snapshot. Retire old keys
                # only when its exact replacement has passed the separate review gate.
                deletes.extend(key for key in keys if key not in identifiers)
    return {
        "uploads": uploads, "deleteIds": sorted(set(deletes)), "withheld": withheld,
        "reviewManifestHash": digest(review) if review is not None else None,
        "maxChunkChars": MAX_CHUNK_CHARS,
    }


def reextract_snapshot(ledger_path: Path, key: str, response_path: Path, catalog: dict,
                       output: Path, *, snapshot_version: str | None = None) -> dict:
    """Re-extract archived, hash-verified HTML into separate candidates without refreshing it."""
    source_bytes = ledger_path.read_bytes()
    original = Ledger(json.loads(source_bytes.decode("utf-8")))
    entry = original.state["documents"].get(key)
    if entry is None or not entry["versions"]:
        raise AcquisitionError("The requested archived document is not present")
    selected = snapshot_version or entry.get("activeVersion") or entry["versions"][-1]["documentVersion"]
    version = next((v for v in entry["versions"] if v["documentVersion"] == selected), None)
    if version is None:
        raise AcquisitionError("The exact archived document version is not present")
    archived = restore_document(version["document"])
    if archived.extraction_method not in (LEGACY_EXTRACTION_METHOD, EXTRACTION_METHOD):
        raise AcquisitionError("Archived re-extraction only supports the existing direct HTML adapters")
    # Reuse the publication integrity/provenance checks, not its approvals or mutations.
    check = Ledger()
    check.state["documents"][key] = entry
    build_publish_plan(check, catalog)
    if response_path.stat().st_size > 8_000_000:
        raise AcquisitionError("Archived HTML exceeds the supported response-size bound")
    body = response_path.read_bytes()
    if hashlib.sha256(body).hexdigest() != archived.response_hash:
        raise AcquisitionError("Archived HTML bytes do not match the exact snapshot response hash")
    source = next(s for s in catalog["sources"] if s["id"] == entry["sourceId"])
    destination = guarded_output(output / "reextractions" / (key[:8] + "-" + archived.response_hash[:12]))
    if (destination / "state.json").resolve() == ledger_path.resolve():
        raise AcquisitionError("Re-extraction must never overwrite its source ledger")
    response = Response(
        archived.metadata.get("sourceUrl") or archived.url, 200, {"content-type": "text/html"},
        body, archived.checked_at, aliases=list(archived.aliases),
    )
    with JsonManifestStore(destination / "state.json") as store:
        identity = {"documentId": key, "responseHash": archived.response_hash}
        identity_path = destination / "identity.json"
        if identity_path.exists() and json.loads(identity_path.read_text(encoding="utf-8")) != identity:
            raise AcquisitionError("Compact re-extraction directory identity collision; select another output")
        save_json(identity_path, identity)
        stored = store.load()
        candidate_ledger = Ledger(stored) if stored is not None else Ledger()
        if any(
            item.get("activeVersion") or any(v.get("wasPublished") for v in item["versions"])
            for item in candidate_ledger.state["documents"].values()
        ):
            raise AcquisitionError("Re-extraction output contains published versions; select a fresh candidate output")
        LocalResponseStore(destination / "responses").put(body)
        candidate_ledger.record(
            response, source["id"], source["publisher"],
            metadata={"topics": sorted(source["topics"])},
        )
        current = candidate_ledger.find(archived.url)["versions"][-1]
        current["fetchedAt"] = version["fetchedAt"]
        current["reextractedAt"] = utc_now()
        current["derivedFromSnapshot"] = {
            "documentId": key, "documentVersion": selected, "responseHash": archived.response_hash,
            "ledgerHash": hashlib.sha256(source_bytes).hexdigest(),
            "publishedChunkIds": published_ids(version) if version.get("wasPublished") or version["status"] == "active" else [],
        }
        current["reviewHash"] = review_identity(candidate_ledger.find(archived.url), current)
        document = restore_document(current["document"])
        try:
            chunks = chunk_document(document)
        except ChunkingError:
            chunks = []
        tables = [block for section in document.sections for block in section.blocks if block["kind"] == "table"]
        report = {
            "mode": "archived-reextraction", "networkRequests": 0, "publicationEnabled": False,
            "sourceDocumentVersion": selected, "sourceResponseHash": archived.response_hash,
            "sourceCheckedAt": archived.checked_at, "sourceFetchedAt": version["fetchedAt"],
            "status": current["status"], "flags": document.flags,
            "chunks": len(chunks), "maxChunkChars": max((len(chunk["content"]) for chunk in chunks), default=0),
            "tableRows": sum(len(table["rows"]) for table in tables),
            "tableReferenceIds": sorted({ref for table in tables for ref in table.get("references", {})}),
            "replacesPublishedChunkIds": current["derivedFromSnapshot"]["publishedChunkIds"],
            "replacementPolicy": "Retire these keys only with the separately approved exact replacement plan",
            "output": str(destination.relative_to(PROJECT_ROOT)),
        }
        save_json(destination / "chunks.json", {"documentId": key, "chunks": chunks})
        save_json(destination / "review-required.json", {
            "publisherPermissionConfirmed": False,
            "notice": "Archived re-extraction is a new candidate, not a new fetch or publication approval.",
            "documents": candidate_ledger.review_candidates(),
        })
        save_json(destination / "extraction-report.json", report)
        store.save(candidate_ledger.state)
        return report
