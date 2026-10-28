from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
import unittest
from unittest.mock import patch

try:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.search.documents.indexes.models import SearchFieldDataType
except ImportError as exc:
    raise unittest.SkipTest("Optional Azure SDK is not installed") from exc

from bc_ingestion.azure_publish import (
    LIVE_INDEX_NAME,
    SEMANTIC_CONFIGURATION_NAME,
    SHADOW_INDEX_NAME,
    build_index,
    ensure_shadow_index,
    index_inventory,
    schema_diff,
)
from bc_ingestion.cli import main
from bc_ingestion.policy import AcquisitionError


class FakeIndexes:
    def __init__(self, live, shadow=None):
        self.live = deepcopy(live)
        self.shadow = deepcopy(shadow)
        self.created = []

    def get_index(self, name):
        if name == self.live.name:
            return deepcopy(self.live)
        if self.shadow is not None and name == self.shadow.name:
            return deepcopy(self.shadow)
        raise ResourceNotFoundError()

    def create_index(self, index):
        self.created.append(deepcopy(index))
        self.shadow = deepcopy(index)
        self.shadow.e_tag = '"shadow-etag"'
        return deepcopy(self.shadow)


class ShadowIndexSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = build_index(SHADOW_INDEX_NAME)

    def test_exact_metadata_aware_field_contract_and_filters(self):
        fields = {field.name: field for field in self.schema.fields}
        string_fields = {
            "id", "documentId", "sourceId", "title", "publisher", "url", "content",
            "section", "status", "documentVersion", "contentHash", "canonicalUrl",
            "sourceUrl", "language", "documentType", "mediaType", "extractionMethod",
            "extractionHash", "responseHash", "rightsStatus", "rightsReviewId",
            "rightsHash", "licenceUrl", "legalStatus", "legalSectionId", "reviewHash",
            "effectiveFrom", "effectiveTo", "consolidationDate", "repealedAt",
        }
        date_fields = {"checkedAt", "publisherUpdatedAt", "fetchedAt"}
        collection_fields = {
            "topics", "journeyIds", "sourceIds", "aliasUrls", "amendmentIds",
            "sectionLocators",
        }
        integer_fields = {"metadataVersion", "chunkPart", "chunkParts"}
        boolean_fields = {"isHistorical", "containsExceptions"}
        expected = (
            string_fields | date_fields | collection_fields | integer_fields | boolean_fields
        )
        self.assertEqual(set(fields), expected)
        for name in string_fields:
            self.assertEqual(str(fields[name].type), "Edm.String", name)
        for name in date_fields:
            self.assertEqual(str(fields[name].type), "Edm.DateTimeOffset", name)
        for name in collection_fields:
            self.assertEqual(str(fields[name].type), "Collection(Edm.String)", name)
        for name in integer_fields:
            self.assertEqual(str(fields[name].type), "Edm.Int32", name)
        for name in boolean_fields:
            self.assertEqual(str(fields[name].type), "Edm.Boolean", name)

        retrieval_fields = {
            "id", "documentId", "sourceId", "title", "publisher", "url", "content",
            "section", "checkedAt", "publisherUpdatedAt", "status", "documentVersion",
            "journeyIds", "metadataVersion", "sourceIds", "documentType", "language",
            "contentHash", "extractionHash", "reviewHash", "rightsStatus",
            "rightsReviewId", "rightsHash", "legalStatus", "effectiveFrom",
            "effectiveTo", "consolidationDate", "repealedAt", "legalSectionId",
            "isHistorical",
        }
        self.assertTrue(retrieval_fields <= set(fields))
        filter_fields = {
            "documentId", "sourceId", "publisher", "checkedAt", "publisherUpdatedAt",
            "status", "topics", "journeyIds", "documentVersion", "canonicalUrl",
            "sourceUrl", "language", "documentType", "mediaType", "extractionMethod",
            "extractionHash", "responseHash", "rightsStatus", "rightsReviewId",
            "rightsHash", "licenceUrl", "legalStatus", "legalSectionId", "reviewHash",
            "effectiveFrom", "effectiveTo", "consolidationDate", "repealedAt",
            "sourceIds", "aliasUrls", "amendmentIds", "sectionLocators",
            "metadataVersion", "chunkPart", "chunkParts", "isHistorical",
            "containsExceptions", "fetchedAt",
        }
        self.assertEqual({name for name, field in fields.items() if field.filterable}, filter_fields)
        self.assertEqual(
            {name for name, field in fields.items() if field.searchable},
            {"title", "content", "section"} | collection_fields,
        )
        self.assertEqual(
            {name for name, field in fields.items() if field.facetable},
            collection_fields,
        )
        self.assertEqual(
            {name for name, field in fields.items() if field.sortable},
            {"checkedAt", "effectiveFrom", "effectiveTo", "consolidationDate", "repealedAt"},
        )
        self.assertTrue(fields["id"].key)
        self.assertEqual(str(fields["content"].analyzer_name), "en.microsoft")

    def test_semantic_configuration_is_exact_and_vectors_are_absent(self):
        inventory = index_inventory(self.schema)
        self.assertIsNone(inventory["vectorSearch"])
        self.assertNotIn("contentVector", {field["name"] for field in inventory["fields"]})
        self.assertEqual(
            inventory["semantic"],
            {
                "defaultConfiguration": None,
                "configurations": [{
                    "name": SEMANTIC_CONFIGURATION_NAME,
                    "titleField": "title",
                    "contentFields": ["content"],
                    "keywordFields": ["section"],
                    "rankingOrder": "BoostedRerankerScore",
                }],
            },
        )

    def test_schema_diff_is_machine_readable(self):
        existing = deepcopy(self.schema)
        existing.fields = existing.fields[:-1]
        diff = schema_diff(existing, self.schema)
        self.assertFalse(diff["compatible"])
        self.assertEqual(diff["missingFields"], ["fetchedAt"])
        self.assertEqual(diff["unexpectedFields"], [])
        self.assertIsInstance(diff["changedFields"], dict)
        self.assertIn("semantic", diff)
        self.assertIn("vectorSearch", diff)


