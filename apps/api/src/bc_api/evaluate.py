"""Content-free live smoke/latency reports; never a substitute for domain review."""

import argparse
import asyncio
import codecs
import json
import math
import re
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from bc_api.config import default_catalog_path
from bc_api.models import JOURNEY_IDS, ResponseContext
from bc_api.output import TRANSACTION_CLAIMS
from bc_api.protocol import PROGRESS


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("origin") != "independently-authored-public-questions"
        or type(data.get("schemaVersion")) is not int
        or data["schemaVersion"] != 1
    ):
        raise ValueError("Use independently authored public-question cases, not Web IQ content.")
    cases = data.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError("Supply a bounded public-question case set.")
    identifiers = set()
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("journeyId"), str)
            or case.get("journeyId") not in JOURNEY_IDS
            or not isinstance(case.get("id"), str)
            or len(case["id"]) > 80
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", case["id"])
            or case["id"] in identifiers
            or not isinstance(case.get("prompt"), str)
            or not 1 <= len(case["prompt"].strip()) <= 4000
            or len(case["prompt"]) > 4000
            or not isinstance(case.get("review"), str)
            or not 1 <= len(case["review"].strip()) <= 1000
        ):
            raise ValueError(
                "Each case needs a unique slug ID, supported journey, bounded public "
                "question and human-review criteria."
            )
        identifiers.add(case["id"])
    return cases


def percentile(values: list[float], percent: float) -> float | None:
    if not 0 < percent <= 1:
        raise ValueError("Percentile must be between zero (exclusive) and one.")
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(percent * len(ordered)) - 1)], 1)


async def stream_events(response: httpx.Response) -> AsyncIterator[dict]:
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    data = []
    received = 0
    async for chunk in response.aiter_bytes():
        received += len(chunk)
        if received > 1024 * 1024:
            raise ValueError("Stream limit exceeded")
        buffer += decoder.decode(chunk)
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.removesuffix("\r")
            if not line and data:
                event = json.loads("\n".join(data))
                if not isinstance(event, dict):
                    raise ValueError("Invalid event")
                yield event
                data = []
            elif line.startswith("data:"):
                data.append(line.removeprefix("data:").removeprefix(" "))
    buffer += decoder.decode(b"", final=True)
    if buffer or data:
        raise ValueError("Truncated event")


async def run_case(client: httpx.AsyncClient, case: dict, *, general: bool = False) -> dict:
    run_id = str(uuid.uuid4())
    started = time.monotonic()
    first = None
    first_event = None
    phases = {}
    response_context = ResponseContext(kind="grounded", origin="model")
    context_seen = not general
    text = ""
    citations = set()
    tokens = None
    outcome = "incomplete"
    run_started = False
    terminal = False
    messages = set()
    active_messages = set()
    payload = {
        "threadId": str(uuid.uuid4()),
        "runId": run_id,
        "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": case["prompt"]}],
        "tools": [],
        "context": [],
        "state": {},
        "forwardedProps": {
            "bc": {"version": 2, "mode": "general"}
            if general
            else {"version": 1, "journeyId": case["journeyId"]},
        },
    }
    try:
        async with asyncio.timeout(180):
            async with client.stream("POST", "/api/agent", json=payload) as response:
                if response.status_code != 200:
                    outcome = f"http-{response.status_code}"
                else:
                    content_type = response.headers.get("content-type", "").split(";")[0]
                    if content_type != "text/event-stream":
                        raise ValueError("Expected an event stream")
                    async for event in stream_events(response):
                        if terminal:
                            raise ValueError("Event after terminal result")
                        kind = event["type"]
                        if first_event is None:
                            first_event = (time.monotonic() - started) * 1000
                        if kind == "RUN_STARTED":
                            if (
                                run_started
                                or event.get("runId") != run_id
                                or event.get("threadId") != payload["threadId"]
                            ):
                                raise ValueError("Invalid run framing")
                            run_started = True
                        elif kind in (
                            "TEXT_MESSAGE_START",
                            "TEXT_MESSAGE_CONTENT",
                            "TEXT_MESSAGE_END",
                        ):
                            message_id = event.get("messageId")
                            if not run_started or not isinstance(message_id, str):
                                raise ValueError("Invalid message framing")
                            if kind == "TEXT_MESSAGE_START":
                                if (
                                    message_id in messages
                                    or event.get("role") != "assistant"
                                    or not context_seen
                                ):
                                    raise ValueError("Invalid assistant message")
                                messages.add(message_id)
                                active_messages.add(message_id)
                                continue
                            if message_id not in active_messages:
                                raise ValueError("Message was not started")
                            if kind == "TEXT_MESSAGE_END":
                                active_messages.remove(message_id)
                                continue
                            if not isinstance(event.get("delta"), str):
                                raise ValueError("Invalid answer content")
                            if first is None and event["delta"].strip():
                                first = (time.monotonic() - started) * 1000
                            text += event["delta"]
                            if len(text) > 60000:
                                raise ValueError("Response limit exceeded")
                        elif kind == "CUSTOM" and event.get("name") == "bc.response":
                            if not run_started or messages or (general and context_seen):
                                raise ValueError("Invalid response context order")
                            response_context = ResponseContext.model_validate(event["value"])
                            context_seen = True
                        elif kind == "CUSTOM" and event.get("name") == "status":
                            phase = event["value"]["phase"]
                            if phase not in PROGRESS:
                                raise ValueError("Invalid progress phase")
                            phases.setdefault(phase, round((time.monotonic() - started) * 1000, 1))
                        elif kind == "CUSTOM" and event.get("name") == "annotations":
                            annotations = event["value"]["annotations"]
                            if not isinstance(annotations, list):
                                raise ValueError("Invalid annotations")
                            for item in annotations:
                                if not isinstance(item, dict) or not isinstance(
                                    item.get("url"), str
                                ):
                                    raise ValueError("Invalid citation")
                                source = urlsplit(item["url"])
                                if source.scheme != "https" or not source.hostname:
                                    raise ValueError("Invalid citation URL")
                                citations.add(item["url"])
                        elif kind == "CUSTOM" and event.get("name") == "usage":
                            count = event["value"]["total_token_count"]
                            if type(count) is not int or count < 0:
                                raise ValueError("Invalid usage")
                            tokens = (tokens or 0) + count
                        elif kind == "RUN_ERROR":
                            outcome = "run-error"
                            terminal = True
                        elif kind == "RUN_FINISHED":
                            if (
                                not run_started
                                or active_messages
                                or event.get("runId") != run_id
                                or event.get("threadId") != payload["threadId"]
                            ):
                                raise ValueError("Invalid terminal framing")
                            outcome = "completed"
                            terminal = True
    except httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError:
        outcome = "transport-or-protocol-error"
    if outcome in ("incomplete", "transport-or-protocol-error"):
        try:
            async with asyncio.timeout(10):
                cancellation = await client.post(f"/api/runs/{run_id}/cancel")
                if cancellation.status_code not in (200, 202, 409):
                    raise ValueError("Cancellation not confirmed")
        except httpx.HTTPError, TimeoutError, ValueError:
            outcome = "transport-error-cancellation-unconfirmed"
    sourced = response_context.kind == "grounded"
    passed = outcome == "completed" and bool(text.strip()) and (bool(citations) or not sourced)
    passed = passed and not TRANSACTION_CLAIMS.search(text)
    grounded = bool(passed and sourced and response_context.origin == "model")
    return {
        "caseId": case["id"],
        "outcome": outcome,
        "protocolPassed": bool(passed),
        "groundedAnswer": grounded,
        "responseKind": response_context.kind if context_seen else None,
        "responseOrigin": response_context.origin if context_seen else None,
        "firstEventMs": round(first_event, 1) if first_event is not None else None,
        "firstResponseMs": round(first, 1) if first is not None else None,
        "firstValidatedContentMs": round(first, 1) if first is not None and grounded else None,
        "phasesMs": phases,
        "durationMs": round((time.monotonic() - started) * 1000, 1),
        "citationCount": len(citations),
        "reportedTokens": tokens,
        "domainReviewRequired": True,
    }


