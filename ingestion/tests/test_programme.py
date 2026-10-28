"""Offline programme fixtures: permissions here are synthetic, never publisher approvals."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from bc_ingestion.catalog import load_catalog
from bc_ingestion.cli import main
from bc_ingestion.fetch import Fetcher, Response
from bc_ingestion.manifest import JsonManifestStore, LocalResponseStore, ProgrammeLimits
from bc_ingestion.metadata import digest
from bc_ingestion.pipeline import Ledger, build_publish_plan, document_id
from bc_ingestion.policy import AcquisitionError, validate_url
from bc_ingestion.programme import ProgrammeRun, retry_at, sitemap_links
from bc_ingestion.programme_policy import ProgrammePolicy, RIGHTS_EXCLUSIONS


ROOT = Path(__file__).resolve().parents[2]
URL = "https://www2.gov.bc.ca/gov/content/health/synthetic"
SITEMAP = "https://www2.gov.bc.ca/sitemap/sitemap_index.xml"
DATE = "2026-10-27T01:20:00Z"
ROBOTS = b"User-agent: *\nDisallow: /private\n"


def html(label="Synthetic guidance", links="", canonical=""):
    return (
        f"<html lang='en-CA'><head><title>{label}</title>{canonical}</head><body><main>"
        f"<h1>{label}</h1><p>" + "Synthetic official preparation guidance with complete source context. " * 8
        + f"</p>{links}</main></body></html>"
    ).encode()


def response(url, body=None, status=200, headers=None):
    return Response(url, status, headers or {"content-type": "text/html"},
                    body if body is not None else html(), DATE)


def rights_for(programme, hosts=("www2.gov.bc.ca",)):
    observations = {item["host"]: item for item in programme["accessObservations"]}
    source_paths = {
        host: [
            prefix
            for source in programme["sources"] if source["host"] == host
            for prefix in source["targetPathPrefixes"]
        ]
        for host in hosts
    }

    def sitemap_prefix(url):
        path = urlsplit_path(url)
        return "/sitemap" if path.startswith("/sitemap/") else path

    return {
        "schemaVersion": 2, "programmeHash": digest(programme), "purpose": "candidate-acquisition",
        "approvalKind": "internal-blanket", "approvalConfirmed": True,
        "reviewer": "SYNTHETIC TEST ONLY",
        "reviewId": "synthetic-rights-fixture", "reviewedAt": "2026-10-26T00:00:00Z",
        "expiresAt": "2026-11-25T00:00:00Z",
        "approvalEvidence": {
            "kind": "internal-session-approval",
            "reference": "test:synthetic-rights-fixture",
            "sha256": "a" * 64,
        },
        "revocation": {
            "status": "active",
            "reference": "test:synthetic-rights-fixture/revocation",
            "revokedAt": None,
        },
        "exclusions": sorted(RIGHTS_EXCLUSIONS),
        "grants": [{
            "host": host,
            "pathPrefixes": source_paths[host],
            "routes": [{
                "technicalRoute": "html",
                "format": "html",
                "pathPrefixes": source_paths[host],
                "clearsAccessHold": None,
            }, *([{
                "technicalRoute": "sitemap-xml",
                "format": "sitemap-xml",
                "pathPrefixes": sorted({
                    sitemap_prefix(url) for url in observations[host].get("sitemaps", [])
                }),
                "clearsAccessHold": None,
            }] if observations[host].get("sitemaps") else [])],
            "publicReferences": [{
                "kind": "terms",
                "url": f"https://{host}/synthetic-terms",
            }],
        } for host in hosts],
    }


class Clock:
    def __init__(self):
        self.now = datetime.fromisoformat(DATE.replace("Z", "+00:00")).timestamp()
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def datetime(self):
        return datetime.fromtimestamp(self.now, timezone.utc)


class Network:
    def __init__(self, clock, pages=None, robots=ROBOTS, robots_type="text/plain"):
        self.clock, self.pages, self.robots, self.robots_type = clock, pages or {}, robots, robots_type
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, self.clock(), kwargs))
        if url.endswith("/robots.txt"):
            return response(url, self.robots, headers={"content-type": self.robots_type})
        item = self.pages.get(url, response(url))
        return item() if callable(item) else item


class ProgrammeFixtures(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(ROOT / "data" / "pilot-catalog.json")
        self.programme = json.loads((ROOT / "data" / "source-programme.json").read_text(encoding="utf-8"))
        self.clock = Clock()
        self.root = ROOT / "ingestion" / ".generated" / ("programme-fixture-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.path = self.root / "manifest.json"

    def policy(self, rights=True, hosts=("www2.gov.bc.ca",)):
        return ProgrammePolicy(self.programme, self.catalog,
                               rights_for(self.programme, hosts) if rights else None, clock=self.clock.datetime)

    def run_once(self, network, *, acquire=True, resume=False, batch=25, limits=None, seeds=None, rights=True):
        with JsonManifestStore(self.path) as store:
            runner = ProgrammeRun(
                self.policy(rights), store, limits=limits, seeds=seeds if seeds is not None else [URL],
                response_store=LocalResponseStore(self.root / "responses"),
                clock=self.clock, sleep=self.clock.sleep, request=network,
            )
            result = runner.run(acquire=acquire, resume=resume, batch_requests=batch)
        return result, runner.state

    def test_review_only_is_default_even_when_rights_are_supplied(self):
        network = Network(self.clock)
        result, state = self.run_once(network, acquire=False)
        self.assertEqual(network.calls, [])
        self.assertEqual(result["status"], "review-only")
        self.assertEqual(state["ledger"]["documents"], {})
        self.assertIsNone(state["rightsReviewHash"])

    def test_twelve_source_inventory_does_not_manufacture_permission(self):
        with JsonManifestStore(self.path) as store:
            runner = ProgrammeRun(self.policy(False), store, clock=self.clock)
            result = runner.run()
            self.assertEqual(set(result["bySource"]), {s["id"] for s in self.catalog["sources"]})
            self.assertFalse(result["coverageTargetMet"])
            self.assertEqual(result["budget"]["requests"], 0)
            self.assertTrue(any("rights-review-required" in reason for reason in result["reasons"]))
            self.assertTrue(any("source-access-hold" in reason for reason in result["reasons"]))
            with self.assertRaises(AcquisitionError):
                runner.run(acquire=True)

    def test_resume_keeps_totals_and_does_not_refetch_finished_documents(self):
        second = URL + "/second"
        network = Network(self.clock, {
            URL: response(URL, html(links=f"<a href='{second}'>Second guide</a>")),
            second: response(second, html("Second synthetic guidance")),
        })
        result, state = self.run_once(network, batch=2)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(state["budget"]["requests"], 2)
        result, state = self.run_once(network, resume=True, batch=2)
        self.assertEqual(result["status"], "frontier-exhausted")
        self.assertEqual(state["budget"]["requests"], 4)
        self.assertEqual([call[0] for call in network.calls if not call[0].endswith("robots.txt")], [URL, second])
        for entry in state["ledger"]["documents"].values():
            self.assertEqual(len(entry["versions"]), 1)
            self.assertIsNone(entry["activeVersion"])
        before = len(network.calls)
        self.run_once(network, resume=True)
        self.assertEqual(len(network.calls), before)

    def test_resume_cannot_change_or_reset_budget_or_review(self):
        limits = ProgrammeLimits(total_requests=2)
        network = Network(self.clock, {URL: response(URL, html(links=f"<a href='{URL}/next'>Next</a>"))})
        self.run_once(network, limits=limits)
        with self.assertRaises(AcquisitionError):
            self.run_once(network, resume=True, limits=ProgrammeLimits(total_requests=100))
        result, state = self.run_once(network, resume=True)
        self.assertEqual(result["pauseReason"], "total-request-budget-exhausted")
        self.assertEqual(len(network.calls), 2)
        altered = rights_for(self.programme)
        altered["reviewId"] = "different-review"
        with JsonManifestStore(self.path) as store, self.assertRaises(AcquisitionError):
            ProgrammeRun(ProgrammePolicy(self.programme, self.catalog, altered, clock=self.clock.datetime), store)
        self.assertEqual(state["budget"]["requests"], 2)

    def test_rights_can_be_bound_after_offline_review_but_not_invented(self):
        network = Network(self.clock)
        self.run_once(network, acquire=False, rights=False)
        result, state = self.run_once(network)
        self.assertEqual(result["states"]["candidate"], 1)
        self.assertEqual(state["rightsReviewHash"], digest(rights_for(self.programme)))

    def test_canonical_overlap_merges_category_tags_and_frontier_identity(self):
        canonical = URL + "/canonical"
        network = Network(self.clock, {
            URL: response(URL, html(canonical=f"<link rel='canonical' href='{canonical}'>")),
            canonical: response(canonical),
        })
        result, state = self.run_once(network, seeds=[URL, canonical, URL + "?utm_source=test#section"])
        self.assertEqual(result["canonicalCandidates"], 1)
        self.assertEqual(result["aliases"], 1)
        self.assertEqual(len([c for c in network.calls if not c[0].endswith("robots.txt")]), 1)
        candidate = next(iter(state["candidates"].values()))
        self.assertEqual(candidate["sourceIds"], ["bc-content", "health"])
        self.assertIn("government-programmes", candidate["topics"])
        self.assertIn("msp", candidate["topics"])
        entry = next(iter(state["ledger"]["documents"].values()))
        self.assertEqual(entry["versions"][0]["document"]["metadata"]["sourceIds"], ["bc-content", "health"])

    def test_canonical_target_requires_robots_permission(self):
        target = URL + "/denied"
        denied = ("User-agent: *\nDisallow: " + urlsplit_path(target)).encode()
        network = Network(self.clock, {URL: response(URL, html(canonical=f"<link rel='canonical' href='{target}'>"))},
                          robots=denied)
        result, state = self.run_once(network)
        document = next(iter(state["ledger"]["documents"].values()))["versions"][0]["document"]
        self.assertEqual(document["url"], URL)
        self.assertIn("unapproved-canonical", document["flags"])
        self.assertEqual(result["states"]["quarantined"], 1)
        self.assertFalse(any(call[0] == target for call in network.calls))

    def test_cross_host_and_unverified_alias_redirects_are_not_followed(self):
        for target in ("https://icbc.com/guide", "https://www.healthlinkbc.ca/find-care/guide"):
            with self.subTest(target=target):
                policy = self.policy(hosts=("www2.gov.bc.ca", "www.healthlinkbc.ca", "www.icbc.com"))
                network = Network(self.clock, {URL: response(URL, b"", 302, {"location": target})})
                fetcher = Fetcher(url_validator=policy.validate_url, request=network, sleep=lambda _: None)
                with self.assertRaises(AcquisitionError):
                    fetcher.fetch(URL)
                self.assertFalse(any(call[0] == target for call in network.calls))
        with self.assertRaisesRegex(AcquisitionError, "unverified-alias"):
            self.policy(hosts=("www.icbc.com",)).validate_url("https://icbc.com/sitemap.xml", kind="sitemap")

    def test_broader_candidate_policy_does_not_widen_manual_publication(self):
        broader = "https://www2.gov.bc.ca/gov/content/education-training/synthetic"
        with self.assertRaises(AcquisitionError):
            validate_url(broader)
        self.assertEqual(self.policy().validate_url(broader), broader)
        with self.assertRaises(AcquisitionError):
            Fetcher(max_pages=500)
        with self.assertRaises(AcquisitionError):
            Fetcher(max_pages=None)

    def test_full_programme_exceeds_sample_size_only_with_its_durable_budget(self):
        urls = [URL + f"/page-{i}" for i in range(30)]
        network = Network(self.clock)
        result, state = self.run_once(
            network, seeds=urls, batch=100, limits=ProgrammeLimits(total_requests=40),
        )
        self.assertEqual(state["budget"]["documentRequests"], 30)
        self.assertEqual(state["budget"]["robotsRequests"], 1)
        self.assertEqual(result["canonicalCandidates"], 30)
        self.assertEqual(result["publishedDocuments"], 0)
        self.assertEqual(result["status"], "frontier-exhausted")

    def test_manual_sample_cap_is_not_reset_by_repeated_acquire_calls(self):
        network = Network(self.clock)
        first = self.root / "manual"
        first.mkdir()
        urls = [("health", URL + f"/page-{i}") for i in range(25)]
        ledger = Ledger()
        ledger.acquire(urls, self.catalog, first, Fetcher(request=network, sleep=lambda _: None))
        reloaded = Ledger.load(first / "state.json")
        result = reloaded.acquire(
            [("health", URL + "/beyond-cap")], self.catalog, first,
            Fetcher(request=network, sleep=lambda _: None),
        )
        self.assertEqual(reloaded.state["sampleBudget"]["documentRequests"], 25)
        self.assertEqual(result["requests"], 0)
        self.assertIn("durable-manual-sample-cap", result["results"][0]["reason"])
        self.assertEqual(len([call for call in network.calls if not call[0].endswith("robots.txt")]), 25)

    def test_rights_path_scope_expiry_and_transaction_boundaries_are_enforced(self):
        rights = rights_for(self.programme)
        rights["grants"][0]["pathPrefixes"] = ["/gov/content/health"]
        rights["grants"][0]["routes"][0]["pathPrefixes"] = ["/gov/content/health"]
        policy = ProgrammePolicy(self.programme, self.catalog, rights, clock=self.clock.datetime)
        self.assertEqual(policy.validate_url(URL), URL)
        with self.assertRaisesRegex(AcquisitionError, "rights-scope-missing"):
            policy.validate_url("https://www2.gov.bc.ca/gov/content/taxes/synthetic")
        for path in ("/account", "/payment", "/booking", "/api", "/upload"):
            with self.subTest(path=path), self.assertRaises(AcquisitionError):
                policy.validate_url(URL + path)
        self.clock.now = datetime(2028, 1, 1, tzinfo=timezone.utc).timestamp()
        with self.assertRaisesRegex(AcquisitionError, "rights-review-expired"):
            policy.validate_url(URL)

    def test_internal_approval_uses_private_hash_reference_without_fake_publisher_url(self):
        rights = rights_for(self.programme)
        rights["grants"][0]["publicReferences"] = []
        policy = ProgrammePolicy(self.programme, self.catalog, rights, clock=self.clock.datetime)
        provenance = policy.metadata(URL)["rights"]
        self.assertEqual(provenance["approvalEvidenceReference"], "test:synthetic-rights-fixture")
        self.assertEqual(provenance["approvalEvidenceHash"], "a" * 64)
        self.assertIsNone(provenance["licenceUrl"])
        invalid = deepcopy(rights)
        invalid["approvalEvidence"]["sha256"] = "not-a-digest"
        with self.assertRaisesRegex(AcquisitionError, "exact private reference and SHA-256"):
            ProgrammePolicy(self.programme, self.catalog, invalid, clock=self.clock.datetime)

    def test_legacy_publisher_evidence_schema_remains_readable(self):
        legacy = {
            "schemaVersion": 1,
            "programmeHash": digest(self.programme),
            "purpose": "candidate-acquisition",
            "publisherPermissionConfirmed": True,
            "reviewer": "SYNTHETIC TEST ONLY",
            "reviewId": "legacy-synthetic-rights",
            "reviewedAt": "2026-10-26T00:00:00Z",
            "expiresAt": "2027-10-26T00:00:00Z",
            "grants": [{
                "host": "www2.gov.bc.ca",
                "pathPrefixes": ["/gov/content"],
                "sitemapPathPrefixes": ["/sitemap"],
                "formats": ["html", "sitemap-xml"],
                "licenceUrl": "https://www2.gov.bc.ca/synthetic-licence",
                "evidenceUrl": "https://www2.gov.bc.ca/synthetic-permission",
            }],
        }
        policy = ProgrammePolicy(self.programme, self.catalog, legacy, clock=self.clock.datetime)
        self.assertEqual(policy.validate_url(URL), URL)
        self.assertEqual(
            policy.metadata(URL)["rights"]["evidenceUrl"],
            "https://www2.gov.bc.ca/synthetic-permission",
        )

    def test_specific_reviewed_route_can_clear_matching_hold_but_wildcard_cannot(self):
        rights = rights_for(self.programme, hosts=("www.icbc.com",))
        rights["grants"][0]["routes"].extend([
            {
                "technicalRoute": "rendered-html",
                "format": "rendered-html",
                "pathPrefixes": ["/"],
                "clearsAccessHold": None,
            },
            {
                "technicalRoute": "rendered-html",
                "format": "rendered-html",
                "pathPrefixes": ["/driver-licensing"],
                "clearsAccessHold": "blocked-publisher-terms",
            },
        ])
        policy = ProgrammePolicy(self.programme, self.catalog, rights, clock=self.clock.datetime)
        approved = "https://www.icbc.com/driver-licensing/getting-licensed"
        self.assertEqual(policy.validate_url(approved, kind="rendered-html"), approved)
        with self.assertRaisesRegex(AcquisitionError, "source-access-hold"):
            policy.validate_url("https://www.icbc.com/", kind="rendered-html")
        wildcard = deepcopy(rights)
        wildcard["grants"][0]["routes"][-1]["pathPrefixes"] = ["/"]
        with self.assertRaisesRegex(AcquisitionError, "non-wildcard route"):
            ProgrammePolicy(self.programme, self.catalog, wildcard, clock=self.clock.datetime)

    def test_legal_xml_is_civix_scoped_and_review_does_not_create_a_generic_fetcher(self):
        rights = rights_for(self.programme, hosts=("www.bclaws.gov.bc.ca",))
        rights["grants"][0]["routes"].append({
            "technicalRoute": "legal-xml",
            "format": "legal-xml",
            "pathPrefixes": ["/civix"],
            "clearsAccessHold": "blocked-general-crawl",
        })
        policy = ProgrammePolicy(self.programme, self.catalog, rights, clock=self.clock.datetime)
        url = "https://www.bclaws.gov.bc.ca/civix/content/complete/statreg"
        self.assertEqual(policy.validate_url(url, kind="legal-xml"), url)
        with self.assertRaisesRegex(AcquisitionError, "rights-scope-missing"):
            policy.validate_url("https://www.bclaws.gov.bc.ca/standards/example.xml", kind="legal-xml")
        fetcher = Fetcher(url_validator=policy.validate_url, request=Network(self.clock),
                          sleep=lambda _: None)
        with self.assertRaisesRegex(AcquisitionError, "No fetch adapter"):
            fetcher.fetch(url, kind="legal-xml")

    def test_revocation_and_review_window_fail_closed(self):
        revoked = rights_for(self.programme)
        revoked["revocation"] = {
            "status": "revoked",
            "reference": "test:synthetic-rights-fixture/revocation",
            "revokedAt": "2026-10-27T00:00:00Z",
        }
        with self.assertRaisesRegex(AcquisitionError, "rights-review-revoked"):
            ProgrammePolicy(self.programme, self.catalog, revoked, clock=self.clock.datetime)
        overlong = rights_for(self.programme)
        overlong["expiresAt"] = "2026-11-26T00:00:01Z"
        with self.assertRaisesRegex(AcquisitionError, "timestamps"):
            ProgrammePolicy(self.programme, self.catalog, overlong, clock=self.clock.datetime)

    def test_repeat_503_retries_are_finite(self):
        network = Network(self.clock, {URL: response(URL, b"later", 503)})
        self.run_once(network, limits=ProgrammeLimits(max_retries=1))
        self.clock.now += 10
        result, state = self.run_once(network, resume=True)
        self.assertEqual(result["states"]["blocked"], 1)
        self.assertIn("retry-budget-exhausted", next(iter(state["candidates"].values()))["reason"])
        before = len(network.calls)
        self.run_once(network, resume=True)
        self.assertEqual(len(network.calls), before)

    def test_invalid_robots_is_terminal_and_resume_does_not_retry_content(self):
        network = Network(self.clock, robots=b"<html>Offline</html>", robots_type="text/html")
        result, state = self.run_once(network)
        self.assertEqual(result["states"]["blocked"], 1)
        self.assertEqual(len(network.calls), 1)
        self.assertEqual(state["ledger"]["documents"], {})
        self.run_once(network, resume=True)
        self.assertEqual(len(network.calls), 1)

    def test_existing_access_holds_cannot_be_cleared_by_rights_grants(self):
        policy = self.policy(hosts=("www.bclaws.gov.bc.ca", "www.workbc.ca", "www.icbc.com"))
        for url in ("https://www.workbc.ca/", "https://www.bclaws.gov.bc.ca/", "https://www.icbc.com/"):
            with self.subTest(url=url), self.assertRaisesRegex(AcquisitionError, "source-access-hold"):
                policy.validate_url(url)
        housing = self.policy(hosts=("www.bchousing.org",))
        self.assertIn("publisher-freshness-review-required", housing.extraction_flags("https://www.bchousing.org/"))

    def test_workbc_hold_can_only_be_cleared_for_the_explicit_publisher_feed(self):
        rights = rights_for(self.programme, hosts=("www.workbc.ca",))
        rights["grants"][0]["routes"].append({
            "technicalRoute": "publisher-feed",
            "format": "publisher-feed",
            "pathPrefixes": ["/publisher-feed"],
            "clearsAccessHold": "blocked-invalid-robots",
        })
        policy = ProgrammePolicy(self.programme, self.catalog, rights, clock=self.clock.datetime)
        self.assertEqual(
            policy.validate_url(
                "https://www.workbc.ca/publisher-feed",
                kind="publisher-feed",
            ),
            "https://www.workbc.ca/publisher-feed",
        )
        with self.assertRaisesRegex(AcquisitionError, "source-access-hold"):
            policy.validate_url("https://www.workbc.ca/", kind="html")

    def test_rights_binding_rechecks_only_the_exact_hold_clearing_route(self):
        with JsonManifestStore(self.path) as store:
            ProgrammeRun(
                self.policy(False),
                store,
                clock=self.clock,
                sleep=self.clock.sleep,
            ).run()
        rights = rights_for(self.programme, hosts=("www.icbc.com",))
        sitemap = next(
            route for route in rights["grants"][0]["routes"]
            if route["technicalRoute"] == "sitemap-xml"
        )
        sitemap["clearsAccessHold"] = "blocked-publisher-terms"
        with JsonManifestStore(self.path) as store:
            runner = ProgrammeRun(
                ProgrammePolicy(
                    self.programme,
                    self.catalog,
                    rights,
                    clock=self.clock.datetime,
                ),
                store,
                clock=self.clock,
                sleep=self.clock.sleep,
            )
            runner._bind_rights()
            candidates = {candidate["url"]: candidate for candidate in runner.state["candidates"].values()}
            self.assertEqual(candidates["https://www.icbc.com/sitemap.xml"]["state"], "pending")
            self.assertEqual(candidates["https://www.icbc.com/"]["state"], "blocked")
            self.assertIn("source-access-hold", candidates["https://www.icbc.com/"]["reason"])

    def test_unsupported_documents_and_rendered_routes_are_not_faked(self):
        for suffix in (".pdf", ".xml", ".docx", ".zip"):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(AcquisitionError, "unsupported-format"):
                self.policy().validate_url(URL + suffix)
        rights = rights_for(self.programme)
        rights["grants"][0]["routes"].append({
            "technicalRoute": "rendered-html",
            "format": "rendered-html",
            "pathPrefixes": ["/gov/content/health"],
            "clearsAccessHold": None,
        })
        policy = ProgrammePolicy(self.programme, self.catalog, rights, clock=self.clock.datetime)
        self.assertEqual(policy.validate_url(URL, kind="rendered-html"), URL)
        fetcher = Fetcher(url_validator=policy.validate_url, request=Network(self.clock),
                          sleep=lambda _: None)
        with self.assertRaisesRegex(AcquisitionError, "No fetch adapter"):
            fetcher.fetch(URL, kind="rendered-html")
        invalid = deepcopy(rights)
        invalid["grants"][0]["routes"][-1]["format"] = "application/xml"
        with self.assertRaisesRegex(AcquisitionError, "Unsupported or ambiguous"):
            ProgrammePolicy(self.programme, self.catalog, invalid, clock=self.clock.datetime)

    def test_registry_change_cannot_silently_resume_acquired_state(self):
        self.run_once(Network(self.clock))
        updated = deepcopy(self.programme)
        updated["accessObservations"][0]["observation"] += " Synthetic stricter access evidence."
        with JsonManifestStore(self.path) as store:
            with self.assertRaisesRegex(AcquisitionError, "identity changed"):
                ProgrammeRun(ProgrammePolicy(updated, self.catalog, clock=self.clock.datetime),
                             store, clock=self.clock)

    def test_per_host_pacing_survives_resume_and_retry_after(self):
        attempts = [0]

        def page():
            attempts[0] += 1
            if attempts[0] == 1:
                return response(URL, b"slow down", 429, {"content-type": "text/plain", "retry-after": "30"})
            return response(URL)

        network = Network(self.clock, {URL: page})
        first, _ = self.run_once(network)
        self.assertEqual(first["pauseReason"], "retry-after")
        before = len(network.calls)
        result, _ = self.run_once(network, resume=True)
        self.assertEqual(len(network.calls), before)
        self.assertEqual(result["pauseReason"], "retry-after")
        self.clock.now += 30
        result, state = self.run_once(network, resume=True)
        self.assertEqual(result["states"]["candidate"], 1)
        self.assertEqual(next(iter(state["candidates"].values()))["attempts"], 2)
        for previous, current in zip(network.calls, network.calls[1:]):
            self.assertGreaterEqual(current[1] - previous[1], 1)

    def test_retry_budget_and_invalid_retry_after_fail_closed(self):
        network = Network(self.clock, {URL: response(URL, b"later", 503, {"retry-after": "invalid"})})
        result, _ = self.run_once(network)
        self.assertEqual(result["states"]["blocked"], 1)
        self.assertTrue(any("Invalid Retry-After" in reason for reason in result["reasons"]))
        with self.assertRaises(AcquisitionError):
            retry_at("NaN", self.clock(), 1)
        expected = datetime(2026, 10, 28, tzinfo=timezone.utc).timestamp()
        self.assertEqual(retry_at("Wed, 28 Oct 2026 00:00:00 GMT", self.clock(), 1), expected)

    def test_byte_reservations_are_bounded_even_for_failed_or_interrupted_reads(self):
        limits = ProgrammeLimits(total_bytes=100, response_bytes=100)
        network = Network(self.clock, {URL: lambda: (_ for _ in ()).throw(KeyboardInterrupt())})
        result, state = self.run_once(network, limits=limits)
        self.assertEqual(result["pauseReason"], "interrupted")
        self.assertLessEqual(state["budget"]["chargedBytes"], 100)
        self.assertEqual(state["budget"]["chargedBytes"], 100)
        self.assertGreater(state["budget"]["chargedBytes"], state["budget"]["responseBytes"])
        self.clock.now += 10
        result, state = self.run_once(network, resume=True)
        self.assertEqual(result["pauseReason"], "total-byte-budget-exhausted")
        self.assertEqual(len(network.calls), 2)

    def test_unknown_inflight_delivery_is_charged_and_retry_is_finite(self):
        network = Network(self.clock)
        self.run_once(network, acquire=False, limits=ProgrammeLimits(max_retries=0))
        with JsonManifestStore(self.path) as store:
            state = store.load()
            state["status"] = "running"
            candidate = next(iter(state["candidates"].values()))
            candidate.update(state="in-flight", attempts=1)
            state["budget"].update(requests=1, documentRequests=1, chargedBytes=500)
            state["budget"]["inFlight"] = {"url": URL, "reservedBytes": 500, "requestNumber": 1, "robots": False}
            store.save(state)
        result, state = self.run_once(network, resume=True)
        self.assertEqual(network.calls, [])
        self.assertEqual(state["budget"]["chargedBytes"], 500)
        self.assertEqual(result["states"]["blocked"], 1)
        self.assertTrue(any(event["type"] == "interrupted-request" for event in state["events"]))

    def test_operator_pause_signal_and_exclusive_manifest_ownership(self):
        network = Network(self.clock)
        self.run_once(network, acquire=False)
        store = JsonManifestStore(self.path)
        store.request_pause()
        with store:
            with self.assertRaises(AcquisitionError):
                with JsonManifestStore(self.path):
                    pass
            runner = ProgrammeRun(self.policy(), store, clock=self.clock, sleep=self.clock.sleep, request=network)
            result = runner.run(acquire=True)
        self.assertEqual(result["pauseReason"], "operator-pause")
        self.assertEqual(network.calls, [])
        result, _ = self.run_once(network, resume=True)
        self.assertEqual(result["status"], "frontier-exhausted")
        self.assertFalse(store.pause_path.exists())

    def test_stale_checkpoints_and_mutated_raw_objects_are_rejected(self):
        with JsonManifestStore(self.path) as store:
            first = {"revision": 0}
            store.save(first)
            with self.assertRaises(AcquisitionError):
                store.save({"revision": 0})
        objects = LocalResponseStore(self.root / "responses")
        key = objects.put(b"synthetic response")
        self.assertEqual(objects.put(b"synthetic response"), key)
        (self.root / "responses" / (key + ".body")).write_bytes(b"changed")
        with self.assertRaises(AcquisitionError):
            objects.put(b"synthetic response")

    def test_frontier_limit_preserves_unexpanded_links_for_auditable_coverage(self):
        links = "".join(f"<a href='{URL}/{i}'>Page {i}</a>" for i in range(3))
        network = Network(self.clock, {URL: response(URL, html(links=links))})
        result, state = self.run_once(network, limits=ProgrammeLimits(max_candidates=2))
        self.assertEqual(result["pauseReason"], "candidate-frontier-limit")
        self.assertEqual(result["unexpandedLinks"], 2)
        self.assertEqual(len(state["candidates"]), 2)
        before = len(network.calls)
        again, _ = self.run_once(network, resume=True)
        self.assertEqual(again["unexpandedLinks"], 2)
        self.assertEqual(len(network.calls), before)

    def test_sitemap_discovery_is_idempotent_not_legal_xml_extraction(self):
        body = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{URL}</loc></url><url><loc>{URL}</loc></url>"
            f"<url><loc>{URL}.pdf</loc></url></urlset>"
        ).encode()
        network = Network(self.clock, {SITEMAP: response(SITEMAP, body, headers={"content-type": "application/xml"})})
        with JsonManifestStore(self.path) as store:
            runner = ProgrammeRun(self.policy(), store, seeds=[], clock=self.clock,
                                  sleep=self.clock.sleep, request=network)
            runner._add(SITEMAP, "sitemap")
            result = runner.run(acquire=True)
        self.assertEqual(result["sitemaps"], 1)
        self.assertEqual(result["canonicalCandidates"], 2)
        self.assertEqual(result["states"]["unsupported"], 1)
        self.assertEqual(len(runner.ledger.state["documents"]), 1)
        for invalid in (b"<legal-export/>", b"<!DOCTYPE x [<!ENTITY a 'text'>]><x/>", b"<html>Offline</html>"):
            with self.subTest(body=invalid), self.assertRaises(AcquisitionError):
                sitemap_links(response(SITEMAP, invalid, headers={"content-type": "application/xml"}))

    def test_candidate_review_and_publication_remain_separate(self):
        network = Network(self.clock)
        _, state = self.run_once(network)
        ledger = Ledger(state["ledger"])
        candidate = ledger.review_candidates()[0]
        review = {
            "publisherPermissionConfirmed": True, "reviewer": "SYNTHETIC TEST ONLY",
            "reviewedAt": DATE, "documents": [candidate],
        }
        self.assertEqual(build_publish_plan(ledger, self.catalog, programme_policy=self.policy())["uploads"], [])
        with self.assertRaises(AcquisitionError):
            build_publish_plan(ledger, self.catalog, review)
        plan = build_publish_plan(ledger, self.catalog, review, programme_policy=self.policy())
        self.assertTrue(plan["uploads"])
        self.assertIsNone(next(iter(ledger.state["documents"].values()))["activeVersion"])
        review["documents"][0]["reviewHash"] = "wrong"
        self.assertEqual(build_publish_plan(ledger, self.catalog, review, programme_policy=self.policy())["uploads"], [])

    def test_cli_programme_defaults_offline_and_rejects_sample_budget_escape(self):
        with patch("bc_ingestion.fetch.transport", side_effect=AssertionError("No network")), redirect_stdout(io.StringIO()) as output:
            result = main(["programme", "--programme-manifest", str(self.path)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["budget"]["requests"], 0)
        self.assertTrue((self.root / "coverage.json").exists())
        review = json.loads((self.root / "review-required.json").read_text())
        self.assertIs(review["publisherPermissionConfirmed"], False)
        for extra in (["--max-pages", "500"], ["--acquire"], ["--execute"], ["--resume"]):
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                self.assertEqual(main(["programme", "--programme-manifest", str(self.path), *extra]), 2)

    def test_cli_exact_review_plan_updates_counts_without_publishing(self):
        _, state = self.run_once(Network(self.clock))
        review = {
            "publisherPermissionConfirmed": True, "reviewer": "SYNTHETIC TEST ONLY", "reviewedAt": DATE,
            "documents": Ledger(state["ledger"]).review_candidates(),
        }
        review_file, rights_file = self.root / "synthetic-review.json", self.root / "synthetic-rights.json"
        review_file.write_text(json.dumps(review), encoding="utf-8")
        rights_file.write_text(json.dumps(rights_for(self.programme)), encoding="utf-8")
        with patch("bc_ingestion.fetch.transport", side_effect=AssertionError("No network")), \
                patch("bc_ingestion.azure_publish._execute", side_effect=AssertionError("No Azure")), \
                redirect_stdout(io.StringIO()) as output:
            result = main([
                "programme", "--programme-manifest", str(self.path),
                "--rights-review", str(rights_file), "--review-manifest", str(review_file),
            ])
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["exactReviewedCurrentDocuments"], 1)
        self.assertEqual(report["publishedDocuments"], 0)
        self.assertEqual(report["publication"]["mode"], "dry-run")
        self.assertTrue((ROOT / report["reviewPlan"]).exists())

    def test_programme_publish_without_rights_is_not_an_implicit_withdrawal(self):
        self.run_once(Network(self.clock))
        before = self.path.read_bytes()
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            result = main(["publish", "--programme-manifest", str(self.path)])
        self.assertEqual(result, 2)
        self.assertEqual(self.path.read_bytes(), before)


def urlsplit_path(url):
    from urllib.parse import urlsplit
    return urlsplit(url).path


if __name__ == "__main__":
    unittest.main()
