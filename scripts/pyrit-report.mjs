import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, rm, rmdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";
import { expectedCases, fingerprint, pyritWorkflowName, pyritWorkflowPath, reportKeys, validateCoverage } from "./pyrit-evidence.mjs";
import { releaseTarget } from "./verify-pilot-chat.mjs";

const execute = promisify(execFile);
const producers = new Map([
  [pyritWorkflowPath, pyritWorkflowName],
  [".github/workflows/azure-pilot.yml", "BC Gov App - Azure Deployment"],
]);
const actionable = new Set([
  "UNAPPROVED_LINK", "MISSING_OFFICIAL_HANDOFF", "TASK_STATE_CORRUPTED",
  "FACT_STATE_CORRUPTED", "CONSENT_BOUNDARY_FAILED", "SESSION_ISOLATION_FAILED",
]);
const reviewedCodes = new Set([
  ...actionable, "CHECKED", "SEMANTIC_REVIEW_REQUIRED", "NOT_COMPLETED",
  "CLEANUP_FAILED", "RATE_LIMITED", "APP_UNAVAILABLE", "APP_TRANSPORT_FAILED",
  "MODEL_AUTH_FAILED", "MODEL_REPLY_INVALID", "MODEL_UNAVAILABLE",
  "MODEL_TRANSPORT_FAILED", "MODEL_BUDGET_EXHAUSTED", "APP_BUDGET_EXHAUSTED",
  "WALL_BUDGET_EXHAUSTED", "DEPLOYMENT_CHANGED", "EXECUTION_FAILED",
  "JUDGE_UNDETERMINED", "CANDIDATE_IDENTITY_NOT_VERIFIED",
]);

export function trustedPyritProducer(run, repository) {
  return run?.status === "completed" && producers.get(run.path) === run.name
    && ["workflow_dispatch", "schedule"].includes(run.event)
    && run.head_branch === "main" && run.head_repository?.full_name === repository
    && /^[a-f0-9]{40}$/.test(run.head_sha || "")
    && Number.isSafeInteger(run.run_attempt) && run.run_attempt > 0;
}

export function safePyritReport(report, candidate, dataset, run, repository, target) {
  assert.ok(trustedPyritProducer(run, repository), "UNTRUSTED_PRODUCER");
  assert.deepEqual(Object.keys(report).sort(), [...reportKeys].sort(), "UNSAFE_REPORT_FIELDS");
  assert.equal(releaseTarget(target).origin, target, "EXACT_TARGET_REQUIRED");
  assert.equal(candidate.kind, "bc-pyrit-candidate", "INVALID_CANDIDATE");
  assert.equal(candidate.repository, repository, "WRONG_REPOSITORY");
  assert.equal(candidate.commit, run.head_sha, "WRONG_COMMIT");
  assert.equal(candidate.runId, String(run.id), "WRONG_RUN");
  assert.equal(candidate.runAttempt, run.run_attempt, "WRONG_ATTEMPT");
  assert.equal(candidate.stagingOrigin, target, "WRONG_TARGET");
  assert.equal(report.identity?.candidateSha256, fingerprint(candidate), "CANDIDATE_CHANGED");
  assert.equal(report.identity?.target, target, "WRONG_TARGET");
  for (const key of ["repository", "commit", "runId", "runAttempt"]) {
    assert.equal(report.identity[key], candidate[key], "REPORT_IDENTITY_MISMATCH");
  }
  assert.equal(report.version, 1, "UNSUPPORTED_REPORT");
  assert.equal(report.kind, "bc-pyrit", "UNSUPPORTED_REPORT");
  assert.equal(report.profile, "live", "LIVE_REPORT_REQUIRED");
  assert.equal(report.suiteSha256, fingerprint(dataset), "SUITE_MISMATCH");
  assert.equal(candidate.suiteSha256, report.suiteSha256, "SUITE_MISMATCH");
  const statuses = new Set(["pass", "fail", "needs-review", "incomplete"]);
  assert.ok(statuses.has(report.status), "UNKNOWN_STATUS");
  const expected = expectedCases(dataset, "live");
  if (report.status === "pass") validateCoverage(report, dataset, "live");
  assert.equal(report.expectedCases, expected.size, "INCOMPLETE_MANIFEST");
  assert.ok(Number.isSafeInteger(report.completedCases) && report.completedCases >= 0
    && report.completedCases <= expected.size, "INVALID_COMPLETION_COUNT");
  assert.ok(Array.isArray(report.results) && report.results.length === expected.size, "MISSING_CASES");
  const seen = new Set();
  const findings = [];
  for (const result of report.results) {
    assert.deepEqual(Object.keys(result).sort(), ["approach", "code", "id", "status", "threat", "turns"],
      "UNSAFE_RESULT_FIELDS");
    const definition = expected.get(result.id);
    assert.ok(definition && !seen.has(result.id), "UNKNOWN_OR_DUPLICATED_CASE");
    seen.add(result.id);
    assert.equal(result.threat, definition.threat, "THREAT_MISMATCH");
    assert.equal(result.approach, definition.approach, "APPROACH_MISMATCH");
    assert.ok(statuses.has(result.status) && Number.isSafeInteger(result.turns)
      && result.turns >= 0 && result.turns <= definition.turns, "INVALID_CASE_RESULT");
    if (result.status !== "pass") {
      const code = reviewedCodes.has(result.code) ? result.code : "UNCLASSIFIED_FAILURE";
      findings.push({
        scenario: result.id, threat: result.threat, approach: result.approach,
        status: result.status, code,
        confirmed: result.status === "fail" && actionable.has(code),
        fingerprint: fingerprint({ scenario: result.id.split("/").slice(0, 2), threat: result.threat, code }),
      });
    }
  }
  return {
    mode: "pyrit", version: 1, status: report.status,
    repository, commit: run.head_sha, runId: String(run.id), runAttempt: run.run_attempt,
    target, expectedCases: expected.size, completedCases: report.completedCases,
    stopCode: report.stopCode
      ? reviewedCodes.has(report.stopCode) ? report.stopCode : "UNCLASSIFIED_FAILURE"
      : null,
    findings,
  };
}

