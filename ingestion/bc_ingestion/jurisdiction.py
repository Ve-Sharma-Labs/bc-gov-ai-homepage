"""Pack selection without widening publisher permissions or legacy BC paths."""

from dataclasses import dataclass
from copy import deepcopy
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from .metadata import digest
from .paths import PROJECT_ROOT
from .policy import AcquisitionError, canonicalize, ProgrammeGate


@dataclass(frozen=True)
class IngestionPack:
    id: str
    manifest_hash: str
    catalog_path: Path
    programme_path: Path
    output_path: Path
    research_hosts: tuple[str, ...]
    approval_status: str = "pending-rag-permission"
    operation_review_path: Path | None = None
    pending_identity: dict | None = None

    @property
    def identity(self):
        return {"jurisdictionId": self.id, "manifestHash": self.manifest_hash}

    def output(self, requested: Path) -> Path:
        path = requested.resolve()
        if self.id != "bc" and not path.is_relative_to(self.output_path.resolve()):
            raise AcquisitionError("Selected pack state must stay in its isolated .generated jurisdiction directory")
        return path

    def rights_path(self, requested: Path) -> Path:
        path = requested.resolve()
        pack_root = self.programme_path.parent.parent
        if not any(path.is_relative_to(root.resolve()) for root in (
            self.output_path, pack_root / "content", pack_root / "ingestion",
        )):
            raise AcquisitionError("Rights evidence must remain inside the selected pack or isolated generated namespace")
        return path

    def assert_operation(self, operation: str):
        if self.id != "bc":
            # This convenience gate has no supplied operation provider and
            # never grants permission from pack configuration alone.
            raise ProgrammeGate(
                "pending-rag-permission",
                f"{self.id} {operation} blocked: verify publisher terms, robots and explicit "
                "operation-specific permission; supply a pinned v3 provider. "
                "exact-snapshot approval is separately required",
            )


def load_pack(jurisdiction_id: str | None = None, *, root: Path = PROJECT_ROOT) -> IngestionPack:
    selected = jurisdiction_id if jurisdiction_id is not None else os.environ.get("JURISDICTION", "bc")
    if not isinstance(selected, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,15}", selected):
        raise AcquisitionError("Invalid JURISDICTION pack id")
    path = root / "jurisdictions" / selected / "jurisdiction.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcquisitionError("Selected jurisdiction manifest is missing or invalid") from exc
    if manifest.get("schemaVersion") != 1 or manifest.get("id") != selected:
        raise AcquisitionError("Jurisdiction manifest identity/version mismatch")
    hosts = manifest.get("researchHosts")
    if not isinstance(hosts, list) or not hosts or any(
        not isinstance(host, str) or not re.fullmatch(r"[a-z0-9.-]+", host) for host in hosts
    ):
        raise AcquisitionError("Pack research hosts must be explicit hostnames")
    source_policy = manifest.get("sourcePolicy", {})
    if not isinstance(source_policy, dict):
        raise AcquisitionError("Invalid pack source-policy contract")
    status = source_policy.get("approvalStatus", "existing-reviewed-snapshots-only" if selected == "bc" else "pending-rag-permission")
    if status not in ({"existing-reviewed-snapshots-only"} if selected == "bc" else {
        "pending-rag-permission", "reviewed-operation-grants",
    }):
        raise AcquisitionError("Unsupported pack source-policy approval status")
    review_path, pending_identity = None, None
    if status == "reviewed-operation-grants":
        reference = source_policy.get("operationReview")
        if not isinstance(reference, dict) or set(reference) != {"path"} or not isinstance(reference["path"], str) or "\\" in reference["path"]:
            raise AcquisitionError("Reviewed packs require only operationReview.path and an independent byte pin")
        relative = Path(reference["path"])
        review_path = (root / relative).resolve()
        base = root / "jurisdictions" / selected
        if relative.is_absolute() or ".." in relative.parts or not any(review_path.is_relative_to(directory.resolve()) for directory in (base / "content", base / "ingestion")):
            raise AcquisitionError("Operation review must remain inside the selected pack content/ingestion directory")
        previous = deepcopy(manifest)
        previous["sourcePolicy"]["approvalStatus"] = "pending-rag-permission"
        previous["sourcePolicy"].pop("operationReview")
        pending_identity = {"jurisdictionId": selected, "manifestHash": digest(previous)}
    elif "operationReview" in source_policy:
        raise AcquisitionError("Only reviewed-operation-grants packs may configure an operationReview")

    def content_path(key):
        value = manifest.get("content", {}).get(key)
        if not isinstance(value, str) or "\\" in value:
            raise AcquisitionError("Pack content paths must be repository-relative portable paths")
        relative = Path(value)
        resolved = (root / relative).resolve()
        allowed = root if selected == "bc" else root / "jurisdictions" / selected / "content"
        if relative.is_absolute() or ".." in relative.parts or not resolved.is_relative_to(allowed.resolve()):
            raise AcquisitionError("Pack content path escapes the selected jurisdiction")
        return resolved

    return IngestionPack(
        selected, digest(manifest), content_path("catalog"), content_path("sourceProgramme"),
        root / "ingestion" / ".generated" / selected if selected != "bc"
        else root / "ingestion" / ".generated",
        tuple(hosts), status, review_path, pending_identity,
    )


def assert_model_operation(operation: str, documents=(), *, pack: IngestionPack | None = None,
                           programme_policy=None):
    """Check before calling an embedding provider, review planner or publisher."""
    selected = pack or (programme_policy.pack if getattr(programme_policy, "jurisdiction_id", "bc") != "bc" else load_pack())
    if selected.id != "bc" and programme_policy is not None:
        if selected.approval_status != "reviewed-operation-grants":
            selected.assert_operation(operation)
        programme_policy.assert_current_rights()
        for document in documents:
            programme_policy.authorize_document(operation, document)
        return
    selected.assert_operation(operation)
    for document in documents:
        if document.get("jurisdictionId", "bc") != "bc":
            raise ProgrammeGate("pending-rag-permission", "Non-BC model inputs require a reviewed rights provider")
        for key in ("url", "canonicalUrl", "sourceUrl"):
            value = document.get(key)
            if value:
                from .source_adapters import SERVICE_BC_DATASET_URL
                normalized = canonicalize(value)
                if urlsplit(normalized).hostname not in _bc_hosts() and normalized != SERVICE_BC_DATASET_URL:
                    raise AcquisitionError("Model input publisher does not belong to the selected BC ingestion pack")


def _bc_hosts():
    from .policy import PUBLISHERS
    return PUBLISHERS
