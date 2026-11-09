import assert from "node:assert/strict";
import test from "node:test";
import { readReleaseEvents, verifyOptionalResearch } from "../verify-optional-research.mjs";

const source = {
  id: "service-bc", title: "Service BC", publisher: "Government of British Columbia",
  status: "available", url: "https://www2.gov.bc.ca/gov/content/servicebc",
};
const capabilities = {
  mode: "foundry", aiConfigured: true, generalChatConfigured: true,
  conversationAvailable: true, conversationAgentReady: true, taskAssistanceAvailable: true,
  journeys: Object.fromEntries([
    "licence-renewal", "road-test-booking", "rental-assistance", "health-coverage",
    "pharmacare-registration", "primary-care", "service-bc",
  ].map((id) => [id, true])),
  requestVersions: [1, 2, 3, 5], retrievalReady: true, transactionsEnabled: false,
  webIqEnabled: true, localEvidenceEvaluation: false,
  sourceHealth: { status: "ready", usableDocuments: 4, coveredSourceIds: ["health", "healthlink-bc", "service-bc"] },
  research: {
    version: 1, foundryIq: { available: true, preview: true },
    webIq: { available: true, preview: false },
  },
};
const frame = (events) => events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
const stream = (events) => new Response(frame(events), {
  headers: { "Content-Type": "text/event-stream", "Set-Cookie": "bc_pilot_session=fixture-owner; HttpOnly" },
});

