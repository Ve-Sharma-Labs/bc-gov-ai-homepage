"""Synthetic offline policy/isolation checks; no publisher requests or approvals."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import Mock, patch

from bc_ingestion.azure_publish import publish
from bc_ingestion.cli import main
from bc_ingestion.fetch import Response
from bc_ingestion.jurisdiction import load_pack
from bc_ingestion.manifest import JsonManifestStore, ProgrammeLimits
from bc_ingestion.pack_policy import CandidateProgrammePolicy, source_policy_report
from bc_ingestion.pipeline import Ledger, build_publish_plan
from bc_ingestion.policy import AcquisitionError, PUBLISHERS
from bc_ingestion.programme import ProgrammeRun, lifecycle_counts
from bc_ingestion.source_adapters import adapt_programme_html
from bc_ingestion.vectors import enrich_documents


ROOT = Path(__file__).resolve().parents[2]
SK_URL = "https://www.saskatchewan.ca/residents/synthetic-guidance"


class JurisdictionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {}, clear=True)
        self.env.start()
        self.pack = replace(load_pack("sk"), approval_status="pending-rag-permission",
                            operation_review_path=None, pending_identity=None)
        self.programme = json.loads(self.pack.programme_path.read_text(encoding="utf-8"))
        self.programme["publicationPolicy"] = "exact-hash-human-review"
        self.output = self.pack.output_path / ("test-" + uuid.uuid4().hex)

    def tearDown(self):
        shutil.rmtree(self.output, ignore_errors=True)
        self.env.stop()

    def cli(self, args):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(args)
        return code, json.loads(output.getvalue() or error.getvalue())

    def test_default_bc_paths_and_environment_selection(self):
        bc = load_pack()
        self.assertEqual(bc.catalog_path, ROOT / "data" / "pilot-catalog.json")
        self.assertEqual(bc.programme_path, ROOT / "data" / "source-programme.json")
        self.assertEqual(bc.output_path, ROOT / "ingestion" / ".generated")
        with patch.dict("os.environ", {"JURISDICTION": "sk"}):
            self.assertEqual(load_pack().id, "sk")
            code, report = self.cli(["source-policy"])
        self.assertEqual(code, 0)
        self.assertEqual(report["jurisdictionId"], "sk")
        for value in ("../bc", "SK", "", "not-installed"):
            with self.subTest(value=value), self.assertRaises(AcquisitionError):
                load_pack(value)

    def test_pack_paths_and_manifest_approval_flags_are_not_permission(self):
        root = self.output / "synthetic-root"
        path = root / "jurisdictions" / "sk" / "jurisdiction.json"
        path.parent.mkdir(parents=True)
        manifest = {
            "schemaVersion": 1, "id": "sk", "researchHosts": ["www.saskatchewan.ca"],
            "content": {
                "catalog": "jurisdictions/sk/content/pilot-catalog.json",
                "sourceProgramme": "jurisdictions/sk/content/source-programme.json",
            },
            "sourcePolicy": {"approvalStatus": "approved", "embeddingAllowed": True},
        }
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AcquisitionError, "Unsupported pack source-policy approval status"):
            load_pack("sk", root=root).assert_operation("embedding")
        manifest["sourcePolicy"] = {
            "approvalStatus": "reviewed-operation-grants",
            "operationReview": {"path": "jurisdictions/sk/content/rights/review.json", "sha256": "a" * 64},
        }
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AcquisitionError, "only operationReview.path"):
            load_pack("sk", root=root)
        manifest["sourcePolicy"]["operationReview"].pop("sha256")
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
            load_pack("sk", root=root).assert_operation("embedding")
        manifest["sourcePolicy"] = {"approvalStatus": "pending-rag-permission"}
        manifest["content"]["sourceProgramme"] = "data/source-programme.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AcquisitionError, "escapes"):
            load_pack("sk", root=root)

    def test_offline_report_does_not_invent_inventory_or_snapshots(self):
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch(
            "bc_ingestion.fetch.Fetcher", side_effect=AssertionError("No fetch")
        ):
            code, report = self.cli(["source-policy", "--jurisdiction", "sk"])
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "pending-rag-permission")
        self.assertEqual(set(report["counts"].values()), {0})
        self.assertFalse(report["liveInventoryAvailable"])
        self.assertFalse(report["coverageTargetMet"])
        self.assertIn("https://www.saskatchewan.ca/sitemap-xml",
                      [item["url"] for item in report["proposedInventory"]])
        self.assertEqual(set(self.programme["sources"][0]["topics"]), {"resident", "business", "government"})
        observation = report["accessObservations"][0]
        self.assertEqual(observation["evidenceKind"], "agent-observed-prior-tool-result")
        self.assertIn("parent assistant", observation["notice"])
        self.assertIsNone(observation["responseSha256"])
        self.assertIsNone(observation["fetchedAt"])
        self.assertEqual(observation["contentSignals"]["search"], "yes")
        self.assertIsNone(observation["contentSignals"]["ai-input"])
        self.assertTrue(observation["searchExcludesAiGeneratedSummaries"])
        self.assertIn("supported-bounded-text-pdf", report["formatSupport"]["pdf"])
        self.assertIn("unsupported-ocr", report["formatSupport"]["scannedPdf"])
        self.assertIn("quarantined", report["formatSupport"]["mixedPdf"])

    def test_external_publisher_with_unknown_robots_signals_remains_unapproved(self):
        programme = deepcopy(self.programme)
        programme["sources"].append({
            "id": "sgi-synthetic", "publisher": "Synthetic SGI", "host": "sgi.sk.ca",
            "seedUrl": "https://sgi.sk.ca/renew-licence", "targetPathPrefixes": ["/"],
            "topics": ["driving"], "formats": ["html"],
        })
        programme["accessObservations"].append({
            "host": "sgi.sk.ca", "robotsUrl": "https://sgi.sk.ca/robots.txt", "sitemaps": [],
            "evidenceKind": "agent-observed-prior-tool-result", "observedDate": "2026-11-24",
            "fetchedAt": None, "responseSha256": None,
            "contentSignals": {"search": None, "ai-train": None, "use": None, "ai-input": None},
            "searchExcludesAiGeneratedSummaries": None, "accessState": "pending-rag-permission",
            "notice": "Synthetic prior observation; it grants no permission.",
        })
        pack = replace(self.pack, research_hosts=(*self.pack.research_hosts, "sgi.sk.ca"))
        policy = CandidateProgrammePolicy(programme, pack)
        with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
            policy.assert_operation("acquisition", "https://sgi.sk.ca/renew-licence")

    def test_no_config_or_execution_switch_grants_rights(self):
        with patch.dict("os.environ", {"JURISDICTION": "sk", "INGESTION_PUBLISH_ENABLED": "true"}):
            for args in (
                ["programme", "--acquire"], ["publish", "--execute", "--approved"],
                ["adapt-source"], ["open-data-service-bc", "--execute"],
                ["programme", "--programme-store", "azure-blob"], ["shadow-index"],
                ["rights-upload"],
            ):
                with self.subTest(args=args):
                    code, error = self.cli(args)
                    self.assertEqual(code, 2)
                    self.assertIn("pending-rag-permission", error["error"])
            code, error = self.cli(["source-policy", "--jurisdiction", "bc"])
            self.assertEqual(code, 2)
            self.assertIn("must agree", error["error"])
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(AcquisitionError, "Legacy/internal blanket"):
            CandidateProgrammePolicy(self.programme, self.pack, {"approvalConfirmed": True})
        with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
            replace(self.pack, manifest_hash="approved").assert_operation("embedding")

    def test_azure_developer_cli_is_limited_to_local_search_publication(self):
        for args in (
            ["programme"], ["shadow-index"],
            ["publish", "--programme-store", "azure-blob"],
            ["publish", "--stage-blob"],
        ):
            with self.subTest(args=args):
                code, error = self.cli([*args, "--credential", "azure-developer-cli"])
                self.assertEqual(code, 2)
                self.assertIn("only for local Search publication", error["error"])

    def test_direct_embedding_and_publication_are_gated_before_provider_calls(self):
        embed = Mock()
        with self.assertRaises(AcquisitionError):
            enrich_documents([{"status": "active", "content": "Synthetic reviewed text", "url": SK_URL}], embed, 3)
        embed.assert_not_called()
        with patch.dict("os.environ", {"JURISDICTION": "sk"}):
            with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
                enrich_documents([{"status": "active", "content": "Synthetic"}], embed, 3)
            with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
                publish({"uploads": [], "deleteIds": [], "withheld": []}, execute=True, approved=True)
        policy = CandidateProgrammePolicy(self.programme, self.pack)
        with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
            build_publish_plan(Ledger(), {"sources": []}, programme_policy=policy)

    def test_candidate_urls_exclusions_and_unsupported_pdf_are_separate(self):
        policy = CandidateProgrammePolicy(self.programme, self.pack)
        self.assertEqual(policy.validate_url(SK_URL, require_rights=False), SK_URL)
        with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
            policy.validate_url(SK_URL)
        for path in ("/sitecore", "/sitecore-more", "/searching", "/temp/file", "/upload/file"):
            with self.subTest(path=path), self.assertRaisesRegex(AcquisitionError, "robots-exclusion"):
                policy.validate_url("https://www.saskatchewan.ca" + path, require_rights=False)
        self.assertEqual(policy.validate_url(SK_URL + ".pdf", require_rights=False), SK_URL + ".pdf")
        with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
            policy.validate_url(SK_URL + ".pdf")
        with self.assertRaisesRegex(AcquisitionError, "sensitive-path"):
            policy.validate_url("https://www.saskatchewan.ca/account/details", require_rights=False)
        for url in ("https://www2.gov.bc.ca/gov/content/health", "https://candidate.example.test/residents"):
            with self.subTest(url=url), self.assertRaisesRegex(AcquisitionError, "out-of-scope-host"):
                policy.validate_url(url, require_rights=False)
        self.assertNotIn("www.saskatchewan.ca", PUBLISHERS)

    def test_public_form_information_is_scope_but_submission_flows_are_not(self):
        policy = CandidateProgrammePolicy(self.programme, self.pack)
        for path in ("/forms", "/forms/information", "/residents/registration", "/residents/appointments"):
            url = "https://www.saskatchewan.ca" + path
            self.assertEqual(policy.validate_url(url, require_rights=False), url)
            with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
                policy.validate_url(url)
        for path in ("/forms/submit", "/forms/payment", "/forms/account", "/forms/upload"):
            with self.subTest(path=path), self.assertRaisesRegex(AcquisitionError, "sensitive-path"):
                policy.validate_url("https://www.saskatchewan.ca" + path, require_rights=False)
        self.assertIn("blank downloadable forms", source_policy_report(self.pack, self.programme)["informationalForms"])

    def test_candidate_schema_does_not_accept_legacy_or_fabricated_observations(self):
        for key, value in (("schemaVersion", 1), ("jurisdictionId", "bc"),
                           ("permissionStatus", "approved")):
            programme = deepcopy(self.programme)
            programme[key] = value
            with self.subTest(key=key), self.assertRaises(AcquisitionError):
                CandidateProgrammePolicy(programme, self.pack)
        programme = deepcopy(self.programme)
        programme["accessObservations"][0]["responseSha256"] = "a" * 64
        with self.assertRaisesRegex(AcquisitionError, "captured"):
            source_policy_report(self.pack, programme)

    def test_isolated_durable_state_cannot_be_rebound_or_budget_reset(self):
        policy = CandidateProgrammePolicy(self.programme, self.pack)
        path = self.output / "programme" / "manifest.json"
        with JsonManifestStore(path) as store:
            runner = ProgrammeRun(policy, store, limits=ProgrammeLimits(total_requests=5))
            report = runner.run()
            self.assertEqual(report["lifecycle"]["configuredSeeds"], 1)
            self.assertEqual(report["lifecycle"]["discovered"], 0)
            self.assertEqual(report["lifecycle"]["eligible"], 0)
            self.assertEqual(report["budget"]["requests"], 0)
            self.assertEqual(runner.state["ledger"]["documents"], {})
            self.assertEqual(runner.state["packIdentity"]["jurisdictionId"], "sk")
            with self.assertRaisesRegex(AcquisitionError, "limits"):
                ProgrammeRun(policy, store, limits=ProgrammeLimits(total_requests=6))
            changed = CandidateProgrammePolicy(self.programme, replace(self.pack, manifest_hash="changed"))
            with self.assertRaisesRegex(AcquisitionError, "identity changed"):
                ProgrammeRun(changed, store)
        with self.assertRaisesRegex(AcquisitionError, "isolated"):
            self.pack.output(ROOT / "ingestion" / ".generated" / "programme" / "manifest.json")
        code, error = self.cli(["programme", "--jurisdiction", "sk",
                                "--programme", str(ROOT / "data" / "source-programme.json")])
        self.assertEqual(code, 2)
        self.assertIn("another jurisdiction", error["error"])

    def test_cli_programme_persists_only_proposal_and_does_not_enlarge_budgets(self):
        args = ["programme", "--jurisdiction", "sk", "--output", str(self.output),
                "--request-budget", "5"]
        code, report = self.cli(args)
        self.assertEqual(code, 0)
        self.assertFalse(report["liveInventoryAvailable"])
        self.assertEqual(report["lifecycle"]["withheld"], 0)
        self.assertEqual(report["lifecycle"]["proposedWithheldSeeds"], 1)
        self.assertEqual(report["budget"]["requests"], 0)
        path = self.output / "programme" / "manifest.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(state["limits"]["total_requests"], 5)
        code, _ = self.cli(args)
        self.assertEqual(code, 0)
        code, error = self.cli(args[:-1] + ["6"])
        self.assertEqual(code, 2)
        self.assertIn("limits", error["error"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["limits"]["total_requests"], 5)

    def test_generic_html_does_not_register_bc_adapters_for_sk(self):
        body = (b"<html><title>Synthetic SK guidance</title><main><h1>Guidance</h1><p>"
                + b"Synthetic local test guidance only. " * 25 + b"</p></main></html>")
        response = Response(SK_URL, 200, {"content-type": "text/html"}, body, "2026-11-23T00:00:00Z")
        policy = CandidateProgrammePolicy(self.programme, self.pack)
        document = adapt_programme_html(response, jurisdiction_id="sk",
                                       url_validator=lambda url: policy.validate_url(url, require_rights=False),
                                       quality_flags=["pending-rag-permission"])
        self.assertIn("pending-rag-permission", document.flags)
        self.assertIsNone(document.metadata["rights"])
        with self.assertRaisesRegex(AcquisitionError, "BC pack only"):
            adapt_programme_html(replace(response, url="https://www2.gov.bc.ca/gov/content/health"),
                                 jurisdiction_id="sk")
    def test_lifecycle_keeps_review_index_failure_and_exclusions_distinct(self):
        state = {
            "candidates": {
                "seed": {"kind": "document", "state": "blocked", "attempts": 0,
                         "reason": "pending-rag-permission", "discoveredFrom": [],
                         "discoveryEvidence": "configured-seed"},
                "page": {"kind": "document", "state": "candidate", "attempts": 1,
                         "reason": None, "discoveredFrom": ["sitemap"], "responseHash": "synthetic"},
                "failure": {"kind": "document", "state": "blocked", "attempts": 1,
                            "reason": "HTTP 500", "discoveredFrom": ["sitemap"]},
            },
            "ledger": {"documents": {
                "page": {"activeVersion": None, "versions": [
                    {"documentVersion": "old", "status": "superseded"},
                    {"documentVersion": "current", "status": "review-required"},
                ]}
            }},
            "reviewPlans": [{"approvedVersions": ["current"]}],
        }
        report = lifecycle_counts(state)
        self.assertEqual(report["discovered"], 2)
        self.assertEqual(report["fetched"], 1)
        self.assertEqual(report["reviewed"], 1)
        self.assertEqual(report["indexed"], 0)
        self.assertEqual(report["withheld"], 1)
        self.assertEqual(report["proposedWithheldSeeds"], 1)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["superseded"], 1)
        state["ledger"]["documents"]["page"]["versions"][-1]["reviewRevoked"] = True
        self.assertEqual(lifecycle_counts(state)["reviewed"], 0)


if __name__ == "__main__":
    unittest.main()
