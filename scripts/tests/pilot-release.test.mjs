import assert from "node:assert/strict";
import test from "node:test";
import {
  assertReleaseCapabilities, decodeReleaseTurn, releaseTarget, verifyPilotChat,
} from "../verify-pilot-chat.mjs";

const capabilities = {
  mode: "foundry", aiConfigured: true, generalChatConfigured: true,
  conversationAvailable: true, conversationAgentReady: true, taskAssistanceAvailable: true,
  journeys: Object.fromEntries([
    "licence-renewal", "road-test-booking", "rental-assistance", "health-coverage",
    "pharmacare-registration", "primary-care", "service-bc",
  ].map((id) => [id, true])),
  requestVersions: [1, 2, 3, 5], retrievalReady: true, transactionsEnabled: false,
  webIqEnabled: false, localEvidenceEvaluation: false,
  sourceHealth: { status: "ready", usableDocuments: 4, coveredSourceIds: ["health", "healthlink-bc", "service-bc"] },
};

test("release verification rejects legacy, unready, stale, and local-only deployments", () => {
  assert.doesNotThrow(() => assertReleaseCapabilities(capabilities));
  for (const change of [
    { mode: "guided" },
    { generalChatConfigured: false },
    { journeys: { ...capabilities.journeys, "licence-renewal": false } },
    { requestVersions: [1, 2, 3] },
    { conversationAgentReady: false },
    { taskAssistanceAvailable: false },
    { retrievalReady: false },
    { sourceHealth: { ...capabilities.sourceHealth, status: "expired", usableDocuments: 0 } },
    { sourceHealth: { ...capabilities.sourceHealth, status: "expiring" } },
    { sourceHealth: { ...capabilities.sourceHealth, coveredSourceIds: ["taxes"] } },
    { requestVersions: [1, 2, 3, 5, 6] },
    { localEvidenceEvaluation: true },
    { transactionsEnabled: true },
    { webIqEnabled: true },
  ]) assert.throws(() => assertReleaseCapabilities({ ...capabilities, ...change }));
});

test("the release target never accepts credentials or an insecure remote origin", () => {
  assert.equal(releaseTarget("https://pilot.example/").origin, "https://pilot.example");
  assert.equal(releaseTarget("http://127.0.0.1:3000").port, "3000");
  for (const url of [
    "http://pilot.example", "https://user:secret@pilot.example", "https://pilot.example/chat",
    "https://pilot.example/?token=secret", "file:///tmp/app", "https://pilot.example/#fragment",
  ]) assert.throws(() => releaseTarget(url));
});

const frame = (events) => events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
const validTurn = [
  { type: "RUN_STARTED" },
  { type: "TEXT_MESSAGE_CONTENT", delta: "Is it a B.C.-issued licence?" },
  { type: "CUSTOM", name: "bc.conversation", value: { threadId: "thread", revision: 1, shareContext: false } },
  { type: "CUSTOM", name: "bc.task", value: { threadId: "thread", revision: 1, task: null } },
  { type: "RUN_FINISHED" },
];

test("HTTP success and RUN_FINISHED cannot disguise a supported-task refusal", () => {
  assert.ok(decodeReleaseTurn(frame(validTurn), "thread", 0).text);
  const refusal = structuredClone(validTurn);
  refusal[1].delta = "I don't have current, reviewed source information to answer that reliably.";
  assert.throws(() => decodeReleaseTurn(frame(refusal), "thread", 0), /generic source-unavailable/);
  assert.throws(() => decodeReleaseTurn(frame(validTurn), "different-thread", 0), /different conversation/);
  assert.throws(() => decodeReleaseTurn(frame(validTurn), "thread", 1), /revision/);
  assert.throws(() => decodeReleaseTurn(frame(validTurn.slice(0, -1)), "thread", 0), /finish/);
  const error = [...validTurn.slice(0, -1), { type: "RUN_ERROR", code: "SOURCES_UNAVAILABLE" }, validTurn.at(-1)];
  assert.throws(() => decodeReleaseTurn(frame(error), "thread", 0), /run error/);
});

test("read-only verification makes no chat, cleanup, or model requests", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ path: url.pathname, method: options.method ?? "GET" });
    assert.equal(options.redirect, "error");
    if (url.pathname === "/api/capabilities") {
      assert.equal(options.headers?.["X-BC-Client-Version"], "6");
    }
    return Response.json(url.pathname === "/api/capabilities" ? {
      ...capabilities, sourceHealth: { ...capabilities.sourceHealth, untrustedExtra: "PRIVATE-FIXTURE" },
    } : {
      journeys: [
        "licence-renewal", "road-test-booking", "rental-assistance", "health-coverage",
        "pharmacare-registration", "primary-care", "service-bc",
      ].map((id) => ({ id, steps: [{}], handoffs: [{}] })),
    });
  };
  const result = await verifyPilotChat({ baseUrl: "https://pilot.example/", fetchImpl });
  assert.equal(result.mode, "read-only");
  assert.equal(result.turns, 0);
  assert.ok(!JSON.stringify(result).includes("PRIVATE-FIXTURE"));
  assert.deepEqual(calls, [
    { path: "/api/capabilities", method: "GET" }, { path: "/api/catalog", method: "GET" },
  ]);
});

