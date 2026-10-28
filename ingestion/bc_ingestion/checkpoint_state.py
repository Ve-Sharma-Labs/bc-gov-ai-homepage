"""Incremental Blob state: bounded journal, immutable index pages and lazy payloads."""

from copy import deepcopy
import json
import math
from urllib.parse import urlsplit

from .checkpoint_tree import ImmutableTree, LazyList, PagedList, RecordMap, StorageLimits, encoded
from .manifest import CheckpointError
from .metadata import digest


MAPS = ("candidates", "urlAliases", "artifacts", "artifactOrigins", "ledger/documents")
LISTS = ("events", "seedLinks", "reviewPlans", "ledger/attempts")
TERMINAL = {"blocked", "unsupported", "candidate", "quarantined", "duplicate", "withdrawn", "sitemap"}


class JournalIndex:
    def __init__(self, objects, limits: StorageLimits):
        self.objects, self.limits = objects, limits
        self.tree = ImmutableTree(objects, limits)
        self.root = None
        self.through = 0
        self.anchor = None
        self.sequence = 0
        self.journals = []
        self.overlay = {}
        self.pending = {}

    def get(self, key):
        if key in self.pending:
            return self.pending[key]
        if key in self.overlay:
            return self.overlay[key]
        return self.tree.get(self.root, key)

    def set(self, key, value):
        if not isinstance(key, str) or not 1 <= len(key) <= 4096:
            raise CheckpointError("checkpoint-index-key-exceeds-bound")
        if value is not None and len(encoded([key, value])) > self.limits.record_bytes:
            raise CheckpointError("checkpoint-record-exceeds-bound")
        if self.get(key) != value:
            self.pending[key] = value

    def scan(self, prefix, after=""):
        overrides = {**self.overlay, **self.pending}
        changed = iter(sorted((k, v) for k, v in overrides.items() if k.startswith(prefix) and k > after))
        current = next(changed, None)
        for key, value in self.tree.scan(self.root, prefix, after):
            while current is not None and current[0] < key:
                if current[1] is not None:
                    yield current
                current = next(changed, None)
            if current is not None and current[0] == key:
                if current[1] is not None:
                    yield current
                current = next(changed, None)
            elif key not in overrides:
                yield key, value
        while current is not None:
            if current[1] is not None:
                yield current
            current = next(changed, None)

    def restore(self, control):
        base = control["base"]
        self.root, self.through, self.anchor = base["tree"], base["through"], base["anchor"]
        self.sequence = control["sequence"]
        count, byte_count = control["journalCount"], control["journalBytes"]
        if (
            any(type(n) is not int or n < 0 for n in (self.through, self.sequence, count, byte_count))
            or self.sequence - self.through != count or count > self.limits.replay_segments
            or byte_count > self.limits.replay_bytes
        ):
            raise CheckpointError("checkpoint-replay-bound-or-sequence-invalid")
        for ref in (self.root, self.anchor):
            if ref is not None:
                self.objects.validate_reference(ref)
        current, expected, seen, actual_bytes = control["journal"], self.sequence, set(), 0
        backwards = []
        for _ in range(count):
            if current is None or current["sha256"] in seen:
                raise CheckpointError("checkpoint-journal-cycle-or-gap")
            seen.add(current["sha256"])
            actual_bytes += current["bytes"]
            if actual_bytes > self.limits.replay_bytes:
                raise CheckpointError("checkpoint-replay-byte-bound-exceeded")
            segment = json.loads(self.objects.get_reference(current, limit=self.limits.segment_bytes))
            operations = segment.get("ops")
            if (
                segment.get("storageSchemaVersion") != 2 or segment.get("sequence") != expected
                or not isinstance(operations, list) or not 1 <= len(operations) <= self.limits.segment_ops
            ):
                raise CheckpointError("checkpoint-journal-sequence-or-shape-invalid")
            keys = []
            for operation in operations:
                if not isinstance(operation, list) or len(operation) != 2:
                    raise CheckpointError("checkpoint-journal-operation-invalid")
                key, value = operation
                if not isinstance(key, str) or not 1 <= len(key) <= 4096:
                    raise CheckpointError("checkpoint-journal-key-invalid")
                if len(encoded(operation)) > self.limits.record_bytes:
                    raise CheckpointError("checkpoint-journal-record-bound-exceeded")
                keys.append(key)
            if len(keys) != len(set(keys)):
                raise CheckpointError("checkpoint-journal-duplicate-operation")
            backwards.append((current, segment))
            current, expected = segment["previous"], expected - 1
        if current != self.anchor or actual_bytes != byte_count:
            raise CheckpointError("checkpoint-journal-anchor-or-byte-count-mismatch")
        self.journals = list(reversed(backwards))
        for _, segment in self.journals:
            self.overlay.update(segment["ops"])

    def prepare(self):
        if len(self.pending) > self.limits.commit_ops:
            raise CheckpointError("checkpoint-delta-operation-bound-exceeded; checkpoint discovery in smaller batches")
        operations = sorted(self.pending.items())
        sequence = self.sequence
        journals = list(self.journals)
        previous = journals[-1][0] if journals else self.anchor
        for start in range(0, len(operations), self.limits.segment_ops):
            sequence += 1
            segment = {
                "storageSchemaVersion": 2, "sequence": sequence, "previous": previous,
                "ops": operations[start:start + self.limits.segment_ops],
            }
            body = encoded(segment)
            if len(body) > self.limits.segment_bytes:
                raise CheckpointError("checkpoint-journal-segment-bound-exceeded")
            previous = self.objects.reference(self.objects.put(body))
            journals.append((previous, segment))
        if len(journals) > self.limits.replay_segments:
            raise CheckpointError("checkpoint-replay-segment-bound-exceeded")
        retire = max(0, len(journals) - self.limits.compact_after)
        if retire > self.limits.compaction_segments:
            raise CheckpointError("checkpoint-compaction-segment-bound-exceeded")
        root, through, anchor = self.root, self.through, self.anchor
        self.tree.written_nodes = self.tree.written_bytes = 0
        if retire:
            changes = [operation for _, segment in journals[:retire] for operation in segment["ops"]]
            root = self.tree.flush(self.tree.apply(root, changes))
            anchor, last = journals[retire - 1]
            through = last["sequence"]
            journals = journals[retire:]
        byte_count = sum(ref["bytes"] for ref, _ in journals)
        if byte_count > self.limits.replay_bytes:
            raise CheckpointError("checkpoint-replay-byte-bound-exceeded")
        return {
            "base": {"tree": root, "through": through, "anchor": anchor},
            "sequence": sequence, "journal": journals[-1][0] if journals else anchor,
            "journalCount": len(journals), "journalBytes": byte_count,
        }, journals

    def acknowledge(self, control, journals):
        self.root = control["base"]["tree"]
        self.through, self.anchor = control["base"]["through"], control["base"]["anchor"]
        self.sequence, self.journals = control["sequence"], journals
        self.overlay = {}
        for _, segment in journals:
            self.overlay.update(segment["ops"])
        self.pending.clear()


