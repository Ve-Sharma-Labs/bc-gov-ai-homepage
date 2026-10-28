import json
from pathlib import Path
import unittest

from bc_ingestion.extract import chunk_document
from bc_ingestion.fetch import Response
from bc_ingestion.metadata import digest
from bc_ingestion.open_data import (
    LICENCE_TITLE,
    LICENCE_URL,
    PACKAGE_ID,
    PACKAGE_NAME,
    PACKAGE_URL,
    RECORDS_URL,
    RESOURCE_ID,
    build_service_bc_candidate,
)
from bc_ingestion.pipeline import Ledger, build_publish_plan
from bc_ingestion.policy import AcquisitionError
from bc_ingestion.service_directory import build_service_bc_directory_document


ROOT = Path(__file__).resolve().parents[2]


def response(url, value):
    return Response(
        url,
        200,
        {"content-type": "application/json; charset=utf-8"},
        json.dumps(value, separators=(",", ":")).encode(),
        "2026-10-27T18:30:00Z",
    )


def package():
    return {
        "success": True,
        "result": {
            "id": PACKAGE_ID,
            "name": PACKAGE_NAME,
            "title": "Service BC Office Locations",
            "license_title": LICENCE_TITLE,
            "license_url": LICENCE_URL,
            "private": False,
            "publish_state": "PUBLISHED",
            "security_class": "PUBLIC",
            "view_audience": "Public",
            "download_audience": "Public",
            "record_last_modified": "2026-10-27",
            "data_quality": "Up-to-date, authoritative source of truth data.",
            "resources": [
                {
                    "id": RESOURCE_ID,
                    "package_id": PACKAGE_ID,
                    "datastore_active": True,
                    "last_modified": "2020-05-08T21:32:47.819000",
                }
            ],
        },
    }


def records():
    fields = {
        "_id": "int",
        "External Site": "text",
        "Address": "text",
        "Locality": "text",
        "Site_Phone_No": "text",
        "Site_Fax_no": "text",
        "Website_URL": "text",
        "Site_Email": "text",
        "Latitude": "numeric",
        "Longitude": "numeric",
        "Office Code": "numeric",
    }
    rows = [
        {
            "_id": 1,
            "External Site": "Service BC - Example",
            "Address": "100 Main Street",
            "Locality": "Example",
            "Site_Phone_No": "250 555-0100",
            "Site_Fax_no": "",
            "Website_URL": "http://www2.gov.bc.ca/servicebc/example",
            "Site_Email": "",
            "Latitude": 50.1,
            "Longitude": -120.2,
            "Office Code": 10,
        },
        {
            "_id": 2,
            "External Site": "Service BC - Another",
            "Address": "200 Main Street",
            "Locality": "Another",
            "Site_Phone_No": "",
            "Site_Fax_no": None,
            "Website_URL": "",
            "Site_Email": "",
            "Latitude": 54.2,
            "Longitude": -123.4,
            "Office Code": 20,
        },
    ]
    return {
        "success": True,
        "result": {
            "resource_id": RESOURCE_ID,
            "total": len(rows),
            "fields": [
                {"id": name, "type": field_type} for name, field_type in fields.items()
            ],
            "records": rows,
        },
    }


