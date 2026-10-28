"""Measured offline corpus-scale storage tests; all Blob operations use an in-memory fake."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import unittest

from bc_ingestion.azure_blob import BlobManifestStore, RightsBlobInput, json_bytes
from bc_ingestion.checkpoint_tree import StorageLimits
from bc_ingestion.manifest import CheckpointError, ProgrammeLimits
from bc_ingestion.metadata import digest
from bc_ingestion.pipeline import Ledger, document_id
from test_blob_store import HAS_AZURE, MemoryAzure
from test_programme import Clock, DATE, URL, html, response, rights_for
from test_programme import ROOT
from bc_ingestion.catalog import load_catalog


def baseline(programme, catalog, reference):
    return {
        "schemaVersion": 1, "mode": "full-programme", "revision": 0,
        "programmeHash": digest(programme), "catalogHash": digest({s["id"]: s for s in catalog["sources"]}),
        "rightsReview": None, "rightsReviewHash": digest(rights_for(programme)),
        "rightsReviewReference": reference,
        "status": "running", "pauseReason": None, "limits": ProgrammeLimits().to_dict(),
        "candidates": {}, "urlAliases": {}, "ledger": Ledger().state, "events": [], "reviewPlans": [],
        "seedLinks": [], "seedCursor": 0,
        "budget": {"requests": 0, "documentRequests": 0, "robotsRequests": 0, "chargedBytes": 0,
                   "responseBytes": 0, "hosts": {}},
    }


def measure_corpus(count):
    clock, catalog = Clock(), load_catalog(ROOT / "data" / "pilot-catalog.json")
    programme = json.loads((ROOT / "data" / "source-programme.json").read_text(encoding="utf-8"))
    memory = MemoryAzure(clock)
    data = json_bytes(rights_for(programme))
    memory.seed("rights", "grant.json", data)
    rights_hash = hashlib.sha256(data).hexdigest()
    totals = {}
    resumes = []
    cold_key = None
    for start in range(0, count, 25):
        rights = RightsBlobInput(memory.get_container_client("rights"), "grant.json", rights_hash)
        rights.load()
        store = BlobManifestStore(memory.get_container_client("candidates"), "scale",
                                  initialize=start == 0, rights_input=rights, monotonic=clock, background_renewal=False)
        before = len(memory.calls)
        with store:
            state = store.load()
            resumes.append({"records": start, "calls": len(memory.calls) - before,
                            "getBytes": store.metrics["downloadedBytes"], "gets": store.metrics["gets"]})
            if state is None:
                state = baseline(programme, catalog, rights.reference)
                store.save(state)
            ledger = Ledger(state["ledger"])
            for index in range(start, min(start + 25, count)):
                url = URL + f"/scale-{index:05d}"
                identifier = document_id(url)
                state["budget"]["requests"] += 1
                state["budget"]["documentRequests"] += 1
                state["budget"]["inFlight"] = {"url": url, "candidateId": identifier, "reservedBytes": 8192}
                store.save(state)  # The same write-before-request boundary used by RequestController.
                body = html(f"Synthetic scale guide {index}", links="") + b" " * 2048
                fetched = response(url, body)
                raw_key = store.objects.put(body)
                cold_key = raw_key
                ledger.record(fetched, "health", "Government of British Columbia")
                state["candidates"][identifier] = {
                    "id": identifier, "url": url, "canonicalUrl": url, "kind": "document",
                    "sourceIds": ["health"], "topics": ["health"], "attempts": 1,
                    "state": "candidate", "reason": None, "discoveredFrom": [],
                    "links": [], "discoveryCursor": 0, "discoveryComplete": True, "responseObject": raw_key,
                }
                state["budget"].pop("inFlight")
                state["budget"]["chargedBytes"] += len(body)
                state["budget"]["responseBytes"] += len(body)
                state["events"].append({"type": "synthetic-response", "documentId": identifier})
                store.save(state)
                state["checkpointCounter"] = index
                store.save(state)  # A hot-control-only save must not rewrite any document payload.
            self_check = store.coverage_counts()
            if self_check["canonicalCandidates"] != min(start + 25, count):
                raise AssertionError("Incremental coverage lost records")
        for key, value in store.metrics.items():
            totals[key] = totals.get(key, 0) + value
    return {"records": count, "metrics": totals, "resumes": resumes,
            "largestObject": max(len(value["data"]) for key, value in memory.items.items() if key[0] == "candidates")}, memory, clock, programme, cold_key


@unittest.skipUnless(HAS_AZURE, "Optional Azure SDK is not installed")
class CheckpointScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.small, _, _, _, _ = measure_corpus(500)
        cls.large, cls.memory, cls.clock, cls.programme, cls.cold_key = measure_corpus(1000)
        cls.original_items = deepcopy(cls.memory.items)
        print("CHECKPOINT_SCALE " + json.dumps({
            "500": cls.small["metrics"], "1000": cls.large["metrics"],
            "resumeMaxCalls": max(row["calls"] for row in cls.large["resumes"]),
            "resumeMaxBytes": max(row["getBytes"] for row in cls.large["resumes"]),
            "largestObject": cls.large["largestObject"],
        }, sort_keys=True))

    def setUp(self):
        self.memory.items = deepcopy(self.original_items)
        self.memory.before_upload = self.memory.after_upload = self.memory.before_download = None
        self.memory.fail_renew = False

    def store(self, **kwargs):
        rights_bytes = json_bytes(rights_for(self.programme))
        rights = RightsBlobInput(self.memory.get_container_client("rights"), "grant.json",
                                 hashlib.sha256(rights_bytes).hexdigest())
        rights.load()
        return BlobManifestStore(self.memory.get_container_client("candidates"), "scale", rights_input=rights,
                                 monotonic=self.clock, background_renewal=False, **kwargs)

    def test_uploaded_bytes_and_calls_are_not_quadratic_at_1000_documents(self):
        self.assertLess(self.large["metrics"]["uploadedBytes"], self.small["metrics"]["uploadedBytes"] * 2.8)
        self.assertLess(self.large["metrics"]["calls"], self.small["metrics"]["calls"] * 2.8)
        self.assertLess(self.large["largestObject"], 131_072)
        self.assertGreater(self.large["metrics"]["compactedSegments"], 0)
        self.assertLess(max(row["calls"] for row in self.large["resumes"]), 20)
        self.assertLess(max(row["getBytes"] for row in self.large["resumes"]), 1_000_000)
        self.assertLessEqual(max(row["gets"] for row in self.large["resumes"]), 10)

    def test_hot_reservation_save_does_not_load_or_upload_cold_documents(self):
        with self.store() as store:
            state = store.load()
            before = dict(store.metrics)
            state["budget"]["inFlight"] = {"url": URL, "reservedBytes": 1024, "candidateId": "synthetic-next"}
            store.save(state)
            self.assertLess(store.metrics["uploadedBytes"] - before["uploadedBytes"], 16_384)
            self.assertEqual(store.metrics["downloadedBytes"] - before["downloadedBytes"], 0)
            self.assertLess(store.metrics["calls"] - before["calls"], 8)
            self.assertEqual(len(state["ledger"]["documents"]), 1000)

    def test_bounded_review_page_and_lazy_exact_hash_validation(self):
        with self.store() as store:
            store.load()
            before = store.metrics["calls"]
            page, cursor = store.review_page(25)
            self.assertEqual(len(page), 25)
            self.assertTrue(cursor)
            self.assertLess(store.metrics["calls"] - before, 20)
            next_page, _ = store.review_page(25, cursor)
            self.assertFalse({v["documentId"] for v in page} & {v["documentId"] for v in next_page})
            self.memory.seed("candidates", "scale/objects/" + self.cold_key, b"corrupted", {"sha256": self.cold_key})
            with self.assertRaises(CheckpointError):
                store.objects.get(self.cold_key)

    def test_storage_io_limit_stops_without_advancing_the_committed_pointer(self):
        limits = replace(StorageLimits(), execution_calls=2)
        before = self.memory.items[("candidates", "scale/manifest.json")]["data"]
        with self.assertRaisesRegex(CheckpointError, "io-bound"):
            with self.store(storage_limits=limits) as store:
                store.load()
        self.assertEqual(self.memory.items[("candidates", "scale/manifest.json")]["data"], before)

    def test_replay_sequence_corruption_is_fatal_not_a_quota_reset(self):
        key = ("candidates", "scale/manifest.json")
        control = json.loads(self.memory.items[key]["data"])
        control["journalCount"] += 1
        self.memory.seed(*key, json_bytes(control))
        with self.assertRaisesRegex(CheckpointError, "replay-bound-or-sequence"):
            with self.store() as store:
                store.load()

    def test_mutation_tracking_persists_nested_updates_and_alias_removal(self):
        identifier = document_id(URL + "/scale-00000")
        with self.store() as store:
            state = store.load()
            candidate = state["candidates"][identifier]
            candidate["sourceIds"].append("bc-content")
            candidate["reason"] = "synthetic-update"
            candidate["state"] = "quarantined"
            entry = state["ledger"]["documents"][identifier]
            entry["versions"][-1]["document"]["flags"].append("synthetic-hold")
            entry["versions"][-1]["status"] = "quarantined"
            store.save(state)
        with self.store() as store:
            state = store.load()
            self.assertIn("bc-content", state["candidates"][identifier]["sourceIds"])
            self.assertEqual(store.coverage_counts()["states"]["quarantined"], 1)
            self.assertIn("synthetic-hold", state["ledger"]["documents"][identifier]["versions"][-1]["document"]["flags"])

    def test_active_record_identity_survives_cache_eviction(self):
        identifier = document_id(URL + "/scale-00000")
        with self.store(storage_limits=replace(StorageLimits(), cached_records=2)) as store:
            state = store.load()
            held = state["candidates"][identifier]
            for index in range(1, 10):
                state["candidates"][document_id(URL + f"/scale-{index:05d}")]
            self.assertIs(state["candidates"][identifier], held)
            held["reason"] = "updated-after-eviction"
            store.save(state)
        with self.store() as store:
            self.assertEqual(store.load()["candidates"][identifier]["reason"], "updated-after-eviction")

    def test_frontier_selection_and_recovery_use_indexes_not_all_record_reads(self):
        ids = [document_id(URL + f"/scale-{index:05d}") for index in range(50)]
        with self.store() as store:
            state = store.load()
            for identifier in ids:
                state["candidates"][identifier].update(state="pending")
            state["candidates"][ids[0]]["state"] = "in-flight"
            store.save(state)
        with self.store() as store:
            store.load()
            before = store.metrics["calls"]
            pending = store.next_work("pending")
            recovering = list(store.inflight())
            self.assertIn(pending["id"], ids)
            self.assertEqual([candidate["id"] for candidate in recovering], [ids[0]])
            self.assertLess(store.metrics["calls"] - before, 30)

    def test_compaction_failure_never_advances_the_leased_pointer(self):
        from azure.core.exceptions import ServiceResponseError
        before = self.memory.items[("candidates", "scale/manifest.json")]["data"]
        with self.assertRaises(CheckpointError):
            with self.store() as store:
                state = store.load()
                state["candidates"][document_id(URL + "/scale-00000")]["reason"] = "pending-compaction-change"

                def fail_tree(blob, data, kwargs):
                    if "/objects/" in blob.name:
                        value = json.loads(data)
                        if isinstance(value, dict) and value.get("kind") in ("leaf", "branch"):
                            raise ServiceResponseError("synthetic compaction failure")

                self.memory.before_upload = fail_tree
                store.save(state)
        self.assertEqual(self.memory.items[("candidates", "scale/manifest.json")]["data"], before)
        self.memory.before_upload = None
        self.clock.now += 61
        with self.store() as store:
            self.assertIsNone(store.load()["candidates"][document_id(URL + "/scale-00000")]["reason"])


if __name__ == "__main__":
    unittest.main()
