"""HTTPS GET only, DNS-pinned connections, robots gates, and finite budgets."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import http.client
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from .manifest import AcquisitionPaused, CheckpointError
from .policy import AcquisitionError, public_addresses, validate_url
from .robots import RobotsPolicy, parse_robots


USER_AGENT = "BCPilotIngest/0.1 (reviewed-public-source-pilot; no transactions)"


class TransientAcquisitionError(AcquisitionError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    checked_at: str = field(default_factory=utc_now)
    aliases: list[str] = field(default_factory=list)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self) -> None:
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def transport(url: str, *, limit: int, timeout: float, headers: dict[str, str]) -> Response:
    parts = urlsplit(url)
    # Validate all answers, and connect to the checked IP without a second DNS lookup.
    addresses = public_addresses(parts.hostname)
    connection = PinnedHTTPS(parts.hostname, addresses[0], timeout)
    deadline = time.monotonic() + timeout
    try:
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        connection.request("GET", target, headers=headers)
        response = connection.getresponse()
        received = {k.lower(): v for k, v in response.getheaders()}
        if received.get("content-encoding", "identity").lower() != "identity":
            raise AcquisitionError("Compressed response rejected; no decompression bombs")
        if int(received.get("content-length", "0")) > limit:
            raise AcquisitionError("Response exceeds configured size limit")
        pieces, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcquisitionError("Response exceeded total timeout")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            piece = response.read1(min(65536, limit - size + 1))
            if not piece:
                break
            size += len(piece)
            if size > limit:
                raise AcquisitionError("Response exceeds configured size limit")
            pieces.append(piece)
        return Response(url, response.status, received, b"".join(pieces))
    except (OSError, http.client.HTTPException, ValueError) as exc:
        if isinstance(exc, AcquisitionError):
            raise
        error = TransientAcquisitionError if isinstance(exc, (OSError, http.client.HTTPException)) else AcquisitionError
        raise error(f"HTTPS acquisition failed: {type(exc).__name__}") from exc
    finally:
        connection.close()


class Fetcher:
    def __init__(
        self, *, max_pages: int | None = 25, timeout: float = 25, max_bytes: int = 4_000_000,
        request=transport, clock=time.monotonic, sleep=time.sleep,
        request_controller=None, url_validator=validate_url,
    ):
        if max_pages is None and request_controller is None:
            raise AcquisitionError("A full-programme fetcher requires a durable request controller")
        if max_pages is not None and (type(max_pages) is not int or not 1 <= max_pages <= 25):
            raise AcquisitionError("This pilot permits at most 25 document requests per run")
        if not 0 < timeout <= 60 or not 1 <= max_bytes <= 8_000_000:
            raise AcquisitionError("Timeout/size must remain within pilot bounds")
        self.max_pages, self.timeout, self.max_bytes = max_pages, timeout, max_bytes
        self.request, self.clock, self.sleep = request, clock, sleep
        self.controller, self.url_validator = request_controller, url_validator
        self.last_request: dict[str, float] = {}
        self.policies: dict[str, RobotsPolicy | AcquisitionError] = {}
        self.robots_observations: dict[str, dict] = {}
        self.requests = 0
        self.total_requests = 0
        self.response_bytes = 0

    def _validate(self, url: str, *, robots=False, kind="document") -> str:
        if kind == "sitemap":
            return self.url_validator(url, kind=kind)
        if kind != "document":
            raise AcquisitionError("No fetch adapter is implemented for this reviewed technical route")
        return self.url_validator(url, robots=robots)

    def _get(self, url: str, *, robots: bool = False, headers=None, kind="document") -> Response:
        host = urlsplit(url).hostname
        policy = self.policies.get(host)
        delay = policy.delay if isinstance(policy, RobotsPolicy) else 1.0
        limit = 512_000 if robots else self.max_bytes
        if self.controller is not None:
            limit = self.controller.before_request(url, limit=limit, delay=delay, robots=robots)
        else:
            wait = delay - (self.clock() - self.last_request.get(host, float("-inf")))
            if wait > 0:
                self.sleep(wait)
            self.last_request[host] = self.clock()
        self.total_requests += 1
        if not robots:
            self.requests += 1
        try:
            response = self.request(
                url, limit=limit, timeout=self.timeout,
                headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity",
                         "Accept": "text/plain" if robots else (
                             "application/xml,text/xml" if kind == "sitemap" else "text/html"
                         ), **(headers or {})},
            )
            if response.url != url or len(response.body) > limit:
                raise AcquisitionError("Transport changed the checked URL or exceeded its response bound")
        except BaseException as exc:
            if self.controller is not None:
                self.controller.after_request(error=exc)
            raise
        self.response_bytes += len(response.body)
        if self.controller is not None:
            self.controller.after_request(response=response)
        return response

    def check_robots(self, host: str) -> RobotsPolicy:
        if host not in self.policies:
            url = self._validate(f"https://{host}/robots.txt", robots=True)
            observation = {"url": url, "checkedAt": utc_now()}
            try:
                response = self._get(url, robots=True)
                observation.update(
                    status=response.status, contentType=response.headers.get("content-type", ""),
                    contentHash=response.digest,
                )
                # A redirect is not a policy. Manual review avoids silently following a
                # login/maintenance redirect or applying another host's policy.
                if response.status != 200:
                    raise AcquisitionError("Robots endpoint did not return 200; fail closed")
                policy = parse_robots(response.body, response.headers.get("content-type", ""))
                self.policies[host] = policy
                observation["result"] = "parsed"
            except (AcquisitionPaused, CheckpointError):
                raise
            except AcquisitionError as exc:
                self.policies[host] = exc
                observation.update(result="blocked", reason=str(exc))
            self.robots_observations[host] = observation
        policy = self.policies[host]
        if isinstance(policy, AcquisitionError):
            raise policy
        return policy

    def validate_canonical(self, url: str, *, origin: str) -> str:
        normalized = self._validate(url)
        host = urlsplit(normalized).hostname
        if host != urlsplit(origin).hostname:
            raise AcquisitionError("Cross-host canonicals require separately verified aliases")
        if not self.check_robots(host).allows(normalized):
            raise AcquisitionError("Robots policy denies the canonical target")
        return normalized

    def fetch(self, url: str, *, etag: str | None = None, last_modified: str | None = None,
              kind: str = "document") -> Response:
        url = self._validate(url, kind=kind)
        origin_host = urlsplit(url).hostname
        aliases = []
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        for _ in range(5):
            url = self._validate(url, kind=kind)
            if urlsplit(url).hostname != origin_host:
                raise AcquisitionError("Cross-host redirects require separate publisher review")
            if url in aliases:
                raise AcquisitionError("Redirect loop")
            if not self.check_robots(origin_host).allows(url):
                raise AcquisitionError("Robots policy denies this document")
            if self.max_pages is not None and self.requests >= self.max_pages:
                raise AcquisitionError("Document request budget exhausted")
            response = self._get(url, headers=headers, kind=kind)
            if response.status not in (301, 302, 303, 307, 308):
                response.aliases = aliases
                return response
            if not response.headers.get("location"):
                raise AcquisitionError("Redirect without a location")
            aliases.append(url)
            url = urljoin(url, response.headers["location"])
            headers = {}
        raise AcquisitionError("Redirect limit exceeded")
