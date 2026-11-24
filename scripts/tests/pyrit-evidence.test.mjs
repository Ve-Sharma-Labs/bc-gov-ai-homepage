import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { expectedCases, fingerprint, validateCandidate, validateQualification } from "../pyrit-evidence.mjs";

const dataset = JSON.parse(readFileSync(new URL("../../data/evaluations/pyrit-conversation-cases.json", import.meta.url)));
const now = Date.parse("2026-11-13T23:00:00Z");
const context = {
  repository: "owner/repo", commit: "a".repeat(40), runId: "123", runAttempt: 1,
  stagingOrigin: "https://staging.example", productionOrigin: "https://production.example",
};

function evidence() {
  const expected = expectedCases(dataset, "live");
  const modelLimit = {
    calls: 100, tokens: 10_000_000, cost_microusd: 10_000_000,
    input_bytes: 4096, output_tokens: 1024, token_price_microusd: 1,
  };
  const limits = { app: 100, wall_seconds: 1800, attacker: modelLimit, judge: modelLimit };
  const candidate = {
    version: 1, kind: "bc-pyrit-candidate", ...context,
    createdAt: new Date(now - 300_000).toISOString(),
    images: {
      api: `registry.azurecr.io/api@sha256:${"b".repeat(64)}`,
      web: `registry.azurecr.io/web@sha256:${"c".repeat(64)}`,
    },
    stagingRevisions: { api: "staging-api--candidate", web: "staging-web--candidate" },
    configurationSha256: "d".repeat(64), sourceSha256: "e".repeat(64), modelSha256: "f".repeat(64),
    suiteSha256: fingerprint(dataset), limitsSha256: fingerprint(limits), evaluatorSha256: "1".repeat(64),
  };
  const results = [...expected].map(([id, value]) => ({
    id, threat: value.threat, approach: value.approach, turns: value.turns,
    status: "pass", code: "CHECKED",
  }));
  const usage = {
    app: { calls: results.reduce((sum, item) => sum + item.turns, 0), tokens: 0, costMicrousd: 0 },
  };
  for (const role of ["attacker", "judge"]) {
    const calls = [...expected.values()].reduce((sum, item) => sum + item[role], 0);
    const tokens = calls * (modelLimit.input_bytes + modelLimit.output_tokens + 256);
    usage[role] = { calls, tokens, costMicrousd: tokens };
  }
  const report = {
    version: 1, kind: "bc-pyrit", profile: "live", status: "pass",
    suiteSha256: fingerprint(dataset), rubricVersion: dataset.rubric_version,
    identity: {
      repository: context.repository, commit: context.commit, runId: context.runId,
      runAttempt: context.runAttempt, target: context.stagingOrigin, candidateSha256: fingerprint(candidate),
    },
    startedAt: (now - 240_000) / 1000, finishedAt: (now - 1000) / 1000,
    expectedCases: results.length, completedCases: results.length, results, usage, limits, stopCode: null,
  };
  return { candidate, report };
}

test("qualification accepts only complete threat coverage for the exact candidate", () => {
  const { candidate, report } = evidence();
  assert.equal(validateQualification(report, candidate, dataset, context, now), report);
});

test("required threats and approaches cannot disappear from the suite", () => {
  for (const field of ["threat", "approach"]) {
    const changed = structuredClone(dataset);
    const removed = field === "threat" ? "privacy" : "adaptive-multi-turn";
    changed.cases = changed.cases.filter((item) => item[field] !== removed);
    assert.throws(() => expectedCases(changed, "live"), /MISSING_/);
  }
});

test("a missing or duplicated attempt cannot count as full coverage", () => {
  for (const change of [
    (report) => report.results.pop(),
    (report) => { report.results[1] = report.results[0]; },
    (report) => { report.completedCases--; },
    (report) => { report.results[0].turns = 0; },
  ]) {
    const { candidate, report } = evidence();
    change(report);
    assert.throws(() => validateQualification(report, candidate, dataset, context, now));
  }
});

test("failure, uncertainty, missing adaptive work and exhausted budgets block release", () => {
  for (const change of [
    (report) => { report.results[0].status = "fail"; },
    (report) => { report.results[0].status = "needs-review"; },
    (report) => { report.results[0].status = "incomplete"; },
    (report) => { report.stopCode = "APP_BUDGET_EXHAUSTED"; },
    (report) => { report.usage.attacker.calls = 0; },
    (report) => { report.usage.judge.calls = 1; },
    (report) => { report.limits.app = 1; },
  ]) {
    const { candidate, report } = evidence();
    change(report);
    assert.throws(() => validateQualification(report, candidate, dataset, context, now));
  }
});

test("offline results, changed budgets, candidate edits and old run attempts are rejected", () => {
  for (const change of [
    (report) => { report.profile = "offline"; },
    (report) => { report.identity.runAttempt = 2; },
    (report) => { report.identity.commit = "b".repeat(40); },
    (report) => { report.identity.target = context.productionOrigin; },
    (report) => { report.identity.candidateSha256 = "0".repeat(64); },
    (report) => { report.limits.wall_seconds++; },
  ]) {
    const { candidate, report } = evidence();
    change(report);
    assert.throws(() => validateQualification(report, candidate, dataset, context, now));
  }
});

test("mutable images, public staging and stale evidence cannot qualify", () => {
  for (const change of [
    (candidate) => { candidate.images.api = "registry.azurecr.io/api:latest"; },
    (candidate) => { candidate.stagingOrigin = context.productionOrigin; },
    (candidate) => { candidate.createdAt = new Date(now - 7_200_000).toISOString(); },
    (candidate) => { candidate.createdAt = new Date(now + 7_200_000).toISOString(); },
    (candidate) => { candidate.stagingRevisions.api = "latest"; },
  ]) {
    const { candidate } = evidence();
    change(candidate);
    assert.throws(() => validateCandidate(candidate, context, now));
  }
});

test("reports cannot carry provider text or unrecognized fields", () => {
  const { candidate, report } = evidence();
  report.results[0].transcript = "Untrusted response";
  assert.throws(() => validateQualification(report, candidate, dataset, context, now), /INVALID_RESULT/);
});
