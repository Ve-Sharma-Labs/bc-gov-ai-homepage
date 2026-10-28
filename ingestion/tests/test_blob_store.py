"""Fault-injected Blob protocol tests. No credentials, emulator, or Azure requests."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bc_ingestion.azure_blob import (
    BlobManifestStore, RightsBlobInput, blob_runtime, control_summary, inspect_blob_control,
    json_bytes,
)
from bc_ingestion.catalog import load_catalog
from bc_ingestion.cli import main
from bc_ingestion.manifest import CheckpointError
from bc_ingestion.policy import AcquisitionError
from bc_ingestion.programme import ProgrammeRun
from bc_ingestion.programme_policy import ProgrammePolicy
from test_programme import Clock, Network, ROOT, URL, html, response, rights_for

try:
    import azure.identity
    import azure.storage.blob
    from azure.core import MatchConditions
    from azure.core.exceptions import (
        ResourceExistsError, ResourceModifiedError, ResourceNotFoundError, ServiceResponseError,
    )
    HAS_AZURE = True
except ImportError:
    HAS_AZURE = False


def error(kind, code, status):
    result = kind("synthetic storage failure")
    result.error_code, result.status_code = code, status
    return result


@unittest.skipUnless(HAS_AZURE, "Optional Azure SDK is not installed")
class BlobInspectorTests(unittest.TestCase):
    def test_control_inspector_uses_bounded_conditional_download(self):
        body = json_bytes({"storageSchemaVersion": 2, "revision": 0, "core": None})
        identity_context, service_context = Mock(), Mock()
        identity_context.__enter__ = Mock(return_value=identity_context)
        identity_context.__exit__ = Mock(return_value=False)
        service_context.__enter__ = Mock(return_value=service_context)
        service_context.__exit__ = Mock(return_value=False)
        blob = service_context.get_blob_client.return_value
        blob.get_blob_properties.return_value = SimpleNamespace(size=len(body), etag='"control"')
        blob.download_blob.return_value.readall.return_value = body
        with patch(
            "azure.identity.ManagedIdentityCredential", return_value=identity_context
        ) as credential, patch(
            "azure.storage.blob.BlobServiceClient", return_value=service_context
        ), patch.dict("os.environ", {"AZURE_CLIENT_ID": "synthetic-client"}):
            result = inspect_blob_control(
                "https://synthetic.blob.core.windows.net",
                "candidates",
                "programme-v1",
            )
        credential.assert_called_once_with(client_id="synthetic-client")
        service_context.get_blob_client.assert_called_once_with(
            container="candidates",
            blob="programme-v1/manifest.json",
        )
        self.assertEqual(
            blob.download_blob.call_args.kwargs,
            {
                "offset": 0,
                "length": len(body),
                "etag": '"control"',
                "match_condition": MatchConditions.IfNotModified,
                "max_concurrency": 1,
            },
        )
        self.assertEqual(result["storageSchemaVersion"], 2)
        self.assertEqual(result["revision"], 0)
        self.assertEqual(result["etag"], '"control"')


class MemoryAzure:
    def __init__(self, clock):
        self.clock, self.items, self.calls = clock, {}, []
        self.sequence, self.leases = 0, 0
        self.before_upload = None
        self.after_upload = None
        self.before_download = None
        self.fail_renew = False
        self.renew_attempted = threading.Event()

    def get_container_client(self, name):
        return MemoryContainer(self, name)

    def seed(self, container, name, body, metadata=None):
        self.sequence += 1
        self.items[(container, name)] = {
            "data": body, "etag": f'"{self.sequence}"', "metadata": metadata or {},
            "lease": None, "expires": 0,
        }


class MemoryContainer:
    def __init__(self, memory, name):
        self.memory, self.container_name = memory, name
        self.url = "https://synthetic.blob.core.windows.net/" + name

    def get_blob_client(self, name):
        return MemoryBlob(self.memory, self.container_name, name)


class MemoryBlob:
    def __init__(self, memory, container, name):
        self.memory, self.container, self.name = memory, container, name
        self.key = (container, name)

    def _item(self):
        if self.key not in self.memory.items:
            raise error(ResourceNotFoundError, "BlobNotFound", 404)
        return self.memory.items[self.key]

    def _conditional(self, item, kwargs, *, writing=False):
        lease = kwargs.get("lease")
        lease_id = getattr(lease, "id", lease)
        active = item["lease"] and item["expires"] > self.memory.clock()
        if (lease_id and (not active or lease_id != item["lease"])) or (writing and active and lease_id != item["lease"]):
            raise error(ResourceModifiedError, "LeaseIdMismatchWithBlobOperation", 412)
        if kwargs.get("match_condition") == MatchConditions.IfNotModified and item["etag"] != kwargs.get("etag"):
            raise error(ResourceModifiedError, "ConditionNotMet", 412)

    def get_blob_properties(self, **kwargs):
        self.memory.calls.append(("head", self.key, kwargs))
        item = self._item()
        self._conditional(item, kwargs)
        return SimpleNamespace(size=len(item["data"]), etag=item["etag"], metadata=deepcopy(item["metadata"]))

    def download_blob(self, **kwargs):
        self.memory.calls.append(("download", self.key, kwargs))
        if self.memory.before_download:
            self.memory.before_download(self)
        item = self._item()
        self._conditional(item, kwargs)
        return SimpleNamespace(readall=lambda: item["data"])

    def upload_blob(self, data, **kwargs):
        self.memory.calls.append(("upload", self.key, kwargs))
        if self.container == "rights":
            raise AssertionError("The rights-review container is read-only")
        if self.memory.before_upload:
            self.memory.before_upload(self, data, kwargs)
        existing = self.memory.items.get(self.key)
        if existing and (
            kwargs.get("if_none_match") == "*"
            or kwargs.get("match_condition") == MatchConditions.IfMissing
            or not kwargs.get("overwrite")
        ):
            raise error(ResourceExistsError, "BlobAlreadyExists", 409)
        if existing:
            self._conditional(existing, kwargs, writing=True)
            lease, expires = existing["lease"], existing["expires"]
        else:
            if kwargs.get("match_condition") == MatchConditions.IfNotModified:
                raise error(ResourceNotFoundError, "BlobNotFound", 404)
            lease, expires = None, 0
        self.memory.seed(self.container, self.name, data, kwargs.get("metadata"))
        item = self._item()
        item.update(lease=lease, expires=expires)
        if self.memory.after_upload:
            self.memory.after_upload(self, data, kwargs)
        return {"etag": item["etag"]}

    def acquire_lease(self, lease_duration, **kwargs):
        self.memory.calls.append(("acquire", self.key, {**kwargs, "lease_duration": lease_duration}))
        item = self._item()
        self._conditional(item, kwargs)
        if item["lease"] and item["expires"] > self.memory.clock():
            raise error(ResourceExistsError, "LeaseAlreadyPresent", 409)
        self.memory.leases += 1
        item.update(lease=f"lease-{self.memory.leases}", expires=self.memory.clock() + lease_duration)
        return MemoryLease(self, item["lease"], lease_duration)

    def delete_blob(self, **kwargs):
        self.memory.calls.append(("delete", self.key, kwargs))
        if self.container == "rights":
            raise AssertionError("The rights-review container is read-only")
        self._conditional(self._item(), kwargs, writing=True)
        del self.memory.items[self.key]


class MemoryLease:
    def __init__(self, blob, lease_id, duration):
        self.blob, self.id, self.duration = blob, lease_id, duration

    def renew(self):
        memory = self.blob.memory
        memory.renew_attempted.set()
        memory.calls.append(("renew", self.blob.key, {"lease": self.id}))
        if memory.fail_renew or self.blob._item()["lease"] != self.id:
            raise error(ResourceModifiedError, "LeaseLost", 412)
        self.blob._item()["expires"] = memory.clock() + self.duration

    def release(self):
        memory = self.blob.memory
        memory.calls.append(("release", self.blob.key, {"lease": self.id}))
        if self.blob._item()["lease"] != self.id:
            raise error(ResourceModifiedError, "LeaseLost", 412)
        self.blob._item().update(lease=None, expires=0)


@unittest.skipUnless(HAS_AZURE, "Optional Azure SDK is not installed")
class BlobStoreTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.memory = MemoryAzure(self.clock)
        self.container = self.memory.get_container_client("candidates")
        self.catalog = load_catalog(ROOT / "data" / "pilot-catalog.json")
        self.programme = json.loads((ROOT / "data" / "source-programme.json").read_text(encoding="utf-8"))
        self.review = rights_for(self.programme)
        self.review_bytes = json_bytes(self.review)
        self.review_hash = hashlib.sha256(self.review_bytes).hexdigest()
        self.memory.seed("rights", "reviews/grant.json", self.review_bytes)

    def rights(self):
        result = RightsBlobInput(self.memory.get_container_client("rights"), "reviews/grant.json", self.review_hash)
        result.load()
        return result

    def store(self, *, initialize=False, rights=None, **kwargs):
        return BlobManifestStore(
            self.container, "programme-v1", initialize=initialize, rights_input=rights,
            monotonic=self.clock, background_renewal=kwargs.pop("background_renewal", False), **kwargs,
        )

    def run_once(self, network, *, initialize=False, resume=False, acquire=True, batch=25):
        rights = self.rights()
        policy = ProgrammePolicy(self.programme, self.catalog, rights.value, clock=self.clock.datetime)
        with self.store(initialize=initialize, rights=rights) as store:
            runner = ProgrammeRun(
                policy, store, response_store=store.objects, seeds=[URL],
                clock=self.clock, sleep=self.clock.sleep, request=network,
            )
            report = runner.run(acquire=acquire, resume=resume, batch_requests=batch)
        return report, runner.state

    def test_two_ephemeral_executions_resume_without_local_files_or_lost_artifacts(self):
        second = URL + "/second"
        network = Network(self.clock, {
            URL: response(URL, html(links=f"<a href='{second}'>Second guide</a>")),
            second: response(second, html("Second guide")),
        })
        report, state = self.run_once(network, initialize=True, batch=2)
        self.assertEqual(report["status"], "paused")
        self.assertIsNone(state["rightsReview"])
        self.assertEqual(state["rightsReviewReference"]["container"], "rights")
        first_object = next(c["responseObject"] for c in state["candidates"].values() if c.get("responseObject"))
        report, state = self.run_once(network, resume=True, batch=2)
        self.assertEqual(report["status"], "frontier-exhausted")
        self.assertEqual(state["budget"]["requests"], 4)
        self.assertEqual([c[0] for c in network.calls if not c[0].endswith("robots.txt")], [URL, second])
        with self.store(rights=self.rights()) as store:
            loaded = store.load()
            self.assertEqual(loaded["ledger"], state["ledger"])
            self.assertEqual(hashlib.sha256(store.objects.get(first_object)).hexdigest(), first_object)
        self.assertFalse(any(call[0] in ("upload", "delete", "acquire") and call[1][0] == "rights"
                             for call in self.memory.calls))

    def test_control_summary_is_bounded_and_read_only(self):
        body = json_bytes(
            {
                "storageSchemaVersion": 2,
                "revision": 0,
                "core": None,
                "checkpoint": None,
            }
        )
        result = control_summary(body)
        self.assertEqual(result["storageSchemaVersion"], 2)
        self.assertEqual(result["revision"], 0)
        self.assertEqual(result["keys"], ["checkpoint", "core", "revision", "storageSchemaVersion"])
        self.assertEqual(result["sha256"], hashlib.sha256(body).hexdigest())
        with self.assertRaisesRegex(CheckpointError, "json-invalid"):
            control_summary(b"not-json")

    def test_every_pointer_commit_is_leased_and_conditional_after_object_upload(self):
        self.run_once(Network(self.clock), initialize=True)
        calls = self.memory.calls
        pointers = [i for i, call in enumerate(calls) if call[0] == "upload" and call[1][1].endswith("manifest.json")]
        self.assertEqual(calls[pointers[0]][2]["if_none_match"], "*")
        self.assertNotIn("etag", calls[pointers[0]][2])
        self.assertNotIn("match_condition", calls[pointers[0]][2])
        for index in pointers[1:]:
            options = calls[index][2]
            self.assertEqual(options["match_condition"], MatchConditions.IfNotModified)
            self.assertTrue(options["etag"])
            self.assertIsInstance(options["lease"], MemoryLease)
            self.assertTrue(any(call[0] == "upload" and "/objects/" in call[1][1] for call in calls[:index]))
        for call in calls:
            if call[0] == "download":
                self.assertEqual(call[2]["offset"], 0)
            if call[0] == "upload" and "/objects/" in call[1][1]:
                self.assertFalse(call[2]["overwrite"])
                self.assertEqual(call[2]["if_none_match"], "*")
                self.assertNotIn("etag", call[2])
                self.assertNotIn("match_condition", call[2])

    def test_missing_resume_and_reinitialization_never_reset_a_run(self):
        with self.assertRaisesRegex(CheckpointError, "run-missing"):
            with self.store():
                pass
        self.run_once(Network(self.clock), initialize=True, acquire=False)
        before = deepcopy(self.memory.items[("candidates", "programme-v1/manifest.json")])
        with self.assertRaisesRegex(CheckpointError, "run-already-exists"):
            with self.store(initialize=True):
                pass
        self.assertEqual(self.memory.items[("candidates", "programme-v1/manifest.json")]["data"], before["data"])

    def test_pristine_create_marker_resumes_initialization_without_resetting_state(self):
        self.memory.seed(
            "candidates",
            "programme-v1/manifest.json",
            json_bytes({"storageSchemaVersion": 2, "revision": 0, "core": None}),
        )
        result, state = self.run_once(Network(self.clock), initialize=True, acquire=False)
        self.assertEqual(result["status"], "review-only")
        self.assertGreater(state["revision"], 0)
        with self.assertRaisesRegex(CheckpointError, "run-already-exists"):
            with self.store(initialize=True):
                pass

    def test_concurrent_workers_are_rejected_without_breaking_the_first_lease(self):
        with self.store(initialize=True):
            with self.assertRaisesRegex(CheckpointError, "lease-lost-or-unavailable"):
                with self.store():
                    pass
        self.assertFalse(any(call[0] == "break" for call in self.memory.calls))

    def test_conditional_commit_failure_leaves_only_unreferenced_objects(self):
        with self.assertRaises(CheckpointError), self.store(initialize=True) as store:
            state = {"revision": 0, "rightsReview": None}
            store.save(state)
            original = self.memory.items[("candidates", "programme-v1/manifest.json")]["data"]
            value = store.objects.put(b"new synthetic response")
            state["artifacts"] = {"synthetic": value}

            def reject(blob, data, kwargs):
                if blob.name.endswith("manifest.json"):
                    raise error(ResourceModifiedError, "ConditionNotMet", 412)

            self.memory.before_upload = reject
            with self.assertRaisesRegex(CheckpointError, "concurrent-modification"):
                store.save(state)
            self.assertEqual(self.memory.items[("candidates", "programme-v1/manifest.json")]["data"], original)
            self.assertIn(("candidates", "programme-v1/objects/" + value), self.memory.items)
            self.assertEqual(state["revision"], 1)
            self.memory.before_upload = None
            # A failed conditional commit poisons this owner; it cannot write an error checkpoint.
            with self.assertRaises(CheckpointError):
                store.save(state)
        # __exit__ propagates a poisoned lease even if an inner assertion consumed the error.

    def test_unknown_commit_outcome_is_not_retried_and_remote_revision_wins_on_resume(self):
        store = self.store(initialize=True)
        store.__enter__()
        state = {"revision": 0, "rightsReview": None}
        store.save(state)

        def lost_ack(blob, data, kwargs):
            if blob.name.endswith("manifest.json"):
                raise ServiceResponseError("synthetic acknowledgement lost")

        self.memory.after_upload = lost_ack
        before = len([c for c in self.memory.calls if c[0] == "upload" and c[1][1].endswith("manifest.json")])
        with self.assertRaisesRegex(CheckpointError, "commit-outcome-unknown"):
            store.save(state)
        after = len([c for c in self.memory.calls if c[0] == "upload" and c[1][1].endswith("manifest.json")])
        self.assertEqual(after - before, 1)
        store.__exit__(CheckpointError)
        self.memory.after_upload = None
        self.clock.now += 61
        with self.store() as resumed:
            self.assertEqual(resumed.load()["revision"], 2)

    def test_lost_lease_during_reservation_cannot_dispatch_or_become_a_publisher_retry(self):
        def deny_reservation(blob, data, kwargs):
            if blob.name.endswith("manifest.json"):
                pointer = json.loads(data)
                reference = pointer.get("core")
                if reference:
                    checkpoint = json.loads(self.memory.items[("candidates", reference["blob"])]["data"])
                    if checkpoint["state"]["budget"]["requests"] == 1:
                        raise error(ResourceModifiedError, "LeaseLost", 412)

        self.memory.before_upload = deny_reservation
        network = Network(self.clock)
        with self.assertRaisesRegex(CheckpointError, "lease-lost"):
            self.run_once(network, initialize=True)
        self.assertEqual(network.calls, [])
        pointer = json.loads(self.memory.items[("candidates", "programme-v1/manifest.json")]["data"])
        committed = json.loads(self.memory.items[("candidates", pointer["core"]["blob"])]["data"])
        self.assertEqual(committed["state"]["budget"]["requests"], 0)

    def test_cold_response_corruption_fails_on_validated_use_without_a_full_resume_scan(self):
        _, state = self.run_once(Network(self.clock), initialize=True)
        key = next(iter(state["candidates"].values()))["responseObject"]
        self.memory.seed("candidates", "programme-v1/objects/" + key, b"changed", {"sha256": key})
        with self.store(rights=self.rights()) as store:
            store.load()
            self.assertFalse(any(call[0] == "head" and call[1][1].endswith(key)
                                 for call in self.memory.calls))
            with self.assertRaisesRegex(CheckpointError, "concurrent-modification|content-mismatch"):
                store.objects.get(key)

    def test_unuploaded_references_cannot_be_committed(self):
        store = self.store(initialize=True)
        store.__enter__()
        with self.assertRaisesRegex(CheckpointError, "unuploaded-object-reference"):
            store.save({"revision": 0, "rightsReview": None, "artifacts": {"missing": "0" * 64}})
        store.__exit__(CheckpointError)

    def test_lease_loss_and_renewal_deadline_stop_before_dispatch(self):
        store = self.store(initialize=True)
        store.__enter__()
        self.memory.fail_renew = True
        with self.assertRaisesRegex(CheckpointError, "lease-lost"):
            store.renew_once()
        with self.assertRaises(CheckpointError):
            store.save({"revision": 0, "rightsReview": None})
        store.__exit__(CheckpointError)
        self.clock.now += 61
        newer = self.store()
        newer.__enter__()
        self.clock.now += 56
        with self.assertRaisesRegex(CheckpointError, "deadline-missed"):
            newer.assert_owned()
        newer.__exit__(CheckpointError)

    def test_background_lease_renewal_failure_is_observed_and_thread_stops(self):
        store = self.store(initialize=True, background_renewal=True, renew_every=0.01)
        store.__enter__()
        self.memory.fail_renew = True
        self.assertTrue(self.memory.renew_attempted.wait(1))
        store.thread.join(timeout=1)
        with self.assertRaises(CheckpointError):
            store.assert_owned()
        store.__exit__(CheckpointError)
        self.assertFalse(store.thread.is_alive())

    def test_pause_signal_does_not_need_the_running_workers_lease(self):
        with self.store(initialize=True) as running:
            self.store().request_pause()
            self.assertTrue(running.pause_requested())
            running.clear_pause()
            self.assertFalse(running.pause_requested())
        deletes = [c for c in self.memory.calls if c[0] == "delete"]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0][2]["match_condition"], MatchConditions.IfNotModified)
        self.assertTrue(deletes[0][1][1].endswith("pause-request.json"))

    def test_rights_hash_race_and_mid_run_change_fail_closed_without_rights_writes(self):
        with self.assertRaisesRegex(CheckpointError, "rights-input-hash"):
            RightsBlobInput(self.memory.get_container_client("rights"), "reviews/grant.json", "0" * 64).load()
        rights = self.rights()
        store = self.store(initialize=True, rights=rights)
        store.__enter__()
        self.memory.seed("rights", "reviews/grant.json", b'{"revoked":true}')
        with self.assertRaises(CheckpointError):
            store.save({"revision": 0, "rightsReview": None})
        store.__exit__(CheckpointError)
        self.assertFalse(any(c[0] in ("upload", "delete") and c[1][0] == "rights" for c in self.memory.calls))

    def test_rights_download_is_conditional_on_the_observed_etag(self):
        def replace_before_download(blob):
            if blob.container == "rights":
                self.memory.seed("rights", blob.name, self.review_bytes + b" ")

        self.memory.before_download = replace_before_download
        with self.assertRaisesRegex(CheckpointError, "concurrent-modification"):
            self.rights()

    def test_writable_rights_copies_and_same_container_configuration_are_rejected(self):
        with self.assertRaises(AcquisitionError):
            BlobManifestStore(self.container, "x", rights_input=SimpleNamespace(container=self.container))
        store = self.store(initialize=True)
        store.__enter__()
        with self.assertRaisesRegex(CheckpointError, "read-only-container"):
            store.save({"revision": 0, "rightsReview": self.review})
        store.__exit__(CheckpointError)

    def test_small_v1_checkpoint_migrates_without_resetting_counters_or_head_scanning_assets(self):
        raw = b"legacy synthetic response"
        raw_hash = hashlib.sha256(raw).hexdigest()
        name = "programme-v1/objects/" + raw_hash
        self.memory.seed("candidates", name, raw, {"sha256": raw_hash})
        item = self.memory.items[("candidates", name)]
        reference = {"blob": name, "sha256": raw_hash, "etag": item["etag"], "bytes": len(raw)}
        state = {"revision": 7, "rightsReview": None, "budget": {"requests": 19},
                 "artifacts": {"legacy-response": raw_hash}, "events": [{"type": "legacy-audit"}]}
        body = json_bytes({"storageSchemaVersion": 1, "state": state, "objects": {raw_hash: reference}})
        key = hashlib.sha256(body).hexdigest()
        checkpoint = "programme-v1/objects/" + key
        self.memory.seed("candidates", checkpoint, body, {"sha256": key})
        checkpoint_ref = {"blob": checkpoint, "sha256": key,
                          "etag": self.memory.items[("candidates", checkpoint)]["etag"], "bytes": len(body)}
        self.memory.seed("candidates", "programme-v1/manifest.json",
                         json_bytes({"storageSchemaVersion": 1, "revision": 7, "checkpoint": checkpoint_ref}))
        with self.store() as store:
            loaded = store.load()
            self.assertEqual(loaded["budget"]["requests"], 19)
            store.save(loaded)
            self.assertEqual(loaded["revision"], 8)
        control = json.loads(self.memory.items[("candidates", "programme-v1/manifest.json")]["data"])
        self.assertEqual(control["storageSchemaVersion"], 2)
        with self.store() as store:
            loaded = store.load()
            self.assertEqual(loaded["budget"]["requests"], 19)
            self.assertEqual(list(loaded["events"]), [{"type": "legacy-audit"}])
            self.assertEqual(store.objects.get(raw_hash), raw)

    def test_identity_configuration_rejects_keys_sas_and_ambiguous_scope_before_sdk_calls(self):
        for endpoint, candidates, prefix, other in (
            ("https://synthetic.blob.core.windows.net/?sig=not-a-real-sas", "candidates", "x", {}),
            ("https://synthetic.blob.core.windows.net", "rights", "x",
             {"rights_container": "rights", "rights_blob": "review.json", "rights_sha256": "0" * 64}),
            ("https://synthetic.blob.core.windows.net", "candidates", "../rights", {}),
        ):
            with self.subTest(prefix=prefix), patch("azure.identity.ManagedIdentityCredential") as credential:
                with self.assertRaises(AcquisitionError):
                    with blob_runtime(endpoint, candidates, prefix, **other):
                        pass
                credential.assert_not_called()

    def test_runtime_uses_only_explicit_identity_and_disables_ambiguous_write_retries(self):
        identity_context, service_context = Mock(), Mock()
        credential = object()
        identity_context.__enter__ = Mock(return_value=credential)
        identity_context.__exit__ = Mock(return_value=False)
        service_context.__enter__ = Mock(return_value=self.memory)
        service_context.__exit__ = Mock(return_value=False)
        for mode in ("managed-identity", "azure-cli"):
            with self.subTest(mode=mode), \
                    patch("azure.identity.ManagedIdentityCredential", return_value=identity_context) as managed, \
                    patch("azure.identity.AzureCliCredential", return_value=identity_context) as cli, \
                    patch("azure.storage.blob.BlobServiceClient", return_value=service_context) as service, \
                    patch.dict("os.environ", {"AZURE_CLIENT_ID": "synthetic-client",
                                              "AZURE_STORAGE_CONNECTION_STRING": "must-not-be-used",
                                              "AZURE_STORAGE_KEY": "must-not-be-used"}):
                with blob_runtime("https://synthetic.blob.core.windows.net", "candidates", "programme-v1",
                                  credential_mode=mode):
                    pass
                if mode == "managed-identity":
                    managed.assert_called_once_with(client_id="synthetic-client")
                    cli.assert_not_called()
                else:
                    cli.assert_called_once_with(process_timeout=5)
                    managed.assert_not_called()
                kwargs = service.call_args.kwargs
                self.assertIs(kwargs["credential"], credential)
                self.assertEqual(kwargs["retry_total"], 0)
                self.assertEqual(kwargs["retry_connect"], 0)
                self.assertEqual(kwargs["retry_read"], 0)
                self.assertEqual(kwargs["connection_timeout"], 5)
                self.assertEqual(kwargs["read_timeout"], 10)

    def test_cli_remote_artifacts_are_durable_and_resume_never_reads_local_outputs(self):
        @contextmanager
        def runtime(*args, **kwargs):
            rights = self.rights() if kwargs.get("rights_container") else None
            store = self.store(initialize=kwargs["initialize"], rights=rights)
            yield store, rights.value if rights is not None else None

        common = [
            "programme", "--programme-store", "azure-blob", "--blob-account-url",
            "https://synthetic.blob.core.windows.net", "--candidate-container", "candidates",
            "--run-prefix", "programme-v1",
        ]
        with patch("bc_ingestion.azure_blob.blob_runtime", side_effect=runtime), \
                patch("bc_ingestion.cli.LocalResponseStore", side_effect=AssertionError("No ephemeral files")), \
                patch("bc_ingestion.cli.save_json", side_effect=AssertionError("No ephemeral files")), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(common + ["--initialize"]), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["coverage"].startswith(self.container.url))
        with self.store() as store:
            state = store.load()
            self.assertIn("coverage.json", state["artifacts"])
            self.assertIn("inputs/programme.json", state["artifacts"])
            for key in state["artifacts"].values():
                self.assertTrue(store.objects.get(key))

    def test_cli_blob_acquisition_requires_separate_pinned_rights_before_opening_store(self):
        with patch("bc_ingestion.azure_blob.blob_runtime") as runtime, redirect_stderr(io.StringIO()):
            self.assertEqual(main([
                "programme", "--programme-store", "azure-blob", "--candidate-container", "candidates",
                "--run-prefix", "programme-v1", "--acquire", "--resume",
            ]), 2)
        runtime.assert_not_called()


if __name__ == "__main__":
    unittest.main()
