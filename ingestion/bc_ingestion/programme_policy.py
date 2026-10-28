"""Explicit candidate-only scope; it cannot widen the manual publication policy."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit

from .catalog import SOURCE_IDS
from .metadata import digest, iso_datetime
from .policy import AcquisitionError, PUBLISHERS, SENSITIVE_PATH, canonicalize


class ProgrammeGate(AcquisitionError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


PROGRAMME_SENSITIVE = re.compile(
    r"(?:^|/)(?:admin|user|users|cart|checkout|pay|payments|booking|book-appointment|"
    r"appointments?|sign-up|sign-out|logout|api|graphql|forms?|personal-records?|"
    r"transactions?)(?:/|$)", re.I,
)

RIGHTS_ROUTES = {
    "html", "sitemap-xml", "rendered-html", "publisher-feed", "legal-xml",
}
RIGHTS_EXCLUSIONS = {
    "authenticated-paths",
    "bookings",
    "forms",
    "payments",
    "pdf",
    "personal-records",
    "third-party-clinical-content",
    "transactions",
    "uploads",
    "workbc-job-board-data",
}
PUBLIC_REFERENCE_KINDS = {
    "access", "copyright", "disclaimer", "licence", "robots", "terms",
}
HOLD_CLEARING_ROUTES = {
    "blocked-publisher-terms": {"rendered-html", "publisher-feed", "sitemap-xml"},
    "blocked-invalid-robots": {"publisher-feed"},
    "blocked-general-crawl": {"legal-xml", "publisher-feed"},
}
PRIVATE_REFERENCE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]{1,512}")
SHA256 = re.compile(r"[0-9a-f]{64}")


def beneath(path: str, prefix: str) -> bool:
    return prefix == "/" or path == prefix or path.startswith(prefix.rstrip("/") + "/")


def private_reference(value) -> bool:
    return (
        isinstance(value, str)
        and PRIVATE_REFERENCE.fullmatch(value) is not None
        and all(ord(character) >= 32 for character in value)
    )


def checked_prefix(host: str, prefix: str) -> str:
    if not isinstance(prefix, str) or not prefix.startswith("/") or "?" in prefix or "#" in prefix:
        raise AcquisitionError("Programme path prefixes must be explicit absolute paths")
    normalized = urlsplit(canonicalize(f"https://{host}{prefix}")).path
    if SENSITIVE_PATH.search(normalized):
        raise AcquisitionError("Programme rights cannot include account/transaction paths")
    return normalized


def validate_programme(value: dict, catalog: dict) -> dict:
    if (
        value.get("schemaVersion") != 1
        or value.get("coverageTarget") != "all-permitted-public-pages"
        or value.get("publicationPolicy") != "exact-hash-human-review"
    ):
        raise AcquisitionError("Unsupported source programme or publication policy")
    sources = value.get("sources", [])
    if not isinstance(sources, list) or len(sources) != 12 or {s.get("id") for s in sources} != SOURCE_IDS:
        raise AcquisitionError("Programme must map exactly the twelve catalogue source IDs")
    catalog_sources = {s["id"]: s for s in catalog["sources"]}
    for source in sources:
        host = source.get("host")
        if host not in PUBLISHERS or urlsplit(catalog_sources[source["id"]]["url"]).hostname != host:
            raise AcquisitionError("Programme publisher must match the catalogue")
        seed = canonicalize(source["seedUrl"])
        prefixes = source.get("targetPathPrefixes")
        if not isinstance(prefixes, list) or not prefixes:
            raise AcquisitionError("Programme sources require explicit candidate path prefixes")
        paths = [checked_prefix(host, p) for p in prefixes]
        if urlsplit(seed).hostname != host or not any(beneath(urlsplit(seed).path, p) for p in paths):
            raise AcquisitionError("Programme seed must belong to its candidate scope")
        topics = source.get("topics")
        if not isinstance(topics, list) or any(not isinstance(t, str) or not t for t in topics):
            raise AcquisitionError("Programme topics must be a string array")
    observations = value.get("accessObservations", [])
    if len(observations) != len(PUBLISHERS) or {o.get("host") for o in observations} != set(PUBLISHERS):
        raise AcquisitionError("Programme access observations must identify all six hosts")
    for observation in observations:
        host = observation["host"]
        if observation.get("robotsUrl") != f"https://{host}/robots.txt":
            raise AcquisitionError("Unexpected programme robots endpoint")
        for sitemap in observation.get("sitemaps", []):
            canonicalize(sitemap)
    return value


class ProgrammePolicy:
    def __init__(self, programme: dict, catalog: dict, rights_review: dict | None = None, *,
                 clock=lambda: datetime.now(timezone.utc)):
        self.programme = deepcopy(validate_programme(programme, catalog))
        self.catalog = {s["id"]: s for s in catalog["sources"]}
        self.programme_hash = digest(self.programme)
        self.rights_review = deepcopy(rights_review)
        self.rights_hash = digest(rights_review) if rights_review is not None else None
        self.clock = clock
        self.grants = {}
        self.legacy_grants = {}
        if rights_review is not None:
            self._validate_rights()

    def _validate_rights(self):
        review = self.rights_review
        if isinstance(review, dict) and review.get("schemaVersion") == 1:
            self._validate_legacy_rights()
            return
        expected = {
            "schemaVersion", "programmeHash", "purpose", "approvalKind", "approvalConfirmed",
            "reviewer", "reviewId", "reviewedAt", "expiresAt", "approvalEvidence",
            "revocation", "exclusions", "grants",
        }
        if (
            not isinstance(review, dict)
            or set(review) != expected
            or review.get("schemaVersion") != 2
            or review.get("programmeHash") != self.programme_hash
            or review.get("purpose") != "candidate-acquisition"
            or review.get("approvalKind") != "internal-blanket"
            or review.get("approvalConfirmed") is not True
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip()
            or not isinstance(review.get("reviewId"), str) or not review["reviewId"].strip()
        ):
            raise AcquisitionError("A programme-bound, accountable candidate rights review is required")
        reviewed, expires = iso_datetime(review.get("reviewedAt")), iso_datetime(review.get("expiresAt"))
        if reviewed > self.clock() or expires <= reviewed or expires - reviewed > timedelta(days=30):
            raise AcquisitionError("Rights review timestamps are invalid or in the future")
        evidence = review.get("approvalEvidence")
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"kind", "reference", "sha256"}
            or evidence.get("kind") != "internal-session-approval"
            or not private_reference(evidence.get("reference"))
            or not isinstance(evidence.get("sha256"), str)
            or not SHA256.fullmatch(evidence["sha256"])
        ):
            raise AcquisitionError("Internal approval evidence requires an exact private reference and SHA-256")
        revocation = review.get("revocation")
        if (
            not isinstance(revocation, dict)
            or set(revocation) != {"status", "reference", "revokedAt"}
            or revocation.get("status") not in {"active", "revoked"}
            or not private_reference(revocation.get("reference"))
        ):
            raise AcquisitionError("Rights reviews require an accountable revocation reference")
        if revocation["status"] == "active":
            if revocation["revokedAt"] is not None:
                raise AcquisitionError("An active rights review cannot have a revocation time")
        else:
            revoked = iso_datetime(revocation.get("revokedAt"))
            if revoked < reviewed or revoked > self.clock():
                raise AcquisitionError("Rights review revocation time is invalid or in the future")
        exclusions = review.get("exclusions")
        if (
            not isinstance(exclusions, list)
            or any(not isinstance(item, str) or not item for item in exclusions)
            or len(exclusions) != len(set(exclusions))
            or not RIGHTS_EXCLUSIONS.issubset(exclusions)
        ):
            raise AcquisitionError("Rights review must retain all mandatory sensitive-content exclusions")
        grants = review.get("grants")
        if not isinstance(grants, list) or not grants:
            raise AcquisitionError("Rights review needs explicit publisher/path/format grants")
        for grant in grants:
            if not isinstance(grant, dict) or set(grant) != {
                "host", "pathPrefixes", "routes", "publicReferences",
            }:
                raise AcquisitionError("Unsupported candidate rights grant")
            host = grant["host"]
            if host not in PUBLISHERS or host in self.grants:
                raise AcquisitionError("Rights grants require unique, registered publisher hosts")
            programme_prefixes = [
                checked_prefix(host, prefix)
                for source in self.programme["sources"] if source["host"] == host
                for prefix in source["targetPathPrefixes"]
            ]
            if (
                not isinstance(grant["pathPrefixes"], list)
                or not grant["pathPrefixes"]
                or len(grant["pathPrefixes"]) != len(set(grant["pathPrefixes"]))
            ):
                raise AcquisitionError("Rights grants need a nonempty public-document scope")
            grant_prefixes = [checked_prefix(host, prefix) for prefix in grant["pathPrefixes"]]
            if len(grant_prefixes) != len(set(grant_prefixes)):
                raise AcquisitionError("Rights grant paths must be unique after canonicalization")
            if any(not any(beneath(prefix, allowed) for allowed in programme_prefixes)
                   for prefix in grant_prefixes):
                raise AcquisitionError("Rights grants cannot widen the programme path scope")
            routes = grant["routes"]
            if not isinstance(routes, list) or not routes:
                raise AcquisitionError("Rights grants need explicit technical route grants")
            route_identities = set()
            observation = next(o for o in self.programme["accessObservations"] if o["host"] == host)
            observed_sitemaps = [urlsplit(canonicalize(url)).path for url in observation.get("sitemaps", [])]
            for route in routes:
                if not isinstance(route, dict) or set(route) != {
                    "technicalRoute", "format", "pathPrefixes", "clearsAccessHold",
                }:
                    raise AcquisitionError("Rights routes require exact route, format, path, and hold scope")
                technical_route, format_name = route["technicalRoute"], route["format"]
                if (
                    technical_route not in RIGHTS_ROUTES
                    or format_name != technical_route
                    or not isinstance(route["pathPrefixes"], list)
                    or not route["pathPrefixes"]
                    or len(route["pathPrefixes"]) != len(set(route["pathPrefixes"]))
                ):
                    raise AcquisitionError("Unsupported or ambiguous candidate route/format grant")
                route_prefixes = [checked_prefix(host, prefix) for prefix in route["pathPrefixes"]]
                if len(route_prefixes) != len(set(route_prefixes)):
                    raise AcquisitionError("Rights route paths must be unique after canonicalization")
                if technical_route != "sitemap-xml" and any(
                    not any(beneath(prefix, allowed) for allowed in grant_prefixes)
                    for prefix in route_prefixes
                ):
                    raise AcquisitionError("Rights route paths must remain inside the host grant")
                if technical_route == "sitemap-xml" and (
                    not observed_sitemaps
                    or any(not any(beneath(sitemap, prefix) for sitemap in observed_sitemaps)
                           for prefix in route_prefixes)
                ):
                    raise AcquisitionError("Sitemap grants must match registered discovery endpoints")
                if technical_route == "legal-xml" and (
                    host != "www.bclaws.gov.bc.ca"
                    or any(not beneath(prefix, "/civix") for prefix in route_prefixes)
                ):
                    raise AcquisitionError("Legal XML is restricted to the registered BC Laws CiviX route")
                clearance = route["clearsAccessHold"]
                if clearance is not None and (
                    not isinstance(clearance, str)
                    or clearance != observation.get("accessState")
                    or not clearance.startswith("blocked-")
                    or technical_route not in HOLD_CLEARING_ROUTES.get(clearance, set())
                    or any(prefix == "/" for prefix in route_prefixes)
                ):
                    raise AcquisitionError("Access holds require an explicit matching non-wildcard route")
                identity = technical_route, format_name, tuple(sorted(route_prefixes))
                if identity in route_identities:
                    raise AcquisitionError("Rights routes must be unique")
                route_identities.add(identity)
            references = grant["publicReferences"]
            if not isinstance(references, list):
                raise AcquisitionError("Public licence and terms references must be an array")
            reference_identities = set()
            for reference in references:
                if (
                    not isinstance(reference, dict)
                    or set(reference) != {"kind", "url"}
                    or reference.get("kind") not in PUBLIC_REFERENCE_KINDS
                ):
                    raise AcquisitionError("Unsupported public rights reference")
                url = canonicalize(reference.get("url"))
                if urlsplit(url).hostname != host:
                    raise AcquisitionError("Public rights references must stay on the granted publisher host")
                identity = (reference["kind"], url)
                if identity in reference_identities:
                    raise AcquisitionError("Public rights references must be unique")
                reference_identities.add(identity)
            self.grants[host] = grant
        self.assert_current_rights()

    def _validate_legacy_rights(self):
        review = self.rights_review
        if (
            review.get("programmeHash") != self.programme_hash
            or review.get("purpose") != "candidate-acquisition"
            or review.get("publisherPermissionConfirmed") is not True
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip()
            or not isinstance(review.get("reviewId"), str) or not review["reviewId"].strip()
        ):
            raise AcquisitionError("A programme-bound, accountable candidate rights review is required")
        reviewed, expires = iso_datetime(review.get("reviewedAt")), iso_datetime(review.get("expiresAt"))
        if reviewed > self.clock() or expires <= reviewed:
            raise AcquisitionError("Rights review timestamps are invalid or in the future")
        grants = review.get("grants")
        if not isinstance(grants, list) or not grants:
            raise AcquisitionError("Rights review needs explicit publisher/path/format grants")
        for grant in grants:
            if not isinstance(grant, dict) or set(grant) != {
                "host", "pathPrefixes", "sitemapPathPrefixes", "formats", "licenceUrl", "evidenceUrl",
            }:
                raise AcquisitionError("Unsupported candidate rights grant; access holds cannot be overridden")
            host = grant["host"]
            if host not in PUBLISHERS or host in self.grants:
                raise AcquisitionError("Rights grants require unique, registered publisher hosts")
            for key in ("pathPrefixes", "sitemapPathPrefixes"):
                if not isinstance(grant[key], list):
                    raise AcquisitionError("Rights path prefixes must be explicit arrays")
                for prefix in grant[key]:
                    checked_prefix(host, prefix)
            if not grant["pathPrefixes"]:
                raise AcquisitionError("Rights grants need a nonempty public-document scope")
            formats = grant["formats"]
            if not isinstance(formats, list) or not formats or set(formats) - {"html", "sitemap-xml"}:
                raise AcquisitionError("Only HTML and discovery-only sitemap XML adapters are implemented")
            for key in ("licenceUrl", "evidenceUrl"):
                if urlsplit(canonicalize(grant[key])).hostname not in PUBLISHERS:
                    raise AcquisitionError("Rights evidence must identify a registered official publisher")
            routes = []
            if "html" in formats:
                routes.append({
                    "technicalRoute": "html", "format": "html",
                    "pathPrefixes": grant["pathPrefixes"], "clearsAccessHold": None,
                })
            if "sitemap-xml" in formats and grant["sitemapPathPrefixes"]:
                routes.append({
                    "technicalRoute": "sitemap-xml", "format": "sitemap-xml",
                    "pathPrefixes": grant["sitemapPathPrefixes"], "clearsAccessHold": None,
                })
            self.grants[host] = {
                "host": host, "pathPrefixes": grant["pathPrefixes"], "routes": routes,
                "publicReferences": [
                    {"kind": "licence", "url": grant["licenceUrl"]},
                    {"kind": "access", "url": grant["evidenceUrl"]},
                ],
            }
            self.legacy_grants[host] = grant
        self.assert_current_rights()

    def assert_current_rights(self) -> None:
        if self.rights_review is None:
            raise ProgrammeGate("rights-review-required", "Inventory scope is not acquisition permission")
        if self.rights_review.get("revocation", {}).get("status") == "revoked":
            raise ProgrammeGate("rights-review-revoked", "The accountable approval has been revoked")
        if iso_datetime(self.rights_review["expiresAt"]) <= self.clock():
            raise ProgrammeGate("rights-review-expired", "Renew the accountable review before another request")

    def _route(self, host: str, path: str, technical_route: str, format_name: str) -> dict:
        grant = self.grants.get(host)
        if grant is None:
            raise ProgrammeGate("rights-scope-missing", "No reviewed grant covers this publisher")
        matches = [
            route for route in grant["routes"]
            if route["technicalRoute"] == technical_route and route["format"] == format_name
            and any(beneath(path, checked_prefix(host, prefix)) for prefix in route["pathPrefixes"])
        ]
        if not matches:
            raise ProgrammeGate("rights-scope-missing", "No reviewed grant covers this path, format, and route")
        return max(
            matches,
            key=lambda route: max(
                len(checked_prefix(host, prefix)) for prefix in route["pathPrefixes"]
                if beneath(path, checked_prefix(host, prefix))
            ),
        )

    def _hold(self, host: str, matching: list[dict]) -> tuple[str | None, str | None]:
        publisher_hold = PUBLISHERS[host].hold
        catalogue_hold = any(self.catalog[source["id"]]["status"] in ("blocked", "pending")
                             for source in matching)
        if not publisher_hold and not catalogue_hold:
            return None, None
        observation = next(o for o in self.programme["accessObservations"] if o["host"] == host)
        code = observation.get("accessState")
        if not isinstance(code, str) or not code.startswith("blocked-"):
            code = "unreviewed-access-hold"
        message = publisher_hold or "Catalogue acquisition hold remains in force"
        return code, message

    def matches(self, url: str) -> list[dict]:
        parts = urlsplit(canonicalize(url))
        return sorted([
            s for s in self.programme["sources"] if s["host"] == parts.hostname and any(
                beneath(parts.path, checked_prefix(s["host"], p)) for p in s["targetPathPrefixes"]
            )
        ], key=lambda s: (
            -max(len(checked_prefix(s["host"], p)) for p in s["targetPathPrefixes"]
                 if beneath(parts.path, checked_prefix(s["host"], p))), s["id"],
        ))

    def tags(self, url: str, *, kind: str = "document") -> tuple[list[str], list[str]]:
        matches = self.matches(url) if kind not in {"sitemap", "sitemap-xml"} else [
            s for s in self.programme["sources"] if s["host"] == urlsplit(url).hostname
        ]
        ids = sorted(s["id"] for s in matches)
        topics = sorted({t for s in matches for t in [*s["topics"], *self.catalog[s["id"]]["topics"]]})
        return ids, topics

    def validate_url(self, url: str, *, robots: bool = False, kind: str = "document",
                     require_rights: bool = True) -> str:
        normalized = canonicalize(url)
        parts = urlsplit(normalized)
        publisher = PUBLISHERS.get(parts.hostname)
        if publisher is None:
            aliases = {a for s in self.programme["sources"] for a in s.get("candidateAliases", [])}
            code = "unverified-alias" if parts.hostname in aliases else "out-of-scope-host"
            raise ProgrammeGate(code, "An alias declaration or cross-publisher link is not canonical approval")
        if SENSITIVE_PATH.search(parts.path) or PROGRAMME_SENSITIVE.search(parts.path):
            raise ProgrammeGate("sensitive-path", "Account, submission and transaction paths are excluded")
        if robots:
            if parts.path != "/robots.txt":
                raise ProgrammeGate("invalid-robots-url", "Only the publisher /robots.txt endpoint is permitted")
            return normalized
        route_for_kind = {
            "document": "html",
            "html": "html",
            "sitemap": "sitemap-xml",
            "sitemap-xml": "sitemap-xml",
            "rendered-html": "rendered-html",
            "publisher-feed": "publisher-feed",
            "legal-xml": "legal-xml",
        }
        technical_route = route_for_kind.get(kind)
        if technical_route is None:
            raise ProgrammeGate("unsupported-route", "The requested technical route is not registered")
        matching = self.matches(normalized) if technical_route != "sitemap-xml" else [
            s for s in self.programme["sources"] if s["host"] == parts.hostname
        ]
        if technical_route in {"html", "rendered-html"}:
            if not self.matches(normalized):
                raise ProgrammeGate("out-of-scope-path", "URL is outside the programme's candidate prefixes")
            if PurePosixPath(parts.path).suffix.lower() in {
                ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".gz", ".xml",
                ".json", ".jpg", ".png", ".mp4", ".exe",
            }:
                raise ProgrammeGate("unsupported-format", "A permitted, reviewed extraction adapter is still needed")
        hold_code, hold_message = self._hold(parts.hostname, matching)
        if require_rights:
            if self.rights_review is None and hold_code is not None:
                raise ProgrammeGate("source-access-hold", hold_message)
            self.assert_current_rights()
            route = self._route(parts.hostname, parts.path, technical_route, technical_route)
            if hold_code is not None and route["clearsAccessHold"] != hold_code:
                raise ProgrammeGate("source-access-hold", hold_message)
        elif hold_code is not None:
            raise ProgrammeGate("source-access-hold", hold_message)
        return normalized

    def metadata(self, url: str) -> dict:
        normalized = self.validate_url(url)
        ids, topics = self.tags(normalized)
        if self.rights_review["schemaVersion"] == 1:
            legacy = self.legacy_grants[urlsplit(normalized).hostname]
            return {
                "sourceIds": ids, "topics": topics,
                "rights": {
                    "status": "candidate-acquisition-permitted",
                    "reviewId": self.rights_review["reviewId"], "reviewHash": self.rights_hash,
                    "licenceUrl": legacy["licenceUrl"], "evidenceUrl": legacy["evidenceUrl"],
                },
            }
        return {
            "sourceIds": ids, "topics": topics,
            "rights": {
                "status": "candidate-acquisition-permitted",
                "reviewId": self.rights_review["reviewId"], "reviewHash": self.rights_hash,
                "approvalEvidenceHash": self.rights_review["approvalEvidence"]["sha256"],
                "approvalEvidenceReference": self.rights_review["approvalEvidence"]["reference"],
                "licenceUrl": None,
            },
        }

    def extraction_flags(self, url: str) -> list[str]:
        host = urlsplit(url).hostname
        observation = next(o for o in self.programme["accessObservations"] if o["host"] == host)
        flags = []
        if observation.get("accessState") == "freshness-review-required":
            flags.append("publisher-freshness-review-required")
        if host == "www.icbc.com":
            flags.append("icbc-rendering-review-required")
        return flags
