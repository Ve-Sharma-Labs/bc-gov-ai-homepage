"""Create-only publisher-identity upload for an exact, canonical rights review."""

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path

from .azure_blob import MAX_RIGHTS_BYTES, blob_name, container_name, json_bytes
from .azure_publish import _endpoint
from .metadata import digest
from .policy import AcquisitionError
from .programme_policy import ProgrammePolicy


RIGHTS_CONTAINER = "bc-ingestion-rights"
RIGHTS_PAYLOAD_ENV = "BC_RIGHTS_UPLOAD_BASE64"


def _payload(rights_file: Path | None) -> bytes:
    encoded = os.environ.get(RIGHTS_PAYLOAD_ENV)
    if rights_file is not None and encoded is not None:
        raise AcquisitionError("Supply the rights bytes by file or the fixed upload environment variable, not both")
    if rights_file is not None:
        body = rights_file.read_bytes()
    elif encoded is not None:
        if len(encoded) > ((MAX_RIGHTS_BYTES + 2) // 3) * 4:
            raise AcquisitionError("Rights upload input exceeds the bounded review size")
        try:
            body = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AcquisitionError("Rights upload environment input is not strict base64") from exc
    else:
        raise AcquisitionError(
            f"Supply --rights-file or the fixed {RIGHTS_PAYLOAD_ENV} environment input"
        )
    if not body or len(body) > MAX_RIGHTS_BYTES:
        raise AcquisitionError("Rights upload input exceeds the bounded review size")
    return body


def _validate(
    body: bytes,
    *,
    expected_sha256: str,
    programme: dict,
    catalog: dict,
    rights_container: str,
    rights_blob: str,
    run_prefix: str,
) -> tuple[dict, dict]:
    actual_sha256 = hashlib.sha256(body).hexdigest()
    if actual_sha256 != expected_sha256:
        raise AcquisitionError("The local rights file does not match --rights-sha256")
    try:
        rights = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AcquisitionError("The rights upload input must be UTF-8 JSON") from exc
    if json_bytes(rights) != body:
        raise AcquisitionError("The rights upload input must use canonical JSON bytes")
    if container_name(rights_container) != RIGHTS_CONTAINER:
        raise AcquisitionError(f"Rights uploads are restricted to {RIGHTS_CONTAINER}")
    run_prefix = blob_name(run_prefix)
    if "/" in run_prefix:
        raise AcquisitionError("Rights uploads require one reviewed top-level run prefix")
    rights_blob = blob_name(rights_blob)
    expected_blob = f"reviews/{run_prefix}.json"
    if rights_blob != expected_blob:
        raise AcquisitionError(f"Rights upload target must be {expected_blob}")
    policy = ProgrammePolicy(programme, catalog, rights)
    canonical_digest = digest(rights)
    if canonical_digest != actual_sha256 or policy.rights_hash != actual_sha256:
        raise AcquisitionError("Raw and canonical rights hashes must be identical")
    return rights, {
        "sha256": actual_sha256,
        "canonicalDigest": canonical_digest,
        "programmeHash": policy.programme_hash,
        "reviewId": rights["reviewId"],
        "expiresAt": rights["expiresAt"],
        "container": rights_container,
        "blob": rights_blob,
        "runPrefix": run_prefix,
        "bytes": len(body),
    }


def upload_rights_review(
    account_url: str,
    rights_container: str,
    rights_blob: str,
    run_prefix: str,
    expected_sha256: str,
    programme: dict,
    catalog: dict,
    *,
    rights_file: Path | None = None,
    execute: bool = False,
) -> dict:
    account_url = _endpoint(account_url, "blob")
    body = _payload(rights_file)
    _, evidence = _validate(
        body,
        expected_sha256=expected_sha256,
        programme=programme,
        catalog=catalog,
        rights_container=rights_container,
        rights_blob=rights_blob,
        run_prefix=run_prefix,
    )
    target = f"{account_url.rstrip('/')}/{evidence['container']}/{evidence['blob']}"
    if not execute:
        return {
            "mode": "validated",
            "target": target,
            "createOnly": True,
            "conditionalReadVerified": False,
            **evidence,
        }

    client_id = os.environ.get("AZURE_CLIENT_ID")
    if not client_id:
        raise AcquisitionError("Rights upload requires an explicit AZURE_CLIENT_ID publisher identity")

    from azure.core import MatchConditions
    from azure.core.exceptions import AzureError, ResourceExistsError, ResourceModifiedError
    from azure.identity import ManagedIdentityCredential
    from azure.storage.blob import BlobServiceClient, ContentSettings

    try:
        with ManagedIdentityCredential(client_id=client_id) as credential, BlobServiceClient(
            account_url,
            credential=credential,
            retry_total=0,
            retry_connect=0,
            retry_read=0,
            connection_timeout=5,
            read_timeout=10,
        ) as service:
            blob = service.get_blob_client(
                container=evidence["container"],
                blob=evidence["blob"],
            )
            mode = "uploaded"
            try:
                blob.upload_blob(
                    body,
                    overwrite=False,
                    if_none_match="*",
                    metadata={
                        "sha256": evidence["sha256"],
                        "programmehash": evidence["programmeHash"],
                    },
                    content_settings=ContentSettings(
                        content_type="application/json; charset=utf-8",
                    ),
                )
            except (ResourceExistsError, ResourceModifiedError):
                mode = "verified-existing"
            properties = blob.get_blob_properties()
            if (
                type(properties.size) is not int
                or properties.size != len(body)
                or not properties.etag
            ):
                raise AcquisitionError("Rights Blob size or ETag does not match the reviewed input")
            downloaded = blob.download_blob(
                offset=0,
                length=properties.size,
                etag=properties.etag,
                match_condition=MatchConditions.IfNotModified,
                max_concurrency=1,
            ).readall()
            if downloaded != body or hashlib.sha256(downloaded).hexdigest() != evidence["sha256"]:
                raise AcquisitionError("Conditional rights Blob read did not match the reviewed input")
            return {
                "mode": mode,
                "target": target,
                "createOnly": True,
                "conditionalReadVerified": True,
                "etag": properties.etag,
                "identityClientId": client_id,
                **evidence,
            }
    except AzureError as exc:
        raise AcquisitionError("Rights Blob upload or conditional verification failed") from exc
