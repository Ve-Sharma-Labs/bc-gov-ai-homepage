import assert from "node:assert/strict";
import test from "node:test";
import policy from "../../data/evaluations/foundry-release-policy.json" with { type: "json" };
import { collectFoundryEvaluation } from "../collect-foundry-evaluation.mjs";
import { releaseCases } from "../verify-pilot-chat.mjs";

const fakeVerification = (change = () => {}) => async ({ observeTurn }) => {
  const report = { mode: "live-synthetic", coverage: "full", cases: [], turns: 0 };
  for (const scenario of policy.cases) {
    for (const [index, turn] of scenario.turns.entries()) {
      const observed = {
        caseId: scenario.id, turn: index + 1, query: turn.query,
        response: `Synthetic response for ${scenario.id} turn ${index + 1}.`,
        cookie: "not-for-export", toolBody: "not-for-export",
      };
      change(observed, report);
      observeTurn(observed);
      report.turns++;
    }
    report.cases.push({
      name: releaseCases[scenario.id], passed: true, turns: scenario.turns.length,
    });
  }
  return report;
};

test("Foundry capture requires explicit approval and an isolated candidate before any requests", async () => {
  for (const options of [
    { baseUrl: "http://127.0.0.1:8000", approved: false },
    { baseUrl: "https://public.example/", approved: true },
    { baseUrl: "http://localhost:8000/?token=fixture", approved: true },
  ]) {
    await assert.rejects(collectFoundryEvaluation({
      ...options, verify: async () => assert.fail("Unapproved collection reached the app."),
    }));
  }
});

test("synthetic capture includes prior dialogue for short answers but never state or tool bodies", async () => {
  const result = await collectFoundryEvaluation({
    baseUrl: "http://127.0.0.1:8000", approved: true, verify: fakeVerification(),
  });
  assert.equal(result.rows.length, 16);
  assert.equal(result.deterministicPassed, true);
  const answer = result.rows.find((row) => row.id === "renewal:2");
  assert.deepEqual(JSON.parse(answer.query), [
    { role: "user", content: "please help me renew my drivers license" },
    { role: "assistant", content: "Synthetic response for renewal turn 1." },
    { role: "user", content: "Yes" },
  ]);
  assert.equal(answer.expected_behavior, policy.cases[0].turns[1].expectedBehavior);
  assert.ok(!JSON.stringify(result).includes("not-for-export"));
});

test("focused, reordered, foreign, missing and oversized observations cannot produce a dataset", async () => {
  for (const change of [
    (_turn, report) => { report.coverage = "focused"; },
    (turn) => { turn.query = "Not a checked-in public question"; },
    (turn) => { turn.caseId = "unknown"; },
    (turn) => { turn.turn++; },
    (turn) => { turn.response = " "; },
    (turn) => { turn.response = "x".repeat(16001); },
  ]) {
    await assert.rejects(collectFoundryEvaluation({
      baseUrl: "http://127.0.0.1:8000", approved: true, verify: fakeVerification(change),
    }));
  }
  await assert.rejects(collectFoundryEvaluation({
    baseUrl: "http://127.0.0.1:8000", approved: true,
    verify: async () => ({ mode: "live-synthetic", coverage: "full", cases: [], turns: 0 }),
  }));
});

test("a deterministic failure or failed cleanup prevents export even after responses were observed", async () => {
  for (const failure of ["outcome failed", "cleanup failed"]) {
    await assert.rejects(collectFoundryEvaluation({
      baseUrl: "http://127.0.0.1:8000", approved: true,
      verify: async (options) => {
        await fakeVerification()(options);
        throw new Error(failure);
      },
    }), new RegExp(failure));
  }
});
