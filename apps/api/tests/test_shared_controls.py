import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis
import fakeredis.aioredis
import pytest
from agent_framework import ChatContext, Content, Message

from bc_api.controls import SharedControls, token_hash
from bc_api.errors import ApiError
from bc_api.model_budget import ModelBudget
from bc_api.retrieval import EvidenceLedger
from bc_api.tools import ToolContext


def control_settings(settings, **changes):
    return settings.model_copy(
        update={
            "api_daily_run_limit": 100,
            "api_daily_token_limit": 10000000,
            "api_daily_cost_limit_microusd": 10000000,
            "api_token_price_microusd": 1,
            **changes,
        }
    )


@pytest.fixture
async def replicas(settings):
    server = fakeredis.FakeServer()
    first = SharedControls(
        control_settings(settings),
        client=fakeredis.aioredis.FakeRedis(server=server, decode_responses=True),
    )
    second = SharedControls(
        control_settings(settings),
        client=fakeredis.aioredis.FakeRedis(server=server, decode_responses=True),
    )
    yield first, second
    await first.close()
    await second.close()


async def test_session_ownership_and_cancellation_cross_replicas(replicas):
    first, second = replicas
    session, fresh = await first.session(None)
    same, fresh_again = await second.session(session.token)
    assert fresh and not fresh_again and same.token == session.token
    run = await first.reserve("run-one", "thread-one", session.token)
    watcher = asyncio.create_task(run.watch())
    try:
        other, _ = await second.session(None)
        with pytest.raises(ApiError, match="RUN_NOT_FOUND"):
            await second.cancel(run.run_id, other.token)
        assert await second.cancel(run.run_id, session.token) == "cancelling"
        await asyncio.wait_for(run.cancellation.wait(), 2)
        assert await run.finish("finished", 20) == "cancelled"
        assert await second.cancel(run.run_id, session.token) == "cancelled"
        budget = await first.client.hgetall(first.prefix + "budget")
        assert int(budget["tokens"]) == first.settings.run_token_reservation
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


async def test_admission_and_refunds_are_atomic_and_idempotent(replicas):
    first, second = replicas
    session, _ = await first.session(None)
    outcomes = await asyncio.gather(
        first.reserve("run-a", "thread", session.token),
        second.reserve("run-b", "thread", session.token),
        return_exceptions=True,
    )
    success = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    assert len(success) == 1
    run = success[0]
    assert await run.finish("finished", 25) == "finished"
    assert await run.finish("finished", 25) == "finished"
    budget = await first.client.hgetall(first.prefix + "budget")
    assert int(budget["runs"]) == 1
    assert int(budget["tokens"]) == 25
    assert int(budget["cost"]) == 25
    with pytest.raises(ApiError, match="RUN_CONFLICT"):
        await second.reserve(run.run_id, "thread", session.token)
    next_run = await second.reserve("run-next", "thread", session.token)
    assert await next_run.finish("not-started", None) == "failed"
    assert int(await first.client.hget(first.prefix + "budget", "tokens")) == 25


async def test_rate_and_global_processing_allowances_cannot_be_reset_by_new_sessions(replicas):
    first, second = replicas
    await first.check_rate("fixture-client", 1)
    with pytest.raises(ApiError, match="RATE_LIMITED"):
        await second.check_rate("fixture-client", 1)
    first.settings.api_daily_run_limit = 1
    second.settings.api_daily_run_limit = 1
    session, _ = await first.session(None)
    run = await first.reserve("run-allowed", "thread", session.token)
    await run.finish("finished", 20)
    other, _ = await second.session(None)
    with pytest.raises(ApiError, match="BUDGET_EXHAUSTED") as exhausted:
        await second.reserve("run-denied", "thread", other.token)
    assert exhausted.value.retry_after is not None
    assert 1 <= exhausted.value.retry_after <= 86400


