"""V2 candidate scope with explicit executable rights; proposed scope is never a grant."""

from copy import deepcopy
from datetime import date
import json
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit

from .metadata import digest
from .policy import AcquisitionError, canonicalize, ProgrammeGate, beneath


SK_FLOW_PATH = re.compile(
    r"(?:^|/)(?:accounts?|login|log-in|signin|sign-in|checkout|submit|submission|"
    r"payments?|uploads?|myaccount|auth|api|graphql|cart|pay|book-appointment|logout|"
    r"sign-out|transactions?|personal-records?|admin)(?:/|$)", re.I,
)


def candidate_prefix(host, prefix):
    if not isinstance(prefix, str) or not prefix.startswith("/") or "?" in prefix or "#" in prefix:
        raise AcquisitionError("Candidate path prefixes must be explicit absolute paths")
    normalized = urlsplit(canonicalize(f"https://{host}{prefix}")).path
    if SK_FLOW_PATH.search(normalized):
        raise AcquisitionError("Candidate scope cannot include account/submission/payment/upload flows")
    return normalized


def validate_candidate_programme(value, pack):
    expected = {
        "schemaVersion", "jurisdictionId", "programmeId", "coverageTarget",
        "publicationPolicy", "permissionStatus", "sources", "accessObservations",
        "exclusions", "externalCandidatePublishers", "scopeNotice",
    }
    if (
        not isinstance(value, dict) or set(value) != expected
        or value["schemaVersion"] != 2 or value["jurisdictionId"] != pack.id
        or value["coverageTarget"] != "all-permitted-public-pages"
        or value["publicationPolicy"] not in (
            {"exact-hash-human-review", "exact-hash-automated-review"}
            if pack.id == "sk" else {"exact-hash-human-review"}
        )
        or value["permissionStatus"] != "pending-rag-permission"
        or value["programmeId"] != f"{pack.id}-public-corpus"
    ):
        raise AcquisitionError("Unsupported candidate programme identity/schema/policy")
    sources = value["sources"]
    if not isinstance(sources, list) or not sources:
        raise AcquisitionError("Candidate programme requires explicit sources")
    ids = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {
            "id", "publisher", "host", "seedUrl", "targetPathPrefixes", "topics", "formats",
        }:
            raise AcquisitionError("Unsupported candidate source fields")
        if not isinstance(source["id"], str) or not source["id"] or source["id"] in ids:
            raise AcquisitionError("Missing or duplicate candidate source identity")
        if not isinstance(source["publisher"], str) or not source["publisher"].strip():
            raise AcquisitionError("Candidate publisher attribution must be explicit")
        ids.add(source["id"])
        seed = canonicalize(source["seedUrl"])
        host = urlsplit(seed).hostname
        # Only explicit research hosts, never official-domain suffixes or links.
        if host != source["host"] or host not in pack.research_hosts:
            raise AcquisitionError("Candidate host must match the selected pack's explicit research hosts")
        prefixes = source["targetPathPrefixes"]
        if not isinstance(prefixes, list) or not prefixes:
            raise AcquisitionError("Candidate sources require path prefixes")
        checked_paths = [candidate_prefix(host, p) for p in prefixes]
        if not any(beneath(urlsplit(seed).path, p) for p in checked_paths):
            raise AcquisitionError("Candidate seed is outside its proposed scope")
        for name in ("topics", "formats"):
            values = source[name]
            if not isinstance(values, list) or not values or any(not isinstance(x, str) or not x for x in values):
                raise AcquisitionError("Candidate topics/formats must be explicit arrays")
        if set(source["formats"]) - {"html", "pdf"}:
            raise AcquisitionError("Only HTML and proposed linked PDFs are supported candidate formats")
    observations = value["accessObservations"]
    hosts = {source["host"] for source in sources}
    if (
        not isinstance(observations, list) or any(not isinstance(o, dict) for o in observations)
        or {o.get("host") for o in observations} != hosts or len(observations) != len(hosts)
    ):
        raise AcquisitionError("Candidate observations must identify each proposed host exactly once")
    for item in observations:
        if set(item) != {
            "host", "robotsUrl", "sitemaps", "evidenceKind", "observedDate", "fetchedAt",
            "responseSha256", "contentSignals", "searchExcludesAiGeneratedSummaries",
            "accessState", "notice",
        } or item["evidenceKind"] != "agent-observed-prior-tool-result":
            raise AcquisitionError("Unsupported prior observation schema")
        try:
            date.fromisoformat(item["observedDate"])
        except (ValueError, TypeError) as exc:
            raise AcquisitionError("Prior observations require an attributed date, not a fetch time") from exc
        signals = item["contentSignals"]
        if not isinstance(signals, dict) or set(signals) != {"search", "ai-train", "use", "ai-input"}:
            raise AcquisitionError("Observed content signals must retain explicit unresolved AI-input permission")
        if (
            signals["ai-train"] not in (None, "no")
            or any(signals[key] is not None and not isinstance(signals[key], str)
                   for key in ("search", "use"))
            or signals["ai-input"] is not None
            or item["accessState"] != "pending-rag-permission"
        ):
            raise AcquisitionError("Prior robots signals cannot become an operation permission grant")
        if item["searchExcludesAiGeneratedSummaries"] is not True and item["searchExcludesAiGeneratedSummaries"] is not None:
            raise AcquisitionError("Unresolved search-summary observations cannot grant AI use")
        if item.get("robotsUrl") != f"https://{item['host']}/robots.txt":
            raise AcquisitionError("Unexpected candidate robots endpoint")
        if item.get("responseSha256") is not None or item.get("fetchedAt") is not None:
            raise AcquisitionError("Prior observation is not a captured publisher snapshot")
        for url in item.get("sitemaps", []):
            if urlsplit(canonicalize(url)).hostname != item["host"]:
                raise AcquisitionError("Candidate sitemap cannot introduce another publisher")
    exclusions = value["exclusions"]
    if not isinstance(exclusions, dict) or set(exclusions) != {"robotsPrefixes", "categories"}:
        raise AcquisitionError("Candidate exclusions must be explicit")
    if not isinstance(exclusions["robotsPrefixes"], list) or any(
        not isinstance(p, str) or not p.startswith("/") for p in exclusions["robotsPrefixes"]
    ):
        raise AcquisitionError("Robots prefix exclusions must be absolute path patterns")
    if not isinstance(exclusions["categories"], list):
        raise AcquisitionError("Candidate exclusion categories must be an array")
    if not isinstance(value["externalCandidatePublishers"], str):
        raise AcquisitionError("External publishers must remain a separate candidate policy")
    return value


