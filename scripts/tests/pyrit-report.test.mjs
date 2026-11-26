import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { expectedCases, fingerprint } from "../pyrit-evidence.mjs";
import { safePyritReport, trustedPyritProducer } from "../pyrit-report.mjs";

const dataset = JSON.parse(readFileSync(new URL("../../data/evaluations/pyrit-conversation-cases.json", import.meta.url)));
const repository = "owner/repo";
const target = "https://stage.example";
const run = {
  id: 123, run_attempt: 1, head_sha: "a".repeat(40), head_branch: "main",
  head_repository: { full_name: repository }, event: "workflow_dispatch", status: "completed",
  name: "PyRIT - AI red teaming", path: ".github/workflows/pyrit-ai-red-teaming.yml",
};

function fixture() {
  const candidate = {
    kind: "bc-pyrit-candidate", repository, commit: run.head_sha,
    runId: "123", runAttempt: 1, stagingOrigin: target,
    suiteSha256: fingerprint(dataset),
  };
  const rows = [...expectedCases(dataset, "live")].map(([id, definition]) => ({
    id, threat: definition.threat, approach: definition.approach,
    status: "incomplete", code: "NOT_COMPLETED", turns: 0,
  }));
  rows[0] = { ...rows[0], status: "fail", code: "UNAPPROVED_LINK", turns: 1 };
  const report = {
    version: 1, kind: "bc-pyrit", profile: "live", status: "fail",
    suiteSha256: fingerprint(dataset), rubricVersion: dataset.rubric_version,
    identity: {
      repository, commit: run.head_sha, runId: "123", runAttempt: 1,
      target, candidateSha256: fingerprint(candidate),
    },
    startedAt: 1, finishedAt: 2, expectedCases: rows.length, completedCases: 1,
    results: rows, usage: {}, limits: {}, stopCode: null,
  };
  return { candidate, report };
}

test("only exact trusted main-branch producers may supply findings", () => {
  assert.equal(trustedPyritProducer(run, repository), true);
  for (const change of [
    { event: "pull_request" }, { head_branch: "feature" },
    { head_repository: { full_name: "fork/repo" } }, { path: ".github/workflows/other.yml" },
    { status: "in_progress" }, { run_attempt: 0 },
  ]) assert.equal(trustedPyritProducer({ ...run, ...change }, repository), false);
});

test("triage retains deterministic findings and drops unneeded report payloads", () => {
  const { candidate, report } = fixture();
  report.limits = { secretField: "never-forward-this-value" };
  const safe = safePyritReport(report, candidate, dataset, run, repository, target);
  assert.equal(safe.findings[0].confirmed, true);
  assert.ok(!JSON.stringify(safe).includes("never-forward"));
  assert.ok(!Object.hasOwn(safe, "limits"));
});

test("model flags are review requests, and unknown reason text is never forwarded", () => {
  const { candidate, report } = fixture();
  report.results[0].status = "needs-review";
  report.results[0].code = "secret provider output";
  const safe = safePyritReport(report, candidate, dataset, run, repository, target);
  assert.equal(safe.findings[0].confirmed, false);
  assert.equal(safe.findings[0].code, "UNCLASSIFIED_FAILURE");
  assert.ok(!JSON.stringify(safe).includes("secret provider output"));
});

test("wrong attempts, forged targets, duplicate cases and transcript fields are rejected", () => {
  for (const change of [
    (report) => { report.identity.runAttempt++; },
    (report) => { report.identity.target = "https://elsewhere.example"; },
    (report) => { report.results[1] = report.results[0]; },
    (report) => { report.results[0].transcript = "untrusted"; },
    (report) => { report.transcript = "untrusted"; },
  ]) {
    const { candidate, report } = fixture();
    change(report);
    assert.throws(() => safePyritReport(report, candidate, dataset, run, repository, target));
  }
});
