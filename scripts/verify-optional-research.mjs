import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";
import {
  assertReleaseCapabilities, assertSuccessfulRun, decodeReleaseEvents, releaseTarget,
} from "./verify-pilot-chat.mjs";

const actions = ["corpus-explore", "web-check"];
const reviewDatePattern = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$/;

export async function readReleaseEvents(response, onEvent = async () => {}) {
  assert.equal(response.status, 200, `Streaming transport failed (HTTP ${response.status}).`);
  assert.ok(response.headers.get("content-type")?.includes("text/event-stream"),
    "The response must be an event stream.");
  assert.ok(response.body, "The response has no stream.");
  const reader = response.body.getReader(), decoder = new TextDecoder();
  const events = [];
  let bytes = 0, pending = "", finished = false;
  const line = async (value) => {
    if (!value.startsWith("data: ")) return;
    assert.ok(events.length < 4096, "The response exceeded its event bound.");
    const event = JSON.parse(value.slice(6));
    events.push(event);
    await onEvent(event);
  };
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) {
        finished = true;
        break;
      }
      bytes += part.value.byteLength;
      assert.ok(bytes <= 262144, "The response exceeded its byte bound.");
      pending += decoder.decode(part.value, { stream: true });
      const lines = pending.split(/\r?\n/);
      pending = lines.pop();
      for (const value of lines) await line(value);
    }
    await line(pending + decoder.decode());
    return events;
  } finally {
    if (!finished) await reader.cancel();
    reader.releaseLock();
  }
}

function assertSupplement(events, request, sources) {
  assertSuccessfulRun(events);
  for (const event of [events[0], events.at(-1)]) {
    assert.equal(event.runId, request.runId, "Research returned another run.");
    assert.equal(event.threadId, request.threadId, "Research returned another conversation.");
  }
  assert.ok(events.every((event) => (
    ["RUN_STARTED", "RUN_FINISHED"].includes(event.type)
    || event.type === "CUSTOM" && ["bc.research.progress", "bc.research.result"].includes(event.name)
  )), "Research must not overwrite normal message, conversation, or task events.");
  const results = events.filter((event) => event.name === "bc.research.result");
  assert.equal(results.length, 1, "Research needs exactly one verified supplement.");
  const result = results[0].value;
  assert.ok(isDeepStrictEqual(Object.keys(result).sort(), [
    "version", "action", "runId", "parentRunId", "parentMessageId", "text", "citations", "notice",
  ].sort()), "Research returned an unexpected result contract.");
  assert.equal(result.version, 1);
  for (const key of ["runId", "action", "parentRunId", "parentMessageId"]) {
    assert.equal(result[key], request[key], "Research is not bound to the selected answer.");
  }
  assert.ok(typeof result.text === "string" && result.text.trim() && result.text.length <= 12000,
    "The supplement text is missing or unbounded.");
  assert.ok(typeof result.notice === "string" && result.notice.trim() && result.notice.length <= 600,
    "The supplement must disclose its distinct provenance.");
  assert.ok(Array.isArray(result.citations) && result.citations.length >= 1
    && result.citations.length <= 5, "Research requires bounded source references.");
  const kind = request.action === "web-check" ? "web" : "indexed";
  for (const citation of result.citations) {
    assert.equal(citation.kind, kind, "Research mixed indexed and public-web provenance.");
    const reference = kind === "indexed" ? citation.reference : citation;
    const source = sources.find((item) => item.id === reference?.sourceId);
    assert.ok(source && ["available", "limited"].includes(source.status),
      "Research used a source outside the approved catalogue.");
    const url = new URL(reference.url), approved = new URL(source.url);
    assert.ok(url.protocol === "https:" && !url.username && !url.password
      && !url.search && !url.hash && url.origin === approved.origin,
    "Research returned an unapproved source URL.");
    if (kind === "web") {
      const prefix = approved.pathname.replace(/\/$/, "");
      assert.ok(url.pathname === prefix || url.pathname.startsWith(`${prefix}/`),
        "Web research escaped the approved source area.");
      assert.equal(citation.humanReviewed, false);
      assert.equal(citation.method, "search", "Browse requires its own source-identity approval.");
      assert.ok(citation.title === source.title && citation.publisher === source.publisher,
        "Web source labels must come from the approved catalogue.");
      assert.ok(Number.isInteger(citation.quoteLimit) && citation.quoteLimit >= 1
        && citation.quoteLimit <= 200, "Public-web display limits must remain bounded.");
      assert.ok(!["reference", "reviewedAt", "checkedAt", "documentId", "documentVersion", "metadata"]
        .some((key) => key in citation),
        "Web results must not claim indexed human-review provenance.");
    } else {
      assert.ok(["documentId", "documentVersion", "title", "publisher"]
        .every((key) => typeof reference[key] === "string" && reference[key].trim())
        && reviewDatePattern.test(reference.checkedAt)
        && Number.isFinite(Date.parse(reference.checkedAt)),
      "Indexed research must retain its document and review provenance.");
    }
    assert.ok(Number.isFinite(Date.parse(citation.retrievedAt)), "Research needs retrieval provenance.");
  }
  return { action: request.action, citations: result.citations.length, kind };
}

