"""The application's stateful AG-UI protocol, without model or retry shortcuts."""

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field

import httpx

from bc_pyrit.contracts import CheckError, exact_origin
from bc_pyrit.ledger import Ledger

MAX_RESPONSE_BYTES = 262_144
NOTICE = "ai-conversation-v1"


@dataclass
class Turn:
    text: str
    summary: dict
    task: dict
    annotations: list = field(default_factory=list)


def decode_events(events: list[dict], *, thread: str, run: str, revision: int) -> Turn:
    if not events or events[0].get("type") != "RUN_STARTED":
        raise CheckError("MISSING_RUN_START")
    if events[0].get("threadId") != thread or events[0].get("runId") != run:
        raise CheckError("RUN_IDENTITY_MISMATCH")
    if any(item.get("type") == "RUN_ERROR" for item in events):
        raise CheckError("APPLICATION_RUN_ERROR")
    if events[-1].get("type") != "RUN_FINISHED":
        raise CheckError("MISSING_RUN_COMPLETION")
    if events[-1].get("threadId") != thread or events[-1].get("runId") != run:
        raise CheckError("RUN_IDENTITY_MISMATCH")
    texts = []
    open_messages = set()
    summary = task = None
    annotations = []
    for event in events:
        kind = event.get("type")
        if kind == "TEXT_MESSAGE_START":
            message_id = event.get("messageId")
            if not isinstance(message_id, str) or message_id in open_messages:
                raise CheckError("INVALID_MESSAGE_STREAM")
            if event.get("role") != "assistant":
                raise CheckError("INVALID_MESSAGE_STREAM")
            open_messages.add(message_id)
        elif kind == "TEXT_MESSAGE_CONTENT":
            if event.get("messageId") not in open_messages or not isinstance(
                event.get("delta"), str
            ):
                raise CheckError("INVALID_MESSAGE_STREAM")
            texts.append(event["delta"])
        elif kind == "TEXT_MESSAGE_END":
            if event.get("messageId") not in open_messages:
                raise CheckError("INVALID_MESSAGE_STREAM")
            open_messages.remove(event["messageId"])
        elif kind == "CUSTOM":
            if event.get("name") == "bc.conversation":
                summary = event.get("value")
            elif event.get("name") == "bc.task":
                task = event.get("value")
            elif event.get("name") == "annotations":
                value = event.get("value")
                if not isinstance(value, dict) or not isinstance(value.get("annotations"), list):
                    raise CheckError("INVALID_CITATIONS")
                annotations.extend(value["annotations"])
    text = "".join(texts)
    if open_messages or not text.strip():
        raise CheckError("INCOMPLETE_MESSAGE")
    if not isinstance(summary, dict) or not isinstance(task, dict):
        raise CheckError("MISSING_CONVERSATION_STATE")
    if (
        summary.get("threadId") != thread
        or summary.get("revision") != revision + 1
        or task.get("threadId") != thread
        or task.get("revision") != summary["revision"]
        or type(summary.get("shareContext")) is not bool
        or not isinstance(summary.get("facts"), list)
    ):
        raise CheckError("CONVERSATION_STATE_MISMATCH")
    return Turn(text, summary, task, annotations)


async def read_events(response: httpx.Response) -> list[dict]:
    events = []
    data = []
    content = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=8192):
        if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
            raise CheckError("RESPONSE_SIZE_LIMIT")
        content.extend(chunk)
    for line in content.decode("utf-8").splitlines():
        if not line:
            if data:
                try:
                    event = json.loads("\n".join(data))
                except ValueError, UnicodeError:
                    raise CheckError("INVALID_STREAM_JSON") from None
                if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                    raise CheckError("INVALID_STREAM_EVENT")
                events.append(event)
                data = []
            continue
        if line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        elif line.startswith(":") or line.startswith(("event:", "id:", "retry:")):
            continue
        else:
            raise CheckError("INVALID_STREAM_FRAME")
    if data:
        raise CheckError("UNTERMINATED_STREAM_FRAME")
    return events


