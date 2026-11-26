import json
import time

import httpx
import pytest

from bc_pyrit.client import MAX_RESPONSE_BYTES, AppClient
from bc_pyrit.contracts import CheckError


class Fragments(httpx.AsyncByteStream):
    def __init__(self, value: bytes, size=7):
        self.value = value
        self.size = size
        self.consumed = 0

    async def __aiter__(self):
        for offset in range(0, len(self.value), self.size):
            part = self.value[offset : offset + self.size]
            self.consumed += len(part)
            yield part


class App:
    def __init__(self, *, failure=None, leak=False, texts=None):
        self.requests = []
        self.pages = {}
        self.failure = failure
        self.leak = leak
        self.stream = None
        self.texts = texts
        self.turn_count = 0

    async def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        page = request.headers.get("x-bc-conversation-page")
        if path.endswith("/cancel"):
            return httpx.Response(200, json={"status": "cancelled"})
        if path == "/api/conversation" and request.method == "DELETE":
            return httpx.Response(204)
        if path == "/api/conversation" and request.method == "GET":
            return httpx.Response(
                200,
                content=json.dumps(self.pages.get(page) if self.leak else None),
                headers={"Content-Type": "application/json"},
            )
        if path == "/api/conversation/control":
            body = json.loads(request.content)
            summary = dict(self.pages[page])
            summary["revision"] += 1
            summary["shareContext"] = body["shareContext"]
            self.pages[page] = summary
            return httpx.Response(200, json={"summary": summary, "task": {}})
        self.turn_count += 1
        body = json.loads(request.content)
        command = body["forwardedProps"]["bc"]["conversation"]
        summary = {
            "threadId": body["threadId"],
            "revision": command["revision"] + 1,
            "shareContext": command["shareContext"],
            "facts": [],
            "question": {"id": "server-question"},
            "goal": "licence-renewal",
        }
        self.pages[page] = summary
        task = {"threadId": body["threadId"], "revision": summary["revision"], "task": None}
        events = [
            {"type": "RUN_STARTED", "runId": body["runId"], "threadId": body["threadId"]},
            {"type": "TEXT_MESSAGE_START", "messageId": "reply", "role": "assistant"},
            {
                "type": "TEXT_MESSAGE_CONTENT",
                "messageId": "reply",
                "delta": (
                    self.texts[self.turn_count - 1] if self.texts else "Safe pr\u00e9paration."
                ),
            },
            {"type": "TEXT_MESSAGE_END", "messageId": "reply"},
            {"type": "CUSTOM", "name": "bc.conversation", "value": summary},
            {"type": "CUSTOM", "name": "bc.task", "value": task},
            {"type": "RUN_FINISHED", "runId": body["runId"], "threadId": body["threadId"]},
        ]
        if self.failure == "missing-terminal":
            events.pop()
        if self.failure == "late-error":
            events.insert(-1, {"type": "RUN_ERROR", "message": "Do not publish this provider text"})
        if self.failure == "wrong-revision":
            task["revision"] += 1
        content = "".join(
            "data: " + json.dumps(event, ensure_ascii=False) + "\r\n\r\n" for event in events
        ).encode()
        if self.failure == "oversized":
            content = b"data: " + b"x" * (MAX_RESPONSE_BYTES * 8)
        self.stream = Fragments(content, size=8192 if self.failure == "oversized" else 7)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Set-Cookie": "bc_pilot_session=synthetic-cookie; HttpOnly; Path=/",
            },
            stream=self.stream,
        )


def client(ledger, app):
    return AppClient(
        "http://127.0.0.1:8123",
        ledger,
        offline=True,
        transport=httpx.MockTransport(app),
    )