export async function verifyOptionalResearch({
  baseUrl, liveApproved = false, researchApproved = false, fetchImpl = fetch,
  pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
}) {
  assert.ok(!liveApproved || researchApproved,
    "Live IQ checks require explicit live and research release approvals.");
  const base = releaseTarget(baseUrl);
  const page = randomUUID(), threadId = randomUUID();
  let cookie = "", summary, lastSent = 0, submissions = 0;
  const headers = () => ({
    "Content-Type": "application/json", Origin: base.origin,
    "X-BC-Client-Version": "6",
    "x-bc-conversation-page": page, "x-bc-research-page": page,
    ...(cookie ? { Cookie: cookie } : {}),
  });
  const request = async (path, options = {}) => {
    const response = await fetchImpl(new URL(path, base), {
      redirect: "error", signal: AbortSignal.timeout(90000), ...options,
      headers: { ...headers(), ...options.headers },
    });
    for (const value of response.headers.getSetCookie()) {
      if (value.startsWith("bc_pilot_session=")) cookie = value.split(";")[0];
    }
    return response;
  };
  const get = async (path) => {
    const response = await request(path);
    assert.equal(response.status, 200, `The ${path} check failed (HTTP ${response.status}).`);
    return response.json();
  };
  const capabilities = await get("/api/capabilities");
  assertReleaseCapabilities(capabilities, { researchApproved });
  const report = {
    target: base.origin, mode: liveApproved ? "live-synthetic" : "read-only",
    supplements: [], cancelled: false, nextSendIndexed: false, submissions: 0,
  };
  if (!liveApproved) return report;
  const sources = (await get("/api/catalog")).sources;
  assert.ok(Array.isArray(sources), "The approved source catalogue is missing.");
  const post = async (path, body, extraHeaders) => {
    assert.ok(submissions < 7, "The bounded IQ check exceeded seven submissions.");
    await pause(Math.max(0, 8000 - (Date.now() - lastSent)));
    lastSent = Date.now();
    submissions++;
    return request(path, { method: "POST", body: JSON.stringify(body), headers: extraHeaders });
  };
  const normal = async (text) => {
    const runId = randomUUID();
    const response = await post("/api/agent", {
      threadId, runId, tools: [], context: [], state: {},
      messages: [{ id: randomUUID(), role: "user", content: text }],
      forwardedProps: { bc: { version: 5, mode: "general", conversation: {
        action: "respond", revision: summary?.revision ?? 0,
        noticeVersion: "ai-conversation-v1", shareContext: false,
        ...(summary?.question ? { questionId: summary.question.id } : {}),
      } } },
    });
    assert.equal(response.status, 200, `Normal chat failed (HTTP ${response.status}); do not reset limits.`);
    const result = decodeReleaseEvents(await readReleaseEvents(response), threadId, summary?.revision ?? 0);
    assert.ok(result.events.some((event) => event.name === "bc.response"
      && event.value.kind === "grounded" && event.value.origin === "model"),
    "The normal request must still use the grounded indexed route.");
    assert.ok(result.events.some((event) => event.name === "annotations" && event.value.annotations?.length),
      "The ordinary answer must retain its indexed citations.");
    assert.ok(!result.events.some((event) => event.name === "bc.research.result"),
      "Normal Send must not start optional research.");
    summary = result.summary;
    return { ...result, runId };
  };
  const expired = async (response) => {
    assert.equal(response.status, 409, "Invalid research scope must be rejected before provider work.");
    const body = await response.json();
    assert.equal(body.error?.code, "RESEARCH_EXPIRED");
  };
  try {
    const parent = await normal("What can Service BC help with?");
    const offers = parent.events.filter((event) => event.name === "bc.research.offer");
    assert.equal(offers.length, 1, "The completed public answer needs one research offer.");
    const offer = offers[0].value;
    assert.equal(offer.version, 1);
    assert.equal(offer.parentRunId, parent.runId);
    assert.equal(offer.threadId, threadId);
    assert.ok(parent.events.some((event) => event.type === "TEXT_MESSAGE_START"
      && event.messageId === offer.parentMessageId), "The offer is not attached to its answer.");
    assert.deepEqual([...offer.actions].sort(), [...actions].sort());
    assert.ok(offer.topics.includes("service-bc") && Date.parse(offer.expiresAt) > Date.now(),
      "The offer needs a current bounded public topic.");
    const original = await get("/api/conversation");
    const body = (action) => ({
      version: 1, action, runId: randomUUID(), threadId,
      parentRunId: offer.parentRunId, parentMessageId: offer.parentMessageId,
      geography: "british-columbia",
    });
    await expired(await post("/api/research", body("web-check"), {
      "x-bc-research-page": randomUUID(),
    }));
    for (const action of actions) {
      const input = body(action);
      const events = await readReleaseEvents(await post("/api/research", input));
      report.supplements.push(assertSupplement(events, input, sources));
      assert.ok(isDeepStrictEqual(await get("/api/conversation"), original),
        "Optional research changed the ordinary conversation.");
    }
    const stopped = body("web-check");
    let cancellationRequested = false;
    const cancelled = await readReleaseEvents(await post("/api/research", stopped), async (event) => {
      if (event.type !== "RUN_STARTED" || cancellationRequested) return;
      cancellationRequested = true;
      const response = await request(`/api/runs/${stopped.runId}/cancel`, { method: "POST" });
      assert.ok([200, 202].includes(response.status),
        "Cancellation was not accepted; a completed-before-cancel race is not a cancellation pass.");
      const state = await response.json();
      assert.ok(state.runId === stopped.runId && ["cancelling", "cancelled"].includes(state.status),
        "Cancellation acknowledgement did not match the owned run.");
    });
    assert.ok(cancellationRequested && cancelled.some((event) => event.type === "RUN_ERROR"
      && event.code === "CANCELLED"), "The running research request did not confirm cancellation.");
    assert.ok(!cancelled.some((event) => event.name === "bc.research.result"),
      "Cancelled research must not publish a supplement.");
    const acknowledgement = await request(`/api/runs/${stopped.runId}/cancel`, { method: "POST" });
    assert.equal(acknowledgement.status, 200, "The cancelled run was not finalized.");
    const state = await acknowledgement.json();
    assert.ok(state.runId === stopped.runId && state.status === "cancelled",
      "The owned run did not reach its cancelled terminal state.");
    assert.ok(isDeepStrictEqual(await get("/api/conversation"), original),
      "Stopping research changed the ordinary conversation.");
    report.cancelled = true;
    await normal("What is the Health Connect Registry?");
    report.nextSendIndexed = true;
    assert.ok(Date.parse(offer.expiresAt) > Date.now(), "The offer expired before revocation was checked.");
    const revoked = await request("/api/research", { method: "DELETE" });
    assert.equal(revoked.status, 204, "The research page could not be revoked.");
    await expired(await post("/api/research", body("corpus-explore")));
    report.submissions = submissions;
    return report;
  } finally {
    if (cookie) {
      const cleanup = await Promise.allSettled(["/api/research", "/api/conversation"].map(async (path) => {
        const response = await request(path, { method: "DELETE" });
        assert.equal(response.status, 204);
      }));
      assert.ok(cleanup.every((result) => result.status === "fulfilled"),
        "The IQ check could not clear its own synthetic page state.");
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const target = process.argv.find((argument) => argument.startsWith("--url="))?.slice(6);
    assert.ok(target, "Select the exact reviewed application with --url=https://your-app/.");
    const report = await verifyOptionalResearch({
      baseUrl: target, liveApproved: process.argv.includes("--live-approved"),
      researchApproved: process.argv.includes("--research-approved"),
    });
    console.log(JSON.stringify({ passed: true, ...report }, null, 2));
  } catch (error) {
    console.error(JSON.stringify({
      passed: false,
      stage: error instanceof Error ? error.releaseStage : undefined,
      error: error instanceof assert.AssertionError
        ? error.message.split("\n")[0]
        : "IQ verification failed; inspect transport and contract metadata without logging response content.",
    }));
    process.exitCode = 1;
  }
}