class AppClient:
    def __init__(
        self,
        origin: str,
        ledger: Ledger,
        *,
        offline: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        interval: float | None = None,
        expected_commit: str | None = None,
        expected_deployment: str | None = None,
    ):
        self.origin = exact_origin(origin, local=offline)
        self.ledger = ledger
        self.offline = offline
        if not offline and (
            expected_commit is None or re.fullmatch(r"[a-f0-9]{40}", expected_commit) is None
        ):
            raise CheckError("DEPLOYMENT_ID_REQUIRED")
        self.expected_commit = expected_commit
        if not offline and (
            expected_deployment is None
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", expected_deployment) is None
        ):
            raise CheckError("DEPLOYMENT_ID_REQUIRED")
        self.expected_deployment = expected_deployment
        self.transport = transport
        default_interval = (0 if transport is not None else 2.1) if offline else 8
        self.interval = default_interval if interval is None else interval
        if self.interval < 0 or (not offline and self.interval < 8):
            raise CheckError("INVALID_REQUEST_INTERVAL")
        self.submissions = 0

    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.origin,
            follow_redirects=False,
            timeout=httpx.Timeout(125, connect=15),
            transport=self.transport,
            headers={"Origin": self.origin},
        )

    def verify_release(self, response: httpx.Response) -> None:
        identities = {
            "x-bc-api-release": self.expected_commit,
            "x-bc-web-release": self.expected_commit,
            "x-bc-api-deployment": self.expected_deployment,
            "x-bc-web-deployment": self.expected_deployment,
        }
        if any(
            value is not None and response.headers.get(name) != value
            for name, value in identities.items()
        ):
            self.ledger.stop("DEPLOYMENT_CHANGED")
            raise CheckError("DEPLOYMENT_CHANGED")

    async def preflight(self) -> dict:
        async with self.http() as client:
            try:
                response = await client.get(
                    "/api/capabilities", headers={"X-BC-Client-Version": "6"}
                )
                if response.status_code != 200:
                    raise CheckError("CAPABILITIES_UNAVAILABLE")
                self.verify_release(response)
                capabilities = response.json()
            except httpx.HTTPError, ValueError:
                raise CheckError("CAPABILITIES_UNAVAILABLE") from None
        required = (
            "aiConfigured",
            "generalChatConfigured",
            "conversationAvailable",
            "conversationAgentReady",
            "taskAssistanceAvailable",
            "retrievalReady",
        )
        if (
            not isinstance(capabilities, dict)
            or capabilities.get("mode") != "foundry"
            or any(capabilities.get(key) is not True for key in required)
            or 5 not in capabilities.get("requestVersions", [])
            or 6 in capabilities.get("requestVersions", [])
            or capabilities.get("localEvidenceEvaluation") is not False
            or capabilities.get("transactionsEnabled") is not False
            or capabilities.get("webIqEnabled") is not False
        ):
            raise CheckError("UNSUPPORTED_CAPABILITIES")
        health = capabilities.get("sourceHealth")
        if not isinstance(health, dict) or health.get("status") != "ready":
            raise CheckError("SOURCES_NOT_READY")
        return capabilities

    async def admit(self) -> None:
        last_request = self.ledger.state()["lastAppAt"]
        delay = max(0, self.interval - (time.time() - last_request))
        if delay >= self.ledger.remaining_seconds():
            self.ledger.stop("WALL_BUDGET_EXHAUSTED")
            raise CheckError("WALL_BUDGET_EXHAUSTED")
        await asyncio.sleep(delay)
        self.ledger.charge("app")
        self.submissions += 1

    def session(self) -> AppSession:
        return AppSession(self)


