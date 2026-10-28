"""Archived HTML and synthetic qualification fixtures; no crawling or approvals."""

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from bs4 import BeautifulSoup

from bc_ingestion.catalog import load_catalog
from bc_ingestion.cli import main
from bc_ingestion.extract import chunk_document, extract
from bc_ingestion.fetch import Response
from bc_ingestion.pipeline import Ledger, build_publish_plan, reextract_snapshot, save_json
from bc_ingestion.policy import AcquisitionError, SERVICE_BC


ROOT = Path(__file__).resolve().parents[2]
DATE = "2026-10-25T00:21:15Z"
URL = "https://www2.gov.bc.ca" + SERVICE_BC
PROSE = "Synthetic public guidance about a published service and official preparation requirements. " * 6


def fixture(body):
    return Response(URL, 200, {"content-type": "text/html"}, (
        "<html lang='en'><head><title>Offices</title></head><body><main>" + body + "</main></body></html>"
    ).encode(), DATE)


class ReextractionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(ROOT / "data" / "pilot-catalog.json")
        self.output = ROOT / "ingestion" / ".generated" / ("rx-" + uuid.uuid4().hex[:8])
        self.output.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.output)

    def test_reference_definitions_retain_qualifications_in_every_affected_chunk(self):
        definition = "The group includes service A and service B. Service B is not available on holidays."
        rows = "".join(f"<tr><th scope='row'>Office {i:03d}</th><td>{PROSE}<a href='#services'>Popular services</a></td></tr>"
                       for i in range(40))
        document = extract(fixture(
            f"<h1>Offices</h1><h2 id='services'>Popular services</h2><p>{definition}</p>"
            f"<h2>Directory</h2><table><tr><th>Office</th><th>Services</th></tr>{rows}</table>"
        ))
        table_chunks = [chunk for chunk in chunk_document(document) if "Office | Services" in chunk["content"]]
        self.assertGreater(len(table_chunks), 1)
        for chunk in table_chunks:
            self.assertIn(definition, chunk["content"])
            self.assertIn("#services", chunk["content"])
            self.assertLessEqual(len(chunk["content"]), 8000)
        for i in range(40):
            self.assertEqual(sum(f"Office {i:03d} | " in chunk["content"] for chunk in table_chunks), 1)

    def test_tfoot_and_describedby_notes_are_repeated_not_misclassified_as_data_rows(self):
        note = "Phone the office to confirm the published schedule."
        footer = "Published hours are not appointment availability."
        rows = "".join(f"<tr><td>Office {i:03d}</td><td>{PROSE}</td></tr>" for i in range(35))
        document = extract(fixture(
            "<h1>Office guide</h1><table aria-describedby='note'>"
            f"<thead><tr><th>Office</th><th>Hours</th></tr></thead><tbody>{rows}</tbody>"
            f"<tfoot><tr><td>Qualification</td><td>{footer}</td></tr></tfoot></table>"
            f"<p id='note'>{note}</p><h2>Other information</h2><p>{PROSE}</p>"
        ))
        block = next(b for s in document.sections for b in s.blocks if b["kind"] == "table")
        self.assertEqual(len(block["rows"]), 35)
        self.assertEqual(len(block["footers"]), 1)
        chunks = [c for c in chunk_document(document) if "Office | Hours" in c["content"]]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(note in c["content"] and footer in c["content"] for c in chunks))

    def test_missing_or_ambiguous_qualification_targets_quarantine_instead_of_omitting(self):
        for definitions in ("", "<p id='note'>First</p><p id='note'>Second</p>"):
            with self.subTest(definitions=definitions):
                document = extract(fixture(
                    f"<h1>Guide</h1><p>{PROSE}</p><table><tr><th>Service</th></tr>"
                    "<tr><td><a href='#note'>Check the qualifications</a></td></tr></table>" + definitions
                ))
                self.assertIn("table-reference-review-required", document.flags)
                self.assertEqual(document.quality, "quarantined")

    def test_reference_group_that_cannot_fit_is_explicitly_quarantined(self):
        document = extract(fixture(
            f"<h1>Guide</h1><h2 id='terms'>Service qualifications</h2><p>{PROSE * 20}</p>"
            "<h2>Directory</h2><table><tr><th>Service</th></tr>"
            "<tr><td><a href='#terms'>Subject to the complete qualifications</a></td></tr></table>"
        ))
        self.assertIn("oversized-table-reference-context", document.flags)
        self.assertEqual(document.quality, "quarantined")
        self.assertTrue(any(PROSE.strip() in s.text for s in document.sections))

    def test_archived_reextraction_checks_raw_hash_and_cannot_promote_or_refresh_dates(self):
        source = Ledger()
        fetched = fixture(f"<h1>Offices</h1><p>{PROSE}</p>")
        source.record(fetched, "service-bc", "Government of British Columbia")
        key = next(iter(source.state["documents"]))
        ledger_path, response_path = self.output / "original.json", self.output / "source.html"
        save_json(ledger_path, source.state)
        response_path.write_bytes(fetched.body)
        original = ledger_path.read_bytes()
        report = reextract_snapshot(ledger_path, key, response_path, self.catalog, self.output)
        self.assertEqual(report["networkRequests"], 0)
        self.assertFalse(report["publicationEnabled"])
        self.assertEqual(report["sourceCheckedAt"], DATE)
        destination = ROOT / report["output"]
        candidate = json.loads((destination / "state.json").read_text(encoding="utf-8"))
        entry = next(iter(candidate["documents"].values()))
        self.assertIsNone(entry["activeVersion"])
        self.assertEqual(entry["versions"][-1]["document"]["checked_at"], DATE)
        self.assertFalse(json.loads((destination / "review-required.json").read_text(encoding="utf-8"))["publisherPermissionConfirmed"])
        self.assertEqual(ledger_path.read_bytes(), original)
        response_path.write_bytes(b"Changed response")
        with self.assertRaises(AcquisitionError):
            reextract_snapshot(ledger_path, key, response_path, self.catalog, self.output)

    def test_archived_oversized_cell_retains_full_source_and_withholds_all_chunks(self):
        body = fixture("<h1>Guide</h1><table><tr><th>Header</th></tr><tr><td>"
                       + PROSE * 20 + "</td></tr></table>")
        source = Ledger()
        source.record(body, "service-bc", "Government of British Columbia")
        key = next(iter(source.state["documents"]))
        ledger_path, response_path = self.output / "original.json", self.output / "source.html"
        save_json(ledger_path, source.state)
        response_path.write_bytes(body.body)
        report = reextract_snapshot(ledger_path, key, response_path, self.catalog, self.output)
        self.assertEqual(report["status"], "quarantined")
        self.assertEqual(report["chunks"], 0)
        self.assertIn("oversized-table-row", report["flags"])
        self.assertTrue((ROOT / report["output"] / "responses" / (body.digest + ".body")).exists())

    def test_captured_service_bc_table_has_all_65_intact_rows_and_reference_definitions(self):
        root = ROOT / "ingestion" / ".generated"
        raw, source_ledger = root / "service-bc.html", root / "state.json"
        if not raw.exists() or not source_ledger.exists():
            self.skipTest("The reviewed publisher response is a local, uncommitted artifact")
        key = "41a0dff74c96234f8edb988e2acbb02b"
        protected = [root / name for name in ("state.json", "approved-review.json", "publish-plan.json")]
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in protected]
        with patch("bc_ingestion.fetch.transport", side_effect=AssertionError("No crawling")), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([
                "reextract", "--from-ledger", str(source_ledger), "--document-id", key,
                "--response-file", str(raw), "--output", str(self.output),
            ]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["tableRows"], 65)
        self.assertEqual(report["flags"], [])
        self.assertEqual(report["status"], "review-required")
        self.assertLessEqual(report["maxChunkChars"], 8000)
        self.assertEqual(len(report["replacesPublishedChunkIds"]), 3)
        destination = ROOT / report["output"]
        chunks = json.loads((destination / "chunks.json").read_text(encoding="utf-8"))["chunks"]
        state = json.loads((destination / "state.json").read_text(encoding="utf-8"))
        doc = state["documents"][key]["versions"][-1]["document"]
        ledger = Ledger(state)
        unapproved = build_publish_plan(ledger, self.catalog)
        self.assertEqual(unapproved["uploads"], [])
        self.assertEqual(unapproved["deleteIds"], [])
        synthetic_review = {
            "publisherPermissionConfirmed": True,
            "reviewer": "SYNTHETIC UNIT TEST ONLY; not a real approval",
            "reviewedAt": DATE, "documents": ledger.review_candidates(),
        }
        replacement = build_publish_plan(ledger, self.catalog, synthetic_review)
        self.assertEqual(len(replacement["uploads"]), 11)
        self.assertEqual(replacement["deleteIds"], sorted(report["replacesPublishedChunkIds"]))
        changed = deepcopy(state)
        changed["documents"][key]["versions"][-1]["derivedFromSnapshot"]["publishedChunkIds"].append("unrelated-key")
        with self.assertRaises(AcquisitionError):
            build_publish_plan(Ledger(changed), self.catalog, synthetic_review)
        table = next(b for s in doc["sections"] for b in s["blocks"] if b["kind"] == "table")
        table_chunks = [c for c in chunks if "Location | Address and contact details | Hours | More information" in c["content"]]
        self.assertEqual(len(table["rows"]), 65)
        for index, row in enumerate(table["rows"]):
            containing = [c for c in table_chunks if row in c["content"]]
            self.assertEqual(len(containing), 1)
            for reference in table["rowReferences"][index]:
                self.assertIn(table["references"][reference], containing[0]["content"])
        source_soup = BeautifulSoup(raw.read_bytes(), "html.parser")
        for reference, text in table["references"].items():
            target = source_soup.find(id=reference)
            self.assertIn(target.parent.get_text(" ", strip=True), " ".join(text.split()))
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in protected])


if __name__ == "__main__":
    unittest.main()