class ServiceBcOpenDataTests(unittest.TestCase):
    def build(self, package_value=None, record_value=None):
        return build_service_bc_candidate(
            response(PACKAGE_URL, package_value or package()),
            response(RECORDS_URL, record_value or records()),
            checked_at="2026-10-27T18:30:00Z",
        )

    def test_dataset_specific_open_licence_creates_candidate_only_artifact(self):
        candidate = self.build()
        self.assertEqual(candidate["recordCount"], 2)
        self.assertEqual(candidate["records"][0]["locality"], "Another")
        self.assertEqual(candidate["rights"]["status"], "dataset-specific-open-licence")
        self.assertFalse(candidate["publicationApproved"])
        self.assertIn("published-hours-not-included", candidate["reviewFlags"])
        self.assertIn("missing-contact-fields-present", candidate["reviewFlags"])
        self.assertIn("legacy-http-office-links-present", candidate["reviewFlags"])
        self.assertEqual(candidate["records"][0]["fax"], "")
        self.assertRegex(candidate["contentHash"], r"^[0-9a-f]{64}$")
        self.assertRegex(candidate["reviewHash"], r"^[0-9a-f]{64}$")

    def test_dataset_identity_licence_and_public_status_cannot_drift(self):
        for field, value in (
            ("id", "other"),
            ("license_title", "Other licence"),
            ("license_url", "https://example.com/licence"),
            ("private", True),
            ("publish_state", "DRAFT"),
        ):
            with self.subTest(field=field):
                changed = package()
                changed["result"][field] = value
                with self.assertRaises(AcquisitionError):
                    self.build(package_value=changed)

    def test_incomplete_or_duplicate_records_fail_closed(self):
        incomplete = records()
        incomplete["result"]["total"] = 3
        with self.assertRaises(AcquisitionError):
            self.build(record_value=incomplete)
        duplicate = records()
        duplicate["result"]["records"][1]["Office Code"] = 10
        with self.assertRaises(AcquisitionError):
            self.build(record_value=duplicate)
        changed_schema = records()
        next(
            field
            for field in changed_schema["result"]["fields"]
            if field["id"] == "Office Code"
        )["type"] = "text"
        with self.assertRaises(AcquisitionError):
            self.build(record_value=changed_schema)

    def test_candidate_rejects_invalid_coordinates_and_websites(self):
        for field, value in (
            ("Latitude", 100),
            ("Longitude", -200),
            ("Website_URL", "javascript:x"),
        ):
            with self.subTest(field=field):
                changed = records()
                changed["result"]["records"][0][field] = value
                with self.assertRaises(AcquisitionError):
                    self.build(record_value=changed)

    def test_candidate_converts_to_reviewable_directory_chunks_without_inference(self):
        candidate = self.build()
        adapted = build_service_bc_directory_document(candidate)
        document = adapted.document
        rendered = "\n".join(section.text for section in document.sections)
        self.assertEqual(document.metadata["documentType"], "service-directory")
        self.assertEqual(document.metadata["sourceIds"], ["service-bc"])
        self.assertIn("http://www2.gov.bc.ca/servicebc/example", rendered)
        self.assertNotIn("Hours:", rendered)
        self.assertNotIn("Services offered:", rendered)
        self.assertGreaterEqual(len(chunk_document(document)), 1)

        ledger = Ledger()
        ledger.record(
            adapted.response,
            adapted.source_id,
            adapted.publisher,
            document=document,
            acquisition_mode="source-adapter",
            origin="source-adapter",
            adapter_id=adapted.adapter_id,
        )
        review = {
            "publisherPermissionConfirmed": True,
            "reviewer": "SYNTHETIC TEST ONLY",
            "reviewedAt": "2026-10-27T18:30:00Z",
            "documents": ledger.review_candidates(),
        }
        plan = build_publish_plan(
            ledger,
            json.loads((ROOT / "data" / "pilot-catalog.json").read_text(encoding="utf-8")),
            review,
        )
        self.assertTrue(plan["uploads"])
        self.assertTrue(all(chunk["documentType"] == "service-directory" for chunk in plan["uploads"]))

    def test_directory_converter_rejects_unreviewed_fields(self):
        candidate = self.build()
        candidate["records"][0]["hours"] = "Never infer this"
        candidate["contentHash"] = digest(candidate["records"])
        candidate["reviewHash"] = digest({
            key: value for key, value in candidate.items() if key != "reviewHash"
        })
        with self.assertRaises(AcquisitionError):
            build_service_bc_directory_document(candidate)


if __name__ == "__main__":
    unittest.main()