function fixture({ mutateResult = () => {}, completedBeforeCancel = false } = {}) {
  let page, parentRun, parentMessage, summary, revoked = false, controller, cancelled = false;
  const calls = [], cleanups = [];
  let normalCalls = 0, researchCalls = 0;
  const fetchImpl = async (url, options) => {
    calls.push({ path: url.pathname, method: options.method ?? "GET" });
    assert.equal(options.redirect, "error");
    if (url.pathname === "/api/capabilities") return Response.json(capabilities);
    if (url.pathname === "/api/catalog") return Response.json({ sources: [source] });
    if (options.method === "DELETE") {
      assert.equal(options.headers.Cookie, "bc_pilot_session=fixture-owner");
      assert.equal(options.headers["x-bc-conversation-page"], page);
      cleanups.push(url.pathname);
      if (url.pathname === "/api/research") revoked = true;
      if (url.pathname === "/api/conversation") summary = null;
      return new Response(null, { status: 204 });
    }
    if (url.pathname === "/api/conversation") return Response.json(summary);
    if (url.pathname.startsWith("/api/runs/")) {
      const runId = url.pathname.split("/")[3];
      if (completedBeforeCancel) return Response.json({ error: { code: "RUN_FINISHED" } }, { status: 409 });
      if (!cancelled) {
        cancelled = true;
        controller.enqueue(new TextEncoder().encode(frame([{ type: "RUN_ERROR", code: "CANCELLED" }])));
        controller.close();
        return Response.json({ runId, status: "cancelling" }, { status: 202 });
      }
      return Response.json({ runId, status: "cancelled" });
    }
    const body = JSON.parse(options.body);
    if (url.pathname === "/api/agent") {
      normalCalls++;
      page ??= options.headers["x-bc-conversation-page"];
      assert.equal(options.headers["x-bc-research-page"], page);
      assert.equal(body.messages.length, 1);
      assert.equal(body.forwardedProps.bc.conversation.shareContext, false);
      assert.equal(body.forwardedProps.bc.conversation.revision, normalCalls - 1);
      assert.equal(body.messages[0].content, normalCalls === 1
        ? "What can Service BC help with?" : "What is the Health Connect Registry?");
      assert.ok(!JSON.stringify(body).includes("PRIVATE-FIXTURE"));
      parentRun ??= body.runId;
      parentMessage ??= "fixture-answer";
      summary = {
        threadId: body.threadId, revision: normalCalls, shareContext: false, question: null,
        goal: normalCalls === 1 ? "service-bc" : "primary-care",
      };
      return stream([
        { type: "RUN_STARTED", threadId: body.threadId, runId: body.runId },
        { type: "TEXT_MESSAGE_START", messageId: parentMessage },
        { type: "TEXT_MESSAGE_CONTENT", delta: "Reviewed indexed fixture." },
        { type: "CUSTOM", name: "bc.response", value: { kind: "grounded", origin: "model" } },
        { type: "CUSTOM", name: "annotations", value: { annotations: [{}] } },
        { type: "CUSTOM", name: "bc.conversation", value: summary },
        { type: "CUSTOM", name: "bc.task", value: {
          threadId: body.threadId, revision: normalCalls, task: null,
        } },
        { type: "CUSTOM", name: "bc.research.offer", value: {
          version: 1, threadId: body.threadId, parentRunId: body.runId,
          parentMessageId: parentMessage, topics: ["service-bc"],
          actions: ["corpus-explore", "web-check"],
          expiresAt: new Date(Date.now() + 600000).toISOString(),
        } },
        { type: "RUN_FINISHED", threadId: body.threadId, runId: body.runId },
      ]);
    }
    assert.equal(url.pathname, "/api/research", "The verifier used an unexpected endpoint.");
    assert.deepEqual(Object.keys(body).sort(), [
      "version", "action", "runId", "threadId", "parentRunId", "parentMessageId", "geography",
    ].sort());
    assert.equal(body.parentRunId, parentRun);
    assert.equal(body.parentMessageId, parentMessage);
    if (revoked || options.headers["x-bc-research-page"] !== page) {
      return Response.json({ error: { code: "RESEARCH_EXPIRED" } }, { status: 409 });
    }
    researchCalls++;
    const start = { type: "RUN_STARTED", runId: body.runId, threadId: body.threadId };
    if (researchCalls === 3) {
      return new Response(new ReadableStream({
        start(value) {
          controller = value;
          value.enqueue(new TextEncoder().encode(frame([start])));
        },
      }), { headers: { "Content-Type": "text/event-stream" } });
    }
    const retrievedAt = new Date().toISOString();
    const result = {
      version: 1, action: body.action, runId: body.runId,
      parentRunId: body.parentRunId, parentMessageId: body.parentMessageId,
      text: "PRIVATE-FIXTURE", notice: "Distinct research provenance.",
      citations: [body.action === "web-check" ? {
        kind: "web", sourceId: source.id, title: source.title, publisher: source.publisher,
        url: source.url, retrievedAt, humanReviewed: false, quoteLimit: 200, method: "search",
      } : {
        kind: "indexed", retrievedAt, reference: {
          sourceId: source.id, url: source.url, title: source.title, publisher: source.publisher,
          documentId: "fixture-document", documentVersion: "fixture-reviewed-version",
          checkedAt: new Date().toISOString().slice(0, 10),
        },
      }],
    };
    mutateResult(result);
    return stream([
      start,
      { type: "CUSTOM", name: "bc.research.progress", value: { version: 1, phase: "retrieving" } },
      { type: "CUSTOM", name: "bc.research.result", value: result },
      { type: "RUN_FINISHED", runId: body.runId, threadId: body.threadId },
    ]);
  };
  return {
    fetchImpl, calls, cleanups,
    counts: () => ({ normalCalls, researchCalls, cancelled }),
  };
}

test("live IQ checks require both approvals before any network call", async () => {
  await assert.rejects(verifyOptionalResearch({
    baseUrl: "https://pilot.example/", liveApproved: true,
    fetchImpl: async () => assert.fail("Unapproved live checks cannot send requests."),
  }), /explicit live and research/);
});

test("read-only IQ verification makes one capability request and no model calls", async () => {
  const mock = fixture();
  const report = await verifyOptionalResearch({
    baseUrl: "https://pilot.example/", researchApproved: true, fetchImpl: mock.fetchImpl,
  });
  assert.equal(report.mode, "read-only");
  assert.deepEqual(mock.calls, [{ path: "/api/capabilities", method: "GET" }]);
  assert.equal(report.submissions, 0);
});