def external_candidates(pack, reference):
    root = pack.programme_path.parents[3]
    from pathlib import Path
    relative = Path(reference)
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(
        (root / "jurisdictions" / pack.id / "ingestion").resolve()
    ):
        raise AcquisitionError("External publisher candidates must stay inside the selected pack's ingestion policy")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "jurisdictionId", "status", "candidates", "notice",
    } or value["schemaVersion"] != 1 or value["jurisdictionId"] != pack.id:
        raise AcquisitionError("External publisher candidate schema/identity mismatch")
    if value["status"] != "pending-separate-publisher-review" or not isinstance(value["candidates"], list):
        raise AcquisitionError("External publisher candidates are not executable publisher approvals")
    for candidate in value["candidates"]:
        if not isinstance(candidate, dict) or set(candidate) != {
            "name", "verifiedHosts", "termsEvidence", "robotsEvidence", "publisherGrant", "status",
        } or candidate["verifiedHosts"] or any(candidate[key] is not None for key in (
            "termsEvidence", "robotsEvidence", "publisherGrant",
        )):
            raise AcquisitionError("Unverified external candidates cannot introduce hosts or grants")
    return value


class CandidateProgrammePolicy:
    def __init__(self, programme, pack, rights_review=None, *, rights_provider=None):
        self.pack = pack
        self.jurisdiction_id = pack.id
        self.identity = pack.identity
        self.programme = deepcopy(validate_candidate_programme(programme, pack))
        self.programme_hash = digest(self.programme)
        self.catalog = {
            source["id"]: {"id": source["id"], "publisher": source["publisher"],
                           "url": source["seedUrl"], "topics": source["topics"]}
            for source in self.programme["sources"]
        }
        self.rights_review = None
        self.rights_hash = None
        self.rights_provider = rights_provider
        self._reviewed_documents = {}
        self._reviewed_plans = set()
        if rights_review is not None:
            raise ProgrammeGate("pending-rag-permission", "Legacy/internal blanket rights cannot authorize a v2 candidate pack")
        if rights_provider is not None:
            from .operation_rights import OperationRightsProvider
            if not isinstance(rights_provider, OperationRightsProvider):
                raise AcquisitionError("Candidate policy requires the evidence-pinned v3 operation provider")
            rights_provider.assert_binding(pack, self.programme)
            self.rights_review = deepcopy(rights_provider.review)
            self.rights_hash = rights_provider.review_hash

    def assert_current_rights(self):
        if self.rights_provider is None:
            self.pack.assert_operation("acquisition")
        self.rights_provider.assert_binding(self.pack, self.programme)

    def assert_operation(self, operation, url, *, format="html"):
        self.assert_current_rights()
        return self.rights_provider.authorize(operation, url, format=format)

    def matches(self, url):
        parts = urlsplit(canonicalize(url))
        return [s for s in self.programme["sources"] if s["host"] == parts.hostname
                and any(beneath(parts.path, p) for p in s["targetPathPrefixes"])]

    def tags(self, url, *, kind="document"):
        matches = self.matches(url)
        return sorted(s["id"] for s in matches), sorted({t for s in matches for t in s["topics"]})

    def document_format(self, url, media_type=None):
        normalized = canonicalize(url)
        suffix = PurePosixPath(urlsplit(normalized).path).suffix.lower()
        mime = media_type.split(";")[0].strip().lower() if media_type is not None else None
        if mime is not None and mime not in {"application/pdf", "text/html", "application/xhtml+xml"}:
            raise ProgrammeGate("unsupported-format", "Only declared HTML and bounded text PDFs are supported")
        if suffix == ".pdf" and mime not in {None, "application/pdf"}:
            raise ProgrammeGate("unsupported-format", "A PDF route cannot be extracted as an HTML response")
        format = "pdf" if suffix == ".pdf" or mime == "application/pdf" else "html"
        if not any(format in s["formats"] for s in self.matches(normalized)):
            raise ProgrammeGate("unsupported-format", "Document format is outside the proposed source scope")
        return format

    def validate_url(self, url, *, robots=False, kind="document", require_rights=True,
                     media_type=None):
        normalized = canonicalize(url)
        parts = urlsplit(normalized)
        if parts.hostname not in {s["host"] for s in self.programme["sources"]}:
            raise ProgrammeGate("out-of-scope-host", "Cross-publisher links are not publisher approval")
        if any(parts.path.startswith(p) or (p.endswith("/") and parts.path == p.rstrip("/"))
               for p in self.programme["exclusions"]["robotsPrefixes"]):
            raise ProgrammeGate("robots-exclusion", "Observed robots prefix excludes this proposed URL")
        if SK_FLOW_PATH.search(parts.path):
            raise ProgrammeGate("sensitive-path", "Account, form-submission, payment, upload and transaction flows are excluded")
        if robots:
            if parts.path != "/robots.txt":
                raise ProgrammeGate("invalid-robots-url", "Only /robots.txt is a robots endpoint")
        elif kind in {"sitemap", "sitemap-xml"}:
            if normalized not in {u for o in self.programme["accessObservations"] for u in o["sitemaps"]}:
                raise ProgrammeGate("unverified-sitemap", "Only explicitly proposed sitemap endpoints may be planned")
        elif kind not in {"document", "html"} or not self.matches(normalized):
            raise ProgrammeGate("out-of-scope-path", "No registered candidate route matches")
        elif PurePosixPath(parts.path).suffix.lower() in {
            ".doc", ".docx", ".xls", ".xlsx", ".zip", ".gz", ".xml", ".json",
            ".jpg", ".jpeg", ".png", ".mp4", ".exe",
        }:
            raise ProgrammeGate("unsupported-format", "Arbitrary document extraction is not enabled")
        document_format = None
        if not robots and kind not in {"sitemap", "sitemap-xml"}:
            document_format = self.document_format(normalized, media_type)
        if require_rights:
            self.assert_current_rights()
            if kind in {"sitemap", "sitemap-xml"} and not robots:
                for operation in ("discovery", "storage"):
                    self.rights_provider.authorize_sitemap(operation, normalized, self.programme)
            else:
                format = "robots" if robots else document_format
                for operation in (("discovery", "storage") if robots else ("acquisition", "storage")):
                    self.assert_operation(operation, normalized, format=format)
        return normalized

    def metadata(self, url, *, media_type=None):
        normalized = self.validate_url(url, media_type=media_type)
        self.assert_operation("extraction", normalized, format=self.document_format(normalized, media_type))
        ids, topics = self.tags(normalized)
        return {
            "sourceIds": ids, "topics": topics,
            "rights": {
                "status": "candidate-acquisition-permitted",
                "reviewId": self.rights_review["reviewId"], "reviewHash": self.rights_hash,
                "approvalEvidenceHash": self.rights_provider.expected_sha256,
                "approvalEvidenceReference": "rights-review-sha256:" + self.rights_provider.expected_sha256,
                "licenceUrl": None,
            },
        }

    def extraction_flags(self, url, *, media_type=None):
        if self.rights_provider is None:
            return ["pending-rag-permission"]
        self.assert_operation("extraction", url, format=self.document_format(url, media_type))
        return []

    def response_options(self, response):
        """Authorize the actual media type before programme response persistence."""
        media_type = response.headers.get("content-type", "")
        return {
            "metadata": self.metadata(response.url, media_type=media_type),
            "quality_flags": self.extraction_flags(response.url, media_type=media_type),
        }

    def publication_catalog(self):
        return {"sources": [{**s, "status": "available"} for s in self.catalog.values()],
                "journeys": [], "locations": []}

    def _register_plan(self, plan):
        if not plan.get("reviewManifestHash") and plan["uploads"]:
            raise AcquisitionError("Unreviewed publication plans cannot contain uploads")
        self._reviewed_plans.add(digest(plan))
        self._reviewed_documents.update({digest(d): deepcopy(d) for d in plan["uploads"]})

    def assert_plan(self, plan, *, reviewed=True):
        self.assert_current_rights()
        if digest(plan) not in self._reviewed_plans:
            raise AcquisitionError("Publication requires the unchanged exact-review plan built with this policy")
        if reviewed and not plan.get("reviewManifestHash"):
            raise AcquisitionError("Publication execution requires an exact-snapshot review manifest")

    def authorize_document(self, operation, document, *, reviewed=True):
        if operation in {"embedding", "rag", "generated-summary", "publication"} and self.pack.approval_status != "reviewed-operation-grants":
            self.pack.assert_operation(operation)
        self.assert_current_rights()
        if reviewed and digest(document) not in self._reviewed_documents:
            raise AcquisitionError("Model/publication input does not match an exact-reviewed chunk")
        url = document.get("url") or document.get("canonicalUrl")
        format = self.document_format(url, document.get("mediaType"))
        self.validate_url(url, media_type=document.get("mediaType"))
        self.assert_operation(operation, url, format=format)

    def assert_embedding_texts(self, texts):
        for text in texts:
            matching = next((d for d in self._reviewed_documents.values() if d["content"] == text), None)
            if matching is None:
                raise AcquisitionError("Embedding text must come from an exact-reviewed publication chunk")
            self.authorize_document("embedding", matching)


