"""URL policy, not an arbitrary fetching facility."""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import unquote, urlsplit

OFFICIAL_DOMAINS = frozenset(
    {"gov.bc.ca", "icbc.com", "bchousing.org", "workbc.ca", "healthlinkbc.ca"}
)
PUBLIC_RESEARCH_HOSTS = frozenset(
    {
        "www2.gov.bc.ca",
        "www.icbc.com",
        "www.bchousing.org",
        "www.healthlinkbc.ca",
    }
)


def https_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("A bounded HTTPS URL is required.")
    if re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValueError("URL contains unsafe characters.")
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
        if re.search(r"[\x00-\x1f\x7f\\]", decoded):
            raise ValueError("URL contains encoded unsafe characters.")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.isascii()
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or "%" in parsed.netloc
            or parsed.hostname.endswith(".")
        ):
            raise ValueError("Only public HTTPS URLs without credentials are allowed.")
    except ValueError:
        raise ValueError("Only public HTTPS URLs without credentials are allowed.") from None
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return value
    else:
        raise ValueError("IP address URLs are not allowed.")


def official_url(value: str) -> str:
    https_url(value)
    host = urlsplit(value).hostname or ""
    if not any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS):
        raise ValueError("The destination must be an official BC publisher.")
    return value


def azure_endpoint(value: str, *, service: str) -> str:
    https_url(value)
    parsed = urlsplit(value)
    suffixes = {
        "foundry": (".services.ai.azure.com",),
        "search": (".search.windows.net",),
        "embedding": (".openai.azure.com", ".services.ai.azure.com"),
    }[service]
    if not (parsed.hostname or "").endswith(suffixes) or parsed.query or parsed.fragment:
        raise ValueError("Use the configured Azure service endpoint.")
    if service == "foundry":
        if not re.fullmatch(r"/api/projects/[A-Za-z0-9._-]+/?", parsed.path):
            raise ValueError("A Foundry project endpoint is required.")
    elif parsed.path not in ("", "/"):
        raise ValueError("Use an Azure service root endpoint.")
    return value.rstrip("/")


async def resolve_addresses(host: str) -> list[str]:
    records = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    return list({record[4][0] for record in records})


async def validate_public_destination(
    url: str,
    *,
    redirect_chain: tuple[str, ...] = (),
    resolver: Callable[[str], Awaitable[list[str]]] = resolve_addresses,
) -> str:
    """Future egress preflight; a transport must also pin the verified address.

    Not called by this pilot. Validate every hop, not merely the initial host.
    DNS validation alone cannot prevent DNS rebinding between check and connect.
    """
    if len(redirect_chain) > 3:
        raise ValueError("Too many redirects.")
    for target in (*redirect_chain, url):
        https_url(target)
        parsed = urlsplit(target)
        if parsed.hostname not in PUBLIC_RESEARCH_HOSTS or parsed.query or parsed.fragment:
            raise ValueError("Public research destination is outside the approved scope.")
        addresses = await resolver(parsed.hostname)
        if not addresses or any(
            not ipaddress.ip_address(address).is_global for address in addresses
        ):
            raise ValueError("Non-public addresses are not permitted.")
    return url