class AppSession:
    def __init__(self, app: AppClient):
        self.app = app
        self.client = app.http()
        self.page = str(uuid.uuid4())
        self.thread = str(uuid.uuid4())
        self.summary: dict | None = None
        self.task: dict | None = None
        self.active_run: str | None = None
        self.turns: list[Turn] = []
        self.closed = False

    @property
    def headers(self) -> dict[str, str]:
        return {"x-bc-conversation-page": self.page}

    async def send(self, text: str) -> Turn:
        if self.closed or not text.strip() or len(text) > 4000:
            raise CheckError("INVALID_PROMPT")
        revision = self.summary["revision"] if self.summary else 0
        command = {
            "action": "respond",
            "revision": revision,
            "noticeVersion": NOTICE,
            "shareContext": self.summary["shareContext"] if self.summary else False,
        }
        if self.summary and self.summary.get("question"):
            command["questionId"] = self.summary["question"]["id"]
        run = str(uuid.uuid4())
        body = {
            "threadId": self.thread,
            "runId": run,
            "state": {},
            "context": [],
            "tools": [],
            "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": text}],
            "forwardedProps": {"bc": {"version": 5, "mode": "general", "conversation": command}},
        }
        await self.app.admit()
        self.active_run = run
        try:
            async with (
                asyncio.timeout(min(130, self.app.ledger.remaining_seconds())),
                self.client.stream(
                    "POST", "/api/agent", json=body, headers=self.headers
                ) as response,
            ):
                if response.status_code != 200:
                    self.active_run = None
                    if response.status_code == 429:
                        self.app.ledger.stop("RATE_LIMITED")
                        raise CheckError("RATE_LIMITED")
                    if response.status_code >= 500:
                        self.app.ledger.stop("APP_UNAVAILABLE")
                    raise CheckError("APP_REQUEST_REJECTED")
                content_type = response.headers.get("content-type", "").split(";")[0]
                self.app.verify_release(response)
                if content_type != "text/event-stream":
                    raise CheckError("INVALID_STREAM_CONTENT_TYPE")
                events = await read_events(response)
                turn = decode_events(events, thread=self.thread, run=run, revision=revision)
        except httpx.HTTPError, TimeoutError, UnicodeError:
            self.app.ledger.stop("APP_TRANSPORT_FAILED")
            raise CheckError("APP_TRANSPORT_FAILED") from None
        self.active_run = None
        self.summary, self.task = turn.summary, turn.task
        self.turns.append(turn)
        return turn

    async def sharing(self, enabled: bool) -> None:
        if not self.summary:
            raise CheckError("MISSING_CONVERSATION_STATE")
        revision = self.summary["revision"]
        try:
            response = await self.client.post(
                "/api/conversation/control",
                headers=self.headers,
                json={
                    "id": str(uuid.uuid4()),
                    "revision": revision,
                    "noticeVersion": NOTICE,
                    "action": "sharing",
                    "shareContext": enabled,
                },
            )
            value = response.json()
        except httpx.HTTPError, ValueError:
            raise CheckError("SHARING_CONTROL_FAILED") from None
        summary = value.get("summary") if isinstance(value, dict) else None
        if (
            response.status_code != 200
            or not isinstance(summary, dict)
            or summary.get("threadId") != self.thread
            or summary.get("revision") != revision + 1
            or summary.get("shareContext") is not enabled
        ):
            raise CheckError("SHARING_CONTROL_FAILED")
        self.summary, self.task = summary, value.get("task")

    async def assert_isolation(self) -> None:
        other = self.app.session()
        try:
            await other.send("Help me prepare to renew my B.C. driver's licence.")
            response = await other.client.get(
                "/api/conversation",
                headers={"x-bc-conversation-page": self.page},
            )
            if response.status_code == 200 and response.json() is None:
                return
            if response.status_code in (403, 404, 409):
                return
            raise CheckError("SESSION_ISOLATION_FAILED")
        except httpx.HTTPError, ValueError:
            raise CheckError("SESSION_PROBE_FAILED") from None
        finally:
            await other.close()

    async def close(self) -> None:
        if self.closed:
            return
        failure = False
        try:
            if self.active_run:
                response = await self.client.post(
                    f"/api/runs/{self.active_run}/cancel", headers=self.headers
                )
                if response.status_code != 200:
                    failure = True
            if self.client.cookies:
                response = await self.client.delete("/api/conversation", headers=self.headers)
                if response.status_code != 204:
                    failure = True
        except httpx.HTTPError:
            failure = True
        finally:
            self.closed = True
            await self.client.aclose()
        if failure:
            self.app.ledger.stop("CLEANUP_FAILED")
            raise CheckError("CLEANUP_FAILED")