def source_policy_report(pack, programme):
    policy = CandidateProgrammePolicy(programme, pack)
    proposed = []
    for source in policy.programme["sources"]:
        proposed.append({"sourceId": source["id"], "url": source["seedUrl"], "kind": "configured-seed",
                         "status": "proposed-not-discovered", "formats": source["formats"]})
    for observation in policy.programme["accessObservations"]:
        proposed.extend({"url": url, "kind": "configured-sitemap", "status": "proposed-not-fetched"}
                        for url in observation["sitemaps"])
    return {
        "mode": "offline-source-policy", "jurisdictionId": pack.id,
        "status": "pending-rag-permission", "networkRequests": 0,
        "configuredApprovalStatus": pack.approval_status,
        "programmeHash": policy.programme_hash, "packIdentity": pack.identity,
        "coverageTargetMet": False, "liveInventoryAvailable": False,
        "counts": {name: 0 for name in (
            "discovered", "eligible", "fetched", "extracted", "reviewed", "indexed",
            "withheld", "failed", "superseded",
        )},
        "proposedInventory": proposed, "exclusions": policy.programme["exclusions"],
        "accessObservations": policy.programme["accessObservations"],
        "externalCandidatePublishers": external_candidates(pack, policy.programme["externalCandidatePublishers"]),
        "formatSupport": {"html": "generic-main-content; permission required",
                          "pdf": "supported-bounded-text-pdf; original-byte-sha256; page-citations; permission-required",
                          "scannedPdf": "unsupported-ocr; empty-image-only-pdfs-rejected",
                          "mixedPdf": "text-extracted; textless-pages-quarantined-with-ocr-unsupported-flags",
                          "otherDocuments": "not-in-scope"},
        "informationalForms": "Public form information and blank downloadable forms are proposed scope; "
                              "submission/account/payment/upload flows are excluded. Blank fields are non-facts. "
                              "Linked form PDFs still require permission and a supported parser.",
        "operations": {name: "blocked-pending-publisher-evidence" for name in (
            "discovery", "acquisition", "extraction", "storage",
            "embedding", "rag", "generated-summary", "publication",
        )},
        "localCapabilities": {
            "operationRightsProvider": "implemented-v3-local-evidence-pinned",
            "genericHtmlPolicy": "accepts-explicit-operation-provider; synthetic integration only",
            "nonBcAcquireResumeCli": "implemented; pinned-v3-operation-grants-required",
            "nonBcModelPublication": "implemented; exact-review-and-operation-grants-required",
            "pdfExtraction": "implemented-bounded-text-pdf; rights-aware-programme-integration",
        },
        "nextAction": "Verify exact-host terms/licence and robots evidence plus explicit AI-input, "
                      "embedding, generated-answer and storage uses; supply a pinned v3 operation review, "
                      "agree bounded acquisition "
                      "limits, then review each exact snapshot. This offline report does not inspect or claim live inventory.",
    }