async def evaluate(
    base_url: str, cases: list[dict], repetitions: int, *, general: bool = False
) -> dict:
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Origin": base_url},
        timeout=90,
        follow_redirects=False,
    ) as client:
        capability = await client.get("/api/capabilities")
        capability.raise_for_status()
        readiness = capability.json()
        if not isinstance(readiness, dict):
            raise ValueError("Invalid capability response")
        ready = (
            readiness.get("generalChatConfigured") is True
            and readiness.get("retrievalReady") is True
            if general
            else readiness.get("aiConfigured") is True
        )
        if not ready:
            return {
                "blocked": "The target is not connected to verified AI and sources.",
                "modelRuns": 0,
            }
        results = []
        for _ in range(repetitions):
            for case in cases:
                results.append(await run_case(client, case, general=general))
    first = [item["firstValidatedContentMs"] for item in results if item["groundedAnswer"]]
    durations = [item["durationMs"] for item in results if item["groundedAnswer"]]
    return {
        "mode": "live-operational-check",
        "domainReviewRequired": True,
        "cases": results,
        "summary": {
            "runs": len(results),
            "protocolPassed": sum(item["protocolPassed"] for item in results),
            "groundedAnswers": sum(item["groundedAnswer"] for item in results),
            "firstValidatedContentP50Ms": percentile(first, 0.5),
            "firstValidatedContentP95Ms": percentile(first, 0.95),
            "completionP50Ms": percentile(durations, 0.5),
            "completionP95Ms": percentile(durations, 0.95),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=default_catalog_path().parent / "evaluations" / "pilot-cases.json",
    )
    parser.add_argument("--base-url")
    parser.add_argument("--repetitions", type=int, default=1, choices=range(1, 11))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--general", action="store_true")
    args = parser.parse_args()
    try:
        cases = load_cases(args.cases)
    except OSError, ValueError:
        parser.error("Use a valid independently authored public-question case file.")
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "review-only",
                    "plannedRuns": len(cases) * args.repetitions,
                    "networkRequests": 0,
                    "domainReviewRequired": True,
                }
            )
        )
        return 0
    if not args.approved or not args.base_url:
        parser.error("Paid live runs require --approved and the reviewed website --base-url.")
    target = urlsplit(args.base_url)
    if (
        target.username
        or target.password
        or target.query
        or target.fragment
        or target.path not in ("", "/")
        or not target.hostname
        or (
            target.scheme != "https"
            and not (target.scheme == "http" and target.hostname in ("localhost", "127.0.0.1"))
        )
    ):
        parser.error("Use a reviewed HTTPS website origin, or a loopback development origin.")
    try:
        report = asyncio.run(
            evaluate(args.base_url.rstrip("/"), cases, args.repetitions, general=args.general)
        )
    except httpx.HTTPError, ValueError:
        print(json.dumps({"blocked": "Target readiness could not be verified.", "modelRuns": 0}))
        return 1
    print(json.dumps(report, indent=2))
    return (
        0 if report.get("summary", {}).get("protocolPassed") == len(cases) * args.repetitions else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