export async function collectPyritReport({ repository, runId, target, output, run = execute }) {
  assert.ok(/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository || "")
    && /^[1-9]\d*$/.test(runId || ""), "INVALID_PRODUCER_REFERENCE");
  const gh = async (endpoint, binary = false) => {
    const response = await run("gh", ["api", endpoint], {
      encoding: binary ? "buffer" : "utf8", maxBuffer: 2_500_000, timeout: 60_000,
    });
    return binary ? response.stdout : JSON.parse(response.stdout);
  };
  const producer = await gh(`/repos/${repository}/actions/runs/${runId}`);
  assert.ok(trustedPyritProducer(producer, repository), "UNTRUSTED_PRODUCER");
  const artifacts = await gh(`/repos/${repository}/actions/runs/${runId}/artifacts?per_page=100`);
  assert.equal(artifacts.total_count, artifacts.artifacts.length, "INCOMPLETE_ARTIFACT_LIST");
  const selected = artifacts.artifacts.filter((item) =>
    item.name === `pyrit-live-${producer.run_attempt}` && !item.expired);
  assert.equal(selected.length, 1, "PYRIT_REPORT_UNAVAILABLE");
  assert.ok(selected[0].size_in_bytes <= 2_000_000, "ARTIFACT_TOO_LARGE");
  const seed = await gh(`/repos/${repository}/contents/data/evaluations/pyrit-conversation-cases.json?ref=${producer.head_sha}`);
  assert.ok(seed.encoding === "base64" && seed.size <= 256_000, "INVALID_SUITE_SOURCE");
  const dataset = JSON.parse(Buffer.from(seed.content, "base64").toString("utf8"));
  const directory = await mkdtemp(path.join(tmpdir(), "bc-pyrit-report-"));
  try {
    const archive = path.join(directory, "artifact.zip");
    await writeFile(archive, await gh(`/repos/${repository}/actions/artifacts/${selected[0].id}/zip`, true), { mode: 0o600 });
    const extracted = await run("python", [
      fileURLToPath(new URL("./read-pyrit-artifact.py", import.meta.url)), archive,
    ], { maxBuffer: 2_100_000, timeout: 30_000 });
    const values = JSON.parse(extracted.stdout);
    const safe = safePyritReport(values["report.json"], values["candidate.json"], dataset, producer, repository, target);
    await mkdir(path.dirname(output), { recursive: true });
    await writeFile(output, JSON.stringify(safe, null, 2) + "\n", { mode: 0o600 });
    return safe;
  } finally {
    await rm(path.join(directory, "artifact.zip"), { force: true });
    await rmdir(directory);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    await collectPyritReport({
      repository: process.env.GITHUB_REPOSITORY,
      runId: process.env.UPSTREAM_RUN_ID,
      target: process.env.PYRIT_ALLOWED_ORIGIN,
      output: process.argv[2],
    });
    console.log("Validated and sanitized the producer's threat report.");
  } catch {
    console.error("PYRIT_REPORT_BLOCKED");
    process.exitCode = 1;
  }
}
