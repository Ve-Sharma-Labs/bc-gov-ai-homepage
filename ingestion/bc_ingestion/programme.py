"""Resumable candidate acquisition using the existing Fetcher, extractor and Ledger."""

from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from .fetch import Fetcher, TransientAcquisitionError, utc_now
from .manifest import AcquisitionPaused, CheckpointError, ManifestStore, ProgrammeLimits, RequestController, ResponseStore
from .metadata import digest, extraction_digest
from .pipeline import Ledger, document_id
from .policy import AcquisitionError, canonicalize
from .programme_policy import ProgrammeGate, ProgrammePolicy
from .source_adapters import adapt_programme_html


SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
TERMINAL_STATES = {"blocked", "unsupported", "candidate", "quarantined", "duplicate", "withdrawn", "sitemap"}


def sitemap_links(response) -> list[dict]:
    mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in ("application/xml", "text/xml") or response.status != 200:
        raise AcquisitionError("Sitemap discovery requires a successful XML response, not a rendered/offline page")
    if b"<!DOCTYPE" in response.body.upper() or b"<!ENTITY" in response.body.upper():
        raise AcquisitionError("Sitemap DTDs/entities are forbidden")
    try:
        root = ET.fromstring(response.body)
    except ET.ParseError as exc:
        raise AcquisitionError("Malformed sitemap XML") from exc
    if root.tag not in (f"{{{SITEMAP_NAMESPACE}}}urlset", f"{{{SITEMAP_NAMESPACE}}}sitemapindex"):
        raise AcquisitionError("Only standard discovery sitemaps are supported; this is not a legal/XML content extractor")
    index = root.tag.endswith("sitemapindex")
    record_name = "sitemap" if index else "url"
    result = []
    for item in root:
        if item.tag != f"{{{SITEMAP_NAMESPACE}}}{record_name}":
            raise AcquisitionError("Unsupported sitemap record structure")
        locations = item.findall(f"{{{SITEMAP_NAMESPACE}}}loc")
        if len(locations) != 1 or not locations[0].text:
            raise AcquisitionError("Sitemap record must have exactly one URL")
        result.append({"url": locations[0].text.strip(), "kind": "sitemap" if index else "document"})
    return result


def retry_at(value: str | None, now: float, attempt: int) -> float:
    backoff = now + min(3600, 2 ** min(attempt, 10))
    if value is None:
        return backoff
    if value.isascii() and value.isdecimal() and len(value) <= 9:
        return max(backoff, now + int(value))
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            raise ValueError("No offset")
        return max(backoff, parsed.timestamp())
    except (ValueError, TypeError, OverflowError) as exc:
        raise AcquisitionError("Invalid Retry-After; a publisher review is required before retrying") from exc


