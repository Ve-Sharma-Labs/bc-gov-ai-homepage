import assert from "node:assert/strict";
import test from "node:test";
import {
  collectorName, collectorPath, eligibleBug, previousCollection, sourceGroups, sourceUpdates,
  trustedCollection,
  validateRepairEvidence,
} from "../agentic-workflows.mjs";

const user = { type: "User", login: "reporter" };
const bot = { type: "Bot", login: "github-actions[bot]" };
const issue = { number: 7, id: 700, title: "Broken follow-up", body: "Synthetic bug",
  state: "open", user, labels: [{ name: "bug" }] };
const report = { schemaVersion: 1, kind: "official-source-freshness", sources: [{
  sourceId: "health", url: "https://www2.gov.bc.ca/gov/content/health",
  checkedAt: "2026-10-25T00:00:00Z", findings: ["stale-check"],
  refresh: "rights-review-required", journeyIds: ["health-coverage"],
}] };

test("open bug reports are eligible without maintainer authorization", () => {
  assert.equal(eligibleBug(issue, { action: "opened", issue }, []), true);
  assert.equal(eligibleBug({ ...issue, labels: [], title: "[Bug]: Test",
    body: "### Bug report\n\nSynthetic report" }, { action: "opened" }, []), true);
});

test("bug eligibility rejects non-bugs, bots, closed reports, edits and mismatched events", () => {
  for (const change of [{ labels: [] }, { user: bot }, { state: "closed" }, { pull_request: {} }]) {
    assert.equal(eligibleBug({ ...issue, ...change }, { action: "opened" }, []), false);
  }
  assert.equal(eligibleBug(issue, { action: "edited" }, []), false);
  assert.equal(eligibleBug(issue, { action: "labeled", label: { name: "triage" } }, []), false);
  assert.equal(eligibleBug(issue, { action: "opened", issue: { number: 8, id: 800 } }, []), false);
});

test("existing bot repair PR prevents duplicate even after it closes", () => {
  assert.equal(eligibleBug(issue, {}, [{ user: bot, title: "[Bug fix] Repair", state: "closed",
    body: "<!-- bc-bug-fix:7 -->" }]), false);
  assert.equal(eligibleBug(issue, {}, [{ user, body: "<!-- bc-bug-fix:7 -->" }]), true);
});

test("source updates are keyed by source and deduplicated by finding fingerprint", () => {
  const groups = sourceGroups(report);
  assert.equal(sourceUpdates(groups, []).length, 1);
  const existing = { number: 3, user: bot, title: "[Source freshness] health",
    body: `${groups[0].marker}\n<!-- bc-source-fingerprint:${groups[0].fingerprint} -->` };
  assert.equal(sourceUpdates(groups, [existing]).length, 0);
  const changed = sourceGroups({ ...report, sources: [{ ...report.sources[0], findings: ["source-changed"] }] });
  assert.equal(sourceUpdates(changed, [existing])[0].issueNumber, 3);
  assert.throws(() => sourceUpdates(groups, [existing, { ...existing, number: 4 }]), /Duplicate/);
});

test("last-attempt time cannot create repeated watchdog issues", () => {
  const first = sourceGroups(report)[0];
  const next = sourceGroups({ ...report, sources: [{ ...report.sources[0], lastAttemptAt: "tomorrow" }] })[0];
  assert.equal(first.fingerprint, next.fingerprint);
});

test("historical fingerprints do not suppress a reverted current finding", () => {
  const [group] = sourceGroups(report);
  const existing = { number: 3, user: bot, title: "[Source freshness] health",
    body: `${group.marker}\n<!-- bc-source-fingerprint:${"0".repeat(64)} -->\nHistory:\n<!-- bc-source-fingerprint:${group.fingerprint} -->` };
  assert.equal(sourceUpdates([group], [existing]).length, 1);
  assert.throws(() => sourceUpdates([group], [{ ...existing, title: "Manually renamed" }]), /policy/);
});

test("source reports fail closed for invalid schema or publisher", () => {
  assert.throws(() => sourceGroups({}), /Invalid/);
  assert.throws(() => sourceGroups({ ...report,
    sources: [{ ...report.sources[0], url: "https://evil.example/secret" }] }), /publisher/);
});

