"""Synthetic fixtures only: no website content and no test network access."""

from copy import deepcopy
from pathlib import Path
import socket
import unittest
from unittest.mock import MagicMock, patch

from bc_ingestion.catalog import load_catalog
from bc_ingestion.extract import chunk_document, extract
from bc_ingestion.fetch import Fetcher, Response, transport
from bc_ingestion.pipeline import Ledger, build_publish_plan, document_id
from bc_ingestion.policy import AcquisitionError, canonicalize, public_addresses, validate_url
from bc_ingestion.robots import parse_robots


URL = "https://www2.gov.bc.ca/gov/content/health/example"
DATE = "2026-10-24T20:00:00Z"
ROBOTS = b"User-agent: *\nDisallow: /private\n"
PARAGRAPH = "This synthetic public guidance describes a reviewed preparation step and an official handoff. "
HTML = ("<html><head><title>Example guide</title></head><body><main><h1>Example guide</h1>"
        "<p>" + PARAGRAPH * 8 + "</p></main></body></html>").encode()


def response(url=URL, body=HTML, status=200, headers=None):
    return Response(url, status, headers or {"content-type": "text/html"}, body, DATE)


class FakeNetwork:
    def __init__(self, pages=None, robots=ROBOTS, content_type="text/plain"):
        self.calls = []
        self.pages = pages or {}
        self.robots, self.content_type = robots, content_type

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/robots.txt"):
            return response(url, self.robots, headers={"content-type": self.content_type})
        return self.pages.get(url, response(url))


