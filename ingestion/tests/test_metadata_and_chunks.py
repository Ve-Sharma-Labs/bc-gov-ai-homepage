"""Hash, legal-time, schema-migration and complete-content regression fixtures."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
from unittest.mock import patch

from bc_ingestion.azure_publish import _execute, build_index, merge_index_schema, migrate_index
from bc_ingestion.catalog import load_catalog
from bc_ingestion.extract import ChunkingError, chunk_document, extract
from bc_ingestion.fetch import Response
from bc_ingestion.metadata import legal_effective_on, validate_legal
from bc_ingestion.pipeline import Ledger, build_publish_plan, document_id, published_ids, restore_document
from bc_ingestion.policy import AcquisitionError


ROOT = Path(__file__).resolve().parents[2]
URL = "https://www2.gov.bc.ca/gov/content/health/synthetic-metadata"
DATE = "2026-10-27T01:20:00Z"
PUBLISHER = "Government of British Columbia"
PROSE = "This synthetic preparation guidance preserves context and official service distinctions. " * 8


def response(body=None, *, status=200):
    text = body if body is not None else f"<h1>Example guide</h1><p>{PROSE}</p>"
    return Response(URL, status, {"content-type": "text/html"}, (
        "<html lang='en-CA'><head><title>Example guide</title></head><body><main>"
        + text + "</main></body></html>"
    ).encode(), DATE)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(ROOT / "data" / "pilot-catalog.json")
        self.ledger = Ledger()
        self.ledger.record(response(), "health", PUBLISHER)
        self.entry = self.ledger.find(URL)

    def review(self):
        return {
            "publisherPermissionConfirmed": True, "reviewer": "SYNTHETIC TEST ONLY",
            "reviewedAt": DATE, "documents": [deepcopy(self.ledger.review_candidates()[0])],
        }

    def test_metadata_round_trip_includes_hashes_language_and_canonical_provenance(self):
        document = self.entry["versions"][0]["document"]
        restored = restore_document(json.loads(json.dumps(document)))
        self.assertEqual(restored.to_dict(), document)
        plan = build_publish_plan(self.ledger, self.catalog, self.review())
        chunk = plan["uploads"][0]
        self.assertEqual(chunk["canonicalUrl"], URL)
        self.assertEqual(chunk["sourceUrl"], URL)
        self.assertEqual(chunk["sourceIds"], ["health"])
        self.assertEqual(chunk["language"], "en-CA")
        self.assertEqual(chunk["documentType"], "guidance")
        self.assertEqual(chunk["mediaType"], "text/html")
        self.assertRegex(chunk["extractionHash"], r"^[0-9a-f]{64}$")
        self.assertEqual(chunk["responseHash"], response().digest)
        self.assertIsNone(chunk["effectiveFrom"])
        self.assertIsNone(chunk["consolidationDate"])
        self.assertEqual(chunk["rightsStatus"], "review-required")

    def test_new_content_requires_metadata_review_not_just_legacy_content_hash(self):
        review = self.review()
        review["documents"][0].pop("extractionHash")
        review["documents"][0].pop("reviewHash")
        self.assertEqual(build_publish_plan(self.ledger, self.catalog, review)["uploads"], [])

    def test_language_or_legal_metadata_tampering_invalidates_review(self):
        for field, value in (("language", "fr"), ("documentType", "notice")):
            with self.subTest(field=field):
                ledger = Ledger(deepcopy(self.ledger.state))
                ledger.find(URL)["versions"][0]["document"]["metadata"][field] = value
                with self.assertRaises(AcquisitionError):
                    build_publish_plan(ledger, self.catalog, self.review())

    def test_same_content_with_new_provenance_gets_a_new_review_identity(self):
        old = self.review()
        previous_hash = self.entry["versions"][-1]["document"]["content_hash"]
        other = response()
        other.body = other.body.replace(b"en-CA", b"fr-CA")
        self.ledger.record(other, "health", PUBLISHER)
        self.assertEqual(self.entry["versions"][-1]["document"]["content_hash"], previous_hash)
        self.assertNotEqual(self.entry["versions"][-1]["reviewHash"], old["documents"][0]["reviewHash"])
        self.assertEqual(build_publish_plan(self.ledger, self.catalog, old)["uploads"], [])

    def test_withdrawal_then_identical_reappearance_never_reuses_old_review(self):
        old = self.review()
        published = build_publish_plan(self.ledger, self.catalog, old)
        self.ledger.acknowledge(published)
        self.ledger.record(response(status=410), "health", PUBLISHER)
        self.ledger.record(response(), "health", PUBLISHER)
        plan = build_publish_plan(self.ledger, self.catalog, old)
        self.assertEqual(plan["uploads"], [])
        self.assertEqual(plan["deleteIds"], [chunk["id"] for chunk in published["uploads"]])
        self.assertNotEqual(self.entry["versions"][-1]["reviewHash"], old["documents"][0]["reviewHash"])
        self.assertEqual(self.entry["versions"][-1]["status"], "review-required")
        self.assertIsNone(self.entry["activeVersion"])

    def test_304_cannot_resurrect_withdrawn_or_quarantined_versions(self):
        for outcome in ("withdrawn", "quarantined"):
            with self.subTest(outcome=outcome):
                ledger = Ledger(deepcopy(self.ledger.state))
                ledger.find(URL)["versions"][-1]["status"] = outcome
                with self.assertRaises(AcquisitionError):
                    ledger.record(response(status=304), "health", PUBLISHER)

    def test_unchanged_quarantine_does_not_create_duplicate_versions(self):
        fetched = response("<h1>Scheduled maintenance</h1><p>Temporarily unavailable.</p>")
        ledger = Ledger()
        for _ in range(3):
            ledger.record(fetched, "health", PUBLISHER)
        self.assertEqual(len(ledger.find(URL)["versions"]), 1)
        self.assertEqual(ledger.find(URL)["versions"][0]["status"], "quarantined")

    def test_new_alias_to_an_existing_canonical_withdraws_old_alias_keys(self):
        original_plan = build_publish_plan(self.ledger, self.catalog, self.review())
        self.ledger.acknowledge(original_plan)
        canonical = response()
        canonical.url = URL + "/canonical"
        canonical.body = canonical.body.replace(b"Example guide", b"Canonical guide")
        self.ledger.record(canonical, "health", PUBLISHER)
        redirected = deepcopy(canonical)
        redirected.aliases = [URL]
        self.ledger.record(redirected, "health", PUBLISHER)
        self.assertEqual(self.ledger.find(URL)["url"], canonical.url)
        self.assertEqual(self.entry["versions"][0]["status"], "superseded")
        plan = build_publish_plan(self.ledger, self.catalog)
        self.assertEqual(plan["deleteIds"], [chunk["id"] for chunk in original_plan["uploads"]])

    def test_same_words_at_a_verified_new_canonical_are_not_a_duplicate_of_superseded_alias(self):
        new = response()
        new.url = URL + "/canonical"
        new.aliases = [URL]
        self.ledger.record(new, "health", PUBLISHER)
        self.assertEqual(self.ledger.find(new.url)["versions"][-1]["status"], "review-required")
        self.assertEqual(self.ledger.find(URL)["url"], new.url)

    def test_invalid_publisher_date_is_not_used_as_a_legal_or_search_date(self):
        fetched = response()
        fetched.body = fetched.body.replace(b"</head>", b"<meta name='dcterms.modified' content='2026-02-30'></head>")
        doc = extract(fetched)
        self.assertIsNone(doc.publisher_updated_at)
        self.assertIsNone(doc.metadata["legal"])
        self.assertIn("invalid-publisher-date", doc.flags)

    def test_legal_dates_are_calendar_intervals_not_publisher_or_fetch_dates(self):
        legal = {
            "status": "historical", "effectiveFrom": "2025-01-01", "effectiveTo": "2026-02-01",
            "consolidationDate": "2026-09-01", "isHistorical": True, "sectionId": "section-17",
            "amendmentIds": ["synthetic-amendment"], "evidenceUrl": URL,
        }
        self.assertFalse(legal_effective_on(legal, "2024-12-31"))
        self.assertTrue(legal_effective_on(legal, "2025-01-01"))
        self.assertTrue(legal_effective_on(legal, "2026-01-31"))
        self.assertFalse(legal_effective_on(legal, "2026-02-01"))
        self.assertIsNone(legal_effective_on(None, "2026-10-27"))
        self.assertIsNone(legal_effective_on({"status": "unknown", "consolidationDate": "2026-09-01",
                                            "evidenceUrl": URL}, "2026-10-27"))
        document = extract(response(), metadata={"documentType": "legal", "legal": legal, "sourceIds": ["health"]})
        ledger = Ledger()
        ledger.record(response(), "health", PUBLISHER, document=document)
        review = {
            "publisherPermissionConfirmed": True, "reviewer": "SYNTHETIC TEST ONLY", "reviewedAt": DATE,
            "documents": ledger.review_candidates(),
        }
        chunk = build_publish_plan(ledger, self.catalog, review)["uploads"][0]
        self.assertEqual(chunk["effectiveFrom"], "2025-01-01")
        self.assertEqual(chunk["effectiveTo"], "2026-02-01")
        self.assertEqual(chunk["consolidationDate"], "2026-09-01")
        self.assertEqual(chunk["legalSectionId"], "section-17")
        self.assertTrue(chunk["isHistorical"])

    def test_future_and_repealed_versions_respect_explicit_dates(self):
        future = {"status": "not-yet-in-force", "effectiveFrom": "2027-01-01", "evidenceUrl": URL}
        self.assertFalse(legal_effective_on(future, "2026-10-27"))
        repealed = {"status": "repealed", "effectiveFrom": "2020-01-01", "repealedAt": "2026-10-01", "evidenceUrl": URL}
        self.assertTrue(legal_effective_on(repealed, "2026-09-30"))
        self.assertFalse(legal_effective_on(repealed, "2026-10-01"))
        for invalid in (
            {"status": "repealed", "evidenceUrl": URL},
            {"effectiveFrom": "2026-02-30", "evidenceUrl": URL},
            {"effectiveFrom": "2026-01-01T00:00:00Z", "evidenceUrl": URL},
            {"effectiveFrom": "2026-02-01", "effectiveTo": "2026-02-01", "evidenceUrl": URL},
            {"effectiveFrom": "2026-02-01", "effectiveTo": "2026-01-01", "evidenceUrl": URL},
            {"effectiveFrom": "2026-01-01"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(AcquisitionError):
                validate_legal(invalid)

    def test_legal_versions_with_identical_words_but_different_dates_are_not_duplicates(self):
        first = {"status": "in-force", "effectiveFrom": "2020-01-01", "evidenceUrl": URL}
        second = {"status": "in-force", "effectiveFrom": "2026-01-01", "evidenceUrl": URL}
        ledger = Ledger()
        for index, legal in enumerate((first, second)):
            fetched = response()
            fetched.url += f"/version-{index}"
            document = extract(fetched, metadata={"documentType": "legal", "legal": legal})
            ledger.record(fetched, "health", PUBLISHER, document=document)
        self.assertEqual([entry["versions"][0]["status"] for entry in ledger.state["documents"].values()],
                         ["review-required", "review-required"])

    def test_legacy_small_snapshot_approval_still_round_trips(self):
        entry = deepcopy(self.entry)
        version = entry["versions"][0]
        doc = version["document"]
        doc.pop("metadata")
        doc.pop("extraction_hash")
        doc["extraction_method"] = "direct-publisher-html/section-aware-v1"
        for section in doc["sections"]:
            section.pop("blocks")
        version["documentVersion"] = f"{entry['documentId']}-{doc['content_hash'][:20]}"
        for key in ("snapshotHash", "reviewGeneration", "reviewHash"):
            version.pop(key)
        ledger = Ledger()
        ledger.state["documents"][entry["documentId"]] = entry
        review = {"publisherPermissionConfirmed": True, "reviewer": "Legacy synthetic reviewer",
                  "reviewedAt": "2026-10-27", "documents": [
                      {"documentId": entry["documentId"], "contentHash": doc["content_hash"]},
                  ]}
        plan = build_publish_plan(ledger, self.catalog, review)
        self.assertTrue(plan["uploads"])
        self.assertIsNone(plan["uploads"][0]["extractionHash"])
        self.assertEqual(plan["uploads"][0]["rightsStatus"], "legacy-exact-review")

    def test_shipped_four_snapshot_state_and_exact_approvals_are_not_rewritten(self):
        root = ROOT / "ingestion" / ".generated"
        paths = [root / name for name in ("state.json", "approved-review.json", "publish-plan.json")]
        if not all(path.exists() for path in paths):
            self.skipTest("Local verified publication artifacts are intentionally not committed")
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
        state = json.loads(paths[0].read_text(encoding="utf-8"))
        review = json.loads(paths[1].read_text(encoding="utf-8"))
        active = [v for e in state["documents"].values() for v in e["versions"] if v["status"] == "active"]
        self.assertEqual(len(active), 4)
        self.assertEqual(sum(len(published_ids(v)) for v in active), 12)
        self.assertEqual(len(review["documents"]), 4)
        plan = build_publish_plan(Ledger(deepcopy(state)), self.catalog, review)
        self.assertTrue(all(len(chunk["content"]) <= 8000 for chunk in plan["uploads"]))
        self.assertTrue(any(row["reason"] == "legacy-structure-review-required"
                            and row["retainedPublishedSnapshot"] for row in plan["withheld"]))
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths])


class ChunkTests(unittest.TestCase):
    def test_long_table_repeats_headers_context_and_exclusions_without_losing_rows(self):
        rows = [f"Office {i:03d} | " + "Synthetic service details " * 8 for i in range(100)]
        table = "<table><caption>Office service capabilities</caption><tr><th>Office</th><th>Services</th></tr>"
        table += "".join("<tr><td>" + row.replace(" | ", "</td><td>") + "</td></tr>" for row in rows)
        table += "</table>"
        warning = "Appointments are not available for this synthetic service."
        fetched = response(f"<h1>Office guide</h1><p>{PROSE}</p>{table}<h2>Exceptions</h2><p>{warning}</p>")
        document = extract(fetched)
        chunks = chunk_document(document)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk["content"]) <= 8000 for chunk in chunks))
        for chunk in chunks:
            self.assertIn("Office | Services", chunk["content"])
            self.assertIn("Office service capabilities", chunk["content"])
            self.assertIn(warning, chunk["content"])
        for row in rows:
            self.assertEqual(sum(row.strip() in chunk["content"] for chunk in chunks), 1)
        self.assertTrue(all(chunk["containsExceptions"] for chunk in chunks))

    def test_long_prose_keeps_following_exceptions_in_each_part(self):
        paragraphs = [f"Clause {i:03d}. " + "Synthetic programme context and detailed conditions. " * 20 for i in range(20)]
        warning = "You are not eligible if the synthetic exception applies."
        document = extract(response("<h1>Eligibility</h1>" + "".join(f"<p>{p}</p>" for p in paragraphs)
                                    + f"<h2>Not eligible</h2><p>{warning}</p>"))
        chunks = chunk_document(document)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(warning in c["content"] and len(c["content"]) <= 8000 for c in chunks))
        for paragraph in paragraphs:
            self.assertEqual(sum(paragraph.strip() in c["content"] for c in chunks), 1)

    def test_one_long_plain_paragraph_is_split_without_truncation(self):
        text = " ".join(f"word{i:05d}" for i in range(1800))
        document = extract(response(f"<h1>Guide</h1><p>{text}</p>"))
        chunks = chunk_document(document)
        self.assertTrue(all(len(c["content"]) <= 8000 for c in chunks))
        for word in text.split():
            self.assertEqual(sum(c["content"].count(word) for c in chunks), 1)

    def test_oversized_row_is_quarantined_with_complete_table_retained(self):
        row = "Synthetic row data " * 600
        document = extract(response(f"<h1>Guide</h1><p>{PROSE}</p>"
                                    "<table><tr><th>Office</th><th>Services</th></tr>"
                                    f"<tr><td>Example</td><td>{row}</td></tr></table>"))
        self.assertEqual(document.quality, "quarantined")
        self.assertIn("oversized-table-row", document.flags)
        self.assertIn(row.strip(), document.sections[0].text)
        with self.assertRaises(ChunkingError):
            chunk_document(document)

    def test_oversized_required_exclusion_is_never_silently_omitted(self):
        text = "You are not eligible. " + PROSE * 15
        document = extract(response(f"<h1>Guide</h1><p>{text}</p>"))
        self.assertIn("oversized-required-context", document.flags)
        self.assertIn(text.strip(), document.sections[0].text)
        with self.assertRaises(ChunkingError):
            chunk_document(document)

    def test_merged_cells_cannot_be_split_as_if_they_were_simple_rows(self):
        rows = "".join(f"<tr><td colspan='2'>{PROSE}</td></tr>" for _ in range(20))
        document = extract(response(f"<h1>Guide</h1><table><tr><th>Header</th></tr>{rows}</table>"))
        self.assertIn("oversized-table-structure-review-required", document.flags)
        with self.assertRaises(ChunkingError):
            chunk_document(document)

    def test_cap_is_not_a_caller_controlled_silent_truncation_target(self):
        document = extract(response())
        with self.assertRaises(AcquisitionError):
            chunk_document(document, max_chars=8001)
        with self.assertRaises(AcquisitionError):
            chunk_document(document, target_chars=9000)

    def test_unstructured_exclusion_text_is_retained_and_never_silently_skipped(self):
        warning = "You are not eligible under this synthetic exclusion."
        document = extract(response(f"<h1>Guide</h1><p>{PROSE}</p><div>{warning}</div>"))
        self.assertIn("unstructured-exclusion-review-required", document.flags)
        self.assertIn(warning, "\n".join(section.text for section in document.sections))
        self.assertEqual(document.quality, "quarantined")

    def test_even_small_merged_tables_require_structural_review(self):
        document = extract(response(
            f"<h1>Guide</h1><p>{PROSE}</p><table><tr><th>One</th><th>Two</th></tr>"
            "<tr><td colspan='2'>A shared condition, not two independent values</td></tr></table>"
        ))
        self.assertIn("complex-table-review-required", document.flags)


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.current = build_index("synthetic-index", 3)
        except ImportError:
            self.skipTest("Optional Azure SDK is not installed")

    def test_additive_migration_preserves_vector_unknown_fields_and_configuration(self):
        from azure.search.documents.indexes.models import SearchFieldDataType, SimpleField
        self.current.fields = self.current.fields[:15] + [
            next(f for f in self.current.fields if f.name == "contentVector"),
            SimpleField(name="publisherExtension", type=SearchFieldDataType.String),
        ]
        self.current.e_tag = '"synthetic-etag"'
        before = deepcopy(self.current.serialize())
        merged = merge_index_schema(self.current, build_index("synthetic-index"))
        self.assertIn("publisherExtension", {f.name for f in merged.fields})
        self.assertEqual(next(f.vector_search_dimensions for f in merged.fields if f.name == "contentVector"), 3)
        self.assertEqual(merged.vector_search.serialize(), self.current.vector_search.serialize())
        self.assertEqual(merged.e_tag, self.current.e_tag)
        self.assertEqual(self.current.serialize(), before)
        self.assertIn("legalSectionId", {f.name for f in merged.fields})

    def test_incompatible_dimensions_and_field_types_fail_before_mutation(self):
        from azure.search.documents.indexes.models import SearchFieldDataType
        before = deepcopy(self.current.serialize())
        with self.assertRaises(AcquisitionError):
            merge_index_schema(self.current, build_index("synthetic-index", 4))
        self.assertEqual(self.current.serialize(), before)
        next(f for f in self.current.fields if f.name == "effectiveFrom").type = SearchFieldDataType.DateTimeOffset
        with self.assertRaises(AcquisitionError):
            merge_index_schema(self.current, build_index("synthetic-index"))

    def test_existing_schema_update_uses_etag_compare_and_swap(self):
        from azure.core import MatchConditions
        self.current.e_tag = '"synthetic-etag"'
        indexes = Mock()
        indexes.get_index.return_value = self.current
        migrate_index(indexes, build_index("synthetic-index"))
        kwargs = indexes.create_or_update_index.call_args.kwargs
        self.assertEqual(kwargs["match_condition"], MatchConditions.IfNotModified)
        self.assertIs(kwargs["allow_index_downtime"], False)
        indexes.create_index.assert_not_called()

    def test_missing_index_uses_create_not_overwriting_upsert(self):
        from azure.core.exceptions import ResourceNotFoundError
        indexes = Mock()
        indexes.get_index.side_effect = ResourceNotFoundError()
        migrate_index(indexes, build_index("synthetic-index"))
        indexes.create_index.assert_called_once()
        indexes.create_or_update_index.assert_not_called()

    def test_existing_index_without_etag_is_not_blindly_overwritten(self):
        indexes = Mock()
        indexes.get_index.return_value = self.current
        with self.assertRaises(AcquisitionError):
            migrate_index(indexes, build_index("synthetic-index"))
        indexes.create_or_update_index.assert_not_called()

    def test_known_withdrawals_run_before_optional_vector_configuration_or_migration(self):
        from types import SimpleNamespace
        selected = Mock()
        selected.__enter__ = Mock(return_value=Mock())
        selected.__exit__ = Mock(return_value=False)
        search = Mock()
        search.delete_documents.return_value = [SimpleNamespace(key="old-key", succeeded=True)]
        search_context = Mock()
        search_context.__enter__ = Mock(return_value=search)
        search_context.__exit__ = Mock(return_value=False)
        with patch("azure.identity.ManagedIdentityCredential", return_value=selected), \
                patch("azure.search.documents.SearchClient", return_value=search_context), \
                patch("bc_ingestion.azure_publish._vector_configuration", side_effect=AcquisitionError("bad config")):
            with self.assertRaises(AcquisitionError):
                _execute({"deleteIds": ["old-key"], "uploads": [{"id": "new-key"}]},
                         "https://synthetic.search.windows.net", "synthetic-index",
                         create_index=True, stage_blob=False)
        search.delete_documents.assert_called_once_with([{"id": "old-key"}])
        search.upload_documents.assert_not_called()

if __name__ == "__main__":
    unittest.main()
