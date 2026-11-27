"""Local synthetic grants are not Saskatchewan publisher permission."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch

from bc_ingestion.cli import main
from bc_ingestion.fetch import Response
from bc_ingestion.jurisdiction import load_pack
from bc_ingestion.metadata import digest
from bc_ingestion.operation_rights import OPERATIONS, OperationRightsProvider
from bc_ingestion.pack_policy import CandidateProgrammePolicy
from bc_ingestion.policy import AcquisitionError
from bc_ingestion.programme import ProgrammeRun
from bc_ingestion.source_adapters import adapt_programme_html


DATE = "2026-11-23T00:00:00Z"
URL = "https://www.saskatchewan.ca/residents/synthetic-guidance"
HOST = "www.saskatchewan.ca"
NETWORK_GUARDS = (
    "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
    "socket.gethostbyaddr", "socket.create_connection", "socket.socket.connect",
    "socket.socket.connect_ex", "socket.socket.send", "socket.socket.sendall",
    "socket.socket.sendto", "http.client.HTTPConnection.connect",
    "http.client.HTTPSConnection.connect", "requests.sessions.Session.send",
)


class OperationRightsTests(unittest.TestCase):
    def setUp(self):
        for target in NETWORK_GUARDS:
            guard = patch(target, side_effect=AssertionError("Synthetic tests prohibit live DNS/HTTP"))
            guard.start()
            self.addCleanup(guard.stop)
        self.env = patch.dict("os.environ", {}, clear=True)
        self.env.start()
        self.pack = replace(load_pack("sk"), approval_status="pending-rag-permission",
                            operation_review_path=None, pending_identity=None)
        self.programme = json.loads(self.pack.programme_path.read_text(encoding="utf-8"))
        self.programme["publicationPolicy"] = "exact-hash-human-review"
        self.output = self.pack.output_path / ("rights-test-" + uuid.uuid4().hex)
        self.output.mkdir(parents=True)
        self.path = self.output / "synthetic-rights.json"
        self.now = datetime(2026, 11, 23, 1, tzinfo=timezone.utc)
        self.review = self.fixture()

    def tearDown(self):
        shutil.rmtree(self.output, ignore_errors=True)
        self.env.stop()

    def fixture(self):
        bodies = {
            "terms": b"SYNTHETIC TEST TERMS ONLY. No actual publisher evidence.",
            "robots": b"User-agent: BCPilotIngest\nDisallow: /residents/blocked\n"
                      b"Content-Signal: search=yes,ai-train=no,use=reference\n",
            "permission": b"SYNTHETIC TEST PERMISSION ONLY. Not a Saskatchewan publisher grant.",
        }
        permitted = {"discovery", "acquisition", "extraction", "storage"}
        evidence = []
        for key, body in bodies.items():
            file = key + ".txt"
            (self.output / file).write_bytes(body)
            evidence.append({
                "id": key, "kind": "publisher-written-permission" if key == "permission" else key,
                "host": HOST, "url": None if key == "permission" else f"https://{HOST}/{key if key == 'terms' else 'robots.txt'}",
                "file": file, "sha256": hashlib.sha256(body).hexdigest(), "capturedAt": DATE,
                "mediaType": "text/plain", "publisherReference": "synthetic-test:" + key,
                "permittedOperations": sorted(permitted) if key == "permission" else [],
            })
        return {
            "schemaVersion": 3, "jurisdictionId": "sk", "programmeHash": digest(self.programme),
            "packIdentity": self.pack.identity, "reviewId": "SYNTHETIC-NOT-PUBLISHER-PERMISSION",
            "reviewer": "SYNTHETIC TEST ONLY", "reviewedAt": DATE, "expiresAt": "2026-11-25T00:00:00Z",
            "revocation": {"status": "active", "reference": "synthetic-test:revocation", "revokedAt": None},
            "evidence": evidence,
            "grants": [{
                "host": HOST, "pathPrefixes": ["/residents", "/forms"],
                "formats": ["html", "robots", "sitemap-xml"],
                "decisions": {
                    operation: {"status": "granted" if operation in permitted else (
                        "denied" if operation in {"training", "fine-tuning"} else "pending"),
                        "evidenceIds": ["permission"] if operation in permitted else []}
                    for operation in OPERATIONS
                },
            }],
        }

    def provider(self, review=None):
        body = json.dumps(review or self.review, sort_keys=True).encode("utf-8")
        self.path.write_bytes(body)
        return OperationRightsProvider(
            self.path, hashlib.sha256(body).hexdigest(), self.pack, self.programme,
            clock=lambda: self.now,
        )

    def test_explicit_scoped_acquisition_does_not_grant_model_uses(self):
        with patch("socket.getaddrinfo", side_effect=AssertionError("No publisher DNS")):
            provider = self.provider()
            self.assertEqual(provider.authorize("acquisition", URL), URL)
            self.assertEqual(provider.authorize("storage", URL), URL)
            report = provider.report()
        self.assertEqual(report["networkRequests"], 0)
        self.assertFalse(report["liveExecutionEnabled"])
        for operation in ("embedding", "rag", "generated-summary", "publication"):
            with self.subTest(operation=operation), self.assertRaisesRegex(AcquisitionError, "rights-operation-pending"):
                provider.authorize(operation, URL)
        for operation in ("training", "fine-tuning"):
            with self.subTest(operation=operation), self.assertRaisesRegex(AcquisitionError, "rights-operation-denied"):
                provider.authorize(operation, URL)

    def test_granted_embedding_needs_its_own_publisher_evidence(self):
        review = deepcopy(self.review)
        review["grants"][0]["decisions"]["embedding"] = {"status": "granted", "evidenceIds": ["permission"]}
        with self.assertRaisesRegex(AcquisitionError, "matching explicit"):
            self.provider(review)
        review["evidence"][-1]["permittedOperations"].append("embedding")
        provider = self.provider(review)
        self.assertEqual(provider.authorize("embedding", URL), URL)
        with self.assertRaisesRegex(AcquisitionError, "rights-operation-pending"):
            provider.authorize("rag", URL)
        with self.assertRaises(AcquisitionError):
            provider.authorize("invented-operation", URL)

    def test_robots_and_terms_never_serve_as_operation_grants(self):
        for evidence_id in ("robots", "terms"):
            review = deepcopy(self.review)
            review["grants"][0]["decisions"]["acquisition"]["evidenceIds"] = [evidence_id]
            with self.subTest(evidence_id=evidence_id), self.assertRaisesRegex(AcquisitionError, "matching explicit"):
                self.provider(review)
        review = deepcopy(self.review)
        review["evidence"][-1]["kind"] = "internal-session-approval"
        with self.assertRaisesRegex(AcquisitionError, "Internal/project"):
            self.provider(review)
        review = deepcopy(self.review)
        review["grants"][0]["decisions"]["training"] = {"status": "granted", "evidenceIds": ["permission"]}
        with self.assertRaisesRegex(AcquisitionError, "Training"):
            self.provider(review)

    def test_saskatchewan_user_attestation_is_explicit_and_scoped(self):
        review = deepcopy(self.review)
        review["reviewId"] = "user-attestation:synthetic"
        permission = review["evidence"][-1]
        permission["kind"] = "user-attestation"
        permission["publisherReference"] = "user-attestation:synthetic"
        provider = self.provider(review)
        self.assertEqual(provider.authorize("acquisition", URL), URL)
        self.assertEqual(provider.report()["authorizationBasis"], "user-attested")
        with self.assertRaisesRegex(AcquisitionError, "rights-operation-pending"):
            provider.authorize("publication", URL)
        for field, value in (("url", f"https://{HOST}/permission"),
                             ("publisherReference", "synthetic-test:permission"),
                             ("mediaType", "application/pdf")):
            invalid = deepcopy(review)
            invalid["evidence"][-1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(AcquisitionError, "attestation"):
                self.provider(invalid)
        invalid = deepcopy(review)
        invalid["reviewId"] = "synthetic-review"
        with self.assertRaisesRegex(AcquisitionError, "attestation"):
            self.provider(invalid)

        other_pack = replace(self.pack, id="zz")
        other_programme = deepcopy(self.programme)
        other_programme["jurisdictionId"] = "zz"
        other_programme["programmeId"] = "zz-public-corpus"
        review["jurisdictionId"] = "zz"
        review["packIdentity"] = other_pack.identity
        review["programmeHash"] = digest(other_programme)
        body = json.dumps(review, sort_keys=True).encode("utf-8")
        self.path.write_bytes(body)
        with self.assertRaisesRegex(AcquisitionError, "Internal/project"):
            OperationRightsProvider(self.path, hashlib.sha256(body).hexdigest(),
                                    other_pack, other_programme, clock=lambda: self.now)

    def test_attested_acquisition_can_bind_same_review_to_reviewed_pack(self):
        self.review["reviewId"] = "user-attestation:synthetic"
        permission = self.review["evidence"][-1]
        permission["kind"] = "user-attestation"
        permission["publisherReference"] = "user-attestation:synthetic"
        self.model_grants()
        runner, _, _, _ = self.pdf_run(pdf_granted=True)
        before = deepcopy(runner.store.state)
        pending_identity = self.pack.identity
        self.pack = replace(
            self.pack, manifest_hash="a" * 64, approval_status="reviewed-operation-grants",
            pending_identity=pending_identity,
        )
        provider = self.provider()
        policy = CandidateProgrammePolicy(self.programme, self.pack, rights_provider=provider)
        with self.assertRaisesRegex(AcquisitionError, "pack identity changed"):
            ProgrammeRun(policy, runner.store)
        changed = deepcopy(before)
        changed["rightsReviewHash"] = "f" * 64
        runner.store.state = changed
        with self.assertRaisesRegex(AcquisitionError, "pack identity changed"):
            ProgrammeRun(policy, runner.store, allow_pack_review_binding=True)
        runner.store.state = deepcopy(before)
        rebound = ProgrammeRun(policy, runner.store, allow_pack_review_binding=True)
        self.assertEqual(rebound.state["packIdentity"], self.pack.identity)
        self.assertEqual(rebound.state["rightsReviewHash"], before["rightsReviewHash"])
        self.assertEqual(rebound.state["budget"], before["budget"])
        self.assertEqual(rebound.state["ledger"], before["ledger"])
        self.pack = replace(self.pack, pending_identity={
            "jurisdictionId": "sk", "manifestHash": "b" * 64,
        })
        with self.assertRaisesRegex(AcquisitionError, "exact jurisdiction, pack and programme"):
            self.provider()

    def test_host_path_format_and_captured_robots_stay_fail_closed(self):
        provider = self.provider()
        for url, code in (
            ("https://unverified.example.test/residents/test", "rights-host-missing"),
            ("https://www.saskatchewan.ca/business/test", "rights-path-missing"),
            ("https://www.saskatchewan.ca/forms/submit", "rights-flow-excluded"),
            ("https://www.saskatchewan.ca/residents/blocked", "rights-robots-denied"),
            (URL + ".pdf", "rights-format-missing"),
        ):
            with self.subTest(url=url), self.assertRaisesRegex(AcquisitionError, code):
                provider.authorize("acquisition", url)
        self.assertEqual(provider.authorize("acquisition", "https://www.saskatchewan.ca/forms/information"),
                         "https://www.saskatchewan.ca/forms/information")
        self.assertEqual(provider.authorize_sitemap("discovery", "https://www.saskatchewan.ca/sitemap-xml",
                                                   self.programme), "https://www.saskatchewan.ca/sitemap-xml")
        with self.assertRaises(AcquisitionError):
            provider.authorize_sitemap("discovery", "https://www.saskatchewan.ca/other-sitemap", self.programme)
        with self.assertRaises(AcquisitionError):
            provider.authorize_sitemap("embedding", "https://www.saskatchewan.ca/sitemap-xml", self.programme)

    def test_pin_evidence_expiry_and_revocation_are_rechecked_at_use(self):
        provider = self.provider()
        (self.output / "permission.txt").write_bytes(b"Changed synthetic evidence")
        with self.assertRaisesRegex(AcquisitionError, "rights-evidence-changed"):
            provider.authorize("acquisition", URL)
        self.review = self.fixture()
        provider = self.provider()
        self.path.write_bytes(self.path.read_bytes() + b"\n")
        with self.assertRaisesRegex(AcquisitionError, "rights-evidence-changed"):
            provider.authorize("acquisition", URL)
        provider = self.provider()
        self.now = datetime(2026, 11, 25, tzinfo=timezone.utc)
        with self.assertRaisesRegex(AcquisitionError, "expired-or-revoked"):
            provider.authorize("acquisition", URL)
        self.now = datetime(2026, 11, 23, 1, tzinfo=timezone.utc)
        review = deepcopy(self.review)
        review["revocation"] = {"status": "revoked", "reference": "synthetic-test:revoked",
                                "revokedAt": "2026-11-23T00:30:00Z"}
        with self.assertRaisesRegex(AcquisitionError, "expired-or-revoked"):
            self.provider(review)

    def test_review_binding_schema_evidence_boundaries_and_lifetime(self):
        mutations = [
            ("jurisdictionId", "bc"), ("schemaVersion", 2),
            ("programmeHash", "a" * 64), ("expiresAt", "2027-01-01T00:00:00Z"),
        ]
        for field, value in mutations:
            review = deepcopy(self.review)
            review[field] = value
            with self.subTest(field=field), self.assertRaises(AcquisitionError):
                self.provider(review)
        review = deepcopy(self.review)
        review["evidence"][-1]["file"] = "..\\outside.txt"
        with self.assertRaisesRegex(AcquisitionError, "review directory"):
            self.provider(review)
        review = deepcopy(self.review)
        del review["grants"][0]["decisions"]["rag"]
        with self.assertRaisesRegex(AcquisitionError, "Every operation"):
            self.provider(review)
        provider = self.provider()
        with self.assertRaisesRegex(AcquisitionError, "pack/programme"):
            provider.assert_binding(replace(self.pack, manifest_hash="changed"), self.programme)
        with self.assertRaisesRegex(AcquisitionError, "independently pinned"):
            OperationRightsProvider(self.path, "a" * 64, self.pack, self.programme, clock=lambda: self.now)

    def test_candidate_html_can_use_provider_without_publication_or_field_facts(self):
        provider = self.provider()
        policy = CandidateProgrammePolicy(self.programme, self.pack, rights_provider=provider)
        self.assertEqual(policy.validate_url(URL), URL)
        self.assertEqual(policy.rights_hash, provider.review_hash)
        body = (b"<html><title>Synthetic public form guidance</title><main><h1>Public information</h1><p>"
                + b"Synthetic public instructions for a blank form. " * 25
                + b"</p><form action='/forms/submit'><label>Applicant value</label>"
                  b"<input name='person' value='BLANK-FIELD-NON-FACT'></form></main></html>")
        document = adapt_programme_html(
            Response(URL, 200, {"content-type": "text/html"}, body, DATE),
            jurisdiction_id="sk", url_validator=policy.validate_url,
            metadata=policy.metadata(URL), quality_flags=policy.extraction_flags(URL),
        )
        self.assertEqual(document.metadata["rights"]["reviewHash"], provider.review_hash)
        self.assertEqual(document.metadata["rights"]["status"], "candidate-acquisition-permitted")
        self.assertNotIn("BLANK-FIELD-NON-FACT", " ".join(s.text for s in document.sections))
        self.assertNotIn("Applicant value", " ".join(s.text for s in document.sections))
        self.assertNotIn("pending-rag-permission", document.flags)
        with self.assertRaisesRegex(AcquisitionError, "rights-operation-pending"):
            policy.assert_operation("publication", URL)
        self.assertEqual(provider.report()["networkRequests"], 0)

    def test_offline_rights_status_reports_provider_but_not_live_execution(self):
        provider = self.provider()
        now = self.now

        class FixedClockProvider(OperationRightsProvider):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs, clock=lambda: now)

        out, error = io.StringIO(), io.StringIO()
        with patch("bc_ingestion.operation_rights.OperationRightsProvider", FixedClockProvider), \
                patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), \
                redirect_stdout(out), redirect_stderr(error):
            code = main(["rights-status", "--jurisdiction", "sk", "--rights-review", str(self.path),
                         "--rights-sha256", provider.expected_sha256])
        self.assertEqual(code, 0, error.getvalue())
        report = json.loads(out.getvalue())
        self.assertEqual(report["networkRequests"], 0)
        self.assertFalse(report["liveExecutionEnabled"])
        self.assertTrue(all("OCR" in gap for gap in report["implementationGaps"]))
        out, error = io.StringIO(), io.StringIO()
        with patch("bc_ingestion.operation_rights.OperationRightsProvider", FixedClockProvider), \
                redirect_stdout(out), redirect_stderr(error):
            code = main(["programme", "--jurisdiction", "sk",
                         "--output", str(self.output / "cli"),
                         "--rights-review", str(self.path), "--rights-sha256", provider.expected_sha256])
        self.assertEqual(code, 0, error.getvalue())
        self.assertEqual(json.loads(out.getvalue())["networkRequests"], 0)

    def test_pdf_scope_and_format_rights_are_independent_of_html(self):
        pdf_url = URL + ".pdf"
        policy = CandidateProgrammePolicy(self.programme, self.pack, rights_provider=self.provider())
        with self.assertRaisesRegex(AcquisitionError, "rights-format-missing"):
            policy.validate_url(pdf_url)
        self.review["grants"][0]["formats"].append("pdf")
        policy = CandidateProgrammePolicy(self.programme, self.pack, rights_provider=self.provider())
        self.assertEqual(policy.validate_url(pdf_url), pdf_url)
        with self.assertRaisesRegex(AcquisitionError, "unsupported-format"):
            policy.metadata(pdf_url, media_type="text/html")
        self.assertEqual(policy.metadata(pdf_url)["rights"]["reviewHash"], policy.rights_hash)
        programme = deepcopy(self.programme)
        programme["sources"][0]["formats"] = ["html"]
        policy = CandidateProgrammePolicy(programme, self.pack)
        with self.assertRaisesRegex(AcquisitionError, "unsupported-format"):
            policy.validate_url(pdf_url, require_rights=False)

    def pdf_run(self, *, pdf_granted, extensionless=False, scanned=False, long=False):
        from test_pdf import pdf_bytes

        if pdf_granted:
            self.review["grants"][0]["formats"].append("pdf")
        provider = self.provider()
        policy = CandidateProgrammePolicy(self.programme, self.pack, rights_provider=provider)
        url = URL if extensionless else URL + ".pdf"
        pages = [
            ["Synthetic public form instructions", "Printed instructions, not an applicant fact."],
            ["Synthetic exceptions", "Confirm current requirements with the responsible publisher."],
        ]
        if long:
            pages[0].append(" ".join(f"Synthetic-step-{i:04d}" for i in range(700)))
        body = pdf_bytes([[]] if scanned else pages, scanned=scanned)
        response = Response(url, 200, {"content-type": "application/pdf"}, body, DATE)

        class MemoryStore:
            state = None
            def load(self):
                return deepcopy(self.state)
            def save(self, state):
                self.state = deepcopy(state)
            def pause_requested(self):
                return False

        class SyntheticFetcher:
            robots_observations = {}
            def __init__(self, request_controller, **kwargs):
                self.controller = request_controller
            def fetch(self, target, **kwargs):
                self.controller.before_request(target, limit=len(body), delay=1, robots=False)
                self.controller.after_request(response=response)
                return response
            def validate_canonical(self, target, **kwargs):
                raise AssertionError("PDF must not invent an HTML canonical link")

        responses = Mock()
        responses.put.return_value = "synthetic-response-object"
        runner = ProgrammeRun(policy, MemoryStore(), seeds=[url], response_store=responses, clock=lambda: 0)
        with patch("bc_ingestion.programme.Fetcher", SyntheticFetcher), patch(
            "socket.getaddrinfo", side_effect=AssertionError("No actual publisher request")
        ):
            report = runner.run(acquire=True)
        return runner, responses, report, body

    def test_synthetic_programme_extracts_text_pdf_with_original_hash_and_citations(self):
        runner, responses, report, body = self.pdf_run(pdf_granted=True)
        responses.put.assert_called_once_with(body)
        self.assertEqual(report["budget"]["requests"], 1)
        self.assertEqual(report["lifecycle"]["extracted"], 1)
        self.assertEqual(report["lifecycle"]["reviewed"], 0)
        self.assertEqual(report["lifecycle"]["indexed"], 0)
        self.assertEqual(runner.state["rightsReviewHash"], runner.policy.rights_hash)
        entry = next(iter(runner.ledger.state["documents"].values()))
        document = entry["versions"][0]["document"]
        self.assertEqual(document["content_hash"], hashlib.sha256(body).hexdigest())
        self.assertEqual(document["metadata"]["schemaVersion"], 2)
        self.assertEqual(document["metadata"]["pageCount"], 2)
        self.assertEqual([section["locator"] for section in document["sections"]], ["page=1", "page=2"])
        self.assertEqual(document["metadata"]["rights"]["reviewHash"], runner.policy.rights_hash)

    def test_extensionless_pdf_without_pdf_rights_is_not_persisted_or_extracted(self):
        runner, responses, report, _ = self.pdf_run(pdf_granted=False, extensionless=True)
        responses.put.assert_not_called()
        self.assertEqual(report["budget"]["requests"], 1)
        self.assertEqual(report["lifecycle"]["extracted"], 0)
        self.assertEqual(runner.ledger.state["documents"], {})
        candidate = next(iter(runner.state["candidates"].values()))
        self.assertEqual(candidate["state"], "blocked")
        self.assertIn("rights-format-missing", candidate["reason"])

    def test_image_only_programme_pdf_is_quarantined_without_fabricated_snapshot(self):
        runner, responses, report, body = self.pdf_run(pdf_granted=True, scanned=True)
        responses.put.assert_called_once_with(body)
        self.assertEqual(report["lifecycle"]["extracted"], 0)
        self.assertEqual(report["lifecycle"]["withheld"], 1)
        self.assertEqual(report["lifecycle"]["failed"], 1)
        self.assertEqual(runner.ledger.state["documents"], {})
        candidate = next(iter(runner.state["candidates"].values()))
        self.assertEqual(candidate["state"], "quarantined")
        self.assertTrue(candidate["reason"].startswith("pdf-quarantine:"))

    def model_grants(self, *, embedding=True):
        operations = {"discovery", "acquisition", "extraction", "storage",
                      "publication", "rag", "generated-summary"}
        if embedding:
            operations.add("embedding")
        permission = next(e for e in self.review["evidence"] if e["id"] == "permission")
        permission["permittedOperations"] = sorted(operations)
        for operation in operations:
            self.review["grants"][0]["decisions"][operation] = {
                "status": "granted", "evidenceIds": ["permission"],
            }

    def reviewed_pdf_plan(self, *, embedding=True, long=False, automated=False):
        from bc_ingestion.pipeline import build_publish_plan

        if automated:
            self.programme["publicationPolicy"] = "exact-hash-automated-review"
            self.review["programmeHash"] = digest(self.programme)
        self.model_grants(embedding=embedding)
        manifest = json.loads((Path(__file__).resolve().parents[2] / "jurisdictions" /
                               "sk" / "jurisdiction.json").read_text(encoding="utf-8"))
        manifest["sourcePolicy"]["approvalStatus"] = "reviewed-operation-grants"
        manifest["sourcePolicy"]["operationReview"] = {"path": "jurisdictions/sk/content/rights/synthetic-review.json"}
        self.pack = replace(self.pack, manifest_hash=digest(manifest), approval_status="reviewed-operation-grants")
        self.review["packIdentity"] = self.pack.identity
        runner, _, _, _ = self.pdf_run(pdf_granted=True, long=long)
        policy = runner.policy
        policy.target = {"indexName": "sk-synthetic-public",
                         "searchEndpoint": "https://synthetic.search.windows.net"}
        review = {"publisherPermissionConfirmed": True, "reviewer": "SYNTHETIC TEST ONLY",
                  "reviewedAt": "2026-11-23", "documents": runner.ledger.review_candidates()}
        if automated:
            review.update(reviewKind="automated-source-review", humanReviewed=False,
                          authorizationReference="synthetic-user-authorized-review")
        plan = build_publish_plan(runner.ledger, policy.publication_catalog(), review,
                                  programme_policy=policy)
        self.assertTrue(plan["uploads"])
        return runner, plan, review

    def test_automated_review_preserves_exact_hash_gate_and_honest_provenance(self):
        from bc_ingestion.pipeline import build_publish_plan

        runner, plan, review = self.reviewed_pdf_plan(automated=True)
        self.assertTrue(plan["uploads"])
        for field in ("reviewKind", "humanReviewed", "authorizationReference"):
            invalid = deepcopy(review)
            invalid.pop(field)
            with self.subTest(field=field), self.assertRaisesRegex(AcquisitionError, "explicit provenance"):
                build_publish_plan(runner.ledger, runner.policy.publication_catalog(),
                                   invalid, programme_policy=runner.policy)
        invalid = deepcopy(review)
        invalid["documents"][0]["reviewHash"] = "0" * 64
        self.assertEqual(build_publish_plan(runner.ledger, runner.policy.publication_catalog(),
                                           invalid, programme_policy=runner.policy)["uploads"], [])

    def test_automated_review_cannot_authorize_human_review_programme(self):
        from bc_ingestion.pipeline import build_publish_plan

        runner, _, review = self.reviewed_pdf_plan()
        review.update(reviewKind="automated-source-review", humanReviewed=False,
                      authorizationReference="synthetic-user-authorized-review")
        with self.assertRaisesRegex(AcquisitionError, "human-review programme"):
            build_publish_plan(runner.ledger, runner.policy.publication_catalog(),
                               review, programme_policy=runner.policy)

    def test_exact_review_and_operation_grants_are_both_required_for_pdf_plan(self):
        from bc_ingestion.azure_publish import publish
        from bc_ingestion.pipeline import build_publish_plan
        from bc_ingestion.vectors import enrich_documents

        runner, plan, review = self.reviewed_pdf_plan()
        policy = runner.policy
        self.assertEqual(plan["uploads"][0]["pageCount"], 2)
        self.assertEqual(plan["uploads"][0]["contentHashBasis"], "original-response-bytes")
        unreviewed = build_publish_plan(runner.ledger, policy.publication_catalog(), programme_policy=policy)
        self.assertEqual(unreviewed["uploads"], [])
        self.assertEqual(publish(unreviewed, programme_policy=policy)["mode"], "dry-run")
        with self.assertRaisesRegex(AcquisitionError, "exact-snapshot review"):
            publish(unreviewed, execute=True, approved=True, programme_policy=policy)
        wrong_review = deepcopy(review)
        wrong_review["documents"][0]["reviewHash"] = "0" * 64
        self.assertEqual(build_publish_plan(runner.ledger, policy.publication_catalog(), wrong_review,
                                           programme_policy=policy)["uploads"], [])
        embed = Mock(return_value=[[1, 2, 3] for _ in plan["uploads"]])
        vectors = enrich_documents(plan["uploads"], embed, 3, programme_policy=policy)
        self.assertNotIn("contentVector", plan["uploads"][0])
        self.assertEqual(vectors[0]["contentVector"], [1.0, 2.0, 3.0])
        mutated = deepcopy(plan["uploads"])
        mutated[0]["content"] += " Unreviewed addition."
        embed.reset_mock()
        with self.assertRaisesRegex(AcquisitionError, "exact-reviewed"):
            enrich_documents(mutated, embed, 3, programme_policy=policy)
        embed.assert_not_called()

    def fake_sdk(self, *, successful=True):
        calls = {"credentials": [], "uploads": [], "deletes": [], "blobs": [], "schemas": [], "embedding": []}

        class Context:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        class Credential(Context):
            def __init__(self, **kwargs):
                calls["credentials"].append(kwargs)
            def get_token(self, scope):
                return SimpleNamespace(token="SYNTHETIC-NONFUNCTIONAL")

        class Search(Context):
            def __init__(self, endpoint, index, credential, **kwargs):
                calls["target"] = (endpoint, index)
            def upload_documents(self, documents):
                calls["uploads"].extend(deepcopy(documents))
                return [SimpleNamespace(key=d["id"], succeeded=successful) for d in documents]
            def delete_documents(self, documents):
                calls["deletes"].extend(documents)
                return [SimpleNamespace(key=d["id"], succeeded=successful) for d in documents]

        class Indexes(Context):
            def __init__(self, *args, **kwargs):
                pass
            def get_index(self, name):
                return SimpleNamespace(fields=[SimpleNamespace(name="contentVector", vector_search_dimensions=3)])

        class Blob(Context):
            def __init__(self, *args, **kwargs):
                pass
            def get_blob_client(self, container, name):
                return SimpleNamespace(upload_blob=lambda body, **kwargs:
                                       calls["blobs"].append((container, name, body, kwargs)))

        class HTTPResponse(Context):
            status_code = 200
            def __init__(self, texts):
                self.texts = texts
            def iter_content(self, size):
                yield json.dumps({"data": [{"index": i, "embedding": [1, 2, 3]}
                                          for i in range(len(self.texts))]}).encode()

        class Session(Context):
            def post(self, url, **kwargs):
                calls["embedding"].append((url, kwargs))
                return HTTPResponse(kwargs["json"]["input"])

        modules = {name: ModuleType(name) for name in (
            "azure", "azure.core", "azure.core.exceptions", "azure.identity", "azure.search",
            "azure.search.documents", "azure.search.documents.indexes", "azure.search.documents.indexes.models",
            "azure.storage", "azure.storage.blob",
        )}
        modules["azure.core.exceptions"].AzureError = type("SyntheticAzureError", (Exception,), {})
        modules["azure.identity"].ManagedIdentityCredential = Credential
        modules["azure.identity"].AzureCliCredential = Credential
        modules["azure.search.documents"].SearchClient = Search
        modules["azure.search.documents.indexes"].SearchIndexClient = Indexes
        modules["azure.storage.blob"].BlobServiceClient = Blob
        modules["azure.storage.blob"].ContentSettings = SimpleNamespace
        models = modules["azure.search.documents.indexes.models"]
        for name in ("SearchField", "SearchIndex", "SearchableField", "SimpleField",
                     "SemanticConfiguration", "SemanticField", "SemanticPrioritizedFields", "SemanticSearch",
                     "HnswAlgorithmConfiguration", "VectorSearch", "VectorSearchProfile"):
            setattr(models, name, SimpleNamespace)
        models.SearchFieldDataType = SimpleNamespace(
            String="Edm.String", Int32="Edm.Int32", Boolean="Edm.Boolean",
            DateTimeOffset="Edm.DateTimeOffset", Single="Edm.Single",
            Collection=lambda value: "Collection(" + value + ")",
        )
        return modules, calls, Session

    def publish_environment(self):
        return {
            "INGESTION_PUBLISH_ENABLED": "true",
            "AZURE_SEARCH_ENDPOINT": "https://synthetic.search.windows.net",
            "AZURE_SEARCH_INDEX": "sk-synthetic-public",
            "AZURE_STORAGE_ACCOUNT_URL": "https://synthetic.blob.core.windows.net",
            "AZURE_STORAGE_CONTAINER": "synthetic-reviewed",
            "AZURE_SEARCH_VECTOR_ENABLED": "true",
            "AZURE_OPENAI_ENDPOINT": "https://synthetic.openai.azure.com",
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "synthetic",
            "AZURE_OPENAI_EMBEDDING_DIMENSIONS": "3",
        }

    def test_real_publish_embedding_blob_interfaces_with_sdk_fakes(self):
        from bc_ingestion.azure_publish import publish

        runner, plan, _ = self.reviewed_pdf_plan()
        modules, calls, session = self.fake_sdk()
        with patch.dict("sys.modules", modules), patch.dict("os.environ", self.publish_environment()), \
             patch("requests.Session", session), patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")):
            result = publish(plan, execute=True, approved=True, stage_blob=True, programme_policy=runner.policy)
        self.assertEqual(result["mode"], "published")
        self.assertEqual(calls["target"], ("https://synthetic.search.windows.net", "sk-synthetic-public"))
        self.assertEqual(len(calls["uploads"]), len(plan["uploads"]))
        self.assertTrue(calls["embedding"])
        self.assertTrue(all(name.startswith("sk/reviewed/") for _, name, _, _ in calls["blobs"]))
        self.assertTrue(all(d["contentVector"] == [1.0, 2.0, 3.0] for d in calls["uploads"]))
        self.assertNotIn("contentVector", plan["uploads"][0])
        runner.ledger.acknowledge(plan)
        self.assertEqual(runner.report()["lifecycle"]["indexed"], 1)

    def test_publication_rejects_mutation_denied_embedding_and_wrong_target_before_credentials(self):
        from bc_ingestion.azure_publish import publish

        runner, plan, _ = self.reviewed_pdf_plan(embedding=False)
        modules, calls, _ = self.fake_sdk()
        with patch.dict("sys.modules", modules), patch.dict("os.environ", self.publish_environment()):
            with self.assertRaisesRegex(AcquisitionError, "rights-operation-pending"):
                publish(plan, execute=True, approved=True, programme_policy=runner.policy)
            for field, value in (("content", "Unreviewed"), ("url", "https://elsewhere.example/")):
                changed = deepcopy(plan)
                changed["uploads"][0][field] = value
                with self.assertRaisesRegex(AcquisitionError, "unchanged exact-review"):
                    publish(changed, execute=True, approved=True, programme_policy=runner.policy)
            with patch.dict("os.environ", {"AZURE_SEARCH_INDEX": "bc-pilot-public"}), \
                 self.assertRaisesRegex(AcquisitionError, "isolated plan target"):
                publish(plan, execute=True, approved=True, programme_policy=runner.policy)
        self.assertEqual(calls["credentials"], [])
        self.assertEqual(calls["uploads"], [])

    def test_failed_sdk_acknowledgement_does_not_activate_snapshot(self):
        from bc_ingestion.azure_publish import publish

        runner, plan, _ = self.reviewed_pdf_plan()
        modules, calls, _ = self.fake_sdk(successful=False)
        with patch.dict("sys.modules", modules), patch.dict("os.environ", {
            **self.publish_environment(), "AZURE_SEARCH_VECTOR_ENABLED": "false",
        }), self.assertRaisesRegex(AcquisitionError, "not fully acknowledged"):
            publish(plan, execute=True, approved=True, programme_policy=runner.policy)
        self.assertTrue(calls["uploads"])
        self.assertEqual(runner.report()["lifecycle"]["indexed"], 0)

    def test_new_pack_schema_has_no_bc_names_and_supports_pdf_fields(self):
        from bc_ingestion.azure_publish import build_index

        modules, _, _ = self.fake_sdk()
        with patch.dict("sys.modules", modules):
            schema = build_index("zz-synthetic-public", 3, jurisdiction_id="zz")
            bc = build_index("bc-synthetic", 3)
        self.assertEqual(schema.semantic_search.configurations[0].name, "zz-public-guidance")
        self.assertEqual(schema.vector_search.profiles[0].name, "zz-vector-profile")
        self.assertEqual(schema.vector_search.algorithms[0].name, "zz-hnsw")
        self.assertIn("pageCount", {f.name for f in schema.fields})
        self.assertNotIn("pageCount", {f.name for f in bc.fields})

    def test_embedding_wire_checks_reviewed_text_before_token(self):
        from bc_ingestion.vectors import azure_embedder

        runner, plan, _ = self.reviewed_pdf_plan()
        credential, session = Mock(), Mock()
        embed = azure_embedder("https://synthetic.openai.azure.com", "synthetic", 3,
                               credential, session, programme_policy=runner.policy)
        with self.assertRaisesRegex(AcquisitionError, "exact-reviewed"):
            embed(["Not reviewed or authorized."])
        credential.get_token.assert_not_called()
        session.post.assert_not_called()

    def test_pending_pack_cannot_publish_from_explicit_operation_grants_alone(self):
        from bc_ingestion.pipeline import build_publish_plan

        self.model_grants()
        runner, _, _, _ = self.pdf_run(pdf_granted=True)
        review = {"publisherPermissionConfirmed": True, "reviewer": "SYNTHETIC TEST ONLY",
                  "reviewedAt": "2026-11-23", "documents": runner.ledger.review_candidates()}
        with self.assertRaisesRegex(AcquisitionError, "pending-rag-permission"):
            build_publish_plan(runner.ledger, runner.policy.publication_catalog(), review,
                               programme_policy=runner.policy)
        self.assertEqual(load_pack("sk").approval_status, "pending-rag-permission")

    def test_long_reviewed_pdf_chunks_are_embedding_compatible_without_losing_source_text(self):
        import re
        from bc_ingestion.vectors import enrich_documents

        runner, plan, _ = self.reviewed_pdf_plan(long=True)
        self.assertTrue(all(len(d["content"]) <= 4000 for d in plan["uploads"]))
        markers = re.findall(r"Synthetic-step-\d{4}", " ".join(d["content"] for d in plan["uploads"]))
        self.assertEqual(markers, [f"Synthetic-step-{i:04d}" for i in range(700)])
        embed = Mock(side_effect=lambda texts: [[1, 2, 3] for _ in texts])
        enriched = enrich_documents(plan["uploads"], embed, 3, programme_policy=runner.policy)
        self.assertEqual(len(enriched), len(plan["uploads"]))

    def test_new_pack_cli_pending_acquire_resume_review_publish_preserves_budgets(self):
        from bc_ingestion.pipeline import Ledger

        scratch = self.output
        self.addCleanup(shutil.rmtree, scratch, True)
        root = Path(__file__).resolve().parents[1] / ".generated" / ("z-" + uuid.uuid4().hex[:8])
        self.addCleanup(shutil.rmtree, root, True)
        content = root / "jurisdictions" / "zz" / "content"
        content.mkdir(parents=True)
        manifest = json.loads((Path(__file__).resolve().parents[2] / "jurisdictions" /
                               "sk" / "jurisdiction.json").read_text(encoding="utf-8"))
        manifest["id"] = "zz"
        manifest["researchHosts"] = ["public.synthetic.example"]
        manifest["content"]["catalog"] = "jurisdictions/zz/content/catalog.json"
        manifest["content"]["sourceProgramme"] = "jurisdictions/zz/content/source-programme.json"
        (content.parent / "jurisdiction.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.programme = json.loads(json.dumps(self.programme).replace(HOST, "public.synthetic.example"))
        self.programme["jurisdictionId"] = "zz"
        self.programme["programmeId"] = "zz-public-corpus"
        self.programme["sources"][0]["id"] = "zz-public-corpus"
        self.programme["sources"][0]["publisher"] = "SYNTHETIC GOVERNMENT"
        self.programme["externalCandidatePublishers"] = "jurisdictions/zz/ingestion/external-policy.json"
        policies = content.parent / "ingestion"
        policies.mkdir()
        (policies / "external-policy.json").write_text(json.dumps({
            "schemaVersion": 1, "jurisdictionId": "zz", "status": "pending-separate-publisher-review",
            "candidates": [], "notice": "SYNTHETIC TEST ONLY",
        }), encoding="utf-8")
        (content / "source-programme.json").write_text(json.dumps(self.programme), encoding="utf-8")
        (content / "catalog.json").write_text("{}", encoding="utf-8")
        self.pack = load_pack("zz", root=root)
        self.output = self.pack.output_path
        self.output.mkdir(parents=True)
        self.path = self.output / "synthetic-review.json"
        self.review = json.loads(json.dumps(self.fixture()).replace(HOST, "public.synthetic.example"))
        self.review["jurisdictionId"] = "zz"
        self.model_grants()
        provider = self.provider()
        url = "https://public.synthetic.example/residents/synthetic-guidance"
        body = (b"<html><head><title>Synthetic guidance</title>"
                b"<meta property='article:modified_time' content='2026-11-23'></head><main><h1>Synthetic guidance</h1><p>"
                + b"Residents can read these synthetic public instructions and confirm current requirements with the responsible publisher. " * 6
                + b"</p></main></html>")
        fetched = []

        class Fetcher:
            robots_observations = {}
            def __init__(self, request_controller, **kwargs):
                self.controller = request_controller
            def fetch(self, target, **kwargs):
                fetched.append(target)
                response = Response(target, 200, {"content-type": "text/html"}, body, DATE)
                self.controller.before_request(target, limit=len(body), delay=1, robots=False)
                self.controller.after_request(response=response)
                return response
            def validate_canonical(self, target, **kwargs):
                return target

        common = ["--jurisdiction", "zz", "--url", "zz-public-corpus=" + url,
                  "--output", str(self.output), "--index-name", "zz-synthetic-public"]
        rights = ["--rights-review", str(self.path), "--rights-sha256", provider.expected_sha256]
        state_path = self.output / "programme" / "manifest.json"

        def cli(command, extra=()):
            out, error = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(error):
                code = main([command, *common, *extra])
            return code, json.loads(out.getvalue()) if code == 0 else None, error.getvalue()

        now = self.now
        class FixedClockProvider(OperationRightsProvider):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs, clock=lambda: now)

        with patch("bc_ingestion.jurisdiction.load_pack", return_value=self.pack) as pack_loader, \
             patch("bc_ingestion.operation_rights.OperationRightsProvider", FixedClockProvider), \
             patch("bc_ingestion.programme.Fetcher", Fetcher):
            code, pending, error = cli("programme", ["--request-budget", "2"])
            self.assertEqual(code, 0, error)
            self.assertEqual(pending["networkRequests"], 0)
            before = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(any(c["reason"].startswith("pending-rag-permission:")
                                for c in before["candidates"].values()))
            before["budget"].update(requests=1, documentRequests=1, chargedBytes=2048)
            before["events"].append({"type": "synthetic-prior-charged-attempt", "responseReceived": False})
            state_path.write_text(json.dumps(before), encoding="utf-8")
            manifest["sourcePolicy"]["approvalStatus"] = "reviewed-operation-grants"
            manifest["sourcePolicy"]["operationReview"] = {"path": "jurisdictions/zz/ingestion/rights/review.json"}
            (content.parent / "jurisdiction.json").write_text(json.dumps(manifest), encoding="utf-8")
            approved = policies / "rights"
            approved.mkdir()
            for item in self.review["evidence"]:
                (approved / item["file"]).write_bytes((self.output / item["file"]).read_bytes())
            self.path = approved / "review.json"
            self.pack = load_pack("zz", root=root)
            with self.assertRaisesRegex(AcquisitionError, "pack|identity|programme"):
                self.provider()
            self.review["packIdentity"] = self.pack.identity
            provider = self.provider()
            rights = ["--rights-review", str(self.path), "--rights-sha256", provider.expected_sha256]
            pack_loader.return_value = self.pack
            code, _, error = cli("programme", ["--acquire"])
            self.assertEqual(code, 2)
            self.assertEqual(fetched, [])
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["budget"], before["budget"])
            altered = deepcopy(before)
            altered["packIdentity"]["manifestHash"] = "0" * 64
            state_path.write_text(json.dumps(altered), encoding="utf-8")
            code, _, error = cli("programme", [*rights, "--acquire"])
            self.assertEqual(code, 2)
            self.assertIn("pack identity changed", error)
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["budget"], before["budget"])
            state_path.write_text(json.dumps(before), encoding="utf-8")
            with patch.dict("os.environ", {"OPERATION_RIGHTS_REVIEW_SHA256": provider.expected_sha256}):
                code, acquired, error = cli("programme", ["--acquire"])
            self.assertEqual(code, 0, error)
            self.assertEqual(acquired["lifecycle"]["extracted"], 1)
            after = json.loads(state_path.read_text(encoding="utf-8"))
            document = next(iter(after["ledger"]["documents"].values()))["versions"][0]["document"]
            self.assertEqual(document["flags"], [], document)
            self.assertEqual(after["limits"], before["limits"])
            self.assertEqual(after["budget"]["requests"], 2)
            self.assertEqual(after["budget"]["chargedBytes"], 2048 + len(body))
            self.assertNotEqual(after["packIdentity"], before["packIdentity"])
            self.assertTrue(any(event["type"] == "reviewed-pack-identity-bound" for event in after["events"]))
            code, resumed, error = cli("programme", [*rights, "--acquire", "--resume"])
            self.assertEqual(code, 0, error)
            self.assertEqual(resumed["networkRequests"], 2)
            self.assertEqual(fetched, [url])
            for extra in (["--request-budget", "3"], ["--index-name", "zz-other-public"]):
                code, _, error = cli("programme", [*rights, "--acquire", "--resume", *extra])
                self.assertEqual(code, 2)
                self.assertTrue("reset" in error or "replace" in error, error)
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["budget"], after["budget"])
            review_path = self.output / "exact-reviewed.json"
            review_path.write_text(json.dumps({
                "publisherPermissionConfirmed": True, "reviewer": "SYNTHETIC TEST ONLY",
                "reviewedAt": "2026-11-23", "documents": Ledger(after["ledger"]).review_candidates(),
            }), encoding="utf-8")
            modules, calls, _ = self.fake_sdk()
            environment = {**self.publish_environment(), "AZURE_SEARCH_INDEX": "zz-synthetic-public",
                           "AZURE_SEARCH_VECTOR_ENABLED": "false"}
            with patch.dict("sys.modules", modules), patch.dict("os.environ", environment):
                code, published, error = cli("publish", [*rights, "--review-manifest", str(review_path),
                                                        "--execute", "--approved", "--stage-blob"])
            self.assertEqual(code, 0, error)
            self.assertEqual(published["lifecycle"]["indexed"], 1)
            final = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(final["budget"], after["budget"])
            self.assertEqual(final["packIdentity"], self.pack.identity)
            self.assertTrue(all(name.startswith("zz/reviewed/") for _, name, _, _ in calls["blobs"]))
            self.assertTrue(all(d["publisherUpdatedAt"] is None and d["publisherUpdatedDate"] == "2026-11-23"
                                for d in calls["uploads"]))
            self.assertEqual(len(fetched), 1)

    def test_pack_relative_review_location_and_independent_pin_keep_full_identity(self):
        allowed = self.pack.programme_path.parent / "synthetic-review.json"
        self.assertEqual(self.pack.rights_path(allowed), allowed.resolve())
        with self.assertRaisesRegex(AcquisitionError, "selected pack"):
            self.pack.rights_path(self.pack.programme_path.parents[2] / "bc" / "content" / "review.json")

    def test_candidate_blob_cli_uses_durable_runner_and_read_only_pinned_rights(self):
        import test_blob_store as storage_fakes
        from test_programme import Clock

        provider = self.provider()
        modules, _, _ = self.fake_sdk()
        errors = modules["azure.core.exceptions"]
        replacements = {"MatchConditions": SimpleNamespace(IfNotModified="not-modified", IfMissing="missing")}
        for name in ("ResourceExistsError", "ResourceModifiedError", "ResourceNotFoundError", "ServiceResponseError"):
            kind = type(name, (errors.AzureError,), {})
            setattr(errors, name, kind)
            replacements[name] = kind
        modules["azure.core"].MatchConditions = replacements["MatchConditions"]
        memory = storage_fakes.MemoryAzure(Clock())
        memory.seed("rights", "sk/review.json", self.path.read_bytes())

        class Service:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return memory
            def __exit__(self, *args):
                return False

        modules["azure.storage.blob"].BlobServiceClient = Service
        now = self.now
        class FixedClockProvider(OperationRightsProvider):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs, clock=lambda: now)

        fetched = []
        body = (b"<html><title>Synthetic guidance</title><main><h1>Synthetic guidance</h1><p>"
                + b"Read these synthetic public instructions and confirm current requirements with the responsible publisher. " * 6
                + b"</p></main></html>")

        class Fetcher:
            robots_observations = {}
            def __init__(self, request_controller, **kwargs):
                self.controller = request_controller
            def fetch(self, target, **kwargs):
                fetched.append(target)
                response = Response(target, 200, {"content-type": "text/html"}, body, DATE)
                self.controller.before_request(target, limit=len(body), delay=1, robots=False)
                self.controller.after_request(response=response)
                return response
            def validate_canonical(self, target, **kwargs):
                return target

        arguments = [
            "programme", "--jurisdiction", "sk", "--output", str(self.output),
            "--url", self.programme["sources"][0]["id"] + "=" + URL,
            "--programme-store", "azure-blob", "--blob-account-url", "https://synthetic.blob.core.windows.net",
            "--candidate-container", "candidates", "--run-prefix", "sk/synthetic-run",
            "--rights-container", "rights", "--rights-blob", "sk/review.json",
            "--rights-review", str(self.path), "--rights-sha256", provider.expected_sha256,
        ]

        def cli(extra):
            out, error = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(error):
                code = main([*arguments, *extra])
            self.assertEqual(code, 0, error.getvalue())
            return json.loads(out.getvalue())

        with patch.dict("sys.modules", modules), patch.multiple(storage_fakes, create=True, **replacements), \
             patch("bc_ingestion.operation_rights.OperationRightsProvider", FixedClockProvider), \
             patch("bc_ingestion.programme.Fetcher", Fetcher):
            initialized = cli(["--initialize", "--request-budget", "2"])
            self.assertEqual(initialized["networkRequests"], 0)
            self.assertEqual(initialized["lifecycle"]["discovered"], 0)
            self.assertEqual(initialized["lifecycle"]["fetched"], 0)
            acquired = cli(["--acquire"])
            self.assertEqual(acquired["networkRequests"], 1)
            self.assertEqual(acquired["reviewRequired"], 1)
            self.assertEqual(acquired["lifecycle"]["discovered"], 1)
            self.assertEqual(acquired["lifecycle"]["fetched"], 1)
            self.assertEqual(acquired["lifecycle"]["extracted"], 1)
            self.assertEqual(acquired["lifecycle"]["reviewed"], 0)
            self.assertEqual(acquired["lifecycle"]["indexed"], 0)
            resumed = cli(["--acquire", "--resume"])
            self.assertEqual(resumed["budget"], acquired["budget"])
            self.assertEqual(resumed["limits"], acquired["limits"])
            self.assertEqual(resumed["lifecycle"], acquired["lifecycle"])
            self.assertEqual(fetched, [URL])
        self.assertTrue(any(container == "candidates" and name.startswith("sk/synthetic-run/objects/")
                            for container, name in memory.items))
        self.assertFalse(any(operation in {"upload", "delete"} and key[0] == "rights"
                             for operation, key, _ in memory.calls))


class NetworkIsolationTests(unittest.TestCase):
    def child(self, arguments):
        code = f"""
