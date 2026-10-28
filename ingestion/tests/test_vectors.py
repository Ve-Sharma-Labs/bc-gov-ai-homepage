import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from bc_ingestion.azure_publish import build_index, verify_results
from bc_ingestion.policy import AcquisitionError
from bc_ingestion.vectors import azure_embedder, enrich_documents, validate_vectors


class VectorTests(unittest.TestCase):
    def test_native_vector_schema_matches_api_field_and_dimensions(self):
        try:
            schema = build_index("bc-test", 3).serialize()
        except ImportError:
            self.skipTest("Optional Azure SDK is not installed")
        fields = {field["name"]: field for field in schema["fields"]}
        self.assertEqual(fields["contentVector"]["dimensions"], 3)
        self.assertEqual(fields["contentVector"]["type"], "Collection(Edm.Single)")
        self.assertEqual(fields["contentVector"]["vectorSearchProfile"], "bc-vector-profile")
        self.assertEqual(schema["vectorSearch"]["profiles"][0]["algorithm"], "bc-hnsw")
        self.assertTrue(fields["status"]["filterable"])

    def test_enrichment_does_not_mutate_reviewed_documents(self):
        documents = [{"id": "fixture", "status": "active", "content": "Synthetic reviewed content."}]
        embed = Mock(return_value=[[0.1, 0.2, 0.3]])
        result = enrich_documents(documents, embed, 3)
        self.assertEqual(result[0]["contentVector"], [0.1, 0.2, 0.3])
        self.assertNotIn("contentVector", documents[0])
        embed.assert_called_once_with(["Synthetic reviewed content."])

    def test_no_vectors_are_fabricated_on_invalid_results(self):
        for value in ([], [[0, 0, 0]], [[1, 2]], [[float("nan"), 1, 2]],
                      [[True, 1, 2]], [[10 ** 1000, 1, 2]]):
            with self.subTest(value=type(value)):
                with self.assertRaises(AcquisitionError):
                    validate_vectors(value, 1, 3)
        embed = Mock()
        with self.assertRaises(AcquisitionError):
            enrich_documents([{"status": "quarantined", "content": "Not approved."}], embed, 3)
        embed.assert_not_called()

    def test_embedding_wire_uses_managed_credential_scope_and_ordered_indices(self):
        class Response:
            status_code = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def iter_content(self, size):
                yield json.dumps({"data": [
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                ]}).encode()

        credential = SimpleNamespace(get_token=Mock(return_value=SimpleNamespace(token="fixture-token")))
        session = SimpleNamespace(post=Mock(return_value=Response()))
        embed = azure_embedder("https://test.openai.azure.com", "test-embedding", 3, credential, session)
        self.assertEqual(embed(["First synthetic section.", "Second synthetic section."]),
                         [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        credential.get_token.assert_called_once_with("https://cognitiveservices.azure.com/.default")
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])
        self.assertEqual(session.post.call_args.kwargs["json"]["dimensions"], 3)

    def test_every_upload_and_withdrawal_requires_complete_acknowledgement(self):
        success = [SimpleNamespace(key="a", succeeded=True)]
        verify_results(success, ["a"], "indexing")
        for result in ([], None, [SimpleNamespace(key="wrong", succeeded=True)],
                       [SimpleNamespace(key="a", succeeded=False)]):
            with self.assertRaises(AcquisitionError):
                verify_results(result, ["a"], "indexing")


if __name__ == "__main__":
    unittest.main()
