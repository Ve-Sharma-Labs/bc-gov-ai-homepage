"""Synthetic, offline checks; fixtures confer no publisher permission."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import unittest
from unittest.mock import patch

from bc_ingestion.freshness import (
    FreshnessStore, LIMITS, collect, initial_state, targets, validate_state,
)
from bc_ingestion.manifest import CheckpointError
from bc_ingestion.policy import AcquisitionError
from bc_ingestion.programme_policy import ProgrammePolicy
import test_programme as fixtures

Network, response, rights_for, URL = (
    fixtures.Network, fixtures.response, fixtures.rights_for, fixtures.URL,
)


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        fixtures.ProgrammeFixtures.setUp(self)
        self.catalog["sources"] = deepcopy(self.catalog["sources"])
        self.provenance = {"documents": [{
            "sourceId": "health", "url": URL, "checkedAt": "2026-09-01T00:00:00Z",
            "responseSha256": hashlib.sha256(b"approved snapshot").hexdigest(),
        }]}
        self.now = datetime(2026, 11, 5, tzinfo=timezone.utc)

    def collect(self, *, rights=True, refresh=True, initialize=True, network=None):
        network = network or Network(self.clock, pages={URL: response(URL, b"approved snapshot")})
        with FreshnessStore(self.path) as store:
            report = collect(
                self.catalog, self.provenance, self.programme, now=self.now,
                rights=rights_for(self.programme) if rights else None,
                refresh=refresh, store=store, initialize=initialize,
                request=network, clock=self.clock, sleep=self.clock.sleep,
            )
        return report, network

    def target(self, report):
        return next(row for row in report["sources"] if row["url"] == URL)

    def test_metadata_only_never_fetches(self):
        report, network = self.collect(refresh=False)
        self.assertEqual(network.calls, [])
        self.assertIn("stale-check", self.target(report)["findings"])

    def test_missing_rights_never_initializes_or_fetches(self):
        report, network = self.collect(rights=False)
        self.assertEqual(network.calls, [])
        self.assertFalse(self.path.exists())
        self.assertEqual(self.target(report)["refresh"], "rights-review-required")

    def test_expired_and_revoked_rights_never_fetch(self):
        for change in ("expired", "revoked"):
            rights = rights_for(self.programme)
            if change == "expired":
                rights["expiresAt"] = "2026-10-27T00:00:00Z"
            else:
                rights["revocation"].update(status="revoked", revokedAt="2026-10-27T00:00:00Z")
            network = Network(self.clock)
            report = collect(
                self.catalog, self.provenance, self.programme, now=self.now, rights=rights,
                refresh=True, request=network,
            )
            self.assertEqual(network.calls, [])
            self.assertEqual(self.target(report)["refresh"], "rights-review-" + change)

    def test_checkpoint_required_does_not_fetch(self):
        report, network = self.collect(initialize=False)
        self.assertEqual(network.calls, [])
        self.assertEqual(self.target(report)["refresh"], "checkpoint-required")

    def test_same_baseline_refresh_is_not_stale(self):
        report, _ = self.collect()
        target = self.target(report)
        self.assertEqual(target["refresh"], "unchanged")
        self.assertNotIn("stale-check", target["findings"])
        self.assertNotIn("approved snapshot", json.dumps(report))

    def test_changed_hash_retains_approved_baseline(self):
        report, _ = self.collect(network=Network(self.clock, pages={URL: response(URL, b"new guidance")}))
        target = self.target(report)
        self.assertIn("source-changed", target["findings"])
        self.assertEqual(target["baselineHash"], self.provenance["documents"][0]["responseSha256"])
        self.assertNotIn("new guidance", self.path.read_text())

    def test_withdrawal_and_unverifiable_304(self):
        for status, expected in ((410, "withdrawn"), (304, "unverifiable-304")):
            if self.path.exists():
                self.path.unlink()
            report, _ = self.collect(network=Network(self.clock, pages={URL: response(URL, status=status)}))
            self.assertEqual(self.target(report)["refresh"], expected)

    def test_cross_host_redirect_is_not_followed(self):
        network = Network(self.clock, pages={
            URL: response(URL, status=302, headers={"location": "https://example.com/private"}),
        })
        report, network = self.collect(network=network)
        self.assertEqual(self.target(report)["refresh"], "access-or-network-unavailable")
        self.assertFalse(any("example.com" in url for url, *_ in network.calls))

    def test_robots_denial_blocks_document(self):
        network = Network(self.clock, robots=b"User-agent: *\nDisallow: /\n")
        report, _ = self.collect(network=network)
        self.assertEqual(self.target(report)["refresh"], "access-or-network-unavailable")
        self.assertTrue(all(url.endswith("robots.txt") for url, *_ in network.calls))

    def test_budget_is_cumulative_and_cannot_reinitialize(self):
        self.collect()
        previous = json.loads(self.path.read_text())["budget"]["requests"]
        self.collect(initialize=False)
        self.assertGreater(json.loads(self.path.read_text())["budget"]["requests"], previous)
        with self.assertRaises(AcquisitionError):
            self.collect()

    def test_exhausted_checkpoint_never_resets(self):
        with FreshnessStore(self.path) as store:
            state = initial_state(ProgrammePolicy(self.programme, self.catalog).programme_hash)
            state["budget"].update(requests=LIMITS.total_requests, documentRequests=LIMITS.total_requests)
            store.save(state)
        report, network = self.collect(initialize=False)
        self.assertEqual(network.calls, [])
        self.assertEqual(self.target(report)["refresh"], "deferred-budget")

    def test_checkpoint_failure_is_fatal(self):
        with patch.object(FreshnessStore, "save", side_effect=CheckpointError("storage unavailable")):
            with self.assertRaises(CheckpointError):
                self.collect()

    def test_denied_sources_are_never_requested(self):
        report, network = self.collect()
        self.assertTrue(any("source-access-hold" in row["findings"] for row in report["sources"]))
        self.assertFalse(any("icbc.com" in url or "workbc.ca" in url for url, *_ in network.calls))

    def test_malformed_checkpoint_and_provenance_fail_closed(self):
        with self.assertRaises(AcquisitionError):
            validate_state({"schemaVersion": 1}, "x")
        self.provenance["documents"][0]["responseSha256"] = "not-a-hash"
        with self.assertRaises(AcquisitionError):
            targets(self.catalog, self.provenance)

    def test_invalid_pacing_checkpoint_cannot_dispatch(self):
        self.collect()
        state = json.loads(self.path.read_text())
        state["budget"]["hosts"]["www2.gov.bc.ca"]["nextAllowedAt"] = -1
        self.path.write_text(json.dumps(state), encoding="utf-8")
        network = Network(self.clock)
        with self.assertRaises(AcquisitionError):
            self.collect(initialize=False, network=network)
        self.assertEqual(network.calls, [])

    def test_retry_after_on_robots_persists_deadline_without_busy_retry(self):
        def network(url, **kwargs):
            return response(url, status=429, headers={"content-type": "text/plain", "retry-after": "600"})
        self.collect(network=network)
        state = json.loads(self.path.read_text())
        self.assertGreater(state["budget"]["hosts"]["www2.gov.bc.ca"]["nextAllowedAt"], self.clock())
        report, network = self.collect(initialize=False)
        self.assertEqual(network.calls, [])
        self.assertEqual(self.target(report)["refresh"], "deferred-budget")

    def test_invalid_retry_after_retains_host_hold_across_invocations(self):
        def network(url, **kwargs):
            return response(url, status=429, headers={"content-type": "text/plain", "retry-after": "invalid"})
        self.collect(network=network)
        report, network = self.collect(initialize=False)
        self.assertEqual(network.calls, [])
        self.assertEqual(self.target(report)["refresh"], "publisher-review-required")