def _container(state, path):
    if "/" not in path:
        return state, path
    parent, key = path.split("/", 1)
    return state.get(parent), key


def _increment(values, key, amount):
    values[key] = values.get(key, 0) + amount
    if values[key] == 0:
        del values[key]
    elif values[key] < 0:
        raise CheckpointError("checkpoint-negative-materialized-count")


class CheckpointState:
    def __init__(self, engine: JournalIndex, state: dict, *, descriptions=None, stats=None):
        self.engine, self.objects, self.limits, self.state = engine, engine.objects, engine.limits, state
        self.maps, self.lists = {}, {}
        self.changed_documents = set()
        self.stats = stats if stats is not None else {
            "states": {}, "reasons": {}, "bySource": {}, "byHost": {},
            "canonicalCandidates": 0, "sitemaps": 0, "unexpandedLinks": 0,
            "publishedDocuments": 0, "exactReviewedCurrentDocuments": 0,
        }
        descriptions = descriptions or {}
        for path in MAPS:
            parent, key = _container(state, path)
            if parent is None or (key not in parent and path not in descriptions):
                continue
            original = parent.pop(key, {})
            value = RecordMap(self, path, descriptions.get(path, {}).get("length", 0))
            parent[key], self.maps[path] = value, value
            for name, item in original.items():
                value[name] = item
        for path in LISTS:
            parent, key = _container(state, path)
            if parent is None or (key not in parent and path not in descriptions):
                continue
            original = parent.pop(key, [])
            value = PagedList(self, path, descriptions.get(path, {}).get("length", 0))
            parent[key], self.lists[path] = value, value
            value.extend(original)

    def attach_new_collections(self):
        # CLI artifacts and optional review history may first appear after initialization.
        for path in MAPS:
            parent, key = _container(self.state, path)
            if parent is not None and key in parent and path not in self.maps:
                old = parent[key]
                value = RecordMap(self, path)
                parent[key] = self.maps[path] = value
                value.update(old)

    def _payload(self, value):
        if isinstance(value, LazyList):
            return value.wire()
        if not isinstance(value, list):
            raise CheckpointError("checkpoint-payload-must-be-a-list")
        body = encoded(value)
        if len(body) > self.limits.payload_bytes:
            raise CheckpointError("checkpoint-payload-byte-bound-exceeded")
        reference = self.objects.reference(self.objects.put(body))
        return {"$payload": reference, "length": len(value)}

    def _unpayload(self, value):
        if not isinstance(value, dict) or set(value) != {"$payload", "length"}:
            raise CheckpointError("checkpoint-payload-reference-invalid")
        return LazyList(self.objects, value["$payload"], value["length"])

    def decode_record(self, path, raw):
        value = deepcopy(raw)
        if path == "candidates" and "links" in value:
            value["links"] = self._unpayload(value["links"])
        elif path == "ledger/documents":
            for version in value["versions"]:
                for field in ("sections", "links"):
                    version["document"][field] = self._unpayload(version["document"][field])
        return value

    def register_object(self, key):
        if self.engine.get("o/" + key) is None:
            self.engine.set("o/" + key, self.objects.reference(key))

    def encode_record(self, path, value):
        if path == "candidates":
            result = {key: deepcopy(item) for key, item in value.items() if key != "links"}
            if "links" in value:
                result["links"] = self._payload(value["links"])
            if result.get("responseObject"):
                self.register_object(result["responseObject"])
        elif path == "ledger/documents":
            result = {key: deepcopy(item) for key, item in value.items() if key != "versions"}
            result["versions"] = []
            for version in value["versions"]:
                copied = {key: deepcopy(item) for key, item in version.items() if key != "document"}
                copied["document"] = {
                    key: deepcopy(item) for key, item in version["document"].items() if key not in ("sections", "links")
                }
                for field in ("sections", "links"):
                    copied["document"][field] = self._payload(version["document"][field])
                self.register_object(version["document"]["response_hash"])
                result["versions"].append(copied)
        else:
            result = deepcopy(value)
            if path == "artifacts":
                self.register_object(result)
        return result

    @staticmethod
    def duplicate_key(url, content_hash, metadata):
        return "d/" + digest({
            "host": urlsplit(url).hostname, "contentHash": content_hash,
            **{field: metadata.get(field) for field in ("language", "documentType", "legal")},
        })

    @staticmethod
    def _work(candidate):
        if candidate is None:
            return set()
        identifier, state = candidate["id"], candidate["state"]
        result = set()
        if state in TERMINAL and not candidate["discoveryComplete"]:
            result.add("w/discovery/" + identifier)
        if state in ("pending", "in-flight"):
            result.add("w/" + state + "/" + identifier)
        if state == "retry-wait":
            at = candidate["retryAt"]
            if not isinstance(at, (int, float)) or not math.isfinite(at) or not 0 <= at < 1e12:
                raise CheckpointError("checkpoint-retry-time-invalid")
            result.add(f"w/retry/{at:020.3f}/" + identifier)
        return result

    def _candidate_counts(self, value, sign):
        if value is None:
            return
        stats = self.stats
        _increment(stats["states"], value["state"], sign)
        if value.get("reason"):
            _increment(stats["reasons"], value["reason"], sign)
        stats["canonicalCandidates" if value["kind"] == "document" else "sitemaps"] += sign
        stats["unexpandedLinks"] += sign * (value.get("links", {}).get("length", 0) - value["discoveryCursor"])
        for source in value["sourceIds"] if value["kind"] == "document" else []:
            counts = stats["bySource"].setdefault(source, {"canonicalCandidates": 0, "states": {}, "reasons": {}})
            counts["canonicalCandidates"] += sign
            _increment(counts["states"], value["state"], sign)
            if value.get("reason"):
                _increment(counts["reasons"], value["reason"], sign)
        if value.get("url"):
            host = urlsplit(value["url"]).hostname
            counts = stats["byHost"].setdefault(host, {"urls": 0, "states": {}, "reasons": {}})
            counts["urls"] += sign
            _increment(counts["states"], value["state"], sign)
            if value.get("reason"):
                _increment(counts["reasons"], value["reason"], sign)

    def _document_indexes(self, key, entry, add):
        if entry is None:
            return
        for url in {entry["url"], *(alias for v in entry["versions"] for alias in v["document"]["aliases"])}:
            if add:
                self.engine.set("u/" + url, key)
            elif self.engine.get("u/" + url) == key:
                self.engine.set("u/" + url, None)
        if not entry["versions"]:
            return
        version = entry["versions"][-1]
        document = version["document"]
        duplicate_key = self.duplicate_key(entry["url"], document["content_hash"], document.get("metadata", {}))
        ids = set(self.engine.get(duplicate_key) or [])
        ids.discard(key)
        if add and version["status"] not in ("withdrawn", "quarantined", "duplicate", "superseded"):
            ids.add(key)
        if len(ids) > 32:
            raise CheckpointError("checkpoint-duplicate-index-bound-exceeded")
        self.engine.set(duplicate_key, sorted(ids) or None)

    def _summary(self, entry):
        if entry is None or not entry["versions"]:
            return None
        version = entry["versions"][-1]
        document = version["document"]
        return {
            "documentId": entry["documentId"], "url": entry["url"],
            "sourceIds": entry.get("sourceIds", [entry["sourceId"]]),
            "documentVersion": version["documentVersion"], "contentHash": document["content_hash"],
            "extractionHash": document.get("extraction_hash"), "reviewHash": version.get("reviewHash"),
            "status": version["status"], "flags": document["flags"],
            "reviewed": bool(self.engine.get("a/" + version["documentVersion"]))
                        and not version.get("reviewRevoked") and version["status"] in ("active", "review-required"),
        }

    def index_record(self, path, key, old, new):
        if path == "urlAliases":
            if old is not None:
                self.engine.set("z/" + old + "\0" + key, None)
            if new is not None:
                self.engine.set("z/" + new + "\0" + key, key)
        elif path == "candidates":
            self._candidate_counts(old, -1)
            self._candidate_counts(new, 1)
            before, after = self._work(old), self._work(new)
            for work in before - after:
                self.engine.set(work, None)
            for work in after:
                self.engine.set(work, new["id"])
        elif path == "ledger/documents":
            self.changed_documents.add(key)
            self._document_indexes(key, old, False)
            self._document_indexes(key, new, True)
            old_summary = self.engine.get("r/" + key)
            summary = self._summary(new)
            self.stats["publishedDocuments"] += int(bool(new and new.get("activeVersion"))) - int(bool(old and old.get("activeVersion")))
            self.stats["exactReviewedCurrentDocuments"] += int(bool(summary and summary["reviewed"])) - int(bool(old_summary and old_summary["reviewed"]))
            self.engine.set("r/" + key, summary)
        elif path == "list:reviewPlans" and new is not None:
            for plan in new:
                for version in plan.get("approvedVersions", []):
                    self.engine.set("a/" + version, True)
                    document_id = version.split("-", 1)[0]
                    summary = self.engine.get("r/" + document_id)
                    if summary and summary["documentVersion"] == version and not summary["reviewed"] and summary["status"] in ("active", "review-required"):
                        summary = {**summary, "reviewed": True}
                        self.stats["exactReviewedCurrentDocuments"] += 1
                        self.engine.set("r/" + document_id, summary)

    def prepare(self, revision: int):
        self.attach_new_collections()
        for collection in self.maps.values():
            collection.flush()
        for collection in self.lists.values():
            collection.pages.flush()
        # Only the small hot control data is copied, never candidate/document records.
        state = {key: value for key, value in self.state.items() if key not in MAPS and key not in LISTS and key != "ledger"}
        if "ledger" in self.state:
            state["ledger"] = {k: v for k, v in self.state["ledger"].items() if k not in ("documents", "attempts")}
        state = deepcopy(state)
        state["revision"] = revision
        descriptions = {path: {"kind": "map", "length": len(value)} for path, value in self.maps.items()}
        descriptions.update({path: {"kind": "list", "length": len(value)} for path, value in self.lists.items()})
        core = {"storageSchemaVersion": 2, "state": state, "collections": descriptions, "stats": self.stats}
        body = encoded(core)
        if len(body) > self.limits.core_bytes:
            raise CheckpointError("checkpoint-hot-control-byte-bound-exceeded")
        return body

    def acknowledge(self):
        for value in self.maps.values():
            value.acknowledge()
        for value in self.lists.values():
            value.pages.acknowledge()

    def next_work(self, kind, now=None):
        for _, identifier in self.engine.scan("w/" + kind + "/"):
            if kind == "retry":
                candidate = self.state["candidates"][identifier]
                if candidate["retryAt"] > now:
                    return None
            return self.state["candidates"][identifier]
        return None

    def inflight(self):
        for _, identifier in self.engine.scan("w/in-flight/"):
            yield self.state["candidates"][identifier]

    def has_retries(self):
        return next(self.engine.scan("w/retry/"), None) is not None

    def review_page(self, limit=None, after=""):
        limit = limit or self.limits.review_page
        if not 1 <= limit <= 1000:
            raise CheckpointError("checkpoint-review-page-limit-invalid")
        values = []
        for key, value in self.engine.scan("r/", "r/" + after if after else ""):
            if len(values) == limit:
                return values, values[-1]["documentId"]
            values.append({k: deepcopy(v) for k, v in value.items() if k != "reviewed"})
        return values, None
