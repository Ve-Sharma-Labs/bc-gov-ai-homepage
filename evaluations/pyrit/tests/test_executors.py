import json

import httpx
import pytest
import pytest_asyncio
from pyrit.memory import CentralMemory
from pyrit.models import Message
from pyrit.setup import IN_MEMORY, initialize_pyrit_async
from test_client import App

from bc_pyrit.client import AppClient
from bc_pyrit.contracts import CheckError
from bc_pyrit.execution import execute_attempt
from bc_pyrit.targets import AzureModelTarget, ModelSettings

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pyrit_memory():
    await initialize_pyrit_async(
        memory_db_type=IN_MEMORY,
        env_files=[],
        initializers=[],
        load_defaults=False,
        silent=True,
    )
    yield
    await CentralMemory.get_memory_instance().dispose_engine_async()


@pytest.mark.usefixtures("pyrit_memory")
@pytest.mark.parametrize(
    ("case_id", "turns"),
    [("licensing-role-override", 1), ("licensing-role-adaptive", 3)],
)
async def test_real_pyrit_fixed_and_adaptive_executors_use_the_stateful_app(
    ledger,
    dataset,
    case_id,
    turns,
):
    server = App()
    app = AppClient(
        "http://127.0.0.1:8123",
        ledger,
        offline=True,
        transport=httpx.MockTransport(server),
    )
    case = next(case for case in dataset.cases if case.id == case_id)
    key, variant = case.attempts()[0]
    result = await execute_attempt(
        app=app,
        ledger=ledger,
        case=case,
        key=key,
        variant=variant,
        models=None,
        token_provider=None,
        api_python="",
    )
    assert result.status == "pass", result
    assert result.turns == turns
    assert ledger.report()["usage"]["judge"]["calls"] == turns
    assert sum(request.url.path == "/api/agent" for request in server.requests) == turns
    assert server.requests[-1].method == "DELETE"


@pytest.mark.usefixtures("pyrit_memory")
async def test_unsafe_earlier_reply_is_not_erased_by_a_later_safe_reply(ledger, dataset):
    server = App(texts=["Your application has been approved.", "I cannot approve an application."])
    app = AppClient(
        "http://127.0.0.1:8123",
        ledger,
        offline=True,
        transport=httpx.MockTransport(server),
    )
    original = next(case for case in dataset.cases if case.id == "conversation-topic-correction")
    case = original.model_copy(update={"expected_goal": None})
    key, variant = case.attempts()[0]
    result = await execute_attempt(
        app=app,
        ledger=ledger,
        case=case,
        key=key,
        variant=variant,
        models=None,
        token_provider=None,
        api_python="",
    )
    assert result.status == "needs-review", result
    assert result.code == "SEMANTIC_REVIEW_REQUIRED"
    assert result.turns == 2


@pytest.mark.usefixtures("pyrit_memory")
@pytest.mark.parametrize("fault", [None, "redirect", "wrong-model", "truncated", "invalid-json"])
async def test_live_model_transport_reserves_every_call_and_stops_on_bad_replies(ledger, fault):
    seen = []

    async def token():
        return "synthetic-token"

    async def provider(request):
        seen.append(request)
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert payload["service_tier"] == "default"
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "https://unapproved.invalid/"})
        return httpx.Response(
            200,
            json={
                "model": "wrong-model" if fault == "wrong-model" else "reviewed-model",
                "choices": [
                    {
                        "finish_reason": "length" if fault == "truncated" else "stop",
                        "message": {
                            "content": "untrusted provider text"
                            if fault == "invalid-json"
                            else json.dumps(
                                {
                                    "score_value": False,
                                    "description": "",
                                    "rationale": "",
                                    "metadata": "",
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 30, "completion_tokens": 10},
            },
        )

    target = AzureModelTarget(
        role="judge",
        settings=ModelSettings(
            endpoint="https://fixture.openai.azure.com/openai/v1",
            deployment="reviewed-deployment",
            response_model="reviewed-model",
        ),
        ledger=ledger,
        token_provider=token,
        transport=httpx.MockTransport(provider),
    )
    message = Message.from_prompt(prompt="Return a JSON verdict.", role="user")
    try:
        if fault:
            with pytest.raises(CheckError) as error:
                await target._send_prompt_to_target_async(normalized_conversation=[message])
            assert "untrusted provider text" not in str(error.value)
            with pytest.raises(CheckError):
                await target._send_prompt_to_target_async(normalized_conversation=[message])
        else:
            response = await target._send_prompt_to_target_async(normalized_conversation=[message])
            assert json.loads(response[0].message_pieces[0].converted_value)["score_value"] is False
    finally:
        await target.close()
    assert len(seen) == 1
    assert ledger.report()["usage"]["judge"]["calls"] == 1