test("bounded live checks isolate supplements, verify cancellation, and clear only their own page", async () => {
  const mock = fixture();
  const report = await verifyOptionalResearch({
    baseUrl: "https://pilot.example/", liveApproved: true, researchApproved: true,
    fetchImpl: mock.fetchImpl, pause: async () => {},
  });
  assert.deepEqual(mock.counts(), { normalCalls: 2, researchCalls: 3, cancelled: true });
  assert.equal(report.submissions, 7);
  assert.equal(report.cancelled, true);
  assert.equal(report.nextSendIndexed, true);
  assert.deepEqual(report.supplements.map((item) => item.kind), ["indexed", "web"]);
  assert.ok(!JSON.stringify(report).includes("PRIVATE-FIXTURE"));
  assert.deepEqual(mock.cleanups, ["/api/research", "/api/research", "/api/conversation"]);
});

for (const [name, mutate] of [
  ["wrong parent", (value) => { value.parentMessageId = "another-answer"; }],
  ["wrong provenance", (value) => { value.citations[0].kind = "web"; }],
  ["missing indexed review", (value) => { delete value.citations[0].reference.documentVersion; }],
  ["unapproved destination", (value) => { value.citations[0].reference.url = "https://untrusted.example/"; }],
]) test(`live IQ checks reject ${name} and still clear their page`, async () => {
  const mock = fixture({ mutateResult: mutate });
  await assert.rejects(verifyOptionalResearch({
    baseUrl: "https://pilot.example/", liveApproved: true, researchApproved: true,
    fetchImpl: mock.fetchImpl, pause: async () => {},
  }));
  assert.deepEqual(mock.cleanups, ["/api/research", "/api/conversation"]);
  assert.equal(mock.counts().researchCalls, 1);
});

for (const [name, mutate] of [
  ["human-review claim", (value) => { value.humanReviewed = true; }],
  ["unapproved browsing", (value) => { value.method = "browse"; }],
  ["unapproved port", (value) => { value.url = source.url.replace(".ca/", ".ca:8443/"); }],
  ["unapproved path", (value) => { value.url = "https://www2.gov.bc.ca/unreviewed"; }],
  ["copied provider title", (value) => { value.title = "PRIVATE-FIXTURE"; }],
  ["excessive display allowance", (value) => { value.quoteLimit = 201; }],
  ["fabricated indexed provenance", (value) => { value.documentVersion = "fabricated"; }],
]) test(`live IQ checks reject a web ${name}`, async () => {
  const mock = fixture({
    mutateResult: (value) => {
      if (value.action === "web-check") mutate(value.citations[0]);
    },
  });
  await assert.rejects(verifyOptionalResearch({
    baseUrl: "https://pilot.example/", liveApproved: true, researchApproved: true,
    fetchImpl: mock.fetchImpl, pause: async () => {},
  }));
  assert.deepEqual(mock.cleanups, ["/api/research", "/api/conversation"]);
  assert.equal(mock.counts().researchCalls, 2);
});

test("a completed-before-cancel race cannot masquerade as cancellation verification", async () => {
  const mock = fixture({ completedBeforeCancel: true });
  await assert.rejects(verifyOptionalResearch({
    baseUrl: "https://pilot.example/", liveApproved: true, researchApproved: true,
    fetchImpl: mock.fetchImpl, pause: async () => {},
  }), /not a cancellation pass/);
  assert.deepEqual(mock.cleanups, ["/api/research", "/api/conversation"]);
});

test("stream decoding handles split UTF-8 frames without retaining an oversized response", async () => {
  const bytes = new TextEncoder().encode(frame([{ type: "CUSTOM", name: "fixture", value: "caf\u00e9" }]));
  const response = new Response(new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
  assert.deepEqual(await readReleaseEvents(response), [{ type: "CUSTOM", name: "fixture", value: "caf\u00e9" }]);
  let cancelled = false;
  const oversized = new Response(new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(262145)); },
    cancel() { cancelled = true; },
  }), { headers: { "Content-Type": "text/event-stream" } });
  await assert.rejects(readReleaseEvents(oversized), /byte bound/);
  assert.equal(cancelled, true);
});