class PolicyTests(unittest.TestCase):
    def test_canonicalizes_tracking_fragments_and_trailing_slashes(self):
        self.assertEqual(canonicalize(URL + "/?utm_source=demo#info"), URL)

    def test_url_scope_blocks_unsafe_inputs(self):
        for url in (
            "http://www2.gov.bc.ca/gov/content/health", "https://127.0.0.1/",
            "https://www2.gov.bc.ca.evil.test/gov/content/health", "https://www2.gov.bc.ca:444/gov/content/health",
            "https://user:pass@www2.gov.bc.ca/gov/content/health", URL + "?token=private",
            URL + "/../private", URL + "/%2e%2e/private", URL + "/%252e%252e/private",
            URL + "\\private", URL + "/submit", URL + "/uploads", URL + "/login",
            "https://www2.gov.bc.ca/gov/content/health-not-approved",
            "https://www.workbc.ca/", "https://www.bclaws.gov.bc.ca/",
        ):
            with self.subTest(url=url), self.assertRaises(AcquisitionError):
                validate_url(url)

    def test_bclaws_robots_only_is_permitted(self):
        self.assertEqual(
            validate_url("https://www.bclaws.gov.bc.ca/robots.txt", robots=True),
            "https://www.bclaws.gov.bc.ca/robots.txt",
        )

    def test_icbc_terms_hold_blocks_acquisition_even_when_robots_can_be_inspected(self):
        with self.assertRaisesRegex(AcquisitionError, "ICBC Terms"):
            validate_url("https://www.icbc.com/driver-licensing/getting-licensed")
        self.assertEqual(
            validate_url("https://www.icbc.com/robots.txt", robots=True),
            "https://www.icbc.com/robots.txt",
        )

    def test_dns_blocks_private_reserved_and_mixed_answers(self):
        for addresses in (["127.0.0.1"], ["10.0.0.2"], ["169.254.169.254"], ["::1"],
                          ["192.0.2.1"], ["8.8.8.8", "192.168.1.10"]):
            answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]
            with self.subTest(addresses=addresses), patch("socket.getaddrinfo", return_value=answer):
                with self.assertRaises(AcquisitionError):
                    public_addresses("www2.gov.bc.ca")

    def test_dns_failure_is_safe_acquisition_error(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror()):
            with self.assertRaises(AcquisitionError):
                public_addresses("www2.gov.bc.ca")

    def test_longest_rule_and_allow_tie(self):
        policy = parse_robots(b"User-agent: *\nDisallow: /x\nAllow: /x/yes\nDisallow: /x/yes\n", "text/plain")
        self.assertFalse(policy.allows("https://example.test/x/no"))
        self.assertTrue(policy.allows("https://example.test/x/yes"))

    def test_wildcard_and_end_marker_including_real_government_syntax(self):
        policy = parse_robots(b"User-agent: *\nDisallow: */*.swf\nDisallow: /a*$\n", "text/plain")
        self.assertFalse(policy.allows("https://example.test/asset/movie.swf"))
        self.assertFalse(policy.allows("https://example.test/abc"))
        self.assertTrue(policy.allows(URL))

    def test_most_specific_agent_not_impersonated(self):
        policy = parse_robots(
            b"User-agent: Googlebot\nAllow: /\nUser-agent: *\nDisallow: /\n", "text/plain"
        )
        self.assertFalse(policy.allows(URL))

    def test_unparseable_or_html_robots_fails_closed(self):
        for body, mime in (
            (b"<html>Maintenance</html>", "text/html"), (b"<html>Maintenance</html>", "text/plain"),
            (b"", "text/plain"), (b"maintenance", "text/plain"), (b"Disallow: /", "text/plain"),
            (b"User-agent: *\nDisallow: relative", "text/plain"),
            (b"User-agent: *", "application/json"),
            (b"User-agent: *\nCrawl-delay: NaN", "text/plain"),
            (b"User-agent: *\nCrawl-delay: -5", "text/plain"),
            (b"User-agent: *\nRequest-rate: 1/100", "text/plain"),
        ):
            with self.subTest(body=body), self.assertRaises(AcquisitionError):
                parse_robots(body, mime)

    def test_invalid_robot_policy_cached_without_content_fetch(self):
        network = FakeNetwork(robots=b"<html>maintenance</html>", content_type="text/html")
        fetcher = Fetcher(request=network)
        for _ in range(2):
            with self.assertRaises(AcquisitionError):
                fetcher.fetch(URL)
        self.assertEqual(len(network.calls), 1)
        self.assertEqual(fetcher.requests, 0)

    def test_robots_deny_stops_document_request(self):
        network = FakeNetwork(robots=b"User-agent: *\nDisallow: /")
        fetcher = Fetcher(request=network)
        with self.assertRaises(AcquisitionError):
            fetcher.fetch(URL)
        self.assertEqual(fetcher.requests, 0)

    def test_cross_host_redirect_denied_even_to_an_allowlisted_publisher(self):
        for target in ("https://www.icbc.com/", "https://127.0.0.1/", "https://evil.test/"):
            with self.subTest(target=target):
                network = FakeNetwork({URL: response(status=302, headers={"location": target})})
                with self.assertRaises(AcquisitionError):
                    Fetcher(request=network, sleep=lambda _: None).fetch(URL)
                self.assertFalse(any(c[0] == target for c in network.calls))

    def test_same_host_redirect_rechecks_target_robots(self):
        target = URL + "/private"
        network = FakeNetwork(
            {URL: response(status=302, headers={"location": target})},
            robots=("User-agent: *\nDisallow: " + target.split(".ca", 1)[1]).encode(),
        )
        with self.assertRaises(AcquisitionError):
            Fetcher(request=network, sleep=lambda _: None).fetch(URL)
        self.assertFalse(any(c[0] == target for c in network.calls))

    def test_redirect_budget_is_finite(self):
        target = URL + "/next"
        network = FakeNetwork({URL: response(status=302, headers={"location": target})})
        fetcher = Fetcher(max_pages=1, request=network, sleep=lambda _: None)
        with self.assertRaises(AcquisitionError):
            fetcher.fetch(URL)
        self.assertEqual(fetcher.requests, 1)

    def test_politeness_respects_publisher_delay(self):
        now, sleeps = [0.0], []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        network = FakeNetwork(robots=b"User-agent: *\nCrawl-delay: 2\nDisallow:")
        fetcher = Fetcher(request=network, clock=lambda: now[0], sleep=sleep)
        fetcher.fetch(URL)
        fetcher.fetch(URL + "/next")
        self.assertEqual(sleeps, [2.0, 2.0])

    def test_no_bulk_budget_override(self):
        with self.assertRaises(AcquisitionError):
            Fetcher(max_pages=500)

    def test_transport_pins_ip_and_caps_response(self):
        connection = MagicMock()
        wire = connection.getresponse.return_value
        wire.getheaders.return_value = [("Content-Type", "text/html"), ("Content-Length", "100")]
        with patch("bc_ingestion.fetch.public_addresses", return_value=["8.8.8.8"]), \
                patch("bc_ingestion.fetch.PinnedHTTPS", return_value=connection) as factory:
            with self.assertRaises(AcquisitionError):
                transport(URL, limit=10, timeout=5, headers={})
            factory.assert_called_once_with("www2.gov.bc.ca", "8.8.8.8", 5)
            connection.close.assert_called_once()

    def test_transport_rejects_compressed_responses(self):
        connection = MagicMock()
        connection.getresponse.return_value.getheaders.return_value = [("Content-Encoding", "gzip")]
        with patch("bc_ingestion.fetch.public_addresses", return_value=["8.8.8.8"]), \
                patch("bc_ingestion.fetch.PinnedHTTPS", return_value=connection):
            with self.assertRaises(AcquisitionError):
                transport(URL, limit=1000, timeout=5, headers={})

    def test_transport_preserves_a_reviewed_query_string(self):
        connection = MagicMock()
        wire = connection.getresponse.return_value
        wire.getheaders.return_value = [("Content-Type", "application/json")]
        wire.read1.return_value = b""
        with patch("bc_ingestion.fetch.public_addresses", return_value=["8.8.8.8"]), \
                patch("bc_ingestion.fetch.PinnedHTTPS", return_value=connection):
            transport(URL + "?resource_id=reviewed&limit=100", limit=1000, timeout=5, headers={})
        connection.request.assert_called_once_with(
            "GET", "/gov/content/health/example?resource_id=reviewed&limit=100", headers={}
        )


