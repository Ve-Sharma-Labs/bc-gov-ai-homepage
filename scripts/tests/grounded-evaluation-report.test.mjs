import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";
import { summarizeFailure, summarizeResult } from "../grounded-evaluation-report.mjs";

const privateText = "PRIVATE_EVALUATION_CANARY_resident@example.invalid";
const root = fileURLToPath(new URL("../../", import.meta.url));
const outputDirectory = join(root, "test-results", `grounded-report-tests-${randomUUID()}`);
after(() => rm(outputDirectory, { recursive: true, force: true }));

test("reports allowlist metadata, counts and flags without changing full in-memory turns", () => {
  const error = new assert.AssertionError({
    message: privateText, actual: privateText, expected: privateText, operator: "strictEqual",
  });
  const originalMessage = error.message;
  const turn = {
    prompt: privateText,
    text: privateText,
    response: { origin: "model", kind: "grounded", details: privateText },
    state: { question: { id: privateText, text: privateText }, resident: privateText },
    task: { task: { municipality: privateText } },
    citations: [{ title: privateText, url: `https://example.invalid/${privateText}`, metadata: { secret: privateText } }],
    errors: [{ code: privateText, message: privateText }],
    warnings: [{ message: privateText }],
  };
  const result = {
    case: "job-loss-to-ei", expectedBehaviour: ["Use official evidence."], passed: false,
    turns: [turn], error, failureContext: { phase: "validate-turn", turn: 1, status: 200 },
    cleanupError: new Error(privateText), cleanupContext: { phase: "cleanup", status: 503 },
    unrelated: privateText,
  };
  const summary = summarizeResult(result);
  assert.deepEqual(summary, {
    case: "job-loss-to-ei", expectedBehaviour: ["Use official evidence."], passed: false,
    turns: [{
      hasText: true, hasState: true, modelResponse: true, groundedResponse: true,
      citationCount: 1, errorCount: 1, warningCount: 1,
    }],
    error: { phase: "validate-turn", code: "assertion_failed", turn: 1, status: 200 },
    cleanupError: { phase: "cleanup", code: "unexpected_error", status: 503 },
  });
  assert.ok(!JSON.stringify(summary).includes(privateText));
  assert.equal(result.turns[0], turn);
  assert.equal(turn.text, privateText);
  assert.equal(turn.state.question.text, privateText);
  assert.equal(result.error, error);
  assert.equal(error.message, originalMessage);
});

test("diagnostics never copy arbitrary names, messages, contexts or exception details", () => {
  const error = Object.assign(new Error(privateText), {
    name: privateText, code: privateText, cause: new Error(privateText), actual: privateText,
  });
  assert.deepEqual(summarizeFailure(error, {
    phase: privateText, turn: privateText, status: privateText, details: privateText,
  }), { phase: "evaluation", code: "unexpected_error" });
  for (const [name, code] of [
    ["AssertionError", "assertion_failed"], ["SyntaxError", "invalid_json"],
    ["TimeoutError", "timed_out"], ["AbortError", "aborted"], ["TypeError", "type_error"],
  ]) {
    assert.deepEqual(summarizeFailure({ name, message: privateText, stack: privateText }),
      { phase: "evaluation", code });
  }
  for (const value of [undefined, null, privateText, Number.NaN, Number.POSITIVE_INFINITY, -1, 0, 1.5]) {
    assert.deepEqual(summarizeFailure(value, { turn: value, status: value }),
      { phase: "evaluation", code: "unexpected_error" });
  }
  for (const status of [99, 600, "500"]) {
    assert.deepEqual(summarizeFailure(null, { status }), { phase: "evaluation", code: "unexpected_error" });
  }
});

test("unknown response values and malformed collections cannot become report text", () => {
  assert.deepEqual(summarizeResult({
    case: "job-loss-to-ei", expectedBehaviour: [], passed: true,
    turns: [{
      text: null, state: null, response: { origin: privateText, kind: privateText },
      citations: privateText, errors: { message: privateText }, warnings: null,
    }],
  }), {
    case: "job-loss-to-ei", expectedBehaviour: [], passed: true,
    turns: [{
      hasText: false, hasState: false, modelResponse: false, groundedResponse: false,
      citationCount: 0, errorCount: 0, warningCount: 0,
    }],
  });
});

