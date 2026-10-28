"""Publisher-only rights upload validation; no live Azure requests."""

import base64
from contextlib import redirect_stdout
import hashlib
import io
import json
import shutil
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch

from bc_ingestion.azure_blob import json_bytes
from bc_ingestion.catalog import load_catalog
from bc_ingestion.cli import main
from bc_ingestion.policy import AcquisitionError
from bc_ingestion.rights_upload import upload_rights_review
from test_programme import ROOT, rights_for

try:
    import azure.identity
    import azure.storage.blob
    from azure.core import MatchConditions
    HAS_AZURE = True
except ImportError:
    HAS_AZURE = False


class RightsUploadValidationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(ROOT / "data" / "pilot-catalog.json")
        self.programme = json.loads((ROOT / "data" / "source-programme.json").read_text(encoding="utf-8"))
        self.rights = rights_for(self.programme)
        self.body = json_bytes(self.rights)
        self.sha256 = hashlib.sha256(self.body).hexdigest()
        self.root = ROOT / "ingestion" / ".generated" / ("rights-upload-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.path = self.root / "review.json"
        self.path.write_bytes(self.body)

    def test_cli_validates_exact_canonical_file_and_target_without_authenticating(self):
        with redirect_stdout(io.StringIO()) as output:
            result = main([
                "rights-upload",
                "--catalog", str(ROOT / "data" / "pilot-catalog.json"),
                "--programme", str(ROOT / "data" / "source-programme.json"),
                "--blob-account-url", "https://synthetic.blob.core.windows.net",
                "--rights-container", "bc-ingestion-rights",
                "--rights-blob", "reviews/programme-v1.json",
                "--run-prefix", "programme-v1",
                "--rights-sha256", self.sha256,
                "--rights-file", str(self.path),
                "--credential", "managed-identity",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "validated")

    def test_rejects_noncanonical_bytes_and_wrong_target(self):
        pretty = self.root / "pretty.json"
        pretty.write_text(json.dumps(self.rights, indent=2), encoding="utf-8")
        pretty_hash = hashlib.sha256(pretty.read_bytes()).hexdigest()
        for change in (
            {"rights_file": pretty, "expected_sha256": pretty_hash},
            {"rights_container": "bc-ingestion-candidates"},
            {"rights_blob": "reviews/another-run.json"},
        ):
            arguments = {
                "account_url": "https://synthetic.blob.core.windows.net",
                "rights_container": "bc-ingestion-rights",
                "rights_blob": "reviews/programme-v1.json",
                "run_prefix": "programme-v1",
                "expected_sha256": self.sha256,
                "programme": self.programme,
                "catalog": self.catalog,
                "rights_file": self.path,
            }
            arguments.update(change)
            with self.subTest(change=change), self.assertRaises(AcquisitionError):
                upload_rights_review(**arguments)


@unittest.skipUnless(HAS_AZURE, "Optional Azure SDK is not installed")
class RightsUploadProtocolTests(unittest.TestCase):
    def test_upload_is_create_only_and_verified_by_conditional_read(self):
        catalog = load_catalog(ROOT / "data" / "pilot-catalog.json")
        programme = json.loads((ROOT / "data" / "source-programme.json").read_text(encoding="utf-8"))
        body = json_bytes(rights_for(programme))
        sha256 = hashlib.sha256(body).hexdigest()
        identity_context, service_context = Mock(), Mock()
        identity_context.__enter__ = Mock(return_value=identity_context)
        identity_context.__exit__ = Mock(return_value=False)
        service_context.__enter__ = Mock(return_value=service_context)
        service_context.__exit__ = Mock(return_value=False)
        blob = service_context.get_blob_client.return_value
        blob.get_blob_properties.return_value = SimpleNamespace(size=len(body), etag='"rights"')
        blob.download_blob.return_value.readall.return_value = body
        with patch("azure.identity.ManagedIdentityCredential", return_value=identity_context) as identity, \
                patch("azure.storage.blob.BlobServiceClient", return_value=service_context) as service, \
                patch.dict("os.environ", {
                    "AZURE_CLIENT_ID": "publisher-client",
                    "BC_RIGHTS_UPLOAD_BASE64": base64.b64encode(body).decode("ascii"),
                }, clear=True):
            result = upload_rights_review(
                "https://synthetic.blob.core.windows.net",
                "bc-ingestion-rights",
                "reviews/programme-v1.json",
                "programme-v1",
                sha256,
                programme,
                catalog,
                execute=True,
            )
        identity.assert_called_once_with(client_id="publisher-client")
        self.assertEqual(service.call_args.kwargs["retry_total"], 0)
        service_context.get_blob_client.assert_called_once_with(
            container="bc-ingestion-rights",
            blob="reviews/programme-v1.json",
        )
        self.assertFalse(blob.upload_blob.call_args.kwargs["overwrite"])
        self.assertEqual(blob.upload_blob.call_args.kwargs["if_none_match"], "*")
        self.assertEqual(
            blob.download_blob.call_args.kwargs,
            {
                "offset": 0,
                "length": len(body),
                "etag": '"rights"',
                "match_condition": MatchConditions.IfNotModified,
                "max_concurrency": 1,
            },
        )
        self.assertTrue(result["conditionalReadVerified"])
        self.assertEqual(result["sha256"], sha256)


if __name__ == "__main__":
    unittest.main()