class ShadowIndexCreationTests(unittest.TestCase):
    def setUp(self):
        self.live = build_index(LIVE_INDEX_NAME)
        self.live.fields = self.live.fields[:15]
        self.live.e_tag = '"live-etag"'
        self.desired = build_index(SHADOW_INDEX_NAME)

    def test_existing_compatible_shadow_is_idempotent(self):
        shadow = deepcopy(self.desired)
        shadow.e_tag = '"shadow-etag"'
        indexes = FakeIndexes(self.live, shadow)
        actual, created, live_before, live_after, diff = ensure_shadow_index(
            indexes, self.desired
        )
        self.assertFalse(created)
        self.assertEqual(indexes.created, [])
        self.assertEqual(actual.e_tag, '"shadow-etag"')
        self.assertTrue(diff["compatible"])
        self.assertEqual(live_before.e_tag, live_after.e_tag)

    def test_incompatible_existing_shadow_is_rejected_without_write(self):
        shadow = deepcopy(self.desired)
        next(field for field in shadow.fields if field.name == "metadataVersion").type = (
            SearchFieldDataType.String
        )
        shadow.e_tag = '"shadow-etag"'
        indexes = FakeIndexes(self.live, shadow)
        with self.assertRaisesRegex(AcquisitionError, "incompatible"):
            ensure_shadow_index(indexes, self.desired)
        self.assertEqual(indexes.created, [])

    def test_create_only_shadow_preserves_live_index(self):
        indexes = FakeIndexes(self.live)
        actual, created, live_before, live_after, diff = ensure_shadow_index(
            indexes, self.desired
        )
        self.assertTrue(created)
        self.assertEqual([index.name for index in indexes.created], [SHADOW_INDEX_NAME])
        self.assertEqual(actual.name, SHADOW_INDEX_NAME)
        self.assertTrue(diff["compatible"])
        self.assertEqual(index_inventory(live_before), index_inventory(live_after))
        self.assertEqual(index_inventory(indexes.live), index_inventory(self.live))

    def test_live_name_can_never_be_used_as_shadow(self):
        indexes = FakeIndexes(self.live)
        with self.assertRaisesRegex(AcquisitionError, "must not equal"):
            ensure_shadow_index(indexes, build_index(LIVE_INDEX_NAME))
        self.assertEqual(indexes.created, [])


class ShadowIndexCliTests(unittest.TestCase):
    def test_cli_defaults_to_v2_and_never_changes_live_environment_index(self):
        report = {
            "operation": "get",
            "valid": False,
            "livePreserved": True,
            "contentPublished": False,
        }
        output = io.StringIO()
        with patch.dict(os.environ, {"AZURE_SEARCH_INDEX": LIVE_INDEX_NAME}, clear=False), \
                patch(
                    "bc_ingestion.azure_publish.shadow_index_operation",
                    return_value=report,
                ) as operation, redirect_stdout(output):
            result = main([
                "shadow-index",
                "--search-endpoint", "https://synthetic.search.windows.net",
                "--shadow-action", "get",
                "--credential", "azure-cli",
            ])
            self.assertEqual(os.environ["AZURE_SEARCH_INDEX"], LIVE_INDEX_NAME)
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), report)
        operation.assert_called_once_with(
            "https://synthetic.search.windows.net",
            operation="get",
            shadow_index_name=SHADOW_INDEX_NAME,
            live_index_name=LIVE_INDEX_NAME,
            execute=False,
            credential_mode="azure-cli",
        )


if __name__ == "__main__":
    unittest.main()