test("verification discovers experimental capabilities using the browser's protocol header", async () => {
  let calls = 0;
  await assert.rejects(verifyPilotChat({
    baseUrl: "https://pilot.example/", liveApproved: true,
    fetchImpl: async (url, options) => {
      calls++;
      assert.equal(url.pathname, "/api/capabilities");
      return Response.json({
        ...capabilities,
        requestVersions: options.headers?.["X-BC-Client-Version"] === "6"
          ? [1, 2, 3, 5, 6] : [1, 2, 3, 5],
      });
    },
  }), /experimental\/local-only/);
  assert.equal(calls, 1);
});

test("the approved probe is bounded, follows pending questions, and clears only its own sessions", async () => {
  const states = new Map();
  const calls = [];
  let cleaned = 0;
  const fetchImpl = async (url, options) => {
    if (url.pathname === "/api/capabilities") return Response.json(capabilities);
    if (url.pathname === "/api/catalog") return Response.json({ journeys: [
      "licence-renewal", "road-test-booking", "rental-assistance", "health-coverage",
      "pharmacare-registration", "primary-care", "service-bc",
    ].map((id) => ({ id, steps: [{}], handoffs: [{}] })) });
    const page = options.headers["x-bc-conversation-page"];
    if (options.method === "DELETE") {
      assert.equal(url.pathname, "/api/conversation");
      assert.ok(states.delete(page), "Cleanup must address a page created by this probe.");
      cleaned++;
      return new Response(null, { status: 204 });
    }
    const input = JSON.parse(options.body);
    calls.push(input);
    assert.equal(input.forwardedProps.bc.version, 5);
    assert.equal(input.messages.length, 1);
    assert.equal(input.forwardedProps.bc.conversation.shareContext, false);
    const text = input.messages[0].content;
    const prior = states.get(page);
    const revision = (prior?.revision ?? 0) + 1;
    assert.equal(input.forwardedProps.bc.conversation.revision, revision - 1);
    if (prior?.question) {
      assert.equal(input.forwardedProps.bc.conversation.questionId, prior.question.id);
    }
    let question = null;
    let goal = prior?.goal ?? "licence-renewal";
    let journeyId = prior?.journeyId ?? null;
    let task = prior?.task ?? null;
    let answer = "Open https://www.icbc.com/driver-licensing/visit-dl-office/Accepted-ID";
    if (text.includes("renew my drivers license")) question = { id: "issuer", factKey: "licence-jurisdiction" };
    if (text === "Yes") {
      journeyId = "licence-renewal";
      task = { id: "fixture-task", activeStepId: "prepare-identification", reviewedStepIds: [] };
    }
    if (text === "I have my ID") task = { ...task, waitingFor: "municipality", reviewedStepIds: ["prepare-identification"] };
    if (text === "Vancouver") {
      task = { ...task, municipality: "Vancouver" };
      answer = "Open https://www.icbc.com/locators";
    }
    if (text === "Issued somewhere else") question = { id: "route", factKey: null };
    if (text === "Renew with the original issuer") answer = "Use the original issuer.";
    for (const [phrase, selected, response] of [
      ["guardianship", "caregiving", "substitute-decision-making"],
      ["disability", "disability", "disability-assistance"],
      ["lost my job", "job-loss", "workbc.ca"],
    ]) {
      if (text.includes(phrase)) {
        goal = selected;
        if (!prior) question = { id: `${goal}-question`, factKey: null };
      }
      if (goal === selected) answer = `Official fixture link: ${response}`;
    }
    const grounded = text === "What is the Health Connect Registry?";
    const summary = { threadId: input.threadId, revision, shareContext: false, goal, journeyId, question };
    states.set(page, { ...summary, task });
    const events = [
      { type: "RUN_STARTED" },
      { type: "CUSTOM", name: "bc.response", value: { kind: grounded ? "grounded" : "handoff", origin: grounded ? "model" : "application" } },
      { type: "TEXT_MESSAGE_CONTENT", delta: answer },
      { type: "CUSTOM", name: "bc.conversation", value: summary },
      { type: "CUSTOM", name: "bc.task", value: { threadId: input.threadId, revision, task } },
      ...(grounded ? [{ type: "CUSTOM", name: "annotations", value: { annotations: [{}] } }] : []),
      { type: "RUN_FINISHED" },
    ];
    return new Response(frame(events), { headers: {
      "Content-Type": "text/event-stream", "Set-Cookie": "bc_pilot_session=fixture-owner; HttpOnly",
    } });
  };
  const report = await verifyPilotChat({
    baseUrl: "https://pilot.example/", liveApproved: true, fetchImpl, pause: async () => {},
  });
  assert.equal(report.turns, 16);
  assert.equal(calls.length, 16);
  assert.equal(report.cases.length, 6);
  assert.equal(cleaned, 6);
  assert.equal(states.size, 0);
});

test("a stale deployment fails before any billable probe, even with live approval", async () => {
  let calls = 0;
  await assert.rejects(verifyPilotChat({
    baseUrl: "https://pilot.example/", liveApproved: true,
    fetchImpl: async (url) => {
      calls++;
      assert.equal(url.pathname, "/api/capabilities");
      return Response.json({ ...capabilities, retrievalReady: false });
    },
  }), /current, verified source coverage/);
  assert.equal(calls, 1);
});
