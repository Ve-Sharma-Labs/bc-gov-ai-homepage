import json
import sys

import httpx
import pytest

from bc_api import evaluate
from bc_api.config import default_catalog_path

CASE = {
    "id": "licence-preparation",
    "journeyId": "licence-renewal",
    "prompt": "What should I prepare before renewing a BC driver's licence?",
    "review": "Verify official guidance and that no renewal is claimed.",
}


def test_case_file_is_independently_authored_and_covers_all_journeys():
    cases = evaluate.load_cases(default_catalog_path().parent / "evaluations" / "pilot-cases.json")
    assert {case["journeyId"] for case in cases} == evaluate.JOURNEY_IDS
    assert len(cases) == len(evaluate.JOURNEY_IDS)


@pytest.mark.parametrize(
    "cases",
    [
        [],
        [CASE, CASE],
        [{**CASE, "id": "unbounded or private text"}],
        [{**CASE, "id": "x" * 81}],
        [{**CASE, "journeyId": "unknown"}],
        [{**CASE, "prompt": " "}],
        [{**CASE, "prompt": "x" * 4001}],
        [{**CASE, "review": ""}],
        [None],
    ],
)
def test_case_validation_rejects_invalid_or_unbounded_sets(tmp_path, cases):
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "origin": "independently-authored-public-questions",
                "schemaVersion": 1,
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        evaluate.load_cases(path)


@pytest.mark.parametrize("document", [[], None, {"schemaVersion": True}, {"origin": "web-iq"}])
def test_case_validation_rejects_unknown_origin_and_shape(tmp_path, document):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        evaluate.load_cases(path)


def test_nearest_rank_percentiles():
    assert evaluate.percentile([], 0.95) is None
    assert evaluate.percentile([100], 0.95) == 100
    assert evaluate.percentile([5, 1, 4, 3, 2], 0.5) == 3
    assert evaluate.percentile(list(range(1, 101)), 0.95) == 95
    with pytest.raises(ValueError):
        evaluate.percentile([1], 0)


def test_review_only_never_constructs_a_network_client(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Review-only mode must not connect to any service.")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(sys, "argv", ["evaluate", "--repetitions", "2"])
    assert evaluate.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "mode": "review-only",
        "plannedRuns": 14,
        "networkRequests": 0,
        "domainReviewRequired": True,
    }


@pytest.mark.parametrize(
    "args",
    [
        ["--execute"],
        ["--execute", "--approved"],
        ["--execute", "--approved", "--base-url", "http://example.org"],
        ["--execute", "--approved", "--base-url", "https://user:secret@example.org"],
        ["--execute", "--approved", "--base-url", "https://example.org/path"],
        ["--execute", "--approved", "--base-url", "https://example.org?key=value"],
    ],
)
def test_paid_execution_requires_an_approved_origin(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["evaluate", *args])
    with pytest.raises(SystemExit) as error:
        evaluate.main()
    assert error.value.code == 2


def successful_events(payload):
    framing = {"threadId": payload["threadId"], "runId": payload["runId"]}
    return [
        {"type": "RUN_STARTED", **framing},
        {"type": "TEXT_MESSAGE_START", "messageId": "answer", "role": "assistant"},
        {
            "type": "CUSTOM",
            "name": "annotations",
            "value": {
                "annotations": [
                    {"url": "https://www.icbc.com/driver-licensing", "title": "Fixture source"}
                ]
            },
        },
        {
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": "answer",
            "delta": "This is synthetic response text that must never be saved in the report.",
        },
        {"type": "TEXT_MESSAGE_END", "messageId": "answer"},
        {"type": "CUSTOM", "name": "usage", "value": {"total_token_count": 42}},
        {"type": "RUN_FINISHED", **framing},
    ]


def response_for(events):
    return httpx.Response(
        200,
        headers={"Content-Type": "text/event-stream; charset=utf-8"},
        content="".join(f"data: {json.dumps(event)}\n\n" for event in events),
    )


async def test_valid_protocol_reports_only_operational_metadata():
    def transport(request):
        payload = json.loads(request.content)
        assert payload["forwardedProps"]["bc"]["journeyId"] == CASE["journeyId"]
        assert "researchRequested" not in payload["forwardedProps"]["bc"]
        return response_for(successful_events(payload))

    async with httpx.AsyncClient(
        base_url="https://example.org", transport=httpx.MockTransport(transport)
    ) as client:
        result = await evaluate.run_case(client, CASE)
    assert result["protocolPassed"]
    assert result["outcome"] == "completed"
    assert result["firstValidatedContentMs"] is not None
    assert result["citationCount"] == 1
    assert result["reportedTokens"] == 42
    assert result["domainReviewRequired"]
    serialized = json.dumps(result)
    assert CASE["prompt"] not in serialized
    assert "synthetic response text" not in serialized
    assert "www.icbc.com" not in serialized


