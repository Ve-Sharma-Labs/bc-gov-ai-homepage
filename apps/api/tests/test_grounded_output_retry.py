import asyncio
import json

import pytest
from ag_ui.core import (
    CustomEvent,
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)

from bc_api.errors import ApiError
from bc_api.foundry import FoundryRuntime
from bc_api.grounded_quotes import expand_source_quotes, quote_registry
from bc_api.model_budget import ModelBudget
from bc_api.protocol import progress_event
from bc_api.retrieval import EvidenceLedger
from bc_api.tools import ToolContext


def request():
    return RunAgentInput(
        thread_id="thread",
        run_id="run",
        state={},
        tools=[],
        context=[],
        messages=[
            {
                "id": "question",
                "role": "user",
                "content": json.dumps({"currentQuestion": "Synthetic guidance question"}),
            }
        ],
        forwarded_props={"bc": {"version": 2, "mode": "general"}},
    )


class FixtureRuntime(FoundryRuntime):
    def __init__(self, settings, catalog, evidence, answers):
        super().__init__(settings, catalog)
        self.evidence = evidence
        self.answers = answers
        self.inputs = []
        self.budgets = []

    async def _events(self, request, context, **kwargs):
        context.model_budget = context.model_budget or ModelBudget(self.settings, context, 100)
        context.model_budget.reserve(len(request.messages[-1].content.encode()))
        self.budgets.append(context.model_budget)
        self.inputs.append(json.loads(request.messages[-1].content))
        context.ledger.add(self.evidence)
        yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
        yield progress_event("retrieving")
        yield TextMessageStartEvent(message_id="answer", role="assistant")
        yield TextMessageContentEvent(message_id="answer", delta=self.answers[len(self.inputs) - 1])
        yield TextMessageEndEvent(message_id="answer")
        yield CustomEvent(name="usage", value={"total_token_count": 10})
        yield RunFinishedEvent(run_id=request.run_id, thread_id=request.thread_id)


def context(repository):
    return ToolContext(
        repository,
        EvidenceLedger(),
        grounded_conversation=True,
        programme_id="ei-regular",
    )


@pytest.mark.asyncio
async def test_one_correction_uses_the_same_budget_and_never_exposes_rejected_text(
    settings,
    repository,
    evidence,
):
    url = evidence.evidence[0].reference.url
    valid = f"Synthetic preparation guidance. [Source]({url})"
    runtime = FixtureRuntime(
        settings,
        repository,
        evidence,
        [
            "REJECTED ANSWER [Bad link](https://www2.gov.bc.ca/gov/content/not-evidence)",
            valid,
        ],
    )
    events = [event async for event in runtime.events(request(), context(repository))]
    assert "".join(event.delta for event in events if event.type == "TEXT_MESSAGE_CONTENT") == valid
    assert len(runtime.inputs) == 2 and runtime.budgets[0] is runtime.budgets[1]
    feedback = runtime.inputs[1]["validationFeedback"]
    assert feedback["code"] == "CITATION_INVALID"
    assert url in feedback["allowedUrls"]
    assert "REJECTED ANSWER" not in json.dumps(runtime.inputs[1])
    assert len([event for event in events if event.type == "RUN_STARTED"]) == 1
    assert len([event for event in events if event.type == "RUN_FINISHED"]) == 1
    assert len([event for event in events if getattr(event, "name", None) == "usage"]) == 2


@pytest.mark.asyncio
async def test_second_invalid_answer_fails_without_a_third_attempt_or_partial_text(
    settings,
    repository,
    evidence,
):
    invalid = "Unverified [link](https://www2.gov.bc.ca/gov/content/not-evidence)"
    runtime = FixtureRuntime(settings, repository, evidence, [invalid, invalid])
    emitted = []
    with pytest.raises(ApiError, match="CITATION_INVALID"):
        async for event in runtime.events(request(), context(repository)):
            emitted.append(event)
    assert len(runtime.inputs) == 2
    assert not [event for event in emitted if event.type.startswith("TEXT_MESSAGE")]
    assert not [event for event in emitted if event.type == "RUN_FINISHED"]


@pytest.mark.asyncio
async def test_selected_quote_is_rendered_from_evidence_not_model_words(
    settings, repository, evidence
):
    evidence.evidence[0].content = "The fee is $75 for adults only."
    key = next(iter(quote_registry(evidence.evidence)))
    marker = "{{quote:" + key + "}}"
    runtime = FixtureRuntime(settings, repository, evidence, [marker])
    events = [event async for event in runtime.events(request(), context(repository))]
    text = "".join(event.delta for event in events if event.type == "TEXT_MESSAGE_CONTENT")
    assert "The fee is $75 for adults only." in text
    assert evidence.evidence[0].reference.url in text
    assert "{{quote:" not in text
    assert len(runtime.inputs) == 1


@pytest.mark.asyncio
async def test_preflight_checks_each_section_not_only_all_citations_together(
    settings,
    repository,
    evidence,
):
    source = evidence.evidence[0]
    source.content = "The fee is $75."
    other = source.model_copy(deep=True)
    other.reference.document_id = "other"
    other.reference.url = source.reference.url + "/other"
    other.content = "Other synthetic guidance without a price."
    evidence.evidence.append(other)
    invalid = (
        f"The fee is $75. [Wrong source]({other.reference.url})\n\n"
        f"More guidance. [Source]({source.reference.url})"
    )
    valid = f"The fee is $75. [Source]({source.reference.url})"
    runtime = FixtureRuntime(settings, repository, evidence, [invalid, valid])
    events = [event async for event in runtime.events(request(), context(repository))]
    assert len(runtime.inputs) == 2
    assert "".join(event.delta for event in events if event.type == "TEXT_MESSAGE_CONTENT") == valid


def test_quote_markers_cannot_select_missing_evidence_or_expand_without_bounds(evidence):
    quotes = quote_registry(evidence.evidence)
    with pytest.raises(ApiError, match="CITATION_INVALID"):
        expand_source_quotes("{{quote:000000000000}}", quotes)
    key = next(iter(quotes))
    with pytest.raises(ApiError, match="OUTPUT_LIMIT"):
        expand_source_quotes(("{{quote:" + key + "}}\n") * 9, quotes)


@pytest.mark.asyncio
async def test_cancellation_closes_a_buffered_native_attempt(settings, repository, evidence):
    waiting, closed = asyncio.Event(), asyncio.Event()

    class BlockingRuntime(FoundryRuntime):
        async def _events(self, request, context, **kwargs):
            try:
                context.ledger.add(evidence)
                yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
                yield TextMessageStartEvent(message_id="answer", role="assistant")
                yield TextMessageContentEvent(message_id="answer", delta="Not yet validated")
                waiting.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

    emitted = []
    runtime = BlockingRuntime(settings, repository)

    async def consume():
        async for event in runtime.events(request(), context(repository)):
            emitted.append(event)

    task = asyncio.create_task(consume())
    await waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert not [event for event in emitted if event.type.startswith("TEXT_MESSAGE")]