async def test_cancellation_before_model_work_refunds_tokens_but_not_run_count(replicas):
    first, second = replicas
    session, _ = await first.session(None)
    run = await first.reserve("cancel-before-model", "thread", session.token)
    assert await second.cancel(run.run_id, session.token) == "cancelling"
    assert await run.finish("not-started", 0) == "cancelled"
    assert await second.cancel(run.run_id, session.token) == "cancelled"
    budget = await first.client.hgetall(first.prefix + "budget")
    assert int(budget["tokens"]) == 0
    assert int(budget["cost"]) == 0
    assert int(budget["runs"]) == 1


async def test_guessed_sessions_and_overrun_cannot_open_an_unmetered_run(replicas):
    first, second = replicas
    supplied = "x" * 43
    session, fresh = await first.session(supplied)
    assert fresh and session.token != supplied
    with pytest.raises(ApiError, match="SESSION_EXPIRED"):
        await second.reserve("unowned", "thread", supplied)
    run = await first.reserve("overrun", "thread", session.token)
    await run.finish("finished", first.settings.run_token_reservation + 1)
    assert await first.client.hget(first.prefix + "budget", "blocked") == "1"
    with pytest.raises(ApiError, match="BUDGET_EXHAUSTED"):
        await second.reserve("after-overrun", "thread", session.token)
    assert await first.client.exists(first.prefix + "session:" + token_hash(session.token))
    keys = await first.client.keys(first.prefix + "*")
    assert not any(session.token in key for key in keys)


async def test_per_model_call_budget_stops_before_another_provider_request(settings, repository):
    settings = settings.model_copy(update={"api_model_calls_per_run": 1})
    tool_context = ToolContext(repository, EvidenceLedger())
    budget = ModelBudget(settings, tool_context, overhead_bytes=100)
    context = ChatContext(
        client=SimpleNamespace(),
        messages=[Message(role="user", contents=[Content.from_text("A synthetic question.")])],
        options={"max_tokens": 999999},
    )
    next_call = AsyncMock()
    await budget.process(context, next_call)
    assert context.options["max_tokens"] == settings.api_model_output_tokens
    assert tool_context.model_work_started is True
    with pytest.raises(ApiError, match="MODEL_BUDGET_EXCEEDED"):
        await budget.process(context, next_call)
    assert next_call.await_count == 1


async def test_model_work_is_marked_before_a_provider_failure(settings, repository):
    tool_context = ToolContext(repository, EvidenceLedger())
    tool_context.model_work_started = False
    budget = ModelBudget(settings, tool_context, overhead_bytes=100)
    context = ChatContext(client=SimpleNamespace(), messages=[], options={})

    async def fail_provider():
        assert tool_context.model_work_started is True
        raise RuntimeError("Provider failed after invocation started")

    with pytest.raises(RuntimeError, match="Provider failed"):
        await budget.process(context, fail_provider)
    assert tool_context.model_work_started is True


async def test_application_dialogue_preserves_ownership_without_consuming_model_budget(replicas):
    first, second = replicas
    session, _ = await first.session(None)
    model = await first.reserve("model-run", "thread", session.token)
    await model.finish("finished", first.settings.run_token_reservation + 1)
    before = await first.client.hgetall(first.prefix + "budget")
    assert before["blocked"] == "1"
    dialogue = await second.reserve("dialogue-run", "thread", session.token, model_work=False)
    other, _ = await first.session(None)
    with pytest.raises(ApiError, match="RUN_NOT_FOUND"):
        await first.cancel(dialogue.run_id, other.token)
    with pytest.raises(ApiError, match="SESSION_BUSY"):
        await first.reserve("duplicate-dialogue", "thread", session.token, model_work=False)
    assert await dialogue.finish("finished", 0) == "finished"
    assert await dialogue.finish("finished", 0) == "finished"
    assert await first.client.hgetall(first.prefix + "budget") == before
    with pytest.raises(ApiError, match="BUDGET_EXHAUSTED"):
        await first.reserve("still-billable", "thread", session.token)
