"""An intentionally narrow publisher/path boundary, independent of robots."""

from dataclasses import dataclass
import ipaddress
import re
import socket
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit


class AcquisitionError(ValueError):
    pass


SERVICE_BC = (
    "/gov/content/governments/organizational-structure/ministries-organizations/"
    "ministries/citizens-services/servicebc"
)


@dataclass(frozen=True)
class Publisher:
    name: str
    prefixes: tuple[str, ...]
    exact: tuple[str, ...] = ()
    hold: str | None = None


PUBLISHERS = {
    "www2.gov.bc.ca": Publisher(
        "Government of British Columbia",
        (
            SERVICE_BC,
            "/gov/content/housing-tenancy",
            "/gov/content/health",
            "/gov/content/family-social-supports",
            "/gov/content/employment-business",
            "/gov/content/taxes",
        ),
        ("/gov/content", "/gov/content/home"),
    ),
    "www.bchousing.org": Publisher(
        "BC Housing", ("/housing-assistance/rental-assistance-programs",), ("/",)
    ),
    "www.icbc.com": Publisher(
        "ICBC", ("/driver-licensing",), ("/",),
        "Hold: ICBC Terms section 16 prohibits non-ICBC automation, bulk collection and reuse; "
        "explicit publisher permission is required."
    ),
    "www.healthlinkbc.ca": Publisher(
        "HealthLink BC", ("/find-care", "/health-services"), ("/",)
    ),
    "www.workbc.ca": Publisher(
        "WorkBC", (), ("/",), "Hold: invalid robots policy in discovery; publisher review required."
    ),
    "www.bclaws.gov.bc.ca": Publisher(
        "BC Laws", (), (), "Hold: general crawler denied; approved CiviX feed/licence pending."
    ),
}

PUBLICATION_HOLDS = {
    "www.bchousing.org": "Publisher freshness pause has not been cleared with reviewed evidence",
    "www.icbc.com": "Complete dynamic/rendered extraction has not been verified",
}

SENSITIVE_PATH = re.compile(
    r"(?:^|/)(?:account|accounts|login|log-in|signin|sign-in|register|registration|"
    r"checkout|submit|payment|upload|uploads|myaccount|auth)(?:/|$)", re.I
)


def canonicalize(url: str) -> str:
    if not isinstance(url, str) or any(ord(c) < 32 for c in url) or "\\" in url:
        raise AcquisitionError("Invalid URL characters")
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as exc:
        raise AcquisitionError("Invalid URL port") from exc
    if parts.scheme.lower() != "https" or not parts.hostname or port not in (None, 443):
        raise AcquisitionError("Only standard-port HTTPS publisher URLs are permitted")
    if parts.username is not None or parts.password is not None:
        raise AcquisitionError("URL credentials are not permitted")
    host = parts.hostname.lower()
    path = parts.path or "/"
    decoded = unquote(path)
    if "%" in decoded or "\\" in decoded or any(ord(c) < 32 for c in decoded):
        raise AcquisitionError("Ambiguous or nested URL encoding")
    if any(p in (".", "..") for p in decoded.split("/")) or "//" in decoded:
        raise AcquisitionError("Ambiguous path traversal")
    if any(not k.lower().startswith("utm_") for k, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise AcquisitionError("Non-tracking query parameters are outside the public-page scope")
    path = quote(decoded, safe="/-._~!$&'()*+,;=:@").rstrip("/") or "/"
    return urlunsplit(("https", host, path, "", ""))


def validate_url(url: str, *, robots: bool = False) -> str:
    normalized = canonicalize(url)
    parts = urlsplit(normalized)
    publisher = PUBLISHERS.get(parts.hostname)
    if publisher is None:
        raise AcquisitionError("Publisher host is not allowlisted")
    if robots:
        if parts.path != "/robots.txt":
            raise AcquisitionError("Robots checks may only request /robots.txt")
        return normalized
    if publisher.hold:
        raise AcquisitionError(publisher.hold)
    if SENSITIVE_PATH.search(parts.path):
        raise AcquisitionError("Account/transaction/upload paths are out of scope")
    if parts.path not in publisher.exact and not any(
        parts.path == p or parts.path.startswith(p + "/") for p in publisher.prefixes
    ):
        raise AcquisitionError("Publisher path is not allowlisted")
    return normalized


def public_addresses(host: str) -> list[str]:
    try:
        addresses = list(dict.fromkeys(
            item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ))
    except OSError as exc:
        raise AcquisitionError("Publisher DNS lookup failed") from exc
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise AcquisitionError("DNS returned a private, loopback, reserved, or missing address")
    return addresses