@pytest.mark.parametrize(
    "kind,origin", [("dialogue", "application"), ("dialogue", "model"), ("handoff", "application")]
)
async def test_general_dialogue_is_not_reported_as_fast_grounded_model_output(kind, origin):
    def transport(request):
        payload = json.loads(request.content)
        assert payload["forwardedProps"] == {"bc": {"version": 2, "mode": "general"}}
        events = successful_events(payload)
        events.pop(2)
        events.insert(
            1,
            {
                "type": "CUSTOM",
                "name": "bc.response",
                "value": {"version": 1, "kind": kind, "origin": origin},
            },
        )
        return response_for(events)

    async with httpx.AsyncClient(
        base_url="https://example.org", transport=httpx.MockTransport(transport)
    ) as client:
        result = await evaluate.run_case(client, CASE, general=True)
    assert result["protocolPassed"]
    assert not result["groundedAnswer"]
    assert result["firstResponseMs"] is not None
    assert result["firstValidatedContentMs"] is None
    assert result["responseKind"] == kind


async def test_general_evaluation_requires_server_response_context_before_text():
    def transport(request):
        if request.url.path.endswith("/cancel"):
            return httpx.Response(202)
        return response_for(successful_events(json.loads(request.content)))

    async with httpx.AsyncClient(
        base_url="https://example.org", transport=httpx.MockTransport(transport)
    ) as client:
        result = await evaluate.run_case(client, CASE, general=True)
    assert not result["protocolPassed"]
    assert result["outcome"] == "transport-or-protocol-error"


@pytest.mark.parametrize(
    "failure",
    [
        "missing-start",
        "open-message",
        "missing-finish",
        "error-then-finish",
        "wrong-run",
        "bad-json",
    ],
)
async def test_protocol_errors_never_pass_and_cancel_remaining_work(failure):
    cancelled = []

    def transport(request):
        if request.url.path.endswith("/cancel"):
            cancelled.append(request.url.path)
            return httpx.Response(202)
        payload = json.loads(request.content)
        events = successful_events(payload)
        if failure == "missing-start":
            events.pop(0)
        elif failure == "open-message":
            events.pop(4)
        elif failure == "missing-finish":
            events.pop()
        elif failure == "error-then-finish":
            events.insert(-1, {"type": "RUN_ERROR", "message": "Private provider detail"})
        elif failure == "wrong-run":
            events[-1]["runId"] = "another-run"
        elif failure == "bad-json":
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"}, content="data: {\n\n"
            )
        return response_for(events)

    async with httpx.AsyncClient(
        base_url="https://example.org", transport=httpx.MockTransport(transport)
    ) as client:
        result = await evaluate.run_case(client, CASE)
    assert not result["protocolPassed"]
    assert result["outcome"] in ("incomplete", "transport-or-protocol-error")
    assert len(cancelled) == 1
    assert "Private provider detail" not in json.dumps(result)


async def test_failed_cancellation_is_explicit():
    def transport(request):
        if request.url.path.endswith("/cancel"):
            return httpx.Response(503)
        return httpx.Response(
            200, headers={"Content-Type": "text/event-stream"}, content="data: []\n\n"
        )

    async with httpx.AsyncClient(
        base_url="https://example.org", transport=httpx.MockTransport(transport)
    ) as client:
        result = await evaluate.run_case(client, CASE)
    assert not result["protocolPassed"]
    assert result["outcome"] == "transport-error-cancellation-unconfirmed"


@pytest.mark.parametrize("failure", ["no-citations", "transaction-claim", "run-error"])
async def test_finished_output_still_needs_citations_and_honest_handoffs(failure):
    def transport(request):
        events = successful_events(json.loads(request.content))
        if failure == "no-citations":
            events.pop(2)
        elif failure == "transaction-claim":
            events[3]["delta"] = "Your licence has been renewed."
        else:
            events[-1] = {"type": "RUN_ERROR"}
        return response_for(events)

    async with httpx.AsyncClient(
        base_url="https://example.org", transport=httpx.MockTransport(transport)
    ) as client:
        result = await evaluate.run_case(client, CASE)
    assert not result["protocolPassed"]


async def test_unconfigured_capability_never_runs_a_model(monkeypatch):
    paths = []
    original_client = httpx.AsyncClient

    def transport(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"aiConfigured": False})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(transport), **kwargs),
    )
    report = await evaluate.evaluate("https://example.org", [CASE], 1)
    assert report["modelRuns"] == 0
    assert "blocked" in report
    assert paths == ["/api/capabilities"]


@pytest.mark.parametrize(
    "content",
    [b"data: {}\n", b"data: " + b"x" * (1024 * 1024)],
    ids=["truncated", "oversized"],
)
async def test_stream_parser_rejects_truncation_and_oversized_events(content):
    response = httpx.Response(200, content=content)
    with pytest.raises(ValueError):
        _ = [event async for event in evaluate.stream_events(response)]
