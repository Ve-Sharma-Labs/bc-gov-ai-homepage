"""Local, evidence-pinned operation decisions; never infer permission from robots."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from urllib.parse import urlsplit

from .metadata import digest, iso_datetime
from .policy import AcquisitionError, canonicalize, ProgrammeGate, beneath, private_reference
from .robots import parse_robots


OPERATIONS = (
    "discovery", "acquisition", "extraction", "storage", "embedding", "rag",
    "generated-summary", "publication", "training", "fine-tuning",
)
FORMATS = {"html", "sitemap-xml", "robots", "pdf"}
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_REVIEW_BYTES = 128 * 1024
MAX_EVIDENCE_BYTES = 4_000_000
MAX_TOTAL_EVIDENCE_BYTES = 8_000_000


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise AcquisitionError("Operation rights fields do not match the strict v3 contract")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise AcquisitionError("Operation rights require accountable, non-empty references")


def _strings(value, *, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty) or any(
        not isinstance(item, str) or not item for item in value
    ) or len(value) != len(set(value)):
        raise AcquisitionError("Operation rights require explicit unique string arrays")


def _sha(value):
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise AcquisitionError("Operation rights require exact SHA-256 evidence identities")


def _read(path, limit):
    if path.stat().st_size > limit:
        raise AcquisitionError("Local operation rights evidence exceeds its byte bound")
    with path.open("rb") as handle:
        body = handle.read(limit + 1)
    if len(body) > limit:
        raise AcquisitionError("Local operation rights evidence exceeds its byte bound")
    return body


def _no_duplicate_fields(items):
    value = {}
    for key, item in items:
        if key in value:
            raise AcquisitionError("Duplicate operation rights JSON fields are ambiguous")
        value[key] = item
    return value


class OperationRightsProvider:
    """An accountable review of scoped evidence, not a publisher verifier."""

    def __init__(self, path, expected_sha256, pack, programme, *,
                 clock=lambda: datetime.now(timezone.utc)):
        from .pack_policy import candidate_prefix, validate_candidate_programme
        validate_candidate_programme(programme, pack)
        _sha(expected_sha256)
        self.path = pack.rights_path(Path(path).resolve())
        self.expected_sha256, self.clock = expected_sha256, clock
        self.pack_identity, self.programme_hash = deepcopy(pack.identity), digest(programme)
        self.programme = deepcopy(programme)
        body = _read(self.path, MAX_REVIEW_BYTES)
        if hashlib.sha256(body).hexdigest() != expected_sha256:
            raise AcquisitionError("Operation rights review bytes do not match the independently pinned SHA-256")
        review = json.loads(body.decode("utf-8"), object_pairs_hook=_no_duplicate_fields)
        _keys(review, "schemaVersion jurisdictionId programmeHash packIdentity reviewId reviewer reviewedAt expiresAt revocation evidence grants")
        pending_attestation = (
            pack.id == "sk"
            and getattr(pack, "pending_identity", None) is not None
            and review["packIdentity"] == pack.pending_identity
            and isinstance(review["reviewId"], str)
            and review["reviewId"].startswith("user-attestation:")
            and isinstance(review["evidence"], list)
            and any(isinstance(item, dict) and item.get("kind") == "user-attestation"
                    for item in review["evidence"])
        )
        if (
            type(review["schemaVersion"]) is not int or review["schemaVersion"] != 3
            or review["jurisdictionId"] != pack.id
            or (review["packIdentity"] != pack.identity and not pending_attestation)
            or review["programmeHash"] != self.programme_hash
        ):
            raise AcquisitionError("Operation rights must bind the exact jurisdiction, pack and programme")
        for key in ("reviewId", "reviewer"):
            _text(review[key])
        reviewed, expires = iso_datetime(review["reviewedAt"]), iso_datetime(review["expiresAt"])
        if reviewed > clock() or expires <= reviewed or expires - reviewed > timedelta(days=30):
            raise AcquisitionError("Operation rights need a current review with at most a 30-day lifetime")
        _keys(review["revocation"], "status reference revokedAt")
        if review["revocation"]["status"] not in {"active", "revoked"} or not private_reference(review["revocation"]["reference"]):
            raise AcquisitionError("Operation rights require an explicit revocation reference")
        if review["revocation"]["status"] == "active" and review["revocation"]["revokedAt"] is not None:
            raise AcquisitionError("Active operation rights cannot have a revocation timestamp")
        if review["revocation"]["status"] == "revoked":
            revoked = iso_datetime(review["revocation"]["revokedAt"])
            if revoked < reviewed or revoked > clock():
                raise AcquisitionError("Invalid operation-rights revocation timestamp")
        hosts = {source["host"] for source in programme["sources"]}
        permission_kinds = {"publisher-licence", "publisher-written-permission"}
        if pack.id == "sk":
            permission_kinds.add("user-attestation")
        evidence = review["evidence"]
        if not isinstance(evidence, list) or not evidence or len(evidence) > 32:
            raise AcquisitionError("Operation rights require bounded, explicit publisher evidence")
        self.evidence, self.evidence_paths, self.robots = {}, {}, {}
        total_bytes = 0
        for item in evidence:
            _keys(item, "id kind host url file sha256 capturedAt mediaType publisherReference permittedOperations")
            for key in ("id", "file", "mediaType"):
                _text(item[key])
            if item["id"] in self.evidence or item["host"] not in hosts:
                raise AcquisitionError("Duplicate or cross-publisher operation evidence")
            if item["kind"] not in {"terms", "robots"} | permission_kinds:
                raise AcquisitionError("Internal/project approval is not publisher operation permission")
            if not private_reference(item["publisherReference"]):
                raise AcquisitionError("Publisher evidence must retain its reviewed source reference")
            if item["url"] is None:
                if item["kind"] not in {"publisher-written-permission", "user-attestation"}:
                    raise AcquisitionError("Only written permission or user attestation may have a private source")
            elif urlsplit(canonicalize(item["url"])).hostname != item["host"]:
                raise AcquisitionError("Publisher evidence URLs must match the exact grant host")
            if item["kind"] == "user-attestation" and (
                item["url"] is not None
                or not item["publisherReference"].startswith("user-attestation:")
                or not review["reviewId"].startswith("user-attestation:")
                or item["mediaType"] != "text/plain"
            ):
                raise AcquisitionError("User attestations require explicit private attestation provenance")
            captured = iso_datetime(item["capturedAt"])
            if captured > reviewed:
                raise AcquisitionError("Evidence capture cannot postdate its accountable review")
            _strings(item["permittedOperations"], allow_empty=True)
            if set(item["permittedOperations"]) - set(OPERATIONS) or set(item["permittedOperations"]) & {"training", "fine-tuning"}:
                raise AcquisitionError("Unknown or prohibited publisher operation evidence")
            if item["kind"] in {"terms", "robots"} and item["permittedOperations"]:
                raise AcquisitionError("Terms/robots presence alone cannot grant AI or acquisition operations")
            relative = Path(item["file"])
            path = (self.path.parent / relative).resolve()
            if ("\\" in item["file"] or relative.is_absolute() or ".." in relative.parts
                    or not path.is_relative_to(self.path.parent)):
                raise AcquisitionError("Operation evidence must remain inside the supplied review directory")
            _sha(item["sha256"])
            evidence_body = _read(path, MAX_EVIDENCE_BYTES)
            total_bytes += len(evidence_body)
            if total_bytes > MAX_TOTAL_EVIDENCE_BYTES:
                raise AcquisitionError("Operation evidence set exceeds its total byte bound")
            if hashlib.sha256(evidence_body).hexdigest() != item["sha256"]:
                raise AcquisitionError("Publisher evidence bytes do not match the reviewed SHA-256")
            if item["kind"] == "robots":
                if item["url"] != f"https://{item['host']}/robots.txt" or item["host"] in self.robots:
                    raise AcquisitionError("Operation review requires one exact captured robots policy per host")
                self.robots[item["host"]] = parse_robots(evidence_body, item["mediaType"])
            self.evidence[item["id"]] = deepcopy(item)
            self.evidence_paths[item["id"]] = path
        grants = review["grants"]
        if not isinstance(grants, list) or not grants or len(grants) > len(hosts):
            raise AcquisitionError("Operation rights require an explicit bounded host grant set")
        self.grants = {}
        for grant in grants:
            _keys(grant, "host pathPrefixes formats decisions")
            host = grant["host"]
            if host not in hosts or host in self.grants:
                raise AcquisitionError("Operation grants cannot duplicate or introduce publishers")
            _strings(grant["pathPrefixes"])
            _strings(grant["formats"])
            if set(grant["formats"]) - FORMATS:
                raise AcquisitionError("Unsupported operation grant format")
            paths = [candidate_prefix(host, p) for p in grant["pathPrefixes"]]
            if paths != grant["pathPrefixes"]:
                raise AcquisitionError("Operation path prefixes must already be canonical")
            source_paths = [p for source in programme["sources"] if source["host"] == host
                            for p in source["targetPathPrefixes"]]
            if any(not any(beneath(p, source_path) for source_path in source_paths) for p in paths):
                raise AcquisitionError("Operation grants cannot widen the programme's content scope")
            kinds = {e["kind"] for e in self.evidence.values() if e["host"] == host}
            if not {"terms", "robots"} <= kinds or not kinds & permission_kinds:
                raise AcquisitionError("Each grant requires captured terms, robots and explicit permission evidence")
            decisions = grant["decisions"]
            if not isinstance(decisions, dict) or set(decisions) != set(OPERATIONS):
                raise AcquisitionError("Every operation must have its own explicit decision")
            for operation, decision in decisions.items():
                _keys(decision, "status evidenceIds")
                if decision["status"] not in {"granted", "denied", "pending"}:
                    raise AcquisitionError("Operation decisions are granted, denied or pending, not flags")
                _strings(decision["evidenceIds"], allow_empty=decision["status"] != "granted")
                if operation in {"training", "fine-tuning"} and decision["status"] != "denied":
                    raise AcquisitionError("Training and fine-tuning remain denied")
                if decision["status"] != "granted" and decision["evidenceIds"]:
                    raise AcquisitionError("Pending/denied decisions cannot carry an implicit grant")
                for evidence_id in decision["evidenceIds"]:
                    item = self.evidence.get(evidence_id)
                    if (
                        item is None or item["host"] != host
                        or item["kind"] not in permission_kinds
                        or operation not in item["permittedOperations"]
                    ):
                        raise AcquisitionError("Granted operations require matching explicit publisher permission evidence")
            self.grants[host] = deepcopy({**grant, "pathPrefixes": paths})
        self.review = deepcopy(review)
        self.review_hash = digest(review)
        self.robots = MappingProxyType(self.robots)
        self.assert_current()

    def assert_binding(self, pack, programme):
        if self.pack_identity != pack.identity or self.programme_hash != digest(programme):
            raise AcquisitionError("Operation provider does not belong to this pack/programme")
        self.assert_current()

    def assert_current(self):
        if digest(self.programme) != self.programme_hash or digest(self.review) != self.review_hash or self.grants != {
            g["host"]: g for g in self.review["grants"]
        } or self.evidence != {e["id"]: e for e in self.review["evidence"]}:
            raise AcquisitionError("In-memory operation rights identity changed")
        if (
            self.review["revocation"]["status"] != "active"
            or iso_datetime(self.review["reviewedAt"]) > self.clock()
            or iso_datetime(self.review["expiresAt"]) <= self.clock()
        ):
            raise ProgrammeGate("rights-expired-or-revoked", "A new accountable publisher review is required")
        if hashlib.sha256(_read(self.path, MAX_REVIEW_BYTES)).hexdigest() != self.expected_sha256:
            raise ProgrammeGate("rights-evidence-changed", "Pinned review changed; never replace the run's rights identity")
        for evidence_id, path in self.evidence_paths.items():
            if hashlib.sha256(_read(path, MAX_EVIDENCE_BYTES)).hexdigest() != self.evidence[evidence_id]["sha256"]:
                raise ProgrammeGate("rights-evidence-changed", "Pinned publisher evidence changed")

    def authorize(self, operation, url, *, format="html"):
        self.assert_current()
        if operation not in OPERATIONS or format not in FORMATS:
            raise AcquisitionError("Unknown operation or format cannot be authorized")
        normalized = canonicalize(url)
        parts = urlsplit(normalized)
        from .pack_policy import SK_FLOW_PATH
        if SK_FLOW_PATH.search(parts.path) or any(
            parts.path.startswith(p) or (p.endswith("/") and parts.path == p.rstrip("/"))
            for p in self.programme["exclusions"]["robotsPrefixes"]
        ):
            raise ProgrammeGate("rights-flow-excluded", "Scope excludes action flows and observed robots paths")
        suffix = Path(parts.path).suffix.lower()
        if suffix == ".pdf" and format != "pdf":
            raise ProgrammeGate("rights-format-missing", "PDF permission cannot be supplied as HTML permission")
        if suffix in {".doc", ".docx", ".xls", ".xlsx", ".zip", ".gz", ".exe"}:
            raise ProgrammeGate("rights-format-missing", "Arbitrary document formats are not registered")
        grant = self.grants.get(parts.hostname)
        if grant is None:
            raise ProgrammeGate("rights-host-missing", "No exact-publisher operation grant")
        if format not in grant["formats"]:
            raise ProgrammeGate("rights-format-missing", "No operation grant for this format")
        if format == "robots":
            if parts.path != "/robots.txt" or operation not in {"discovery", "acquisition", "storage"}:
                raise ProgrammeGate("rights-path-missing", "Robots grants apply only to /robots.txt")
        elif format == "sitemap-xml":
            # Sitemap endpoints are infrastructure, not content-scope prefixes.
            # CandidateProgrammePolicy separately checks exact programme endpoints.
            raise ProgrammeGate("rights-path-missing", "Use authorize_sitemap for exact programme endpoints")
        elif not any(beneath(parts.path, prefix) for prefix in grant["pathPrefixes"]):
            raise ProgrammeGate("rights-path-missing", "No operation grant for this content path")
        self._decision(grant, operation)
        if operation in {"discovery", "acquisition"} and format != "robots" and not self.robots[parts.hostname].allows(normalized):
            raise ProgrammeGate("rights-robots-denied", "Captured crawler policy still excludes this route")
        return normalized

    def authorize_sitemap(self, operation, url, programme):
        self.assert_current()
        if digest(programme) != self.programme_hash:
            raise AcquisitionError("Sitemap authorization requires the bound programme")
        if operation not in {"discovery", "acquisition", "storage"}:
            raise ProgrammeGate("rights-operation-denied", "Sitemaps are discovery infrastructure, not model inputs")
        normalized = canonicalize(url)
        if normalized not in {u for o in programme["accessObservations"] for u in o["sitemaps"]}:
            raise ProgrammeGate("rights-path-missing", "No exact programme sitemap approval")
        host = urlsplit(normalized).hostname
        grant = self.grants.get(host)
        if grant is None or "sitemap-xml" not in grant["formats"]:
            raise ProgrammeGate("rights-format-missing", "No sitemap operation grant")
        self._decision(grant, operation)
        if not self.robots[host].allows(normalized):
            raise ProgrammeGate("rights-robots-denied", "Captured crawler policy excludes this sitemap")
        return normalized

    @staticmethod
    def _decision(grant, operation):
        if operation not in OPERATIONS:
            raise AcquisitionError("Unknown operation cannot be authorized")
        decision = grant["decisions"][operation]
        if decision["status"] != "granted":
            raise ProgrammeGate("rights-operation-" + decision["status"], f"{operation} has no affirmative publisher grant")

    def report(self):
        self.assert_current()
        attested = any(item["kind"] == "user-attestation" for item in self.evidence.values())
        notice = "Byte identity and scoped decisions are validated locally, not legal truth. "
        if attested:
            notice += "User attestation is not independently verified publisher evidence. "
        notice += "No content snapshot is approved, no publisher request or model/cloud operation was performed."
        return {
            "schemaVersion": 3, "programmeHash": self.programme_hash,
            "packIdentity": self.pack_identity, "rightsReviewHash": self.review_hash,
            "rightsFileSha256": self.expected_sha256, "networkRequests": 0,
            "status": "local-reviewed-operation-decisions",
            "authorizationBasis": "user-attested" if attested else "publisher-evidence",
            "liveExecutionEnabled": False,
            "executionInterfaces": "implemented; explicit execute/acquire flags and exact content review still required",
            "grants": [{"host": g["host"], "pathPrefixes": g["pathPrefixes"], "formats": g["formats"],
                        "operations": {op: decision["status"] for op, decision in g["decisions"].items()}}
                       for g in self.grants.values()],
            "notice": notice,
            "implementationGaps": [
                "OCR for scanned PDFs remains unsupported; text-PDF policy/extractor integration is implemented",
            ],
        }