test("recovered or blocked source updates never imply automatic issue closure", () => {
  const groups = sourceGroups({ ...report, sources: [{ ...report.sources[0],
    findings: [], refresh: "unchanged" }] });
  assert.equal(sourceUpdates(groups, []).length, 0);
  const update = sourceUpdates(groups, [{ number: 3, state: "closed", user: bot, title: "[Source freshness] health",
    body: groups[0].marker }])[0];
  assert.equal(update.issueState, "closed");
  assert.equal(update.issueNumber, 3);
});

test("only exact default-branch collector runs can restore state", () => {
  const run = { id: 3, name: collectorName, path: collectorPath, event: "schedule",
    head_branch: "main", head_repository: { full_name: "owner/repo" }, status: "completed" };
  assert.equal(trustedCollection(run, "owner/repo", "main"), true);
  assert.equal(trustedCollection({ ...run, event: "pull_request" }, "owner/repo", "main"), false);
  assert.equal(trustedCollection({ ...run, head_branch: "feature" }, "owner/repo", "main"), false);
  assert.equal(trustedCollection(run, "attacker/repo", "main"), false);
  assert.equal(previousCollection([{ ...run, id: 2 }, run], 3, "owner/repo", "main").id, 2);
});

test("collector rename preserves historical charged state without accepting old current events", () => {
  const legacy = { id: 1, name: "Official source collection", path: collectorPath,
    event: "schedule", head_branch: "main", head_repository: { full_name: "owner/repo" },
    status: "completed", conclusion: "failure" };
  const current = { ...legacy, id: 2, name: collectorName };
  assert.equal(trustedCollection(legacy, "owner/repo", "main"), false);
  assert.equal(trustedCollection(current, "owner/repo", "main"), true);
  assert.equal(previousCollection([legacy, current], 2, "owner/repo", "main"), legacy);
  assert.equal(previousCollection([legacy, current], 3, "owner/repo", "main"), current);
});

test("historical collector aliases retain exact path, repository, branch and event checks", () => {
  for (const name of [collectorName, "Official source collection"]) {
    const run = { id: 1, name, path: collectorPath, event: "workflow_dispatch",
      head_branch: "main", head_repository: { full_name: "owner/repo" }, status: "completed" };
    assert.equal(previousCollection([run], 2, "owner/repo", "main"), run);
    for (const change of [
      { name: "Untrusted collection" },
      { path: ".github/workflows/untrusted.yml" },
      { head_repository: { full_name: "attacker/repo" } },
      { head_branch: "feature" },
      { event: "pull_request" },
      { event: "push" },
    ]) {
      assert.equal(previousCollection([{ ...run, ...change }], 2, "owner/repo", "main"), undefined);
      assert.equal(trustedCollection({ ...run, ...change }, "owner/repo", "main"), false);
    }
  }
});

test("collector history never substitutes an older success for the latest charged attempt", () => {
  const successful = { id: 1, name: "Official source collection", path: collectorPath,
    event: "schedule", head_branch: "main", head_repository: { full_name: "owner/repo" },
    status: "completed", conclusion: "success" };
  for (const name of [collectorName, successful.name]) {
    for (const attempt of [
      { status: "completed", conclusion: "failure" },
      { status: "completed", conclusion: "cancelled" },
      { status: "in_progress", conclusion: null },
    ]) {
      const latest = { ...successful, ...attempt, id: 2, name };
      assert.equal(previousCollection([latest, successful], 3, "owner/repo", "main"), latest);
    }
  }
});

test("repair PR requires matching failing-before and passing-after evidence and a changed regression", () => {
  const context = { number: 7, baseSha: "a".repeat(40) };
  const evidence = {
    issueNumber: 7, baseSha: context.baseSha, regressionFiles: ["apps/api/tests/test_regression.py"],
    command: ["python", "-m", "pytest", "apps/api/tests/test_regression.py"],
    beforeExitCode: 1, afterExitCode: 0, failureKind: "assertion",
    beforeSummary: "Expected next task, received repeated intake",
    afterSummary: "1 passed",
  };
  const changed = evidence.regressionFiles;
  assert.doesNotThrow(() => validateRepairEvidence(evidence, context, changed));
  for (const change of [{ beforeExitCode: 0 }, { afterExitCode: 1 }, { failureKind: "import" },
    { baseSha: "b".repeat(40) }, { regressionFiles: [] }, { issueNumber: 8 }, { beforeSummary: "" }]) {
    assert.throws(() => validateRepairEvidence({ ...evidence, ...change }, context, changed), /evidence/);
  }
  assert.throws(() => validateRepairEvidence(evidence, context, []), /evidence/);
});
