"""Bounded offline fixtures for source-specific grounding adapters."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import unittest
import uuid

from bc_ingestion.adapter_bundle import write_adapter_bundle
from bc_ingestion.cli import main
from bc_ingestion.fetch import Response
from bc_ingestion.legal_xml import parse_bc_laws_civix
from bc_ingestion.metadata import (
    LEGAL_XML_EXTRACTION_METHOD,
    PUBLISHER_FEED_EXTRACTION_METHOD,
    RENDERED_HTML_EXTRACTION_METHOD,
)
from bc_ingestion.pipeline import Ledger, build_publish_plan
from bc_ingestion.policy import AcquisitionError
from bc_ingestion.source_adapters import (
    adapt_bc_housing_html,
    adapt_healthlink_html,
    adapt_icbc_publisher_feed,
    adapt_icbc_rendered_html,
    adapt_programme_html,
    adapt_workbc_publisher_feed,
    adapt_workbc_static_html,
    classify_province_route,
    classify_workbc_record,
    classify_workbc_route,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
DATE = "2026-10-27T18:30:00Z"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def response(url: str, name: str, content_type="text/html") -> Response:
    return Response(url, 200, {"content-type": content_type}, fixture(name), DATE)


class ProvinceAndPublisherHtmlTests(unittest.TestCase):
    def test_province_routes_keep_broad_and_specific_tags(self):
        health = classify_province_route(
            "https://www2.gov.bc.ca/gov/content/health/health-drug-coverage"
        )
        self.assertEqual(health.source_ids, ("bc-content", "health"))
        self.assertIn("msp", health.topics)
        self.assertIn("government-programmes", health.topics)
        service = classify_province_route(
            "https://www2.gov.bc.ca/gov/content/governments/organizational-structure/"
            "ministries-organizations/ministries/citizens-services/servicebc/locations"
        )
        self.assertEqual(service.source_ids, ("bc-content", "service-bc"))
        generic = classify_province_route(
            "https://www2.gov.bc.ca/gov/content/education-training"
        )
        self.assertEqual(generic.source_ids, ("bc-content",))

    def test_programme_registry_applies_canonical_overlap_tags(self):
        body = (
            "<html lang='en-CA'><head><title>Health guidance</title></head>"
            "<body><main><h1>Health guidance</h1><p>"
            + "Complete synthetic Province guidance with official context. " * 12
            + "</p></main></body></html>"
        ).encode()
        document = adapt_programme_html(Response(
            "https://www2.gov.bc.ca/gov/content/health/synthetic",
            200,
            {"content-type": "text/html"},
            body,
            DATE,
        ))
        self.assertEqual(document.metadata["sourceIds"], ["bc-content", "health"])
        self.assertIn("public-health", document.metadata["topics"])

    def test_bc_housing_freeze_notice_is_explicit_quality_and_date_metadata(self):
        document = adapt_bc_housing_html(response(
            "https://www.bchousing.org/housing-assistance/rental-assistance-programs/rap",
            "bc_housing_paused.html",
        ))
        self.assertEqual(document.publisher_updated_at, "2026-09-22")
        self.assertIn("publisher-updates-paused", document.flags)
        self.assertIn("publisher-freshness-review-required", document.flags)
        self.assertEqual(document.quality, "quarantined")

    def test_healthlink_separates_government_navigation_from_third_party_clinical(self):
        administrative = adapt_healthlink_html(response(
            "https://www.healthlinkbc.ca/find-care/health-connect-registry",
            "healthlink_admin.html",
        ))
        self.assertNotIn("healthlink-third-party-clinical-content", administrative.flags)
        self.assertIn("health-connect-registry", administrative.metadata["topics"])
        clinical = adapt_healthlink_html(response(
            "https://www.healthlinkbc.ca/health-topics/synthetic",
            "healthlink_third_party.html",
        ))
        self.assertIn("healthlink-third-party-clinical-content", clinical.flags)
        self.assertIn("healthlink-third-party-rights-review-required", clinical.flags)
        self.assertIn("healthlink-publisher-date-missing", clinical.flags)


class IcbcAndWorkBcContractTests(unittest.TestCase):
    ICBC_URL = (
        "https://www.icbc.com/driver-licensing/getting-licensed/"
        "renew-your-licence-or-id"
    )

    def test_icbc_controlled_render_requires_complete_canonical_main(self):
        adapted = adapt_icbc_rendered_html(
            response(self.ICBC_URL, "icbc_rendered.html"),
            complete_main=True,
        )
        self.assertEqual(adapted.document.extraction_method, RENDERED_HTML_EXTRACTION_METHOD)
        self.assertNotIn("icbc-rendering-review-required", adapted.document.flags)
        with self.assertRaises(AcquisitionError):
            adapt_icbc_rendered_html(
                response(self.ICBC_URL, "icbc_rendered.html"),
                complete_main=False,
            )
        with self.assertRaises(AcquisitionError):
            adapt_icbc_rendered_html(
                response(
                    "https://icbc.com/driver-licensing/getting-licensed/renew-your-licence-or-id",
                    "icbc_rendered.html",
                ),
                complete_main=True,
            )

    def test_icbc_excludes_personal_transaction_routes(self):
        for segment in ("account", "booking", "payment", "personal"):
            with self.subTest(segment=segment), self.assertRaises(AcquisitionError):
                adapt_icbc_rendered_html(
                    response(f"https://www.icbc.com/{segment}/fixture", "icbc_rendered.html"),
                    complete_main=True,
                )

    def test_icbc_complete_publisher_feed_is_adapted_offline(self):
        adapted = adapt_icbc_publisher_feed(response(
            "https://www.icbc.com/publisher-feed",
            "icbc_feed.json",
            "application/feed+json",
        ))
        self.assertEqual(len(adapted), 1)
        self.assertEqual(
            adapted[0].document.extraction_method,
            PUBLISHER_FEED_EXTRACTION_METHOD,
        )
        self.assertEqual(adapted[0].document.publisher_updated_at, "2026-10-18")
        changed = json.loads(fixture("icbc_feed.json"))
        changed["items"][0]["contentComplete"] = False
        invalid = Response(
            "https://www.icbc.com/publisher-feed",
            200,
            {"content-type": "application/feed+json"},
            json.dumps(changed).encode(),
            DATE,
        )
        with self.assertRaises(AcquisitionError):
            adapt_icbc_publisher_feed(invalid)

    def test_workbc_static_guidance_is_separate_from_jobs_and_offline_pages(self):
        adapted = adapt_workbc_static_html(response(
            "https://www.workbc.ca/explore-training-and-education",
            "workbc_static.html",
        ))
        self.assertEqual(adapted.adapter_id, "workbc-static-html-v1")
        self.assertEqual(
            classify_workbc_route("https://www.workbc.ca/job-search").content_class,
            "live-job-board",
        )
        self.assertEqual(
            classify_workbc_record({"recordType": "job-posting"}),
            "live-job-board",
        )
        self.assertEqual(
            classify_workbc_record({"contentType": "training"}),
            "approved-static",
        )
        with self.assertRaises(AcquisitionError):
            adapt_workbc_static_html(response(
                "https://www.workbc.ca/job-search",
                "workbc_static.html",
            ))
        with self.assertRaises(AcquisitionError):
            adapt_workbc_static_html(response(
                "https://www.workbc.ca/explore-training-and-education",
                "workbc_offline.html",
            ))

    def test_workbc_feed_reports_live_jobs_as_excluded_records(self):
        result = adapt_workbc_publisher_feed(response(
            "https://www.workbc.ca/publisher-feed",
            "workbc_feed.json",
            "application/feed+json",
        ))
        self.assertEqual(len(result.documents), 1)
        self.assertEqual(
            result.documents[0].document.extraction_method,
            PUBLISHER_FEED_EXTRACTION_METHOD,
        )
        self.assertEqual(
            result.excluded,
            [{"id": "job-123", "reason": "live-job-board-record"}],
        )

    def test_adapter_availability_does_not_clear_icbc_or_workbc_holds(self):
        catalog = json.loads((ROOT / "data" / "pilot-catalog.json").read_text(encoding="utf-8"))
        candidates = [
            adapt_icbc_rendered_html(
                response(self.ICBC_URL, "icbc_rendered.html"),
                complete_main=True,
            ),
            adapt_workbc_static_html(response(
                "https://www.workbc.ca/explore-training-and-education",
                "workbc_static.html",
            )),
        ]
        for adapted in candidates:
            with self.subTest(adapter=adapted.adapter_id):
                ledger = Ledger()
                ledger.record(
                    adapted.response,
                    adapted.source_id,
                    adapted.publisher,
                    document=adapted.document,
                    acquisition_mode="source-adapter",
                    origin="source-adapter",
                    adapter_id=adapted.adapter_id,
                )
                review = {
                    "publisherPermissionConfirmed": True,
                    "reviewer": "SYNTHETIC TEST ONLY",
                    "reviewedAt": DATE,
                    "documents": ledger.review_candidates(),
                }
                plan = build_publish_plan(ledger, catalog, review)
                self.assertEqual(plan["uploads"], [])
                self.assertTrue(plan["withheld"])


class BcLawsContractTests(unittest.TestCase):
    URL = "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/24001"
    EVIDENCE = "https://www.bclaws.gov.bc.ca/standards/Licence.html"

    def parse(self, name="bc_laws_current.xml", **kwargs):
        return parse_bc_laws_civix(
            response(self.URL, name, "application/xml"),
            evidence_url=self.EVIDENCE,
            **kwargs,
        )

    def test_civix_parser_emits_current_legal_identity_and_sections(self):
        adapted = self.parse()
        document = adapted.document
        self.assertEqual(adapted.source_identity, "SBC-2024-c-1")
        self.assertEqual(document.extraction_method, LEGAL_XML_EXTRACTION_METHOD)
        self.assertEqual(document.metadata["legal"]["status"], "in-force")
        self.assertEqual(document.metadata["legal"]["consolidationDate"], "2026-10-01")
        self.assertEqual(document.metadata["legal"]["effectiveFrom"], "2024-01-01")
        self.assertEqual(document.metadata["legal"]["amendmentIds"], ["SBC-2025-c-2"])
        self.assertEqual(
            [section.locator for section in document.sections],
            ["section-1", "section-2"],
        )
        self.assertEqual(document.metadata["legal"]["evidenceUrl"], self.EVIDENCE)

    def test_civix_parser_fails_closed_on_ambiguous_or_noncurrent_status(self):
        missing = fixture("bc_laws_current.xml").replace(b'status="in-force"', b"")
        with self.assertRaises(AcquisitionError):
            parse_bc_laws_civix(
                Response(self.URL, 200, {"content-type": "application/xml"}, missing, DATE),
                evidence_url=self.EVIDENCE,
            )
        for token in (b'historical="false"', b'consolidationDate="2026-10-01"'):
            with self.subTest(token=token), self.assertRaises(AcquisitionError):
                parse_bc_laws_civix(
                    Response(
                        self.URL,
                        200,
                        {"content-type": "application/xml"},
                        fixture("bc_laws_current.xml").replace(token, b""),
                        DATE,
                    ),
                    evidence_url=self.EVIDENCE,
                )
        with self.assertRaises(AcquisitionError):
            self.parse("bc_laws_historical.xml")
        historical = self.parse("bc_laws_historical.xml", require_current=False)
        self.assertEqual(historical.document.metadata["legal"]["status"], "historical")
        self.assertTrue(historical.document.metadata["legal"]["isHistorical"])

    def test_civix_parser_is_not_a_sitemap_parser(self):
        sitemap = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{self.URL}</loc></url></urlset>"
        ).encode()
        with self.assertRaises(AcquisitionError):
            parse_bc_laws_civix(
                Response(self.URL, 200, {"content-type": "application/xml"}, sitemap, DATE),
                evidence_url=self.EVIDENCE,
            )
        with self.assertRaises(AcquisitionError):
            parse_bc_laws_civix(
                Response(
                    self.URL,
                    200,
                    {"content-type": "application/xml"},
                    b"<!DOCTYPE x [<!ENTITY a 'text'>]><act>&a;</act>",
                    DATE,
                ),
                evidence_url=self.EVIDENCE,
            )

    def test_adapter_bundle_generates_review_and_chunks_without_publication(self):
        output = ROOT / "ingestion" / ".generated" / ("adapter-" + uuid.uuid4().hex)
        try:
            result = write_adapter_bundle(self.parse(), output)
            self.assertFalse(result["publicationApproved"])
            review = json.loads((output / "review-required.json").read_text())
            chunks = json.loads((output / "chunks.json").read_text())
            self.assertEqual(review["documents"][0]["adapterId"], "bc-laws-civix-xml-v1")
            self.assertEqual(review["documents"][0]["sourceIdentity"], "SBC-2024-c-1")
            self.assertEqual(chunks["documentCount"], 1)
            self.assertGreaterEqual(chunks["chunkCount"], 1)
        finally:
            if output.exists():
                shutil.rmtree(output)

    def test_legal_adapter_does_not_clear_pending_source_status(self):
        adapted = self.parse()
        ledger = Ledger()
        ledger.record(
            adapted.response,
            adapted.source_id,
            adapted.publisher,
            document=adapted.document,
            acquisition_mode="source-adapter",
            origin="source-adapter",
            adapter_id=adapted.adapter_id,
        )
        review = {
            "publisherPermissionConfirmed": True,
            "reviewer": "SYNTHETIC TEST ONLY",
            "reviewedAt": DATE,
            "documents": ledger.review_candidates(),
        }
        catalog = json.loads((ROOT / "data" / "pilot-catalog.json").read_text(encoding="utf-8"))
        plan = build_publish_plan(ledger, catalog, review)
        self.assertEqual(plan["uploads"], [])
        self.assertTrue(plan["withheld"])

    def test_offline_cli_writes_review_bundle_without_catalog_or_network(self):
        output = ROOT / "ingestion" / ".generated" / ("adapter-cli-" + uuid.uuid4().hex)
        try:
            with redirect_stdout(io.StringIO()) as stdout:
                status = main([
                    "adapt-source",
                    "--adapter", "bc-laws-civix",
                    "--source-url", self.URL,
                    "--evidence-url", self.EVIDENCE,
                    "--response-file", str(FIXTURES / "bc_laws_current.xml"),
                    "--checked-at", DATE,
                    "--output", str(output),
                    "--catalog", str(output / "deliberately-unused-catalog.json"),
                ])
            self.assertEqual(status, 0)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["publicationApproved"])
            self.assertTrue((ROOT / result["reviewCandidates"]).exists())
        finally:
            if output.exists():
                shutil.rmtree(output)


if __name__ == "__main__":
    unittest.main()