// Each CLI run replaces fetch completely; neither the app nor a model is contacted.
async function mockedCli({ script, output, scenario, privateText }) {
  process.env.PILOT_BASE_URL = scenario === "invalid-config" ? privateText : "http://127.0.0.1:43210";
  if (scenario === "remote-base") process.env.PILOT_BASE_URL = "https://example.invalid";
  process.argv = [process.execPath, script, "--case=job-loss-to-ei", `--output=${output}`];
  if (scenario !== "missing-approval") process.argv.push("--live-approved");
  globalThis.setTimeout = (callback) => { callback(); return 0; };
  let turnNumber = 0;
  globalThis.fetch = async (input, options) => {
    const url = new URL(input);
    if (url.pathname === "/api/capabilities") {
      if (scenario === "capabilities-json-error") return new Response(privateText);
      return Response.json({
        requestVersions: [6], conversationAgentReady: true, retrievalReady: true, localEvidenceEvaluation: true,
      });
    }
    if (url.pathname === "/api/conversation") {
      if (options.method !== "DELETE") throw new Error(privateText);
      if (scenario === "cleanup-rejection") throw new Error(privateText);
      if (scenario === "cleanup-http-error") return new Response(privateText, { status: 503 });
      return new Response(null, { status: 204 });
    }
    if (url.pathname !== "/api/agent") throw new Error(privateText);
    if (scenario === "request-error") throw new Error(privateText);
    const headers = { "set-cookie": `bc_pilot_session=${privateText}; HttpOnly` };
    if (scenario === "raw-http-error") return new Response(privateText, { status: 500, headers });
    if (scenario === "malformed-events") return new Response(`data: ${privateText}\n`, { headers });
    turnNumber += 1;
    const body = JSON.parse(options.body);
    if (body.forwardedProps.bc.conversation.revision !== turnNumber - 1) throw new Error(privateText);
    const replies = ["Here are EI next steps.", "You can apply for EI online.", "You can apply without your ROE."];
    if (scenario === "outcome-assertion") replies[1] = "This does not answer the question.";
    const events = [
      { type: "TEXT_MESSAGE_CONTENT", delta: `${replies[turnNumber - 1]} ${privateText}` },
      { name: "bc.response", value: { origin: "model", kind: "grounded", details: privateText } },
      { name: "bc.conversation", value: { revision: turnNumber, questionCount: 0, resident: privateText } },
      { name: "bc.task", value: { task: { municipality: privateText } } },
      { name: "annotations", value: { annotations: [{
        url: `https://www.canada.ca/ei?secret=${privateText}`, title: privateText,
        metadata: { version: 2, useScope: "local-noncommercial-evaluation", humanReviewed: false, details: privateText },
      }] } },
    ];
    if (scenario === "turn-assertion") events.push({ type: "RUN_ERROR", message: privateText });
    if (scenario === "warning-assertion") events.push({ name: "bc.warning", value: { message: privateText } });
    events.push({ type: "RUN_FINISHED" });
    return new Response(events.map((event) => `data: ${JSON.stringify(event)}\n`).join(""), { headers });
  };
  await import(script);
}

for (const { scenario, error, cleanupError, turns = 3, noReport = false } of [
  { scenario: "success" },
  { scenario: "outcome-assertion", error: { phase: "check-outcome", code: "assertion_failed" } },
  { scenario: "turn-assertion", error: { phase: "validate-turn", code: "assertion_failed", turn: 1, status: 200 }, turns: 1 },
  { scenario: "warning-assertion", error: { phase: "validate-turn", code: "assertion_failed", turn: 1, status: 200 }, turns: 1 },
  { scenario: "raw-http-error", error: { phase: "response", code: "assertion_failed", turn: 1, status: 500 }, turns: 0 },
  { scenario: "malformed-events", error: { phase: "parse-events", code: "invalid_json", turn: 1, status: 200 }, turns: 0 },
  { scenario: "request-error", error: { phase: "request", code: "unexpected_error", turn: 1 }, turns: 0 },
  { scenario: "cleanup-http-error", cleanupError: { phase: "cleanup", code: "assertion_failed", status: 503 } },
  { scenario: "cleanup-rejection", cleanupError: { phase: "cleanup", code: "unexpected_error" } },
  { scenario: "capabilities-json-error", error: { phase: "capabilities", code: "invalid_json" }, noReport: true },
  { scenario: "invalid-config", error: { phase: "configuration", code: "type_error" }, noReport: true },
  { scenario: "missing-approval", error: { phase: "approval", code: "assertion_failed" }, noReport: true },
  { scenario: "remote-base", error: { phase: "approval", code: "assertion_failed" }, noReport: true },
]) {
  test(`offline CLI ${scenario} minimizes both persisted and console diagnostics`, async () => {
    const output = join(outputDirectory, `${scenario}.json`);
    const script = new URL("../evaluate-grounded-conversation.mjs", import.meta.url).href;
    const code = `await (${mockedCli.toString()})(${JSON.stringify({ script, output, scenario, privateText })});`;
    const child = spawnSync(process.execPath, ["--input-type=module", "--eval", code], {
      cwd: root, encoding: "utf8", timeout: 15_000, windowsHide: true,
    });
    assert.ifError(child.error);
    const passed = !error && !cleanupError;
    assert.equal(child.status, passed ? 0 : 1, child.stderr);
    assert.ok(!`${child.stdout}${child.stderr}`.includes(privateText));
    const logs = `${child.stdout}${child.stderr}`.trim().split(/\r?\n/u).map((line) => JSON.parse(line));
    assert.ok(logs.every((entry) => entry.passed === passed));
    if (noReport) {
      assert.deepEqual(logs, [{ passed: false, error }]);
      await assert.rejects(readFile(output), { code: "ENOENT" });
      return;
    }
    const raw = await readFile(output, "utf8");
    assert.ok(!raw.includes(privateText));
    assert.ok(!raw.includes("I just lost my job, what do I do?"));
    const report = JSON.parse(raw);
    assert.equal(report.scope, "local-noncommercial-evaluation");
    assert.equal(report.version, 6);
    assert.equal(report.results.length, 1);
    const result = report.results[0];
    assert.equal(result.case, "job-loss-to-ei");
    assert.ok(result.expectedBehaviour.length > 0);
    assert.equal(result.passed, passed);
    assert.equal(result.turns.length, turns);
    assert.deepEqual(result.error, error);
    assert.deepEqual(result.cleanupError, cleanupError);
    assert.deepEqual(logs[0], {
      case: result.case, passed, turns,
      ...(error ? { error } : {}), ...(cleanupError ? { cleanupError } : {}),
    });
    if (!passed) {
      assert.deepEqual(logs[1], { passed: false, error: { phase: "completion", code: "assertion_failed" } });
    }
    if (turns) {
      assert.deepEqual(result.turns[0], {
        hasText: true, hasState: true, modelResponse: true, groundedResponse: true, citationCount: 1,
        errorCount: scenario === "turn-assertion" ? 1 : 0,
        warningCount: scenario === "warning-assertion" ? 1 : 0,
      });
    }
  });
}
