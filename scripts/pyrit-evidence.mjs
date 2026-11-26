import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { pinnedImage } from "./azure-preflight.mjs";
import { releaseTarget } from "./verify-pilot-chat.mjs";

const sha256 = /^[a-f0-9]{64}$/;
const commit = /^[a-f0-9]{40}$/;
const slug = /^[a-z][a-z0-9-]{0,63}$/;
export const pyritWorkflowName = "PyRIT - AI red teaming";
export const pyritWorkflowPath = ".github/workflows/pyrit-ai-red-teaming.yml";
export const liveThreats = new Set([
  "direct-injection", "false-completion", "high-stakes", "grounding", "privacy", "conversation",
]);
export const allThreats = new Set([...liveThreats, "indirect-injection", "resource-exhaustion"]);
const approaches = new Set([
  "fixed-single-turn", "fixed-multi-turn", "adaptive-multi-turn", "prompt-variations", "repeated-attempts",
]);
export const reportKeys = [
  "version", "kind", "profile", "status", "suiteSha256", "rubricVersion", "identity",
  "startedAt", "finishedAt", "expectedCases", "completedCases", "results", "usage", "limits", "stopCode",
];

export function canonical(value) {
  const normalize = (item) => {
    if (Array.isArray(item)) return item.map(normalize);
    if (item && typeof item === "object") {
      return Object.fromEntries(Object.keys(item).sort().map((key) => [key, normalize(item[key])]));
    }
    return item;
  };
  return JSON.stringify(normalize(value))
    .replace(/[\u007f-\uffff]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

export function fingerprint(value) {
  return createHash("sha256").update(canonical(value)).digest("hex");
}

function keys(value, expected, code) {
  assert.ok(value && typeof value === "object" && !Array.isArray(value), code);
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort(), code);
}

function integer(value, minimum = 0, maximum = Number.MAX_SAFE_INTEGER) {
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}

export function expectedCases(dataset, profile) {
  assert.equal(dataset.version, 1, "UNSUPPORTED_SUITE");
  assert.ok(Array.isArray(dataset.cases) && dataset.cases.length >= 8, "INCOMPLETE_SUITE");
  const rows = new Map();
  const seen = new Set();
  const selected = dataset.cases.filter((item) => item.profiles?.includes(profile));
  assert.deepEqual(new Set(selected.map((item) => item.threat)),
    profile === "live" ? liveThreats : allThreats, "MISSING_THREAT");
  assert.deepEqual(new Set(selected.map((item) => item.approach)), approaches, "MISSING_APPROACH");
  assert.ok(selected.some((item) => item.benign === true), "MISSING_BENIGN_CONTROL");
  for (const item of dataset.cases) {
    assert.ok(slug.test(item.id) && !seen.has(item.id), "INVALID_CASE_ID");
    seen.add(item.id);
  }
  for (const item of selected) {
    assert.ok(Array.isArray(item.variants) && item.variants.length > 0, "MISSING_VARIANT");
    const repetitions = item.repetitions ?? 1;
    assert.ok(integer(repetitions, 1, 3), "INVALID_REPETITIONS");
    for (const variant of item.variants) {
      assert.ok(slug.test(variant.id) && Array.isArray(variant.prompts)
        && variant.prompts.length > 0, "INVALID_VARIANT");
      for (let attempt = 1; attempt <= repetitions; attempt++) {
        const id = `${item.id}/${variant.id}/${attempt}`;
        assert.ok(!rows.has(id), "DUPLICATE_ATTEMPT");
        const turns = item.offline_check ? 0
          : (item.approach === "adaptive-multi-turn" ? item.max_turns : variant.prompts.length)
            + Number(item.isolation_probe === true);
        assert.ok(integer(turns, 0, 9), "INVALID_TURN_LIMIT");
        rows.set(id, {
          threat: item.threat, approach: item.approach, turns,
          judge: item.offline_check ? 0 : turns - Number(item.isolation_probe === true),
          attacker: item.approach === "adaptive-multi-turn" ? item.max_turns : 0,
        });
      }
    }
  }
  return rows;
}

export function validateCandidate(value, context, now = Date.now()) {
  keys(value, [
    "version", "kind", "repository", "commit", "runId", "runAttempt", "createdAt",
    "stagingOrigin", "productionOrigin", "images", "stagingRevisions",
    "configurationSha256", "sourceSha256", "modelSha256", "suiteSha256", "limitsSha256", "evaluatorSha256",
  ], "INVALID_CANDIDATE");
  assert.equal(value.version, 1, "INVALID_CANDIDATE");
  assert.equal(value.kind, "bc-pyrit-candidate", "INVALID_CANDIDATE");
  assert.ok(commit.test(value.commit) && /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(value.repository),
    "INVALID_CANDIDATE_IDENTITY");
  assert.ok(/^[1-9]\d*$/.test(value.runId) && integer(value.runAttempt, 1), "INVALID_RUN_IDENTITY");
  for (const field of ["repository", "commit", "runId", "runAttempt", "stagingOrigin", "productionOrigin"]) {
    assert.equal(value[field], context[field], "CANDIDATE_IDENTITY_MISMATCH");
  }
  const created = Date.parse(value.createdAt);
  assert.ok(Number.isFinite(created) && created <= now + 30_000 && now - created <= 3_600_000,
    "STALE_CANDIDATE");
  for (const field of ["stagingOrigin", "productionOrigin"]) {
    const url = releaseTarget(value[field]);
    assert.equal(url.protocol, "https:", "LIVE_ORIGIN_REQUIRED");
    assert.equal(url.origin, value[field], "EXACT_ORIGIN_REQUIRED");
  }
  assert.notEqual(value.stagingOrigin, value.productionOrigin, "STAGING_MUST_BE_SEPARATE");
  keys(value.images, ["api", "web"], "INVALID_IMAGE_PAIR");
  keys(value.stagingRevisions, ["api", "web"], "INVALID_REVISION_PAIR");
  for (const component of ["api", "web"]) {
    assert.ok(pinnedImage.test(value.images[component]), "IMMUTABLE_IMAGE_REQUIRED");
    assert.ok(/^[a-z][a-z0-9-]{2,100}--[a-z0-9][a-z0-9-]{0,63}$/.test(
      value.stagingRevisions[component]), "EXACT_REVISION_REQUIRED");
  }
  for (const field of [
    "configurationSha256", "sourceSha256", "modelSha256", "suiteSha256", "limitsSha256", "evaluatorSha256",
  ]) assert.ok(sha256.test(value[field]), "MISSING_FINGERPRINT");
  return value;
}

export function validateCoverage(report, dataset, profile) {
  keys(report, reportKeys, "INVALID_REPORT");
  assert.equal(report.version, 1, "INVALID_REPORT");
  assert.equal(report.kind, "bc-pyrit", "INVALID_REPORT");
  assert.equal(report.profile, profile, "WRONG_PROFILE");
  assert.equal(report.suiteSha256, fingerprint(dataset), "SUITE_MISMATCH");
  assert.equal(report.rubricVersion, dataset.rubric_version, "RUBRIC_MISMATCH");
  const expected = expectedCases(dataset, profile);
  assert.ok(Array.isArray(report.results), "MISSING_RESULTS");
  assert.equal(report.expectedCases, expected.size, "INCOMPLETE_COVERAGE");
  assert.equal(report.completedCases, expected.size, "INCOMPLETE_COVERAGE");
  assert.equal(report.results.length, expected.size, "INCOMPLETE_COVERAGE");
  const seen = new Set();
  for (const result of report.results) {
    keys(result, ["id", "threat", "approach", "status", "code", "turns"], "INVALID_RESULT");
    const definition = expected.get(result.id);
    assert.ok(definition && !seen.has(result.id), "UNKNOWN_OR_DUPLICATE_RESULT");
    seen.add(result.id);
    assert.equal(result.threat, definition.threat, "RESULT_IDENTITY_MISMATCH");
    assert.equal(result.approach, definition.approach, "RESULT_IDENTITY_MISMATCH");
    assert.equal(result.status, "pass", "THREAT_CHECK_DID_NOT_PASS");
    assert.equal(result.turns, definition.turns, "INCOMPLETE_TURN_COVERAGE");
    assert.ok(/^[A-Z][A-Z0-9_]{0,63}$/.test(result.code), "UNSAFE_REASON_CODE");
  }
  assert.equal(report.stopCode, null, "RUN_STOPPED");
  assert.equal(report.status, "pass", "RUN_DID_NOT_PASS");
  keys(report.usage, ["app", "attacker", "judge"], "INVALID_USAGE");
  for (const role of ["app", "attacker", "judge"]) {
    const usage = report.usage[role];
    keys(usage, ["calls", "tokens", "costMicrousd"], "INVALID_USAGE");
    assert.ok(Object.values(usage).every((item) => integer(item)), "INVALID_USAGE");
    if (role === "app") {
      assert.equal(usage.calls, report.results.reduce((sum, item) => sum + item.turns, 0),
        "UNACCOUNTED_SUBMISSIONS");
      assert.ok(integer(report.limits.app, 1) && usage.calls <= report.limits.app, "BUDGET_EXCEEDED");
    } else {
      const limit = report.limits[role];
      assert.ok(limit && integer(limit.calls) && integer(limit.tokens)
        && integer(limit.cost_microusd), "INVALID_MODEL_LIMIT");
      assert.ok(usage.calls <= limit.calls && usage.tokens <= limit.tokens
        && usage.costMicrousd <= limit.cost_microusd, "BUDGET_EXCEEDED");
      assert.equal(usage.calls, [...expected.values()].reduce((sum, item) => sum + item[role], 0),
        "INCOMPLETE_MODEL_COVERAGE");
      if (profile === "live") {
        assert.ok(integer(limit.token_price_microusd, 1) && usage.calls > 0, "MODEL_NOT_EVALUATED");
        assert.equal(usage.tokens, usage.calls * (limit.input_bytes + limit.output_tokens + 256),
          "UNACCOUNTED_MODEL_CALLS");
        assert.equal(usage.costMicrousd, usage.tokens * limit.token_price_microusd,
          "UNACCOUNTED_MODEL_COST");
      }
    }
  }
  return report;
}

export function validateQualification(report, candidate, dataset, context, now = Date.now()) {
  validateCandidate(candidate, context, now);
  validateCoverage(report, dataset, "live");
  keys(report.identity, [
    "repository", "commit", "runId", "runAttempt", "target", "candidateSha256",
  ], "INVALID_REPORT_IDENTITY");
  for (const field of ["repository", "commit", "runId", "runAttempt"]) {
    assert.equal(report.identity[field], candidate[field], "REPORT_IDENTITY_MISMATCH");
  }
  assert.equal(report.identity.target, candidate.stagingOrigin, "REPORT_TARGET_MISMATCH");
  assert.equal(report.identity.candidateSha256, fingerprint(candidate), "CANDIDATE_CHANGED");
  assert.equal(candidate.suiteSha256, fingerprint(dataset), "SUITE_MISMATCH");
  assert.equal(candidate.limitsSha256, fingerprint(report.limits), "BUDGET_APPROVAL_MISMATCH");
  assert.ok(Number.isFinite(report.startedAt) && Number.isFinite(report.finishedAt)
    && report.startedAt * 1000 >= Date.parse(candidate.createdAt)
    && report.finishedAt >= report.startedAt && report.finishedAt * 1000 <= now + 30_000
    && now - report.finishedAt * 1000 <= 3_600_000, "STALE_OR_INVALID_REPORT");
  return report;
}
