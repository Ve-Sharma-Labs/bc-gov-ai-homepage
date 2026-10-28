"""Contract and location fixtures are synthetic; the shipped catalogue is real."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from bc_ingestion.azure_publish import publish
from bc_ingestion.catalog import load_catalog, validate_catalog
from bc_ingestion.cli import main
from bc_ingestion.locations import parse_service_bc_offices
from bc_ingestion.policy import AcquisitionError, SERVICE_BC
from bc_ingestion.fetch import Fetcher, Response


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "data" / "pilot-catalog.json"
SOURCE = "https://www2.gov.bc.ca" + SERVICE_BC
DATE = "2026-10-24T20:00:00Z"


def office_fixture(info):
    return ("""
    <main><a id="services"></a><h2>Popular services</h2>
    <p>ICBC driver licensing</p><p>Income and disability assistance</p>
    <p>BC Services Card account setup and BCeID registration</p>
    <table><thead><tr><th>Location</th><th>Address and contact details</th>
    <th>Hours</th><th>More information</th></tr></thead><tbody><tr>
    <th scope="row">Fixture Town</th><td><a href="https://maps.example.test/">123 Example Street</a></td>
    <td>Monday to Friday; closed at lunch</td><td>""" + info + "</td></tr></tbody></table></main>").encode()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CATALOG)

    def test_shipped_exact_contract(self):
        self.assertEqual(len(self.catalog["sources"]), 12)
        self.assertEqual(len(self.catalog["journeys"]), 7)
        self.assertEqual(len(self.catalog["locations"]), 7)
        for journey in self.catalog["journeys"]:
            self.assertIn("Curated", journey["notice"])

    def test_bad_source_reference_is_rejected(self):
        self.catalog["journeys"][0]["steps"][0]["sourceIds"] = ["invented"]
        with self.assertRaises(AcquisitionError):
            validate_catalog(self.catalog)

    def test_blocked_source_cannot_substantiate_steps(self):
        self.catalog["journeys"][0]["sourceIds"].append("workbc")
        with self.assertRaises(AcquisitionError):
            validate_catalog(self.catalog)

    def test_invalid_date_is_rejected(self):
        self.catalog["sources"][0]["checkedAt"] = "2026-02-30"
        with self.assertRaises(AcquisitionError):
            validate_catalog(self.catalog)

    def test_unknown_fields_do_not_silently_break_shared_api(self):
        self.catalog["live"] = True
        with self.assertRaises(AcquisitionError):
            validate_catalog(self.catalog)

    def test_unsafe_handoff_is_rejected(self):
        self.catalog["journeys"][0]["handoffs"][0]["url"] = "https://example.invalid/pay"
        with self.assertRaises(AcquisitionError):
            validate_catalog(self.catalog)

    def test_source_gates_and_unknown_dates_are_honest(self):
        sources = {s["id"]: s for s in self.catalog["sources"]}
        self.assertEqual(sources["workbc"]["status"], "blocked")
        self.assertEqual(sources["bc-laws"]["status"], "pending")
        self.assertEqual(sources["icbc"]["status"], "limited")
        self.assertEqual(sources["bc-housing"]["status"], "limited")
        self.assertIn("September 22, 2026", sources["bc-housing"]["description"])
        self.assertIsNone(sources["bc-housing"]["publisherUpdatedAt"])

    def test_location_capabilities_and_exclusions(self):
        offices = {o["municipality"]: o for o in self.catalog["locations"]}
        self.assertIn("icbc-licensing", offices["Nanaimo"]["services"])
        self.assertIn("income-assistance", offices["Nanaimo"]["excludedServices"])
        for city in ("Vancouver", "Surrey", "Victoria", "Kamloops", "Kelowna", "Burns Lake"):
            self.assertNotIn("icbc-licensing", offices[city]["services"])
            self.assertIn("icbc-licensing", offices[city]["excludedServices"])
        for city in ("Vancouver", "Surrey"):
            self.assertEqual(offices[city]["services"], ["bc-services-card", "bceid"])
            self.assertIn("Appointments are not available", offices[city]["hours"])

    def test_provenance_resolves_sources_and_every_handoff(self):
        provenance = json.loads((ROOT / "data" / "provenance.json").read_text(encoding="utf-8"))
        docs = provenance["documents"]
        self.assertEqual(len(docs), 17)
        self.assertEqual(len(provenance["robots"]), 6)
        self.assertEqual(provenance["asOf"], self.catalog["asOf"])
        sources = {source["id"] for source in self.catalog["sources"]}
        urls = {doc["url"] for doc in docs if doc["httpStatus"] == 200}
        for doc in docs:
            self.assertIn(doc["sourceId"], sources)
            self.assertRegex(doc["responseSha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn(doc["sourceId"], ("workbc", "bc-laws"))
        for journey in self.catalog["journeys"]:
            for handoff in journey["handoffs"]:
                self.assertIn(handoff["url"], urls)


class OfficeParserTests(unittest.TestCase):
    def parse(self, info):
        return parse_service_bc_offices(office_fixture(info), SOURCE, DATE, ["Fixture Town"])[0]

    def test_explicit_popular_group_not_missing_data(self):
        office = self.parse('This office offers the following services: <a href="#services">Popular services</a>')
        self.assertEqual(set(office["services"]), {"icbc-licensing", "income-assistance", "bc-services-card", "bceid"})

    def test_explicit_exclusion_overrides_group_inclusion(self):
        office = self.parse('This office offers the following services: <a href="#services">Popular services</a>'
                            ' Not available at this location: ICBC Driver Licensing')
        self.assertNotIn("icbc-licensing", office["services"])
        self.assertIn("icbc-licensing", office["excludedServices"])

    def test_unknown_services_are_not_inferred_available(self):
        office = self.parse("Contact this office to ask about services.")
        self.assertEqual(office["services"], [])
        self.assertEqual(office["excludedServices"], [])

    def test_closed_list_explicitly_excludes_other_tracked_capabilities(self):
        office = self.parse("This office only offers the following services: BC Services Card account setup; BCeID registration.")
        self.assertEqual(office["services"], ["bc-services-card", "bceid"])
        self.assertEqual(office["excludedServices"], ["icbc-licensing", "income-assistance"])

    def test_absent_or_unverified_municipality_is_not_fabricated(self):
        with self.assertRaises(AcquisitionError):
            parse_service_bc_offices(office_fixture("BCeID"), SOURCE, DATE, ["Not Present"])

    def test_unrelated_page_cannot_claim_office_provenance(self):
        with self.assertRaises(AcquisitionError):
            parse_service_bc_offices(office_fixture("BCeID"), SOURCE + "/other", DATE, ["Fixture Town"])


class CliAndAzureTests(unittest.TestCase):
    def test_offline_catalog_validation(self):
        with redirect_stdout(io.StringIO()) as output:
            result = main(["validate", "--catalog", str(CATALOG)])
        self.assertEqual(result, 0)
        self.assertTrue(json.loads(output.getvalue())["valid"])

    def test_dry_run_never_fetches(self):
        with patch("bc_ingestion.fetch.transport", side_effect=AssertionError("No network")), \
                redirect_stdout(io.StringIO()) as output:
            result = main(["dry-run", "--catalog", str(CATALOG), "--url", "health=https://www2.gov.bc.ca/gov/content/health"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["networkRequests"], 0)

    def test_discovery_requires_explicit_pages(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["discover", "--catalog", str(CATALOG)]), 2)

    def test_service_bc_open_data_requires_execute_and_never_approves_publication(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["open-data-service-bc", "--catalog", str(CATALOG)]), 2)
        candidate = {
            "recordCount": 65,
            "reviewHash": "1" * 64,
            "contentHash": "2" * 64,
            "publicationApproved": False,
        }
        output = ROOT / "ingestion" / ".generated" / ("open-data-" + uuid.uuid4().hex)
        try:
            with patch(
                "bc_ingestion.open_data.acquire_service_bc_candidate",
                return_value=candidate,
            ), redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(
                    main(
                        [
                            "open-data-service-bc",
                            "--catalog",
                            str(CATALOG),
                            "--output",
                            str(output),
                            "--execute",
                        ]
                    ),
                    0,
                )
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["mode"], "candidate-only")
            self.assertFalse(result["publicationApproved"])
            self.assertTrue((output / "open-data" / ("service-bc-office-locations-" + "1" * 12 + ".json")).exists())
        finally:
            if output.exists():
                shutil.rmtree(output)

    def test_blob_inspect_is_read_only_and_requires_explicit_remote_identity(self):
        summary = {
            "storageSchemaVersion": 2,
            "revision": 0,
            "sha256": "1" * 64,
        }
        args = [
            "blob-inspect",
            "--catalog",
            str(CATALOG),
            "--programme-store",
            "azure-blob",
            "--blob-account-url",
            "https://example.blob.core.windows.net",
            "--candidate-container",
            "candidate-data",
            "--run-prefix",
            "run-v1",
            "--credential",
            "managed-identity",
        ]
        with patch(
            "bc_ingestion.azure_blob.inspect_blob_control", return_value=summary
        ), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(args), 0)
        self.assertEqual(json.loads(output.getvalue()), summary)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main([*args, "--execute"]), 2)
        with patch.dict(
            "os.environ",
            {
                "AZURE_STORAGE_ACCOUNT_URL": "https://example.blob.core.windows.net",
                "BC_CANDIDATE_CONTAINER": "candidate-data",
                "BC_RUN_PREFIX": "run-v1",
            },
            clear=True,
        ), patch(
            "bc_ingestion.azure_blob.inspect_blob_control", return_value=summary
        ), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["blob-inspect", "--catalog", str(CATALOG)]), 0)
        self.assertEqual(json.loads(output.getvalue()), summary)
        with patch.dict(
            "os.environ",
            {
                "BC_INSPECT_CONTROL": "1",
                "AZURE_STORAGE_ACCOUNT_URL": "https://example.blob.core.windows.net",
                "BC_CANDIDATE_CONTAINER": "candidate-data",
                "BC_RUN_PREFIX": "run-v1",
            },
            clear=True,
        ), patch(
            "bc_ingestion.azure_blob.inspect_blob_control", return_value=summary
        ), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(output.getvalue()), summary)

    def test_invalid_dry_run_budget_or_source_is_rejected(self):
        for args in (["--max-pages", "500"], ["--url", "unknown=https://www2.gov.bc.ca/gov/content/health"]):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["dry-run", "--catalog", str(CATALOG), *args]), 2)

    def test_cli_extract_and_discover_persist_only_in_ignored_project_output(self):
        output = ROOT / "ingestion" / ".generated" / ("fixture-" + uuid.uuid4().hex)
        url = "https://www2.gov.bc.ca/gov/content/health/synthetic"
        html = ("<title>Fixture</title><main><h1>Fixture</h1><p>"
                + "Synthetic preparation guidance and official source context. " * 10
                + "</p><a href='/gov/content/health/related'>Related guide</a></main>").encode()

        def request(target, **kwargs):
            if target.endswith("/robots.txt"):
                return Response(target, 200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow:")
            return Response(target, 200, {"content-type": "text/html"}, html)

        try:
            for command in ("extract", "discover"):
                fetcher = Fetcher(request=request, sleep=lambda _: None)
                with patch("bc_ingestion.cli.Fetcher", return_value=fetcher), redirect_stdout(io.StringIO()):
                    result = main([command, "--catalog", str(CATALOG), "--output", str(output),
                                   "--url", "health=" + url])
                self.assertEqual(result, 0)
            state = json.loads((output / "state.json").read_text())
            self.assertEqual(len(state["documents"]), 1)
            self.assertEqual(len(next(iter(state["documents"].values()))["versions"]), 1)
            discovery = json.loads((output / "discovery.json").read_text())
            self.assertTrue(any(c["url"].endswith("/related") for c in discovery["candidates"]))
        finally:
            if output.exists():
                shutil.rmtree(output)

    def test_publish_defaults_offline_without_azure_import(self):
        result = publish({"uploads": [], "deleteIds": [], "withheld": []})
        self.assertEqual(result["mode"], "dry-run")

    def test_publish_requires_two_explicit_execution_gates(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(AcquisitionError):
                publish({"uploads": [], "deleteIds": [], "withheld": []}, execute=True, approved=True)

    def test_optional_native_index_schema_matches_retrieval_contract(self):
        try:
            from bc_ingestion.azure_publish import build_index
            schema = build_index("bc-pilot-public").serialize()
        except ImportError:
            self.skipTest("Optional Azure SDK not installed; core operation is intentionally offline")
        fields = {field["name"]: field for field in schema["fields"]}
        self.assertTrue({
            "id", "documentId", "sourceId", "title", "publisher", "url", "content", "section",
            "checkedAt", "publisherUpdatedAt", "status", "topics", "journeyIds", "documentVersion", "contentHash",
        } <= set(fields))
        self.assertTrue({
            "canonicalUrl", "sourceUrl", "sourceIds", "language", "documentType", "rightsHash",
            "extractionHash", "responseHash", "effectiveFrom", "effectiveTo", "consolidationDate",
            "repealedAt", "legalSectionId", "amendmentIds", "isHistorical", "reviewHash",
        } <= set(fields))
        self.assertEqual(fields["effectiveFrom"]["type"], "Edm.String")
        self.assertTrue(fields["id"]["key"])
        self.assertTrue(fields["status"]["filterable"])
        self.assertTrue(fields["content"]["searchable"])
        self.assertEqual(fields["checkedAt"]["type"], "Edm.DateTimeOffset")


if __name__ == "__main__":
    unittest.main()
