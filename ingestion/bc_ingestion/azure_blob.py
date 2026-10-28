"""Optional identity-only Blob checkpoints. No Azure calls occur on import."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
import re
import threading
import time

from .azure_publish import _endpoint
from .checkpoint_state import CheckpointState, JournalIndex, MAPS, LISTS
from .checkpoint_tree import StorageLimits
from .fetch import utc_now
from .manifest import CheckpointError
from .policy import AcquisitionError


MAX_OBJECT_BYTES = 256_000_000
MAX_CONTROL_BYTES = 16_384
MAX_RIGHTS_BYTES = 1_000_000
LEASE_SECONDS = 60
RENEW_SECONDS = 15
SHA256 = re.compile(r"[0-9a-f]{64}")


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


INITIAL_CONTROL = json_bytes({"storageSchemaVersion": 2, "revision": 0, "core": None})


def container_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9]|-(?!-)){1,61}[a-z0-9]", value):
        raise AcquisitionError("A pre-existing, explicitly named private Blob container is required")
    return value


def blob_name(value: str) -> str:
    if (
        not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,1023}", value)
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise AcquisitionError("Blob names/prefixes must be relative object names, without credentials or traversal")
    return value


def _conditions():
    from azure.core import MatchConditions
    return MatchConditions


def _read(blob, properties, limit: int, *, lease=None) -> bytes:
    if type(properties.size) is not int or not 0 <= properties.size <= limit or not properties.etag:
        raise CheckpointError("checkpoint-object-size-or-etag-invalid")
    if properties.size == 0:
        return b""
    options = {"lease": lease} if lease is not None else {}
    # The HEAD/download pair is conditional; a changed object is never mixed into a checkpoint.
    result = blob.download_blob(
        offset=0, length=properties.size or 1, etag=properties.etag,
        match_condition=_conditions().IfNotModified, max_concurrency=1, **options,
    ).readall()
    if not isinstance(result, bytes) or len(result) != properties.size:
        raise CheckpointError("checkpoint-object-length-mismatch")
    return result


def _failure(operation: str, exc: Exception) -> CheckpointError:
    code = str(getattr(exc, "error_code", "") or "")
    if "lease" in code.lower():
        reason = "lease-lost-or-unavailable"
    elif getattr(exc, "status_code", None) in (409, 412):
        reason = "concurrent-modification"
    else:
        reason = "storage-unavailable-or-commit-outcome-unknown"
    return CheckpointError(f"checkpoint-{reason}: {operation}; stop and resume from the remote manifest, never reset it")


class RightsBlobInput:
    """Only read methods exist here; candidate writers never receive a rights output path."""

    def __init__(self, container, name: str, expected_hash: str):
        if not isinstance(expected_hash, str) or not SHA256.fullmatch(expected_hash):
            raise AcquisitionError("--rights-sha256 must pin the exact rights file bytes")
        self.container, self.name, self.expected_hash = container, blob_name(name), expected_hash
        self.blob = container.get_blob_client(self.name)
        self.reference = None
        self.value = None

    def load(self) -> dict:
        from azure.core.exceptions import AzureError
        try:
            properties = self.blob.get_blob_properties()
            body = _read(self.blob, properties, MAX_RIGHTS_BYTES)
            if hashlib.sha256(body).hexdigest() != self.expected_hash:
                raise CheckpointError("checkpoint-rights-input-hash-mismatch; the separate review changed")
            value = json.loads(body.decode("utf-8"))
            if not isinstance(value, dict):
                raise CheckpointError("checkpoint-rights-input-is-not-an-object")
            self.reference = {
                "container": self.container.container_name, "blob": self.name,
                "sha256": self.expected_hash, "etag": properties.etag,
            }
            self.value = value
            return deepcopy(value)
        except AzureError as exc:
            raise _failure("read-only rights input", exc) from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CheckpointError("checkpoint-rights-input-invalid-json") from exc

    def assert_current(self) -> None:
        from azure.core.exceptions import AzureError
        if self.reference is None:
            raise CheckpointError("checkpoint-rights-input-not-read")
        try:
            properties = self.blob.get_blob_properties(
                etag=self.reference["etag"], match_condition=_conditions().IfNotModified,
            )
            if properties.etag != self.reference["etag"]:
                raise CheckpointError("checkpoint-rights-input-changed")
        except AzureError as exc:
            raise _failure("rights input changed or unreadable", exc) from exc


class BlobArtifacts:
    """Create-only, content-addressed objects. References include the acknowledged ETag."""

    def __init__(self, container, prefix: str, *, guard=lambda: None, observe=lambda *_: None,
                 payload_limit=16_777_216):
        self.container, self.prefix, self.guard = container, blob_name(prefix), guard
        self.observe, self.payload_limit, self.resolve = observe, payload_limit, None
        self.references: dict[str, dict] = {}

    def _name(self, key: str) -> str:
        if not isinstance(key, str) or not SHA256.fullmatch(key):
            raise CheckpointError("checkpoint-invalid-object-hash")
        return f"{self.prefix}/objects/{key}"

    def _properties(self, key: str):
        self.observe("head", 0)
        return self.container.get_blob_client(self._name(key)).get_blob_properties()

    def _reference(self, key: str, properties) -> dict:
        if (
            not properties.etag or type(properties.size) is not int
            or not 0 <= properties.size <= MAX_OBJECT_BYTES
            or (properties.metadata or {}).get("sha256") != key
        ):
            raise CheckpointError("checkpoint-immutable-object-metadata-mismatch")
        return {"blob": self._name(key), "sha256": key, "etag": properties.etag, "bytes": properties.size}

    def put(self, body: bytes) -> str:
        from azure.core.exceptions import AzureError, ResourceExistsError, ResourceModifiedError
        from azure.storage.blob import ContentSettings
        self.guard()
        if not isinstance(body, bytes) or len(body) > self.payload_limit:
            raise CheckpointError("checkpoint-object-exceeds-storage-bound")
        key = hashlib.sha256(body).hexdigest()
        try:
            if key in self.references:
                return key
            blob = self.container.get_blob_client(self._name(key))
            try:
                self.observe("put", len(body))
                result = blob.upload_blob(
                    body,
                    overwrite=False,
                    if_none_match="*",
                    metadata={"sha256": key},
                    content_settings=ContentSettings(content_type="application/octet-stream"),
                )
            except (ResourceExistsError, ResourceModifiedError):
                self.observe("head", 0)
                properties = blob.get_blob_properties()
                self.observe("get", properties.size)
                existing = _read(blob, properties, MAX_OBJECT_BYTES)
                if hashlib.sha256(existing).hexdigest() != key or existing != body:
                    raise CheckpointError("checkpoint-immutable-object-content-mismatch")
                self.references[key] = self._reference(key, properties)
            else:
                if not result.get("etag"):
                    raise CheckpointError("checkpoint-object-upload-not-acknowledged")
                self.references[key] = {
                    "blob": self._name(key), "sha256": key, "etag": result["etag"], "bytes": len(body),
                }
            self.guard()
            return key
        except AzureError as exc:
            raise _failure("immutable object upload", exc) from exc

    def put_json(self, value) -> str:
        try:
            encoded = json_bytes(value)
        except (TypeError, ValueError) as exc:
            raise CheckpointError("checkpoint-object-is-not-canonical-json") from exc
        return self.put(encoded)

    def validate_reference(self, reference: dict) -> None:
        if (
            not isinstance(reference, dict)
            or set(reference) != {"blob", "sha256", "etag", "bytes"}
            or reference["blob"] != self._name(reference["sha256"])
            or not isinstance(reference["etag"], str) or not reference["etag"]
            or type(reference["bytes"]) is not int or not 0 <= reference["bytes"] <= MAX_OBJECT_BYTES
        ):
            raise CheckpointError("checkpoint-reference-escapes-candidate-object-scope")

    def verify(self, reference: dict) -> None:
        from azure.core.exceptions import AzureError
        try:
            self.validate_reference(reference)
            properties = self._properties(reference["sha256"])
            if self._reference(reference["sha256"], properties) != reference:
                raise CheckpointError("checkpoint-referenced-object-changed")
        except AzureError as exc:
            raise _failure("referenced object missing or changed", exc) from exc

    def reference(self, key: str) -> dict:
        self.guard()
        if key not in self.references and self.resolve is not None:
            reference = self.resolve(key)
            if reference is not None:
                self.validate_reference(reference)
                self.references[key] = reference
        if key not in self.references:
            raise CheckpointError("checkpoint-unuploaded-object-reference")
        return deepcopy(self.references[key])

    def get(self, key: str) -> bytes:
        return self.get_reference(self.reference(key), limit=self.payload_limit)

    def get_reference(self, reference: dict, *, limit: int) -> bytes:
        from azure.core.exceptions import AzureError
        self.guard()
        self.validate_reference(reference)
        if reference["bytes"] > limit:
            raise CheckpointError("checkpoint-object-read-bound-exceeded")
        try:
            blob = self.container.get_blob_client(reference["blob"])
            self.observe("get", reference["bytes"])
            body = blob.download_blob(
                offset=0, length=reference["bytes"] or None, etag=reference["etag"],
                match_condition=_conditions().IfNotModified, max_concurrency=1,
            ).readall()
            if not isinstance(body, bytes) or len(body) != reference["bytes"] or hashlib.sha256(body).hexdigest() != reference["sha256"]:
                raise CheckpointError("checkpoint-referenced-object-content-mismatch")
            return body
        except AzureError as exc:
            raise _failure("immutable object read", exc) from exc

    def uri(self, key: str) -> str:
        return self.container.url.rstrip("/") + "/" + self._name(key)


class BlobManifestStore:
    """Leased pointer to bounded hot control, a journal and sharded immutable state."""

    requires_response_store = True

    def __init__(self, container, prefix: str, *, initialize=False,
                 rights_input: RightsBlobInput | None = None, renew_every=RENEW_SECONDS,
                 monotonic=time.monotonic, background_renewal=True, storage_limits=None):
        self.container, self.prefix = container, blob_name(prefix)
        self.initialize, self.rights_input = initialize, rights_input
        if rights_input is not None and rights_input.container.container_name == container.container_name:
            raise AcquisitionError("Rights input and writable candidates must use separate containers")
        if not 0 < renew_every < LEASE_SECONDS / 2:
            raise AcquisitionError("Lease renewal must precede expiry with a safe margin")
        self.renew_every, self.monotonic, self.background_renewal = renew_every, monotonic, background_renewal
        self.blob = container.get_blob_client(f"{self.prefix}/manifest.json")
        self.pause_blob = container.get_blob_client(f"{self.prefix}/pause-request.json")
        self.limits = storage_limits or StorageLimits()
        self.metrics = {"calls": 0, "puts": 0, "gets": 0, "heads": 0, "uploadedBytes": 0, "downloadedBytes": 0,
                        "compactedSegments": 0, "compactedNodes": 0, "compactedBytes": 0, "replayedSegments": 0}
        self.started = self.monotonic()
        self.objects = BlobArtifacts(container, self.prefix, guard=self.assert_owned, observe=self._io,
                                     payload_limit=self.limits.payload_bytes)
        self.index = JournalIndex(self.objects, self.limits)
        self.objects.resolve = lambda key: self.index.get("o/" + key)
        self.model = None
        self.loaded = False
        self.legacy = False
        self.lease = None
        self.etag = None
        self.revision = 0
        self.last_renewed = None
        self.thread = None
        self.stop = threading.Event()
        self.failure: CheckpointError | None = None

    @property
    def rights_reference(self):
        return deepcopy(self.rights_input.reference) if self.rights_input is not None else None

    def _poison(self, error: CheckpointError):
        self.failure = error
        return error

    def _io(self, kind, size):
        next_calls = self.metrics["calls"] + 1
        write = self.metrics["uploadedBytes"] + (size if kind == "put" else 0)
        read = self.metrics["downloadedBytes"] + (size if kind == "get" else 0)
        if (
            type(size) is not int or size < 0 or next_calls > self.limits.execution_calls
            or write > self.limits.execution_write_bytes or read > self.limits.execution_read_bytes
            or self.monotonic() - self.started > self.limits.execution_seconds
        ):
            raise self._poison(CheckpointError("checkpoint-execution-io-bound-exceeded; resume the committed cursor in another execution"))
        self.metrics["calls"], self.metrics["uploadedBytes"], self.metrics["downloadedBytes"] = next_calls, write, read
        if kind in ("put", "get", "head"):
            self.metrics[{"put": "puts", "get": "gets", "head": "heads"}[kind]] += 1

    def assert_owned(self) -> None:
        if self.failure is not None:
            raise self.failure
        if self.lease is None or self.last_renewed is None:
            raise CheckpointError("checkpoint-exclusive-lease-required")
        if self.monotonic() - self.last_renewed >= LEASE_SECONDS - 5:
            raise self._poison(CheckpointError("checkpoint-lease-renewal-deadline-missed"))
    def assert_boundary(self) -> None:
        self.assert_owned()
        if self.rights_input is not None:
            try:
                self._io("head", 0)
                self.rights_input.assert_current()
            except CheckpointError as exc:
                raise self._poison(exc)

    def renew_once(self) -> None:
        from azure.core.exceptions import AzureError
        if self.failure is not None:
            raise self.failure
        if self.lease is None:
            raise CheckpointError("checkpoint-exclusive-lease-required")
        try:
            started = self.monotonic()
            self._io("lease", 0)
            self.lease.renew()
            self.last_renewed = started
        except AzureError as exc:
            raise self._poison(_failure("lease renewal", exc)) from exc

    def _heartbeat(self):
        while not self.stop.wait(self.renew_every):
            try:
                self.renew_once()
            except Exception as exc:
                self._poison(exc if isinstance(exc, CheckpointError) else CheckpointError("checkpoint-lease-renewal-failed"))
                return

    def __enter__(self):
        from azure.core.exceptions import AzureError, ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
        try:
            if self.initialize:
                try:
                    self.blob.upload_blob(
                        INITIAL_CONTROL,
                        overwrite=False,
                        if_none_match="*",
                    )
                except (ResourceExistsError, ResourceModifiedError) as exc:
                    try:
                        existing = self.blob.get_blob_properties()
                        if _read(self.blob, existing, MAX_CONTROL_BYTES) != INITIAL_CONTROL:
                            raise CheckpointError(
                                "checkpoint-run-already-exists; initialize never resets budgets"
                            ) from exc
                    except CheckpointError:
                        raise
                    except AzureError as read_exc:
                        raise CheckpointError(
                            "checkpoint-run-already-exists; initialize never resets budgets"
                        ) from read_exc
            try:
                properties = self.blob.get_blob_properties()
            except ResourceNotFoundError as exc:
                raise CheckpointError("checkpoint-run-missing; explicit --initialize is required, never reset an ephemeral resume") from exc
            self.etag = properties.etag
            started = self.monotonic()
            self.lease = self.blob.acquire_lease(
                lease_duration=LEASE_SECONDS, etag=self.etag, match_condition=_conditions().IfNotModified,
            )
            self.last_renewed = started
            if self.background_renewal:
                self.thread = threading.Thread(target=self._heartbeat, name="bc-ingestion-blob-lease", daemon=True)
                self.thread.start()
            return self
        except AzureError as exc:
            raise self._poison(_failure("exclusive manifest ownership", exc)) from exc

    def __exit__(self, exc_type, *_):
        from azure.core.exceptions import AzureError
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=20)
            if self.thread.is_alive():
                self._poison(CheckpointError("checkpoint-lease-renewer-did-not-stop"))
        if self.lease is not None and self.failure is None:
            try:
                self.lease.release()
            except AzureError as exc:
                self._poison(_failure("lease release", exc))
        self.lease = None
        if exc_type is None and self.failure is not None:
            raise self.failure

    @staticmethod
    def _referenced_keys(state: dict) -> set[str]:
        keys = set(state.get("artifacts", {}).values())
        keys.update(c["responseObject"] for c in state.get("candidates", {}).values() if c.get("responseObject"))
        keys.update(
            version["document"]["response_hash"]
            for entry in state.get("ledger", {}).get("documents", {}).values()
            for version in entry["versions"]
        )
        if any(not isinstance(key, str) or not SHA256.fullmatch(key) for key in keys):
            raise CheckpointError("checkpoint-invalid-artifact-reference")
        return keys

    def load(self) -> dict | None:
        from azure.core.exceptions import AzureError
        if self.loaded:
            self.assert_owned()
            return self.model.state if self.model is not None else None
        self.assert_boundary()
        try:
            self._io("head", 0)
            properties = self.blob.get_blob_properties(
                lease=self.lease, etag=self.etag, match_condition=_conditions().IfNotModified,
            )
            self._io("get", properties.size)
            control = json.loads(_read(self.blob, properties, MAX_CONTROL_BYTES, lease=self.lease))
            if (
                control.get("storageSchemaVersion") not in (1, 2) or type(control.get("revision")) is not int
                or control["revision"] < 0
            ):
                raise CheckpointError("checkpoint-control-schema-invalid")
            self.revision = control["revision"]
            if self.revision == 0 and not control.get("core") and not control.get("checkpoint"):
                self.loaded = True
                return None
            if control["storageSchemaVersion"] == 1:
                self._load_legacy(control)
            else:
                if control.get("storageLimits") != self.limits.format_limits():
                    raise CheckpointError("checkpoint-storage-format-limits-changed")
                self.index.restore(control)
                self.metrics["replayedSegments"] += control["journalCount"]
                core = json.loads(self.objects.get_reference(control["core"], limit=self.limits.core_bytes))
                if (
                    core.get("storageSchemaVersion") != 2 or core["state"].get("revision") != self.revision
                    or set(core["collections"]) - set(MAPS + LISTS)
                    or any(v.get("kind") != ("map" if path in MAPS else "list")
                           or type(v.get("length")) is not int or not 0 <= v["length"] <= 1_000_000
                           for path, v in core["collections"].items())
                ):
                    raise CheckpointError("checkpoint-state-or-collection-shape-invalid")
                stats = core["stats"]
                candidates = core["collections"].get("candidates", {}).get("length", 0)
                documents = core["collections"].get("ledger/documents", {}).get("length", 0)
                if (
                    any(type(stats.get(key)) is not int or stats[key] < 0 for key in (
                        "canonicalCandidates", "sitemaps", "unexpandedLinks", "publishedDocuments",
                        "exactReviewedCurrentDocuments",
                    ))
                    or stats["canonicalCandidates"] + stats["sitemaps"] != candidates
                    or any(type(v) is not int or v < 0 for v in stats["states"].values())
                    or sum(stats["states"].values()) != candidates
                    or stats["publishedDocuments"] > documents or stats["exactReviewedCurrentDocuments"] > documents
                ):
                    raise CheckpointError("checkpoint-materialized-counts-invalid")
                self.model = CheckpointState(self.index, core["state"], descriptions=core["collections"], stats=core["stats"])
            state = self.model.state
            if state.get("rightsReview") is not None:
                raise CheckpointError("checkpoint-rights-input-must-remain-in-its-read-only-container")
            if state.get("rightsReviewReference") and state["rightsReviewReference"] != self.rights_reference:
                raise CheckpointError("checkpoint-rights-reference-changed-or-not-supplied")
            self.assert_boundary()
            self.loaded = True
            return state
        except CheckpointError as exc:
            raise self._poison(exc)
        except AzureError as exc:
            raise self._poison(_failure("manifest read", exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise self._poison(CheckpointError("checkpoint-corrupt-or-unsupported-state")) from exc

    def _load_legacy(self, control):
        reference = control.get("checkpoint")
        if reference is None:
            raise CheckpointError("checkpoint-missing-committed-state")
        envelope = json.loads(self.objects.get_reference(reference, limit=self.limits.legacy_bytes))
        state, objects = envelope["state"], envelope["objects"]
        if (
            envelope.get("storageSchemaVersion") != 1 or state.get("revision") != self.revision
            or set(objects) != self._referenced_keys(state)
        ):
            raise CheckpointError("checkpoint-legacy-state-or-reference-closure-invalid")
        records = len(state.get("candidates", {})) + len(state.get("ledger", {}).get("documents", {}))
        if records > 24:
            raise CheckpointError("checkpoint-legacy-migration-bound-exceeded; use a separately reviewed offline migration, never reset the run")
        for key, item in objects.items():
            self.objects.validate_reference(item)
            if item["sha256"] != key:
                raise CheckpointError("checkpoint-object-identity-mismatch")
            self.objects.references[key] = item
        self.model, self.legacy = CheckpointState(self.index, state), True

    def save(self, state: dict) -> None:
        from azure.core.exceptions import AzureError
        self.assert_boundary()
        try:
            if type(state.get("revision")) is not int or state["revision"] != self.revision:
                raise CheckpointError("checkpoint-stale-revision")
            if state.get("rightsReview") is not None:
                raise CheckpointError("checkpoint-rights-input-must-remain-in-its-read-only-container")
            if state.get("rightsReviewReference") and state["rightsReviewReference"] != self.rights_reference:
                raise CheckpointError("checkpoint-rights-reference-mismatch")
            if self.model is None:
                self.model = CheckpointState(self.index, state)
            elif state is not self.model.state:
                raise CheckpointError("checkpoint-state-handle-replaced; mutate the loaded tracked state")
            body = self.model.prepare(self.revision + 1)
            core = self.objects.reference(self.objects.put(body))
            indexed, journals = self.index.prepare()
            control = {
                "storageSchemaVersion": 2, "revision": self.revision + 1, "core": core,
                "storageLimits": self.limits.format_limits(), **indexed,
            }
            body = json_bytes(control)
            if len(body) > MAX_CONTROL_BYTES:
                raise CheckpointError("checkpoint-control-byte-bound-exceeded")
            self.assert_boundary()
            self._io("put", len(body))
            result = self.blob.upload_blob(
                body, overwrite=True, lease=self.lease, etag=self.etag,
                match_condition=_conditions().IfNotModified,
            )
            if not result.get("etag"):
                raise CheckpointError("checkpoint-commit-not-acknowledged")
            self.metrics["compactedSegments"] += indexed["base"]["through"] - self.index.through
            self.metrics["compactedNodes"] += self.index.tree.written_nodes
            self.metrics["compactedBytes"] += self.index.tree.written_bytes
            self.etag, self.revision = result["etag"], control["revision"]
            state["revision"] = self.revision
            self.index.acknowledge(indexed, journals)
            self.model.acknowledge()
            self.loaded = True
        except CheckpointError as exc:
            raise self._poison(exc)
        except AzureError as exc:
            raise self._poison(_failure("conditional manifest commit", exc)) from exc
        except (TypeError, ValueError, KeyError) as exc:
            raise self._poison(CheckpointError("checkpoint-state-cannot-be-serialized")) from exc

    def next_work(self, kind, now=None):
        return self.model.next_work(kind, now)

    def inflight(self):
        return self.model.inflight()

    def has_retries(self):
        return self.model.has_retries()

    def review_page(self, limit=None, after=""):
        return self.model.review_page(limit, after)

    def coverage_counts(self):
        return deepcopy(self.model.stats)

    def request_pause(self) -> None:
        from azure.core.exceptions import AzureError, ResourceExistsError, ResourceModifiedError
        try:
            self.blob.get_blob_properties()  # A pause never initializes a missing run.
            try:
                self.pause_blob.upload_blob(
                    json_bytes({"reason": "operator-pause", "requestedAt": utc_now()}),
                    overwrite=False,
                    if_none_match="*",
                )
            except (ResourceExistsError, ResourceModifiedError):
                pass
        except AzureError as exc:
            raise _failure("pause request", exc) from exc

    def pause_requested(self) -> bool:
        from azure.core.exceptions import AzureError, ResourceNotFoundError
        self.assert_owned()
        try:
            self._io("head", 0)
            self.pause_blob.get_blob_properties()
            return True
        except ResourceNotFoundError:
            return False
        except AzureError as exc:
            raise self._poison(_failure("pause check", exc)) from exc

    def clear_pause(self) -> None:
        from azure.core.exceptions import AzureError, ResourceNotFoundError
        self.assert_owned()
        try:
            self._io("head", 0)
            properties = self.pause_blob.get_blob_properties()
            self._io("delete", 0)
            self.pause_blob.delete_blob(etag=properties.etag, match_condition=_conditions().IfNotModified)
        except ResourceNotFoundError:
            return
        except AzureError as exc:
            raise self._poison(_failure("conditional pause acknowledgement", exc)) from exc


@contextmanager
def blob_runtime(account_url: str, candidate_container: str, prefix: str, *,
                 credential_mode="managed-identity", initialize=False,
                 rights_container=None, rights_blob=None, rights_sha256=None):
    """Connect only on an explicit Blob CLI invocation, never via keys/SAS/fallback auth."""
    account_url = _endpoint(account_url, "blob")
    candidate_container, prefix = container_name(candidate_container), blob_name(prefix)
    rights_values = (rights_container, rights_blob, rights_sha256)
    if any(rights_values):
        if not all(rights_values) or container_name(rights_container) == candidate_container:
            raise AcquisitionError("Supply separate read-only --rights-container/--rights-blob/--rights-sha256")
        blob_name(rights_blob)
        if not SHA256.fullmatch(rights_sha256):
            raise AcquisitionError("--rights-sha256 must pin the exact rights file bytes")
    if credential_mode not in ("managed-identity", "azure-cli"):
        raise AcquisitionError("Choose managed-identity or explicitly authorized azure-cli authentication")
    from azure.identity import AzureCliCredential, ManagedIdentityCredential
    from azure.storage.blob import BlobServiceClient
    identity = os.environ.get("AZURE_CLIENT_ID")
    selected = (ManagedIdentityCredential(**({"client_id": identity} if identity else {}))
                if credential_mode == "managed-identity" else AzureCliCredential(process_timeout=5))
    with selected as credential, BlobServiceClient(
        account_url, credential=credential, retry_total=0, retry_connect=0, retry_read=0,
        connection_timeout=5, read_timeout=10,
    ) as service:
        candidates = service.get_container_client(candidate_container)
        rights = RightsBlobInput(service.get_container_client(rights_container), rights_blob, rights_sha256) if all(rights_values) else None
        review = rights.load() if rights is not None else None
        store = BlobManifestStore(candidates, prefix, initialize=initialize, rights_input=rights)
        yield store, review


def control_summary(body: bytes) -> dict:
    if not isinstance(body, bytes) or len(body) > MAX_CONTROL_BYTES:
        raise CheckpointError("checkpoint-control-byte-bound-exceeded")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointError("checkpoint-control-json-invalid") from exc
    if not isinstance(value, dict):
        raise CheckpointError("checkpoint-control-shape-invalid")
    return {
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "storageSchemaVersion": value.get("storageSchemaVersion"),
        "revision": value.get("revision"),
        "keys": sorted(value),
        "core": value.get("core"),
        "checkpoint": value.get("checkpoint"),
        "storageLimits": value.get("storageLimits"),
        "base": value.get("base"),
        "journals": value.get("journals"),
        "journalCount": value.get("journalCount"),
    }


def inspect_blob_control(
    account_url: str,
    candidate_container: str,
    prefix: str,
    *,
    credential_mode: str = "managed-identity",
) -> dict:
    """Read only the small manifest control record; never acquire a lease or mutate state."""
    account_url = _endpoint(account_url, "blob")
    candidate_container, prefix = container_name(candidate_container), blob_name(prefix)
    if credential_mode not in ("managed-identity", "azure-cli"):
        raise AcquisitionError("Choose managed-identity or explicitly authorized azure-cli authentication")
    from azure.identity import AzureCliCredential, ManagedIdentityCredential
    from azure.storage.blob import BlobServiceClient

    identity = os.environ.get("AZURE_CLIENT_ID")
    selected = (
        ManagedIdentityCredential(**({"client_id": identity} if identity else {}))
        if credential_mode == "managed-identity"
        else AzureCliCredential(process_timeout=5)
    )
    with selected as credential, BlobServiceClient(
        account_url,
        credential=credential,
        retry_total=0,
        retry_connect=0,
        retry_read=0,
        connection_timeout=5,
        read_timeout=10,
    ) as service:
        blob = service.get_blob_client(
            container=candidate_container,
            blob=prefix.rstrip("/") + "/manifest.json",
        )
        properties = blob.get_blob_properties()
        body = blob.download_blob(
            offset=0,
            length=properties.size or None,
            etag=properties.etag,
            match_condition=_conditions().IfNotModified,
            max_concurrency=1,
        ).readall()
        return {
            **control_summary(body),
            "etag": properties.etag,
            "container": candidate_container,
            "prefix": prefix,
        }