async def test_fragmented_stream_keeps_cookie_question_and_server_revision(ledger):
    app = App()
    session = client(ledger, app).session()
    first = await session.send("Help with renewal")
    second = await session.send("Yes")
    assert first.text == "Safe pr\u00e9paration."
    assert second.summary["revision"] == 2
    requests = [item for item in app.requests if item.url.path == "/api/agent"]
    command = json.loads(requests[1].content)["forwardedProps"]["bc"]["conversation"]
    assert command["questionId"] == "server-question"
    assert command["revision"] == 1
    assert requests[1].headers["cookie"] == "bc_pilot_session=synthetic-cookie"
    assert (
        requests[0].headers["x-bc-conversation-page"]
        == requests[1].headers["x-bc-conversation-page"]
    )
    await session.close()
    assert app.requests[-1].method == "DELETE"


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("missing-terminal", "MISSING_RUN_COMPLETION"),
        ("late-error", "APPLICATION_RUN_ERROR"),
        ("wrong-revision", "CONVERSATION_STATE_MISMATCH"),
        ("oversized", "RESPONSE_SIZE_LIMIT"),
    ],
)
async def test_invalid_or_incomplete_stream_is_not_a_pass_and_cancels_owned_run(
    ledger,
    failure,
    code,
):
    app = App(failure=failure)
    session = client(ledger, app).session()
    with pytest.raises(CheckError, match=code):
        await session.send("Help with renewal")
    await session.close()
    assert any(item.url.path.endswith("/cancel") for item in app.requests)
    assert app.requests[-1].method == "DELETE"
    assert ledger.report()["usage"]["app"]["calls"] == 1
    if failure == "oversized":
        assert app.stream.consumed <= MAX_RESPONSE_BYTES + 8192


async def test_sharing_controls_advance_revision_without_an_extra_chat_turn(ledger):
    app = App()
    session = client(ledger, app).session()
    await session.send("Help with renewal")
    await session.sharing(True)
    await session.sharing(False)
    assert session.summary["revision"] == 3
    assert session.summary["shareContext"] is False
    assert ledger.report()["usage"]["app"]["calls"] == 1
    await session.close()


@pytest.mark.parametrize("leak", [False, True])
async def test_foreign_page_probe_checks_state_isolation_and_cleans_both_sessions(ledger, leak):
    app = App(leak=leak)
    session = client(ledger, app).session()
    await session.send("Help with renewal")
    if leak:
        with pytest.raises(CheckError, match="SESSION_ISOLATION_FAILED"):
            await session.assert_isolation()
    else:
        await session.assert_isolation()
    await session.close()
    assert sum(item.method == "DELETE" for item in app.requests) == 2
    assert ledger.report()["usage"]["app"]["calls"] == 2


async def test_redirect_is_never_followed(ledger):
    seen = []

    async def redirect(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://unapproved.invalid/"})

    session = client(ledger, redirect).session()
    with pytest.raises(CheckError, match="APP_REQUEST_REJECTED"):
        await session.send("Help with renewal")
    await session.close()
    assert seen == ["http://127.0.0.1:8123/api/agent"]


async def test_failed_cleanup_stops_the_whole_run(ledger):
    app = App()

    async def handler(request):
        if request.method == "DELETE":
            return httpx.Response(503)
        return await app(request)

    session = client(ledger, handler).session()
    await session.send("Help with renewal")
    with pytest.raises(CheckError, match="CLEANUP_FAILED"):
        await session.close()
    with pytest.raises(CheckError, match="CLEANUP_FAILED"):
        ledger.charge("app")


async def test_request_pacing_survives_a_new_actions_step(ledger, monkeypatch):
    clock = [ledger.state()["started"] + 1]
    monkeypatch.setattr(time, "time", lambda: clock[0])

    async def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr("bc_pyrit.client.asyncio.sleep", sleep)
    first = AppClient("http://127.0.0.1:8123", ledger, offline=True, interval=8)
    await first.admit()
    before = ledger.state()["lastAppAt"]
    second = AppClient("http://127.0.0.1:8123", ledger, offline=True, interval=8)
    await second.admit()
    assert ledger.state()["lastAppAt"] - before == 8
    assert ledger.report()["usage"]["app"]["calls"] == 2
