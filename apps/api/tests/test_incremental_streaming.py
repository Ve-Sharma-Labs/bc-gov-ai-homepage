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
from bc_api.models import EvidenceBundle, PreparationArtifact
from bc_api.output import OutputGate
from bc_api.retrieval import EvidenceLedger
from bc_api.security import Run
from bc_api.streaming import stream_run


def gate_for(repository, evidence):
    ledger = EvidenceLedger()
    ledger.add(evidence)
    gate = OutputGate(repository, ledger)
    gate.hold(TextMessageStartEvent(message_id="answer", role="assistant"))
    return gate


def contents(events):
    return "".join(event.delta for event in events if event.type == "TEXT_MESSAGE_CONTENT")


def test_first_validated_section_is_not_held_until_completion(repository, evidence):
    gate = gate_for(repository, evidence)
    url = evidence.evidence[0].reference.url
    first = f"Bring accepted identification. [Official source]({url})\n\n"
    second = f"Check the source before your visit. [Official source]({url})"
    gate.hold(TextMessageContentEvent(message_id="answer", delta=first))
    early = gate.flush_sections()
    assert contents(early) == first
    assert early[0].type == "TEXT_MESSAGE_START"
    assert early[1].name == "annotations"
    assert not any(event.type == "TEXT_MESSAGE_END" for event in early)
    assert gate.flush_sections() == []
    gate.hold(TextMessageContentEvent(message_id="answer", delta=second))
    gate.hold(TextMessageEndEvent(message_id="answer"))
    final = gate.finish()
    assert contents(final) == second
    assert not any(event.type == "TEXT_MESSAGE_START" for event in final)
    assert sum(event.type == "TEXT_MESSAGE_END" for event in final) == 1


def test_incomplete_links_and_unsupported_claims_never_stream(repository, evidence):
    gate = gate_for(repository, evidence)
    url = evidence.evidence[0].reference.url
    gate.hold(TextMessageContentEvent(message_id="answer", delta=f"Read [the source]({url}"))
    assert gate.flush_sections() == []
    gate.hold(TextMessageContentEvent(message_id="answer", delta=")\n\n"))
    assert contents(gate.flush_sections()) == f"Read [the source]({url})\n\n"
    gate.hold(
        TextMessageContentEvent(
            message_id="answer", delta=f"The fee is $99999. [Source]({url})\n\n"
        )
    )
    with pytest.raises(ApiError, match="CRITICAL_CLAIM_UNVERIFIED"):
        gate.flush_sections()


def test_all_chunks_of_a_page_remain_available_for_verification(repository, evidence):
    first = evidence.evidence[0].model_copy(
        update={
            "reference": evidence.evidence[0].reference.model_copy(update={"chunk_id": "first"}),
        }
    )
    second = first.model_copy(
        update={
            "reference": first.reference.model_copy(update={"chunk_id": "second"}),
            "content": "A different section of the same official document.",
        }
    )
    bundle = EvidenceBundle(evidence=[first, second])
    gate = gate_for(repository, bundle)
    assert len(gate.ledger.items) == 2
    gate.hold(
        TextMessageContentEvent(
            message_id="answer", delta=f"The fee is $75. [Source]({first.reference.url})\n\n"
        )
    )
    events = gate.flush_sections()
    assert contents(events)
    refs = next(event.value["annotations"] for event in events if event.type == "CUSTOM")
    assert {ref["chunkId"] for ref in refs} == {"first", "second"}
    changed = first.model_copy(
        update={
            "reference": first.reference.model_copy(update={"document_version": "changed"}),
        }
    )
    with pytest.raises(ApiError, match="SOURCE_CONFLICT"):
        gate.ledger.add(EvidenceBundle(evidence=[changed]))


def test_only_canonical_artifacts_can_be_committed(repository, evidence):
    gate = gate_for(repository, evidence)
    plan = repository.plan("licence-renewal")
    artifact = PreparationArtifact(id="plan-test", journey=plan.journey, sources=plan.sources)
    gate.hold(CustomEvent(name="bc.artifact", value=artifact.model_dump(by_alias=True)))
    assert gate.flush_sections()[0].value["kind"] == "preparation"
    assert gate.flush_sections() == []
    forged = artifact.model_dump(by_alias=True)
    forged["journey"]["steps"][0]["description"] = "An invented instruction."
    with pytest.raises(ApiError, match="OUTPUT_INVALID"):
        gate.hold(CustomEvent(name="bc.artifact", value=forged))


async def test_sse_yields_verified_content_while_the_producer_is_still_running(
    repository, evidence, settings, run_input
):
    resume = asyncio.Event()
    url = evidence.evidence[0].reference.url

    class IncrementalRuntime(FoundryRuntime):
        async def events(self, request, context):
            context.ledger.add(evidence)
            yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
            yield TextMessageStartEvent(message_id="answer", role="assistant")
            yield TextMessageContentEvent(
                message_id="answer", delta=f"Read the guidance. [Source]({url})\n\n"
            )
            await resume.wait()
            yield TextMessageEndEvent(message_id="answer")
            yield RunFinishedEvent(run_id=request.run_id, thread_id=request.thread_id)

    run = Run(run_input["runId"], run_input["threadId"], "test-owner")
    stream = stream_run(
        RunAgentInput.model_validate(run_input),
        run,
        IncrementalRuntime(settings, repository),
        repository,
        settings,
    )
    received = []
    try:
        async with asyncio.timeout(5):
            while not any(event["type"] == "TEXT_MESSAGE_CONTENT" for event in received):
                frame = await anext(stream)
                received.append(json.loads(frame.removeprefix("data: ").strip()))
        assert not resume.is_set()
        assert run.status == "running"
        assert not any(event["type"] == "RUN_FINISHED" for event in received)
        resume.set()
        async for frame in stream:
            received.append(json.loads(frame.removeprefix("data: ").strip()))
        assert received[-1]["type"] == "RUN_FINISHED"
        assert run.status == "finished"
    finally:
        await stream.aclose()


async def test_verified_sections_finish_with_warning_when_later_critical_detail_is_withheld(
    repository, evidence, settings, run_input
):
    url = evidence.evidence[0].reference.url

    class MixedRuntime(FoundryRuntime):
        async def events(self, request, context):
            context.ledger.add(evidence)
            yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
            yield TextMessageStartEvent(message_id="answer", role="assistant")
            yield TextMessageContentEvent(
                message_id="answer", delta=f"Read the guidance. [Source]({url})\n\n"
            )
            yield TextMessageContentEvent(
                message_id="answer", delta=f"The fee is $99999. [Source]({url})\n\n"
            )

    run = Run(run_input["runId"], run_input["threadId"], "test-owner")
    stream = stream_run(
        RunAgentInput.model_validate(run_input),
        run,
        MixedRuntime(settings, repository),
        repository,
        settings,
    )
    received = [
        json.loads(frame.removeprefix("data: ").strip())
        async for frame in stream
        if frame.startswith("data: ")
    ]
    assert "Read the guidance." in json.dumps(received)
    assert "$99999" not in json.dumps(received)
    assert any(
        event.get("type") == "CUSTOM"
        and event.get("name") == "bc.warning"
        and event.get("value") == {"version": 1, "code": "DETAILS_WITHHELD"}
        for event in received
    )
    assert any(event["type"] == "TEXT_MESSAGE_END" for event in received)
    assert received[-1]["type"] == "RUN_FINISHED"
    assert not any(event["type"] == "RUN_ERROR" for event in received)
    assert run.status == "finished"