class ProgrammeRun:
    def __init__(self, policy: ProgrammePolicy, store: ManifestStore, *,
                 limits: ProgrammeLimits | None = None, response_store: ResponseStore | None = None,
                 seeds: list[str] | None = None, clock=time.time, sleep=time.sleep, request=None):
        self.policy, self.store, self.response_store = policy, store, response_store
        if getattr(store, "requires_response_store", False) and response_store is None:
            raise CheckpointError("Remote acquisition requires a durable candidate response store")
        self.clock, self.sleep, self.request = clock, sleep, request
        self.state = store.load()
        catalog_hash = digest(policy.catalog)
        if self.state is None:
            self.limits = limits or ProgrammeLimits()
            self.state = {
                "schemaVersion": 1, "mode": "full-programme", "revision": 0,
                "programmeHash": policy.programme_hash, "catalogHash": catalog_hash,
                "rightsReviewHash": None, "rightsReview": None,
                "createdAt": utc_now(), "updatedAt": utc_now(),
                "status": "review-only", "pauseReason": None,
                "limits": self.limits.to_dict(), "candidates": {}, "urlAliases": {},
                "ledger": Ledger().state, "events": [], "reviewPlans": [],
                "budget": {
                    "requests": 0, "documentRequests": 0, "robotsRequests": 0,
                    "chargedBytes": 0, "responseBytes": 0, "hosts": {},
                },
            }
            initial = [{"url": url, "kind": "document"} for url in (
                seeds if seeds is not None else [s["seedUrl"] for s in policy.programme["sources"]]
            )]
            if seeds is None:
                initial.extend({"url": url, "kind": "sitemap"}
                               for o in policy.programme["accessObservations"] for url in o.get("sitemaps", []))
            # Never lose unqueued seeds when an intentionally small frontier cap is used.
            self.state["seedLinks"] = initial
            self.state["seedCursor"] = 0
            self._save()
        else:
            if (
                self.state.get("schemaVersion") != 1 or self.state.get("mode") != "full-programme"
                or self.state.get("programmeHash") != policy.programme_hash
                or self.state.get("catalogHash") != catalog_hash
            ):
                raise AcquisitionError("Manifest programme/catalogue identity changed; do not reset or reuse its budgets")
            self.limits = ProgrammeLimits(**self.state["limits"])
            if limits is not None and limits != self.limits:
                raise AcquisitionError("Resume cannot enlarge or reset the durable run's request/byte/retry limits")
            if seeds is not None and seeds != [
                item["url"] for item in self.state["seedLinks"] if item["kind"] == "document"
            ]:
                raise AcquisitionError("Resume cannot replace the run's original discovery seeds")
            budget = self.state["budget"]
            if (
                any(type(budget.get(key)) is not int or budget[key] < 0 for key in (
                    "requests", "documentRequests", "robotsRequests", "chargedBytes", "responseBytes",
                ))
                or budget["requests"] != budget["documentRequests"] + budget["robotsRequests"]
                or budget["requests"] > self.limits.total_requests
                or budget["chargedBytes"] > self.limits.total_bytes
                or budget["responseBytes"] > budget["chargedBytes"]
            ):
                raise AcquisitionError("Invalid or inconsistent durable request/byte accounting")
        if self.state["rightsReviewHash"] and policy.rights_hash and self.state["rightsReviewHash"] != policy.rights_hash:
            raise AcquisitionError("Resume cannot replace the exact rights review bound to this run")
        self.ledger = Ledger(self.state["ledger"])

    def _save(self):
        self.state["updatedAt"] = utc_now()
        self.store.save(self.state)

    def _add(self, url: str, kind: str, parent: dict | None = None) -> dict:
        reason = None
        try:
            normalized = canonicalize(url)
            normalized = self.state["urlAliases"].get(normalized, normalized)
            key = document_id(normalized)
            source_ids, topics = self.policy.tags(normalized, kind=kind)
            self.policy.validate_url(normalized, kind=kind)
        except AcquisitionError as exc:
            if "normalized" not in locals():
                normalized, key = None, "invalid-" + digest(url)[:32]
                source_ids, topics = [], []
            reason = str(exc)
        existing = self.state["candidates"].get(key)
        if existing:
            existing["sourceIds"] = sorted(set(existing["sourceIds"]) | set(source_ids))
            existing["topics"] = sorted(set(existing["topics"]) | set(topics))
            if parent:
                existing["discoveredFrom"] = sorted(set([*existing["discoveredFrom"], parent["id"]]))
            return existing
        if len(self.state["candidates"]) >= self.limits.max_candidates:
            raise AcquisitionPaused("candidate-frontier-limit")
        candidate = {
            "id": key, "url": normalized, "canonicalUrl": normalized, "kind": kind,
            "sourceIds": source_ids, "topics": topics, "attempts": 0,
            "state": "unsupported" if reason and reason.startswith("unsupported-") else ("blocked" if reason else "pending"),
            "reason": reason, "discoveredFrom": [parent["id"]] if parent else [],
            "links": [], "discoveryCursor": 0, "discoveryComplete": False,
        }
        self.state["candidates"][key] = candidate
        return self.state["candidates"][key]

    def _seed(self):
        while self.state["seedCursor"] < len(self.state["seedLinks"]):
            item = self.state["seedLinks"][self.state["seedCursor"]]
            self._add(item["url"], item["kind"])
            self.state["seedCursor"] += 1
            if self.state["seedCursor"] % 50 == 0:
                self._save()
        self._save()

    def _discover(self, candidate: dict):
        while candidate["discoveryCursor"] < len(candidate["links"]):
            item = candidate["links"][candidate["discoveryCursor"]]
            self._add(item["url"], item.get("kind", "document"), candidate)
            candidate["discoveryCursor"] += 1
            if candidate["discoveryCursor"] % 50 == 0:
                self._save()
                if self.store.pause_requested():
                    raise AcquisitionPaused("operator-pause")
                if getattr(self, "deadline", float("inf")) <= self.clock():
                    raise AcquisitionPaused("invocation-time-checkpoint")
        candidate["discoveryComplete"] = True
        self._save()

    def _bind_rights(self):
        self.policy.assert_current_rights()
        if self.state["rightsReviewHash"] is None:
            self.state["rightsReviewHash"] = self.policy.rights_hash
            if getattr(self.store, "rights_reference", None) is not None:
                self.state["rightsReview"] = None
                self.state["rightsReviewReference"] = self.store.rights_reference
            else:
                self.state["rightsReview"] = self.policy.rights_review
            self.state["events"].append({"type": "rights-bound", "rightsReviewHash": self.policy.rights_hash})
        elif self.state["rightsReviewHash"] != self.policy.rights_hash:
            raise AcquisitionError("Acquire/resume requires the run's exact reviewed rights file")
        else:
            self._save()
            return
        for candidate in self.state["candidates"].values():
            if candidate["state"] == "blocked" and (candidate["reason"] or "").startswith((
                "rights-",
                "source-access-hold:",
            )):
                try:
                    self.policy.validate_url(candidate["url"], kind=candidate["kind"])
                    candidate["state"], candidate["reason"] = "pending", None
                except AcquisitionError as exc:
                    candidate["reason"] = str(exc)
        self._save()

    def _recover(self):
        reservation = self.state["budget"].pop("inFlight", None)
        if reservation:
            self.state["events"].append({
                "type": "interrupted-request", **reservation,
                "reason": "Reserved bytes and request count remain charged; delivery is unknown",
            })
        inflight = self.store.inflight() if hasattr(self.store, "inflight") else self.state["candidates"].values()
        for candidate in inflight:
            if candidate["state"] == "in-flight":
                candidate["reason"] = "interrupted-request"
                candidate["state"] = "retry-wait" if candidate["attempts"] <= self.limits.max_retries else "blocked"
                candidate["retryAt"] = max(
                    self.clock(), candidate.get("attemptStartedAt", self.clock()) + 2 ** candidate["attempts"],
                )
        self._save()

    def _canonical_candidate(self, candidate: dict, document, response) -> dict:
        target = document.url
        key = document_id(target)
        source_ids, topics = self.policy.tags(target)
        aliases = sorted(set([candidate["url"], response.url, *response.aliases, *document.aliases]) - {target})
        existing = self.state["candidates"].get(key)
        if existing and existing is not candidate:
            source_ids = sorted(set(source_ids) | set(existing["sourceIds"]))
            topics = sorted(set(topics) | set(existing["topics"]))
            candidate["discoveredFrom"] = sorted(set(candidate["discoveredFrom"]) | set(existing["discoveredFrom"]))
            candidate["attempts"] += existing["attempts"]
            del self.state["candidates"][key]
        old_key = candidate["id"]
        self.state["candidates"].pop(old_key, None)
        candidate.update(id=key, url=target, canonicalUrl=target)
        candidate["sourceIds"] = sorted(set(candidate["sourceIds"]) | set(source_ids))
        candidate["topics"] = sorted(set(candidate["topics"]) | set(topics))
        self.state["candidates"][key] = candidate
        candidate = self.state["candidates"][key]
        for alias in aliases:
            self.state["urlAliases"][alias] = target
        if aliases:
            alias_map = self.state["urlAliases"]
            previous = alias_map.reverse_values(aliases) if hasattr(alias_map, "reverse_values") else (
                alias for alias, canonical in list(alias_map.items()) if canonical in aliases
            )
            for alias in list(previous):
                alias_map[alias] = target
        document.metadata["sourceIds"] = candidate["sourceIds"]
        document.metadata["topics"] = candidate["topics"]
        document.aliases = sorted(set(document.aliases) | set(aliases))
        document.extraction_hash = extraction_digest(document)
        return candidate

    def _retry(self, candidate: dict, controller: RequestController, reason: str, after=None):
        candidate["reason"] = reason
        if candidate["attempts"] > self.limits.max_retries:
            candidate["state"], candidate["reason"] = "blocked", "retry-budget-exhausted: " + reason
        else:
            candidate["state"], candidate["retryAt"] = "retry-wait", retry_at(after, self.clock(), candidate["attempts"])
            controller.defer_host(urlsplit(candidate["url"]).hostname, candidate["retryAt"])

    def _acquire(self, candidate: dict, fetcher: Fetcher, controller: RequestController):
        url = candidate["url"]
        request_start = self.state["budget"]["requests"]
        candidate.update(state="in-flight", reason=None, lastAttemptAt=utc_now(), attemptStartedAt=self.clock())
        candidate["attempts"] += 1
        controller.candidate_id = candidate["id"]
        self._save()
        source = self.policy.matches(url)[0] if candidate["kind"] == "document" else None
        checkpoint_failed = False
        try:
            previous = self.ledger.find(url) or {}
            response = fetcher.fetch(
                url, etag=previous.get("etag"), last_modified=previous.get("lastModified"),
                kind=candidate["kind"],
            )
            candidate.update(checkedAt=response.checked_at, httpStatus=response.status, responseHash=response.digest)
            if self.response_store is not None and response.status == 200:
                candidate["responseObject"] = self.response_store.put(response.body)
            if response.status in RETRYABLE_STATUS:
                if source:
                    self.ledger.fail(url, source["id"], f"HTTP {response.status}; retry review pending")
                self._retry(candidate, controller, f"HTTP {response.status}", response.headers.get("retry-after"))
                return
            if candidate["kind"] == "sitemap":
                candidate["links"] = sitemap_links(response)
                candidate["state"] = "sitemap"
            else:
                document = None
                if response.status == 200:
                    document = adapt_programme_html(
                        response, url_validator=self.policy.validate_url,
                        canonical_validator=lambda target: fetcher.validate_canonical(target, origin=response.url),
                        metadata=self.policy.metadata(response.url),
                        quality_flags=self.policy.extraction_flags(response.url),
                    )
                    candidate = self._canonical_candidate(candidate, document, response)
                    source = self.policy.matches(document.url)[0]
                result = self.ledger.record(
                    response, source["id"], self.policy.catalog[source["id"]]["publisher"],
                    document=document, acquisition_mode="full-programme",
                )
                entry = self.ledger.find(candidate["url"])
                latest = entry["versions"][-1] if entry and entry["versions"] else None
                status = latest["status"] if latest else result["status"]
                candidate["state"] = "candidate" if status in ("review-required", "active") else status
                candidate["reason"] = result.get("reason")
                if latest:
                    candidate.update(documentId=entry["documentId"], documentVersion=latest["documentVersion"])
                    candidate["reason"] = "; ".join(latest["document"]["flags"]) or candidate["reason"]
                    unsafe = {
                        "maintenance-or-access-page", "dynamic-or-incomplete", "footer-only",
                        "missing-main-region", "prompt-like-content", "unapproved-canonical",
                    }
                    candidate["links"] = [] if (
                        response.status in (404, 410) or unsafe & set(latest["document"]["flags"])
                    ) else latest["document"]["links"]
            candidate["discoveryCursor"] = 0
            candidate["discoveryComplete"] = False
        except CheckpointError:
            checkpoint_failed = True
            raise
        except AcquisitionPaused:
            # No new request means this checkpoint is not an acquisition retry.
            if self.state["budget"]["requests"] == request_start:
                candidate["attempts"] -= 1
            candidate["state"] = "pending"
            raise
        except TransientAcquisitionError as exc:
            if source:
                self.ledger.fail(url, source["id"], str(exc))
            self._retry(candidate, controller, str(exc))
        except AcquisitionError as exc:
            if source:
                self.ledger.fail(url, source["id"], str(exc))
            candidate["state"] = "unsupported" if str(exc).startswith("unsupported-format") else "blocked"
            candidate["reason"] = str(exc)
        finally:
            self.ledger.state["robots"].update(fetcher.robots_observations)
            if not checkpoint_failed:
                self._save()

    def run(self, *, acquire=False, resume=False, batch_requests=25, run_seconds=120) -> dict:
        if resume and not acquire:
            raise AcquisitionError("Resume must explicitly invoke acquisition")
        if acquire and self.state["status"] != "review-only" and not resume:
            raise AcquisitionError("Existing runs require --resume; invocation does not reset their budgets")
        checkpoint_failed = False
        try:
            self._seed()
            if not acquire:
                return self.report()
            self._bind_rights()
            if resume:
                self.store.clear_pause()
                self._recover()
            controller = RequestController(
                self.state, self.store, self.limits, batch_requests=batch_requests,
                run_seconds=run_seconds, clock=self.clock, sleep=self.sleep,
                rights_check=self.policy.assert_current_rights,
            )
            self.deadline = controller.deadline
            self.state.update(status="running", pauseReason=None)
            options = {"request": self.request} if self.request is not None else {}
            fetcher = Fetcher(
                max_pages=None, timeout=self.limits.timeout, max_bytes=self.limits.response_bytes,
                request_controller=controller, url_validator=self.policy.validate_url, **options,
            )
            while True:
                if self.store.pause_requested():
                    raise AcquisitionPaused("operator-pause")
                if self.clock() >= controller.deadline:
                    raise AcquisitionPaused("invocation-time-checkpoint")
                indexed = hasattr(self.store, "next_work")
                incomplete = self.store.next_work("discovery") if indexed else next((
                    c for c in self.state["candidates"].values()
                    if c["state"] in TERMINAL_STATES and not c["discoveryComplete"]
                ), None)
                if incomplete:
                    self._discover(incomplete)
                    continue
                candidate = (self.store.next_work("pending") or self.store.next_work("retry", self.clock())) if indexed else next((c for c in self.state["candidates"].values() if (
                    c["state"] == "pending" or (c["state"] == "retry-wait" and c["retryAt"] <= self.clock())
                )), None)
                if candidate is None:
                    retry_waiting = self.store.has_retries() if indexed else any(
                        c["state"] == "retry-wait" for c in self.state["candidates"].values()
                    )
                    if retry_waiting:
                        raise AcquisitionPaused("retry-after")
                    self.state["status"] = "frontier-exhausted"
                    break
                self._acquire(candidate, fetcher, controller)
        except CheckpointError:
            checkpoint_failed = True
            raise
        except AcquisitionPaused as exc:
            self.state.update(status="paused", pauseReason=exc.reason)
            self.state["events"].append({"type": "paused", "reason": exc.reason})
        except KeyboardInterrupt:
            self.state.update(status="paused", pauseReason="interrupted")
            self.state["events"].append({"type": "paused", "reason": "interrupted"})
        finally:
            if not checkpoint_failed:
                self._save()
        return self.report()

    def report(self) -> dict:
        if hasattr(self.store, "coverage_counts"):
            stats = self.store.coverage_counts()
            return {
                "mode": "full-programme", "status": self.state["status"], "pauseReason": self.state["pauseReason"],
                "programmeHash": self.state["programmeHash"], "catalogHash": self.state["catalogHash"],
                "coverageTargetMet": False,
                "coverageNotice": "Bounded run counts, not proof of complete coverage; held sources and unsupported formats remain gaps.",
                "canonicalCandidates": stats["canonicalCandidates"], "sitemaps": stats["sitemaps"],
                "aliases": len(self.state["urlAliases"]), "states": stats["states"], "reasons": stats["reasons"],
                "unexpandedLinks": stats["unexpandedLinks"] + len(self.state["seedLinks"]) - self.state["seedCursor"],
                "bySource": {key: stats["bySource"].get(key, {"canonicalCandidates": 0, "states": {}, "reasons": {}})
                             for key in self.policy.catalog},
                "byHost": {source["host"]: stats["byHost"].get(source["host"], {"urls": 0, "states": {}, "reasons": {}})
                           for source in self.policy.programme["sources"]},
                "budget": self.state["budget"], "limits": self.state["limits"],
                "rightsReviewHash": self.state["rightsReviewHash"],
                "reviewRequired": stats["states"].get("candidate", 0),
                "exactReviewedCurrentDocuments": stats["exactReviewedCurrentDocuments"],
                "publishedDocuments": stats["publishedDocuments"],
                "publicationScope": "This manifest only; the existing pilot publication ledger is separate",
            }
        candidates = list(self.state["candidates"].values())
        sources = {}
        for source_id in self.policy.catalog:
            selected = [c for c in candidates if source_id in c["sourceIds"] and c["kind"] == "document"]
            sources[source_id] = {
                "canonicalCandidates": len(selected),
                "states": dict(Counter(c["state"] for c in selected)),
                "reasons": dict(Counter(c["reason"] for c in selected if c["reason"])),
            }
        published = sum(bool(entry["activeVersion"]) for entry in self.ledger.state["documents"].values())
        approved_versions = {
            version for plan in self.state["reviewPlans"] for version in plan.get("approvedVersions", [])
        }
        reviewed_current = sum(
            bool(entry["versions"]) and entry["versions"][-1]["documentVersion"] in approved_versions
            and not entry["versions"][-1].get("reviewRevoked")
            and entry["versions"][-1]["status"] in ("active", "review-required")
            for entry in self.ledger.state["documents"].values()
        )
        hosts = {}
        for host in {s["host"] for s in self.policy.programme["sources"]}:
            selected = [c for c in candidates if c["url"] and urlsplit(c["url"]).hostname == host]
            hosts[host] = {
                "urls": len(selected), "states": dict(Counter(c["state"] for c in selected)),
                "reasons": dict(Counter(c["reason"] for c in selected if c["reason"])),
            }
        return {
            "mode": "full-programme", "status": self.state["status"], "pauseReason": self.state["pauseReason"],
            "programmeHash": self.state["programmeHash"], "catalogHash": self.state["catalogHash"],
            "coverageTargetMet": False,
            "coverageNotice": "Frontier counts are evidence of this bounded run, not proof of complete publisher coverage; held sources and unsupported formats remain gaps.",
            "canonicalCandidates": sum(c["kind"] == "document" for c in candidates),
            "sitemaps": sum(c["kind"] == "sitemap" for c in candidates),
            "aliases": len(self.state["urlAliases"]),
            "states": dict(Counter(c["state"] for c in candidates)),
            "reasons": dict(Counter(c["reason"] for c in candidates if c["reason"])),
            "unexpandedLinks": sum(len(c["links"]) - c["discoveryCursor"] for c in candidates)
                              + len(self.state["seedLinks"]) - self.state["seedCursor"],
            "bySource": sources, "byHost": hosts, "budget": self.state["budget"], "limits": self.state["limits"],
            "rightsReviewHash": self.state["rightsReviewHash"],
            "reviewRequired": len([c for c in candidates if c["state"] == "candidate"]),
            "exactReviewedCurrentDocuments": reviewed_current, "publishedDocuments": published,
            "publicationScope": "This manifest only; the existing pilot publication ledger is separate",
        }
