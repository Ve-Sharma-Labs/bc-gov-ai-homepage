import asyncio
import importlib.util
import json
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from pyrit.backend.services.target_service import TargetService
from pyrit.memory import CentralMemory, SQLiteMemory
from pyrit.models import Message
from pyrit.prompt_normalizer import PromptNormalizer
from pyrit.registry import TargetRegistry

from bc_pyrit.auth import AzureCliAuth
from bc_pyrit.client import AppClient
from bc_pyrit.contracts import CheckError
from bc_pyrit.ledger import Ledger
from bc_pyrit.manual import ManualAppTarget, ManualSettings, create_manual_target, load_settings

COMMIT = "a" * 40
DEPLOYMENT = "staging-fixture"


def configuration(**overrides):
    return {
        "version": 1,
        "origin": "https://staging.example",
        "release_commit": COMMIT,
        "deployment_id": DEPLOYMENT,
        "live_use_approved": True,
        "request_limit": 20,
        "wall_seconds": 300,
        **overrides,
    }


class FixtureApp:
    def __init__(self):
        self.sent = []
        self.controls = []
        self.release = COMMIT
        self.error = None
        self.block = False
        self.started = asyncio.Event()
        self.closed_stream = False
        self.cancel_count = 0

    def __call__(self, request):
        headers = {
            "X-BC-API-Release": self.release,
            "X-BC-Web-Release": COMMIT,
            "X-BC-API-Deployment": DEPLOYMENT,
            "X-BC-Web-Deployment": DEPLOYMENT,
        }
        if request.url.path == "/api/capabilities":
            return httpx.Response(200, headers=headers, json={
                "mode": "foundry", "aiConfigured": True, "generalChatConfigured": True,
                "conversationAvailable": True, "conversationAgentReady": True,
                "taskAssistanceAvailable": True, "retrievalReady": True,
                "requestVersions": [5], "localEvidenceEvaluation": False,
                "transactionsEnabled": False, "webIqEnabled": False,
                "sourceHealth": {"status": "ready"},
            })
        if request.url.path.endswith("/cancel"):
            self.controls.append((request.method, request.url.path, dict(request.headers)))
            self.cancel_count += 1
            return httpx.Response(202 if self.cancel_count == 1 else 200, json={})
        if request.method == "DELETE":
            self.controls.append((request.method, request.url.path, dict(request.headers)))
            return httpx.Response(204)
        assert request.url.path == "/api/agent"
        body = json.loads(request.content)
        self.sent.append((body, dict(request.headers)))
        assert request.headers["origin"] in ("http://127.0.0.1:8012", "https://staging.example")
        headers.update({
            "Content-Type": "text/event-stream",
            "Set-Cookie": f"bc_pilot_session={uuid.uuid4()}; Path=/api; HttpOnly",
        })
        thread, run = body["threadId"], body["runId"]
        command = body["forwardedProps"]["bc"]["conversation"]
        assert command["shareContext"] is False
        summary = {
            "threadId": thread, "revision": command["revision"] + 1,
            "shareContext": False, "facts": [], "question": {"id": "server-question"},
        }
        events = [
            {"type": "RUN_STARTED", "threadId": thread, "runId": run},
            {"type": "TEXT_MESSAGE_START", "messageId": "answer", "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "answer", "delta": "Fixture reply."},
            {"type": "TEXT_MESSAGE_END", "messageId": "answer"},
            {"type": "CUSTOM", "name": "bc.conversation", "value": summary},
            {"type": "CUSTOM", "name": "bc.task", "value": {
                "threadId": thread, "revision": summary["revision"],
            }},
            {"type": "RUN_FINISHED", "threadId": thread, "runId": run},
        ]
        if self.error == "truncated":
            events.pop()
        elif self.error == "run":
            events[-1] = {"type": "RUN_ERROR", "message": "private provider detail"}
        payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()
        if not self.block:
            return httpx.Response(200, headers=headers, content=payload)
        fixture = self

        class BlockedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                fixture.started.set()
                yield payload[:20]
                await asyncio.Event().wait()

            async def aclose(self):
                fixture.closed_stream = True

        return httpx.Response(200, headers=headers, stream=BlockedStream())


@pytest.fixture
async def memory():
    instance = SQLiteMemory.__new__(SQLiteMemory)
    instance.__init__(db_path=":memory:", silent=True)
    with patch.object(CentralMemory, "get_memory_instance", return_value=instance):
        yield instance
    await instance.dispose_engine_async()


def make_target(tmp_path, fixture, *, requests=20):
    settings = ManualSettings.model_validate(configuration(request_limit=requests))
    ledger = Ledger.open_manual(
        tmp_path / "manual.sqlite", limits=settings.limits(), identity={"fixture": True}
    )
    app = AppClient(
        "http://127.0.0.1:8012", ledger, offline=True, interval=0,
        transport=httpx.MockTransport(fixture),
        expected_commit=COMMIT, expected_deployment=DEPLOYMENT,
    )
    return ManualAppTarget(app=app), ledger


async def send(target, conversation, text):
    return await PromptNormalizer().send_prompt_async(
        message=Message.from_prompt(prompt=text, role="user"),
        target=target, conversation_id=conversation,
    )


@contextmanager
def target_failure(code):
    with pytest.raises(Exception, match="Error sending prompt with conversation ID") as caught:
        yield caught
    assert isinstance(caught.value.__cause__, CheckError)
    assert caught.value.__cause__.code == code


async def test_manual_chat_uses_normalizer_and_isolates_conversations(memory, tmp_path):
    fixture = FixtureApp()
    target, _ = make_target(tmp_path, fixture)
    one, two = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        assert (await send(target, one, "Help with a licence.")).get_piece().converted_value
        await send(target, two, "Help with a service.")
        await send(target, one, "Yes")
        first, other, followup = fixture.sent
        assert first[0]["threadId"] == followup[0]["threadId"] != other[0]["threadId"]
        page = "x-bc-conversation-page"
        assert first[1][page] == followup[1][page] != other[1][page]
        assert "cookie" not in first[1] and "cookie" not in other[1]
        assert "bc_pilot_session=" in followup[1]["cookie"]
        command = followup[0]["forwardedProps"]["bc"]["conversation"]
        assert command["revision"] == 1 and command["questionId"] == "server-question"
        assert followup[0]["messages"] == [followup[0]["messages"][-1]]
        assert not any(path == "/api/conversation/control" for _, path, _ in fixture.controls)
        await target.reset_conversation_async(conversation_id=one)
        deletes = [headers for method, _, headers in fixture.controls if method == "DELETE"]
        assert len(deletes) == 1 and deletes[0][page] == first[1][page]
    finally:
        await target.close_async()


async def test_old_history_is_not_replayed_into_a_new_session(memory, tmp_path):
    fixture = FixtureApp()
    target, _ = make_target(tmp_path, fixture)
    conversation = str(uuid.uuid4())
    try:
        await send(target, conversation, "Help with a licence.")
        await target.reset_conversation_async(conversation_id=conversation)
        with target_failure("NEW_CONVERSATION_REQUIRED"):
            await send(target, conversation, "Yes")
        assert len(fixture.sent) == 1
    finally:
        await target.close_async()


async def test_edited_history_fails_before_another_app_request(memory, tmp_path):
    fixture = FixtureApp()
    target, _ = make_target(tmp_path, fixture)
    conversation = str(uuid.uuid4())
    try:
        await send(target, conversation, "Help with a licence.")
        current = Message.from_prompt(prompt="Yes", role="user")
        current.get_piece().conversation_id = conversation
        with pytest.raises(CheckError, match="CONVERSATION_HISTORY_CHANGED"):
            await target._send_prompt_to_target_async(normalized_conversation=[
                Message.from_prompt(prompt="Edited prior question", role="user"),
                Message.from_prompt(prompt="Fixture reply.", role="assistant"),
                current,
            ])
        assert len(fixture.sent) == 1
    finally:
        await target.close_async()


async def test_release_drift_blocks_preflight_without_sending_a_prompt(memory, tmp_path):
    fixture = FixtureApp()
    fixture.release = "b" * 40
    target, ledger = make_target(tmp_path, fixture)
    with pytest.raises(CheckError, match="DEPLOYMENT_CHANGED"):
        await target.app.preflight()
    assert not fixture.sent
    assert ledger.state()["stop"] == "DEPLOYMENT_CHANGED"


@pytest.mark.parametrize("error,code", [
    ("truncated", "MISSING_RUN_COMPLETION"),
    ("run", "APPLICATION_RUN_ERROR"),
])
async def test_failed_stream_never_becomes_a_successful_reply(memory, tmp_path, error, code):
    fixture = FixtureApp()
    fixture.error = error
    target, ledger = make_target(tmp_path, fixture)
    with target_failure(code) as caught:
        await send(target, str(uuid.uuid4()), "Help with a licence.")
    assert "private provider detail" not in str(caught.value)
    assert len(fixture.sent) == 1 and fixture.cancel_count == 2
    assert any(method == "DELETE" for method, _, _ in fixture.controls)
    assert ledger.state()["lastAppAt"] > 0
    assert not target._conversations


async def test_cancellation_closes_stream_and_cleans_only_the_owned_session(memory, tmp_path):
    fixture = FixtureApp()
    fixture.block = True
    target, _ = make_target(tmp_path, fixture)
    pending = asyncio.create_task(send(target, str(uuid.uuid4()), "Help with a service."))
    await asyncio.wait_for(fixture.started.wait(), timeout=5)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert fixture.closed_stream and fixture.cancel_count == 2
    assert len(fixture.sent) == 1
    assert any(method == "DELETE" for method, _, _ in fixture.controls)


async def test_restart_preserves_request_charges_and_rejects_budget_changes(memory, tmp_path):
    fixture = FixtureApp()
    target, ledger = make_target(tmp_path, fixture, requests=1)
    await send(target, str(uuid.uuid4()), "Help with a licence.")
    started = ledger.state()["started"]
    await target.close_async()
    restarted, same_ledger = make_target(tmp_path, fixture, requests=1)
    assert same_ledger.state()["started"] == started
    with target_failure("APP_BUDGET_EXHAUSTED"):
        await send(restarted, str(uuid.uuid4()), "Another question.")
    assert len(fixture.sent) == 1
    with pytest.raises(CheckError, match="MANUAL_BUDGET_CHANGED"):
        make_target(tmp_path, fixture, requests=2)


@pytest.mark.parametrize("change", [
    {"live_use_approved": False},
    {"deployment_id": "production"},
    {"release_commit": "main"},
    {"origin": "https://user:secret@staging.example"},
    {"origin": "https://staging.example?key=secret"},
    {"origin": "http://127.0.0.1:3000"},
])
def test_live_configuration_requires_explicit_scoped_approval(tmp_path, change):
    file = tmp_path / "manual.json"
    file.write_text(json.dumps(configuration(**change)), encoding="utf-8")
    with pytest.raises(CheckError) as caught:
        load_settings(file)
    assert "secret" not in str(caught.value)


async def test_registry_initializer_recreates_target_without_resetting_ledger(
    memory, tmp_path, monkeypatch
):
    fixture = FixtureApp()
    config = tmp_path / "manual.json"
    config.write_text(json.dumps(configuration()), encoding="utf-8")
    monkeypatch.setenv("BC_PYRIT_MANUAL_CONFIG", str(config))
    original_client = httpx.AsyncClient

    def mocked_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(fixture)
        return original_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mocked_client)
    file = Path(__file__).parents[1] / "copyrit_initializer.py"
    spec = importlib.util.spec_from_file_location("fixture_initializer", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        TargetRegistry.reset_registry_singleton()
        await module.BCGovStagingInitializer().initialize_async()
        registered = TargetRegistry.get_registry_singleton().instances.get("bc-gov-staging")
        assert isinstance(registered, ManualAppTarget)
        advertised = await TargetService().list_targets_async()
        assert [item.target_registry_name for item in advertised.items] == ["bc-gov-staging"]
        assert advertised.items[0].capabilities.supports_multi_turn
        started = registered.app.ledger.state()["started"]
        await registered.close_async()
        TargetRegistry.reset_registry_singleton()
        await module.BCGovStagingInitializer().initialize_async()
        restored = TargetRegistry.get_registry_singleton().instances.get("bc-gov-staging")
        assert isinstance(restored, ManualAppTarget)
        assert restored.app.ledger.state()["started"] == started
        assert not fixture.sent
        await restored.close_async()
    finally:
        TargetRegistry.reset_registry_singleton()


async def test_staging_auth_caches_refreshes_and_never_sends_to_another_origin(monkeypatch):
    now = [1000]
    calls = []
    sent = []

    class Credential:
        def __init__(self, **kwargs):
            assert kwargs == {"subscription": "subscription", "process_timeout": 15}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_token(self, scope):
            calls.append(scope)
            return AccessToken(f"private-token-{len(calls)}", now[0] + 600)

    monkeypatch.setattr("bc_pyrit.auth.AzureCliCredential", Credential)
    monkeypatch.setattr("bc_pyrit.auth.time", lambda: now[0])
    auth = AzureCliAuth(
        origin="https://staging.example", subscription_id="subscription", client_id="app"
    )

    def respond(request):
        sent.append(request.headers["authorization"])
        return httpx.Response(200)

    async with httpx.AsyncClient(auth=auth, transport=httpx.MockTransport(respond)) as client:
        await client.get("https://staging.example/api/capabilities")
        await client.post("https://staging.example/api/agent")
        now[0] = 1490
        await client.delete("https://staging.example/api/conversation")
        for url in ("https://another.example/", "http://staging.example/", "https://staging.example:444/"):
            with pytest.raises(CheckError, match="STAGING_AUTH_ORIGIN_MISMATCH"):
                await client.get(url)
    assert calls == ["api://app/.default", "api://app/.default"]
    assert sent == ["Bearer private-token-1", "Bearer private-token-1", "Bearer private-token-2"]


async def test_staging_sign_in_failure_is_private_and_sends_no_request(monkeypatch):
    class Credential:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_token(self, _):
            raise ClientAuthenticationError(message="private credential diagnostic")

    monkeypatch.setattr("bc_pyrit.auth.AzureCliCredential", Credential)
    auth = AzureCliAuth(
        origin="https://staging.example", subscription_id="subscription", client_id="app"
    )
    sent = []
    async with httpx.AsyncClient(
        auth=auth, transport=httpx.MockTransport(lambda request: sent.append(request))
    ) as client:
        with pytest.raises(CheckError, match="STAGING_SIGN_IN_REQUIRED") as failure:
            await client.get("https://staging.example/api/capabilities")
    assert not sent
    assert "private credential" not in str(failure.value)


async def test_authenticated_manual_target_covers_preflight_chat_and_cleanup(
    memory, tmp_path, monkeypatch
):
    fixture = FixtureApp()
    requests = []
    original = httpx.AsyncClient

    class Auth(httpx.Auth):
        async def async_auth_flow(self, request):
            request.headers["Authorization"] = "Bearer private-fixture-token"
            yield request

    def respond(request):
        assert request.headers["authorization"] == "Bearer private-fixture-token"
        requests.append((request.method, request.url.path))
        return fixture(request)

    def client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(respond)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr("bc_pyrit.manual.AzureCliAuth", lambda **_: Auth())
    config = tmp_path / "target.json"
    config.write_text(json.dumps(configuration(authentication={
        "provider": "azure-cli",
        "subscription_id": "11111111-1111-4111-8111-111111111111",
        "client_id": "22222222-2222-4222-8222-222222222222",
    })))
    target = await create_manual_target(config)
    try:
        await send(target, str(uuid.uuid4()), "Help with a service.")
    finally:
        await target.close_async()
    assert requests == [
        ("GET", "/api/capabilities"), ("POST", "/api/agent"), ("DELETE", "/api/conversation"),
    ]
    assert b"private-fixture-token" not in (tmp_path / "manual-budget.sqlite").read_bytes()