import json, sys, socket, http.client, subprocess
from unittest.mock import patch
guards = []
for target in {NETWORK_GUARDS!r} + ("subprocess.Popen",):
    guard = patch(target, side_effect=AssertionError("Live DNS/HTTP or child execution forbidden"))
    guard.start()
    guards.append(guard)
import requests
if sys.argv[1:] == ["--verify-network-guards"]:
    probes = [
        ("DNS", lambda: socket.getaddrinfo("guard.invalid", 443)),
        ("socket", lambda: socket.create_connection(("192.0.2.1", 443))),
        ("HTTPS", lambda: http.client.HTTPSConnection("guard.invalid").connect()),
        ("requests", lambda: requests.Session().send(requests.Request("GET", "https://guard.invalid").prepare())),
        ("child", lambda: subprocess.Popen([sys.executable, "-c", "pass"])),
    ]
    blocked = []
    for name, probe in probes:
        try:
            probe()
        except AssertionError:
            blocked.append(name)
    print(json.dumps({{"blocked": blocked}}))
    raise SystemExit(0 if len(blocked) == len(probes) else 1)
from bc_ingestion.cli import main
raise SystemExit(main(sys.argv[1:]))
"""
        root = Path(__file__).resolve().parents[2]
        return subprocess.run(
            [sys.executable, "-B", "-c", code, *arguments], cwd=root,
            env={**os.environ, "JURISDICTION": "sk", "PYTHONPATH": str(root / "ingestion"),
                 "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=30, check=False,
        )

    def test_subprocess_cli_policy_is_read_only_with_child_network_guards(self):
        result = self.child(["source-policy", "--jurisdiction", "sk"])
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["networkRequests"], 0)
        self.assertEqual(set(report["counts"].values()), {0})
        self.assertEqual(report["status"], "pending-rag-permission")

    def test_subprocess_guards_block_dns_http_and_further_children(self):
        result = self.child(["--verify-network-guards"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["blocked"], ["DNS", "socket", "HTTPS", "requests", "child"])


if __name__ == "__main__":
    unittest.main()
