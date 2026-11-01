"""Bounded, process-local controls for a single-worker local preview."""

import asyncio
import re
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie
from typing import TYPE_CHECKING

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bc_api.authentication import ApiAuthenticator
from bc_api.config import Settings, is_loopback_host
from bc_api.errors import ApiError

if TYPE_CHECKING:
    from bc_api.controls import SharedControls

SESSION_COOKIE = "bc_pilot_session"


@dataclass
class Session:
    token: str
    touched: float


class PreviewControls:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions: dict[str, Session] = {}
        self.requests: dict[str, deque[float]] = {}

    def check_rate(self, key: str, limit: int) -> None:
        now = time.monotonic()
        self.requests = {key: times for key, times in self.requests.items() if times[-1] > now - 60}
        if key not in self.requests and len(self.requests) >= 4096:
            raise ApiError(
                429, "RATE_LIMITED", "The local preview is busy. Please try again later."
            )
        window = self.requests.setdefault(key, deque())
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= limit:
            raise ApiError(429, "RATE_LIMITED", "Too many requests. Please wait a minute.")
        window.append(now)

    def session(self, token: str | None, *, create: bool = True) -> tuple[Session, bool]:
        now = time.monotonic()
        self.sessions = {
            key: session for key, session in self.sessions.items() if session.touched > now - 3600
        }
        if token and token in self.sessions:
            self.sessions[token].touched = now
            return self.sessions[token], False
        if not create:
            raise ApiError(404, "RUN_NOT_FOUND", "No cancellable run was found for this session.")
        if len(self.sessions) >= self.settings.api_max_sessions:
            raise ApiError(
                429, "SESSION_LIMIT", "The local preview is busy. Please try again later."
            )
        session = Session(secrets.token_urlsafe(32), now)
        self.sessions[session.token] = session
        return session, True


@dataclass
class Run:
    run_id: str
    thread_id: str
    owner: str
    created: float = field(default_factory=time.monotonic)
    cancellation: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = "running"
    usage_tokens: int | None = None
    usage_valid: bool = True
    control_failure: ApiError | None = None
    watch: Callable[[], Awaitable[None]] | None = None
    finish: Callable[[str, int | None], Awaitable[str]] | None = None
    finalized: bool = False
    trace_ref: str = field(default_factory=lambda: secrets.token_hex(16))
    first_content_at: float | None = None
    first_response_at: float | None = None
    response_kind: str | None = None
    response_origin: str | None = None
    phase_times: dict[str, float] = field(default_factory=dict)


class RunRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runs: dict[str, Run] = {}

    def reserve(self, run_id: str, thread_id: str, owner: str) -> Run:
        cutoff = time.monotonic() - 600
        self.runs = {
            key: run
            for key, run in self.runs.items()
            if run.status == "running" or run.created > cutoff
        }
        if run_id in self.runs:
            raise ApiError(409, "RUN_CONFLICT", "Use a new run ID for each request.")
        running = [run for run in self.runs.values() if run.status == "running"]
        if any(run.owner == owner for run in running):
            raise ApiError(
                409, "SESSION_BUSY", "Stop the current response before starting another."
            )
        if len(running) >= self.settings.api_max_concurrent_runs or len(self.runs) >= 2048:
            raise ApiError(429, "RUN_LIMIT", "The local preview is busy. Please try again shortly.")
        run = Run(run_id, thread_id, owner)
        self.runs[run_id] = run
        return run

    def cancel(self, run_id: str, owner: str) -> Run:
        run = self.runs.get(run_id)
        if run is None or not secrets.compare_digest(run.owner, owner):
            raise ApiError(404, "RUN_NOT_FOUND", "No cancellable run was found for this session.")
        if run.status in ("finished", "failed"):
            raise ApiError(409, "RUN_FINISHED", "That response has already ended.")
        run.cancellation.set()
        return run


class SecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        controls: PreviewControls,
        shared: SharedControls | None = None,
        authenticator: ApiAuthenticator | None = None,
    ) -> None:
        self.app = app
        self.settings = settings
        self.controls = controls
        self.shared = shared
        self.authenticator = authenticator or ApiAuthenticator(settings)
        self.origins = frozenset(settings.origins)
        self.hosts = frozenset(host.strip() for host in settings.api_allowed_hosts.split(","))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        try:
            if self.settings.local_evidence_evaluation_enabled:
                endpoints = (scope.get("client"), scope.get("server"))
                if (
                    any(not endpoint or not is_loopback_host(endpoint[0]) for endpoint in endpoints)
                    or any(
                        headers.get(name)
                        for name in (
                            "forwarded",
                            "x-forwarded-for",
                            "x-forwarded-host",
                        )
                    )
                    or (
                        scope["path"].startswith("/api/")
                        and headers.get("x-bc-evaluation-scope") != "local-noncommercial"
                    )
                ):
                    raise ApiError(
                        403,
                        "LOCAL_EVALUATION_ONLY",
                        "These sources are available only through the loopback evaluation app.",
                    )
            host = headers.get("host", "").split("]")[0].lstrip("[")
            if ":" in host and not headers.get("host", "").startswith("["):
                host = host.split(":", 1)[0]
            if host.lower() not in self.hosts:
                raise ApiError(400, "INVALID_HOST", "The API host is not configured.")
            origin = headers.get("origin")
            if origin is not None and origin not in self.origins:
                raise ApiError(403, "ORIGIN_DENIED", "This origin is not allowed to use the API.")
            if scope["method"] not in ("GET", "HEAD", "OPTIONS") and origin not in self.origins:
                raise ApiError(
                    403, "ORIGIN_REQUIRED", "Use the assistant from its configured website."
                )
            path = scope["path"]
            if not path.startswith("/api/"):
                await self.app(scope, receive, send)
                return
            if (
                self.settings.app_env == "production"
                and not self.settings.production_controls_ready
            ):
                raise ApiError(
                    503,
                    "PUBLIC_CONTROLS_REQUIRED",
                    "The public pilot's service authentication and request controls are not ready.",
                )
            await self.authenticator.authorize(headers)
            ip = (scope.get("client") or ("unknown", 0))[0]
            if self.settings.api_auth_audience:
                client_key = headers.get("x-bc-client", "")
                if not re.fullmatch(r"[a-f0-9]{64}", client_key):
                    raise ApiError(
                        403, "CLIENT_CONTEXT_REQUIRED", "Trusted request context is missing."
                    )
                ip = client_key

            async def rate(key: str, limit: int) -> None:
                if self.shared is not None:
                    await self.shared.check_rate(key, limit)
                else:
                    self.controls.check_rate(key, limit)

            if path.startswith("/api/") and not path.endswith("/cancel"):
                await rate("http:" + ip, self.settings.api_requests_per_minute)
            if path.endswith("/cancel"):
                await rate("cancel:" + ip, 60)
            if path == "/api/agent" and scope["method"] == "POST":
                await rate("agent:" + ip, self.settings.api_agent_runs_per_minute)
            length = headers.get("content-length")
            if length is not None:
                try:
                    size = int(length)
                except ValueError:
                    raise ApiError(400, "INVALID_LENGTH", "Invalid request length.") from None
                if size < 0 or size > self.settings.api_max_request_bytes:
                    raise ApiError(413, "REQUEST_TOO_LARGE", "The request is too large.")
            if headers.get("content-encoding", "identity").lower() != "identity":
                raise ApiError(
                    415, "ENCODING_UNSUPPORTED", "Compressed request bodies are not supported."
                )
            body: list[bytes] = []
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > self.settings.api_max_request_bytes:
                    raise ApiError(413, "REQUEST_TOO_LARGE", "The request is too large.")
                body.append(chunk)
                if not message.get("more_body", False):
                    break
            public_metadata = scope["method"] in ("GET", "HEAD", "OPTIONS") and (
                path
                in (
                    "/api/catalog",
                    "/api/capabilities",
                    "/api/demo/personas",
                    "/api/locations",
                )
                or path.startswith("/api/journeys/")
            )
            session = None
            fresh = False
            scope.setdefault("state", {})
            # A late metadata response must not replace the cookie owning an already-started run.
            if not public_metadata:
                cookie = SimpleCookie()
                try:
                    cookie.load(headers.get("cookie", ""))
                except CookieError:
                    cookie = SimpleCookie()
                morsel = cookie.get(SESSION_COOKIE)
                if self.shared is not None:
                    session, fresh = await self.shared.session(
                        morsel.value if morsel else None, create=not path.endswith("/cancel")
                    )
                else:
                    session, fresh = self.controls.session(
                        morsel.value if morsel else None, create=not path.endswith("/cancel")
                    )
                scope["state"]["session"] = session
            scope["state"]["client_ip"] = ip
        except ApiError as exc:
            response = JSONResponse(exc.payload(), status_code=exc.status)
            response.headers["Cache-Control"] = "no-store"
            if exc.status == 429:
                response.headers["Retry-After"] = "60"
            await response(scope, receive, send)
            return

        delivered = False

        async def buffered_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(body), "more_body": False}
            return await receive()

        async def guarded_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                output_headers = MutableHeaders(scope=message)
                output_headers["Cache-Control"] = "no-store"
                output_headers["X-Content-Type-Options"] = "nosniff"
                output_headers["Referrer-Policy"] = "no-referrer"
                if fresh and session is not None and path.startswith("/api/"):
                    cookie_response = JSONResponse(None)
                    cookie_response.set_cookie(
                        SESSION_COOKIE,
                        session.token,
                        max_age=3600,
                        httponly=True,
                        secure=self.settings.app_env == "production",
                        samesite="strict",
                        path="/api",
                    )
                    output_headers.append("Set-Cookie", cookie_response.headers["set-cookie"])
            await send(message)

        await self.app(scope, buffered_receive, guarded_send)