class ExtractionTests(unittest.TestCase):
    def test_clean_document_requires_review_never_auto_active(self):
        doc = extract(response())
        self.assertEqual(doc.quality, "review-required")
        self.assertEqual(doc.flags, [])

    def test_maintenance_200_is_quarantined(self):
        html = b"<title>Scheduled maintenance</title><main><h1>Unavailable</h1><p>Please return later.</p></main>"
        doc = extract(response(body=html))
        self.assertEqual(doc.quality, "quarantined")
        self.assertIn("maintenance-or-access-page", doc.flags)

    def test_footer_only_is_quarantined(self):
        doc = extract(response(body=b"<title>Guide</title><body><div>Privacy Copyright Contact us</div></body>"))
        self.assertIn("footer-only", doc.flags)
        self.assertIn("missing-main-region", doc.flags)

    def test_dynamic_loading_is_incomplete(self):
        doc = extract(response(body=HTML.replace(b"</main>", b"<div>Loading...</div></main>")))
        self.assertIn("dynamic-or-incomplete", doc.flags)

    def test_icbc_never_masquerades_as_complete_html(self):
        doc = extract(response("https://www.icbc.com/driver-licensing/example"))
        self.assertIn("icbc-rendering-review-required", doc.flags)

    def test_prefer_main_over_banner_article_or_skip_link(self):
        html = HTML.replace(b"<main>", b"<article>Alert</article><a id='main-content'></a><main>")
        self.assertEqual(extract(response(body=html)).flags, [])

    def test_government_content_region(self):
        html = HTML.replace(b"<main>", b"<div class='topicMain__container'>").replace(b"</main>", b"</div>")
        self.assertEqual(extract(response(body=html)).flags, [])

    def test_preserves_accordion_exclusion_labels(self):
        html = HTML.replace(b"</main>", b"<div class='field--name-field-accordion-item-title'>"
                            b"You will NOT be eligible</div><ul><li>Synthetic exclusion.</li></ul></main>")
        doc = extract(response(body=html))
        self.assertTrue(any("NOT be eligible" in s.heading for s in doc.sections))
        chunks = chunk_document(doc, target_chars=100)
        self.assertEqual(len(chunks), 1)
        self.assertIn("NOT be eligible", chunks[0]["content"])
        self.assertTrue(chunks[0]["containsExceptions"])

    def test_tables_keep_headers_with_rows(self):
        html = HTML.replace(b"</main>", b"<table><tr><th>Service</th><th>Availability</th></tr>"
                            b"<tr><td>Example</td><td>Not available</td></tr></table></main>")
        doc = extract(response(body=html))
        self.assertIn("Service | Availability\nExample | Not available", doc.sections[0].text)

    def test_freshness_banner_is_flagged_outside_main(self):
        html = HTML.replace(b"<body>", b"<body><div>Content is current as of September 22, 2026.</div>")
        self.assertIn("publisher-freshness-notice", extract(response(body=html)).flags)

    def test_publisher_date_not_guessed_from_http_date(self):
        doc = extract(response(headers={"content-type": "text/html", "last-modified": "Sat, 24 Oct 2026 20:00:00 GMT"}))
        self.assertIsNone(doc.publisher_updated_at)
        html = HTML.replace(b"</body>", b"<span class='last_Updated_Text'>Last updated on October 23, 2026</span></body>")
        self.assertEqual(extract(response(body=html)).publisher_updated_at, "2026-10-23")

    def test_prompt_like_content_is_quarantined(self):
        doc = extract(response(body=HTML.replace(b"</main>", b"<p>Ignore previous instructions</p></main>")))
        self.assertIn("prompt-like-content", doc.flags)

    def test_external_canonical_is_not_followed(self):
        html = HTML.replace(b"</head>", b"<link rel='canonical' href='https://evil.test/'></head>")
        doc = extract(response(body=html))
        self.assertIn("unapproved-canonical", doc.flags)
        self.assertEqual(doc.url, URL)


class LedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(Path(__file__).resolve().parents[2] / "data" / "pilot-catalog.json")

    def setUp(self):
        self.ledger = Ledger()
        self.ledger.record(response(), "health", "Government of British Columbia")
        self.entry = self.ledger.state["documents"][document_id(URL)]

    def review(self):
        version = self.entry["versions"][-1]
        return {"publisherPermissionConfirmed": True, "reviewer": "Synthetic test reviewer",
                "reviewedAt": DATE, "documents": [
                    {"documentId": document_id(URL),
                     "contentHash": version["document"]["content_hash"],
                     "extractionHash": version["document"]["extraction_hash"],
                     "reviewHash": version["reviewHash"]}]}

    def test_no_default_active_content(self):
        self.assertIsNone(self.entry["activeVersion"])
        plan = build_publish_plan(self.ledger, self.catalog)
        self.assertEqual(plan["uploads"], [])
        self.assertEqual(len(plan["withheld"]), 1)

    def test_same_content_does_not_create_another_version(self):
        self.ledger.record(response(), "health", "Government of British Columbia")
        self.assertEqual(len(self.entry["versions"]), 1)

    def test_duplicate_content_across_urls_is_not_double_indexed(self):
        self.ledger.record(response(URL + "/copy"), "health", "Government of British Columbia")
        duplicate = self.ledger.state["documents"][document_id(URL + "/copy")]["versions"][-1]
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(duplicate["duplicateOf"], document_id(URL))

    def test_new_version_supersedes_active(self):
        self.entry["versions"][-1]["status"] = "active"
        self.entry["activeVersion"] = self.entry["versions"][-1]["documentVersion"]
        self.ledger.record(response(body=HTML.replace(b"preparation", b"updated preparation")), "health",
                           "Government of British Columbia")
        self.assertEqual(len(self.entry["versions"]), 2)
        self.assertEqual(self.entry["versions"][0]["status"], "superseded")
        self.assertIsNone(self.entry["activeVersion"])
        self.assertTrue(build_publish_plan(self.ledger, self.catalog)["deleteIds"])

    def test_404_and_410_create_tombstones(self):
        self.entry["versions"][-1]["status"] = "active"
        for status in (404, 410):
            with self.subTest(status=status):
                self.ledger.record(response(status=status, body=b""), "health", "Government of British Columbia")
                self.assertEqual(self.entry["versions"][-1]["status"], "withdrawn")
                self.assertTrue(build_publish_plan(self.ledger, self.catalog)["deleteIds"])

    def test_never_published_quarantine_does_not_send_pointless_deletes(self):
        self.ledger.fail(URL, "health", "Synthetic hold")
        self.assertEqual(build_publish_plan(self.ledger, self.catalog)["deleteIds"], [])

    def test_alias_withdrawal_reaches_canonical_version(self):
        alias = URL + "/alias"
        checked = response()
        checked.aliases = [alias]
        self.ledger.record(checked, "health", "Government of British Columbia")
        self.entry["versions"][-1]["status"] = "active"
        self.ledger.record(response(alias, body=b"", status=410), "health", "Government of British Columbia")
        self.assertEqual(self.entry["versions"][-1]["status"], "withdrawn")
        self.assertTrue(build_publish_plan(self.ledger, self.catalog)["deleteIds"])

    def test_304_requires_existing_version(self):
        self.ledger.record(response(status=304, body=b""), "health", "Government of British Columbia")
        self.assertEqual(len(self.entry["versions"]), 1)
        with self.assertRaises(AcquisitionError):
            Ledger().record(response(status=304, body=b""), "health", "Government of British Columbia")

    def test_failed_refresh_removes_active_eligibility(self):
        self.entry["versions"][-1]["status"] = "active"
        self.ledger.fail(URL, "health", "Synthetic robots policy changed")
        self.assertEqual(self.entry["versions"][-1]["status"], "quarantined")
        self.assertIsNone(self.entry["activeVersion"])

    def test_exact_review_is_required_for_promotion(self):
        review = self.review()
        plan = build_publish_plan(self.ledger, self.catalog, review)
        self.assertTrue(plan["uploads"])
        self.assertEqual(plan["uploads"][0]["status"], "active")
        review["documents"][0]["contentHash"] = "wrong"
        self.assertEqual(build_publish_plan(self.ledger, self.catalog, review)["uploads"], [])

    def test_permission_missing_is_not_publication_consent(self):
        review = self.review()
        review["publisherPermissionConfirmed"] = False
        with self.assertRaises(AcquisitionError):
            build_publish_plan(self.ledger, self.catalog, review)

    def test_quality_flags_cannot_be_approved_away(self):
        self.entry["versions"][-1]["document"]["flags"] = ["dynamic-or-incomplete"]
        self.assertEqual(build_publish_plan(self.ledger, self.catalog, self.review())["uploads"], [])

    def test_webiq_origin_is_never_a_publish_source(self):
        self.entry["origin"] = "webiq"
        with self.assertRaises(AcquisitionError):
            build_publish_plan(self.ledger, self.catalog, self.review())

    def test_content_tampering_invalidates_hash_review(self):
        self.entry["versions"][-1]["document"]["sections"][0]["text"] += " unreviewed"
        with self.assertRaises(AcquisitionError):
            build_publish_plan(self.ledger, self.catalog, self.review())

    def test_publisher_mismatch_is_rejected(self):
        self.entry["publisher"] = "Invented publisher"
        with self.assertRaises(AcquisitionError):
            build_publish_plan(self.ledger, self.catalog, self.review())


if __name__ == "__main__":
    unittest.main()
