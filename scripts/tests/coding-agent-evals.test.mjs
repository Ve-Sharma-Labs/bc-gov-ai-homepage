import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import {
  collect, containerArguments, evaluateCase, gateReport, gradeSubmission, loadSuite,
  prepare, prepareKit, readRegular, summary,
} from "../coding-agent-evals.mjs";
import { root } from "../runtime.mjs";
import { checks } from "../../tests/agent-evals/checks.mjs";

const suite = loadSuite();
const revision = "a".repeat(40);

function fixture(t) {
  const directory = mkdtempSync(path.join(tmpdir(), "bc-agent-eval-test-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  for (const relative of [
    "data/evaluations/coding-agent", "scripts/coding-agent-evals.mjs",
    ".github/aw/instructions.md", ".github/workflows/coding-agent-evals.md",
    ".github/workflows/shared/coding-agent-policy.md",
  ]) {
    const target = path.join(directory, relative);
    mkdirSync(path.dirname(target), { recursive: true });
    cpSync(path.join(root, relative), target, { recursive: true });
  }
  return directory;
}

function executeLocally({ solution, invocations }) {
  // Test-owned fixtures only; the production CLI has no host-execution fallback.
  const directory = mkdtempSync(path.join(tmpdir(), "bc-agent-eval-worker-test-"));
  try {
    const file = path.join(directory, "solution.mjs");
    writeFileSync(file, solution);
    return spawnSync(process.execPath, [path.join(root, "scripts", "coding-agent-eval-worker.mjs"), file], {
      input: JSON.stringify({ invocations }), encoding: "utf8", timeout: 15_000, maxBuffer: 128 * 1024,
    });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

function solve(directory) {
  for (const item of suite.cases) {
    writeFileSync(path.join(directory, "test-results/coding-agent-evals/work", `${item.id}.mjs`),
      readFileSync(path.join(root, item.source)));
  }
}

test("every frozen starter fails and the repository's accepted implementation passes independent checks", () => {
  for (const item of suite.cases) {
    const assertions = [...item.smoke, ...checks[item.id]];
    const broken = evaluateCase(item, assertions, executeLocally, {
      solution: readFileSync(path.join(root, "data/evaluations/coding-agent/fixtures", `${item.id}.mjs`)),
    });
    assert.equal(broken.status, "failed", item.id);
    const accepted = evaluateCase(item, assertions, executeLocally, {
      solution: readFileSync(path.join(root, item.source)),
    });
    assert.equal(accepted.status, "passed", JSON.stringify(accepted));
    assert.ok(accepted.checks > item.smoke.length);
  }
});

test("an independently graded complete submission passes without using agent claims", (t) => {
  const directory = fixture(t);
  const manifest = prepare(directory, { revision, model: "auto" });
  solve(directory);
  const submission = path.join(directory, "submission");
  collect(directory, submission, manifest);
  const report = gradeSubmission(directory, submission, {
    revision, agentResult: "success", checks, execute: executeLocally, runtimeReady: () => true,
  });
  assert.equal(report.status, "passed");
  assert.equal(report.passRate, 1);
  assert.match(summary(report), /6\/6 tasks passed/);
});

test("the agent kit contains no source solutions, private grading checks or Git objects", (t) => {
  const directory = fixture(t);
  mkdirSync(path.join(directory, ".git"));
  writeFileSync(path.join(directory, ".git/fixture"), "not for the agent");
  mkdirSync(path.join(directory, "tests/agent-evals"), { recursive: true });
  writeFileSync(path.join(directory, "tests/agent-evals/checks.mjs"), "private checks");
  writeFileSync(path.join(directory, "scripts/runtime.mjs"), "reference implementation");
  const kit = path.join(directory, "kit");
  const manifest = prepareKit(directory, kit, { revision, model: "auto" });
  assert.equal(manifest.caseIds.length, suite.cases.length);
  for (const relative of [".git", "tests/agent-evals/checks.mjs", "scripts/runtime.mjs"]) {
    assert.equal(existsSync(path.join(kit, relative)), false, relative);
  }
  assert.ok(existsSync(path.join(kit, ".github/workflows/shared/coding-agent-policy.md")));
  assert.ok(existsSync(path.join(kit, "test-results/coding-agent-evals/work/strict-ports.mjs")));
});

test("changing protected checks cannot turn a bad candidate into a passing evaluation", (t) => {
  const directory = fixture(t);
  const manifest = prepare(directory, { revision, model: "auto" });
  solve(directory);
  writeFileSync(path.join(directory, "test-results/coding-agent-evals/work/strict-ports.test.mjs"), "");
  const submission = path.join(directory, "submission");
  assert.equal(collect(directory, submission, manifest).controlsIntact, false);
  const report = gradeSubmission(directory, submission, {
    revision, agentResult: "success", checks, runtimeReady: () => assert.fail("Must not execute"),
  });
  assert.equal(report.status, "blocked");
  assert.ok(report.blockers.includes("protected-inputs-not-preserved"));
});

test("missing, oversized and symlinked candidate files are not evaluated or followed", (t) => {
  const directory = fixture(t);
  const manifest = prepare(directory, { revision, model: "auto" });
  const work = path.join(directory, "test-results/coding-agent-evals/work");
  rmSync(path.join(work, "strict-ports.mjs"));
  writeFileSync(path.join(work, "loopback-settings.mjs"), "x".repeat(32 * 1024 + 1));
  const outside = path.join(directory, "outside");
  mkdirSync(outside);
  writeFileSync(path.join(outside, "file.mjs"), "not a candidate");
  symlinkSync(outside, path.join(directory, "linked"), process.platform === "win32" ? "junction" : "dir");
  assert.throws(() => readRegular(directory, "linked/file.mjs"), /cannot be links/);
  const submission = path.join(directory, "submission");
  assert.deepEqual(collect(directory, submission, manifest).missing, ["strict-ports", "loopback-settings"]);
  const report = gradeSubmission(directory, submission, {
    revision, agentResult: "success", checks, execute: executeLocally, runtimeReady: () => true,
  });
  assert.equal(report.status, "blocked");
  assert.equal(report.cases[0].reason, "missing-or-unsafe-solution");
});

test("failed, skipped and mismatched agent runs fail closed even with correct solutions", (t) => {
  const directory = fixture(t);
  const manifest = prepare(directory, { revision, model: "auto" });
  solve(directory);
  const submission = path.join(directory, "submission");
  collect(directory, submission, manifest);
  for (const agentResult of ["failure", "cancelled", "skipped"]) {
    assert.equal(gradeSubmission(directory, submission, {
      revision, agentResult, checks, runtimeReady: () => assert.fail("Must not execute"),
    }).status, "blocked");
  }
  assert.equal(gradeSubmission(directory, submission, {
    revision: "b".repeat(40), agentResult: "success", checks, runtimeReady: () => assert.fail("Must not execute"),
  }).status, "blocked");
  assert.equal(gradeSubmission(directory, path.join(directory, "absent"), {
    revision, agentResult: "success", checks, runtimeReady: () => assert.fail("Must not execute"),
  }).status, "blocked");
  assert.equal(gradeSubmission(directory, submission, {
    revision, agentResult: "success", checks, runtimeReady: () => false,
  }).status, "blocked");
  const capturePath = path.join(submission, "capture.json");
  const capture = JSON.parse(readFileSync(capturePath, "utf8"));
  for (const change of [{ schemaVersion: 0 }, { suiteHash: "0".repeat(64) },
    { configurationHash: "0".repeat(64) }, { model: "different-model" }]) {
    writeFileSync(capturePath, JSON.stringify({ ...capture, ...change }));
    assert.equal(gradeSubmission(directory, submission, {
      revision, agentResult: "success", checks, runtimeReady: () => assert.fail("Must not execute"),
    }).status, "blocked");
  }
});

test("the grading CLI exits nonzero and preserves an explicit incomplete report without an artifact", (t) => {
  const directory = fixture(t);
  mkdirSync(path.join(directory, "tests/agent-evals"), { recursive: true });
  cpSync(path.join(root, "tests/agent-evals/checks.mjs"), path.join(directory, "tests/agent-evals/checks.mjs"));
  const result = spawnSync(process.execPath, [path.join(directory, "scripts/coding-agent-evals.mjs"), "grade"], {
    env: { ...process.env, GITHUB_SHA: revision, EVAL_AGENT_RESULT: "failure", GITHUB_STEP_SUMMARY: "" },
    encoding: "utf8", timeout: 15_000,
  });
  assert.equal(result.status, 1, result.stderr);
  const report = JSON.parse(readFileSync(path.join(directory,
    "test-results/coding-agent-evals/report/report.json"), "utf8"));
  assert.equal(report.status, "blocked");
  assert.equal(report.passed, 0);
  assert.ok(report.blockers.includes("missing-or-invalid-submission"));
});

test("a zero exit, self-reported score or missing export is not proof of correct behavior", () => {
  const item = suite.cases[0];
  for (const solution of [
    "process.exit(0);",
    'console.log(JSON.stringify({ passed: true, passRate: 1 }));',
    "export const unrelated = 1;",
    'export function portFrom() { throw new Error("Always reject"); }',
  ]) {
    assert.equal(evaluateCase(item, [...item.smoke, ...checks[item.id]], executeLocally,
      { solution }).status, "failed");
  }
  assert.equal(evaluateCase(item, item.smoke, () => ({ status: null, error: { code: "ETIMEDOUT" } }),
    {}).status, "failed");
});

test("the threshold uses all tasks and incomplete runs cannot pass even above a lowered threshold", () => {
  const cases = suite.cases.map((item) => ({ id: item.id, status: "passed" }));
  cases[0].status = "failed";
  assert.equal(gateReport(suite, cases, {}).status, "failed");
  cases[0].status = "blocked";
  assert.equal(gateReport({ ...suite, minimumPassRate: 0.5 }, cases, {}).status, "blocked");
  assert.throws(() => gateReport(suite, cases.slice(1), {}));
  cases[0].status = "skipped";
  assert.throws(() => gateReport(suite, cases, {}));
});

test("candidate execution is isolated, bounded and receives neither the grader nor credentials", () => {
  const args = containerArguments(suite.image, "/tmp/fixture", "fixture-container");
  for (const required of ["--network=none", "--read-only", "--cap-drop=ALL",
    "--security-opt=no-new-privileges", "--user=65534:65534", "--pids-limit=64", "--memory=128m",
    "--cpus=1", "--pull=never"]) assert.ok(args.includes(required));
  assert.ok(args.includes("type=bind,source=/tmp/fixture,target=/eval,readonly"));
  assert.equal(args.filter((part) => part === "--mount").length, 1);
  assert.ok(!args.some((part) => /--env|--privileged|docker\.sock|GITHUB_WORKSPACE/.test(part)));
});

test("the coding workflow shares production policy and grades on a fresh, always-run job", () => {
  const workflow = readFileSync(path.join(root, ".github/workflows/coding-agent-evals.md"), "utf8");
  const repair = readFileSync(path.join(root, ".github/workflows/bug-regression-fix.md"), "utf8");
  for (const source of [workflow, repair]) {
    assert.match(source, /engine: copilot/);
    assert.match(source, /imports:\r?\n  - shared\/coding-agent-policy\.md/);
  }
  assert.match(workflow, /allowed: \[\]/);
  assert.match(workflow, /github: false/);
  assert.match(workflow, /report-failure-as-issue: false/);
  assert.match(workflow, /report-as-issue: false/);
  assert.match(workflow, /staged: true/);
  assert.match(workflow, /checkout: false/);
  assert.match(workflow, /name: coding-agent-kit/);
  assert.match(workflow, /EVAL_MANIFEST: \$\{\{ needs\.prepare_evals\.outputs\.manifest \}\}/);
  assert.match(workflow, /name: BC Gov Agents - Coding Agent Eval Gate/);
  assert.match(workflow, /needs: \[agent, activation, pre_activation\]/);
  assert.match(workflow, /always\(\) &&/);
  assert.match(workflow, /config_scope_result != 'success'/);
  assert.match(workflow, /file\.previous_filename/);
  assert.doesNotMatch(workflow, /\n    paths:/);
  assert.match(workflow, /Collector was modified/);
  assert.match(workflow, /node scripts\/coding-agent-evals\.mjs grade/);
  assert.doesNotMatch(workflow, /pull_request_target|contents: write|issues: write|pull-requests: write/);
  const grading = workflow.slice(workflow.indexOf("  grade:"));
  assert.match(grading, /ref: \$\{\{ github\.sha \}\}/);
  assert.match(grading, /EVAL_AGENT_RESULT: \$\{\{ needs\.agent\.result \}\}/);
  assert.doesNotMatch(grading, /COPILOT_GITHUB_TOKEN|copilot-requests: write/);
});

test("PR scope detection covers configuration, renamed files and schedules without hiding lookup failures", async () => {
  const source = readFileSync(path.join(root, ".github/workflows/coding-agent-evals.md"), "utf8");
  const body = source.match(/- id: config_scope[\s\S]*?script: \|\r?\n([\s\S]*?)    - id: eval_needed/)[1]
    .split(/\r?\n/).map((line) => line.replace(/^ {10}/, "")).join("\n");
  const run = new (Object.getPrototypeOf(async () => {}).constructor)("github", "context", body);
  const context = { eventName: "pull_request", repo: { owner: "fixture", repo: "repo" },
    payload: { pull_request: { number: 7, changed_files: 1 } } };
  const github = (files) => ({ rest: { pulls: { listFiles: {} } }, paginate: async () => files });
  for (const filename of [".github/workflows/shared/coding-agent-policy.md", "CLAUDE.md", "AGENTS.md",
    "scripts/coding-agent-evals.mjs", "scripts/coding-agent-eval-worker.mjs",
    "scripts/tests/coding-agent-evals.test.mjs", "tests/agent-evals/checks.mjs",
    "data/evaluations/coding-agent/suite.json"]) {
    assert.equal(await run(github([{ filename }]), context), true, filename);
  }
  assert.equal(await run(github([{ filename: "apps/web/src/app/page.tsx" }]), context), false);
  assert.equal(await run(github([{ filename: "docs/old-policy.md",
    previous_filename: ".github/workflows/shared/coding-agent-policy.md" }]), context), true);
  assert.equal(await run({}, { eventName: "schedule" }), true);
  assert.equal(await run({}, { eventName: "workflow_dispatch" }), true);
  assert.equal(await run({}, { ...context,
    payload: { pull_request: { number: 7, changed_files: 3001 } } }), true);
  await assert.rejects(() => run({ ...github([]), paginate: async () => { throw new Error("unavailable"); } },
    context), /unavailable/);
});

test("compiled activation references real outputs and safe outputs cannot publish repository writes", () => {
  const compiled = readFileSync(path.join(root, ".github/workflows/coding-agent-evals.lock.yml"), "utf8");
  for (const id of ["trusted_source", "config_scope", "eval_needed"]) {
    assert.ok(compiled.includes(`${id}_result: \${{ steps.${id}.outcome }}`), id);
    assert.ok(compiled.includes(`needs.pre_activation.outputs.${id}_result`), id);
  }
  assert.match(compiled, /GH_AW_SAFE_OUTPUTS_STAGED: "true"/);
  const manifest = JSON.parse(compiled.match(/^# gh-aw-manifest: (.+)$/m)[1]);
  assert.ok(!manifest.mcp_servers.some((server) => server.name === "github"));
});

test("compiled permissions cover smoke and syntax checks without authorizing arbitrary Node execution", () => {
  const source = readFileSync(path.join(root, ".github/workflows/coding-agent-evals.md"), "utf8");
  const compiled = readFileSync(path.join(root, ".github/workflows/coding-agent-evals.lock.yml"), "utf8");
  const invocation = compiled.split(/\r?\n/).find((line) =>
    !line.trimStart().startsWith("#") && line.includes("--allow-tool") && line.includes("shell("));
  assert.ok(invocation, "Missing compiled agent invocation");
  const rules = [...invocation.matchAll(/shell\(([^)]+)\)/g)].map((match) => match[1]);
  // Copilot command prefixes are not shell filename globs.
  const permits = (command) => rules.some((rule) => {
    const prefix = rule.endsWith(":*") ? rule.slice(0, -2) : rule;
    return command === prefix || command.startsWith(`${prefix} `);
  });
  const smoke = source.match(/`(node --test [^`]+)`/)[1];
  assert.ok(permits(smoke), smoke);
  for (const item of suite.cases) {
    for (const command of [
      `node --test test-results/coding-agent-evals/work/${item.id}.test.mjs`,
      `node --check test-results/coding-agent-evals/work/${item.id}.mjs`,
    ]) assert.ok(permits(command), command);
  }
  for (const command of [
    "node --eval 'process.exit(0)'", "node scripts/coding-agent-evals.mjs grade",
    "node --test-other file.mjs", "npm install", "curl https://example.com",
  ]) assert.equal(permits(command), false, command);
  assert.ok(!invocation.includes("--allow-all-tools"));
  assert.doesNotMatch(invocation, /--allow-tool shell(?:\s|$)/);
});

test("the documented public smoke command reproduces assertions in the task-only workspace", (t) => {
  const directory = fixture(t);
  const kit = path.join(directory, "kit");
  prepareKit(directory, kit, { revision, model: "auto" });
  const source = readFileSync(path.join(root, ".github/workflows/coding-agent-evals.md"), "utf8");
  const command = source.match(/`(node --test [^`]+)`/)[1].split(" ");
  const result = spawnSync(process.execPath, command.slice(1), {
    cwd: kit, env: { ...process.env, NODE_TEST_CONTEXT: undefined },
    encoding: "utf8", timeout: 15_000, maxBuffer: 128 * 1024,
  });
  assert.equal(result.status, 1, result.stderr);
  assert.match(result.stdout, /ERR_ASSERTION/);
  assert.doesNotMatch(`${result.stdout}\n${result.stderr}`, /MODULE_NOT_FOUND|ENOENT|Could not find/);
  for (const item of suite.cases) assert.ok(result.stdout.includes(`${item.id}.test.mjs`), item.id);
});
