import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  appendFileSync, chmodSync, cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync,
  readdirSync, rmSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual } from "node:util";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const suitePath = "data/evaluations/coding-agent/suite.json";
const workPath = "test-results/coding-agent-evals/work";
const helperPath = "scripts/coding-agent-evals.mjs";
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const writeJson = (file, value) => writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, { flag: "wx" });

export function readRegular(directory, relative, limit = 64 * 1024) {
  const parts = relative.split("/");
  assert.ok(parts.every((part) => /^[A-Za-z0-9_.-]+$/.test(part) && ![".", ".."].includes(part)),
    "Unsafe evaluation path");
  let current = path.resolve(directory);
  for (const [index, part] of parts.entries()) {
    current = path.join(current, part);
    const stat = lstatSync(current);
    assert.ok(!stat.isSymbolicLink(), "Evaluation paths cannot be links");
    if (index < parts.length - 1) assert.ok(stat.isDirectory(), "Invalid evaluation directory");
    else assert.ok(stat.isFile() && stat.size <= limit, "Missing or oversized evaluation file");
  }
  return readFileSync(current);
}

export function loadSuite(directory = root) {
  const suite = JSON.parse(readRegular(directory, suitePath));
  assert.equal(suite.schemaVersion, 1);
  assert.match(suite.id, /^[a-z][a-z0-9-]+$/);
  assert.ok(Number.isFinite(suite.minimumPassRate) && suite.minimumPassRate > 0 && suite.minimumPassRate <= 1);
  assert.match(suite.image, /^node:24-bookworm-slim@sha256:[0-9a-f]{64}$/);
  assert.ok(Array.isArray(suite.cases) && suite.cases.length > 0 && suite.cases.length <= 50);
  const ids = new Set();
  for (const item of suite.cases) {
    assert.match(item.id, /^[a-z][a-z0-9-]{0,60}$/);
    assert.ok(!ids.has(item.id), "Duplicate evaluation case");
    ids.add(item.id);
    assert.match(item.function, /^[A-Za-z][A-Za-z0-9]*$/);
    assert.ok(typeof item.prompt === "string" && item.prompt.length > 0 && item.prompt.length <= 4000);
    assert.ok(Array.isArray(item.smoke) && item.smoke.length > 0);
    for (const check of item.smoke) {
      assert.ok(Array.isArray(check.args));
      assert.equal(["value", "throws", "undefined"].filter((key) => key in check).length, 1);
    }
  }
  return suite;
}

function snapshot(directory, suite, includeSmoke = true) {
  const files = {};
  function visit(relative) {
    const stat = lstatSync(path.join(directory, relative));
    assert.ok(!stat.isSymbolicLink(), "Protected paths cannot be links");
    if (stat.isDirectory()) {
      for (const name of readdirSync(path.join(directory, relative)).sort()) visit(`${relative}/${name}`);
    } else files[relative] = sha256(readRegular(directory, relative, 2 * 1024 * 1024));
  }
  for (const relative of [".github", "data/evaluations/coding-agent", helperPath]) visit(relative);
  for (const relative of ["AGENTS.md", "CLAUDE.md"]) {
    if (existsSync(path.join(directory, relative))) visit(relative);
  }
  if (includeSmoke) {
    for (const item of suite.cases) visit(`${workPath}/${item.id}.test.mjs`);
  }
  return files;
}

function inputHashes(files, model) {
  const entries = Object.entries(files);
  const tasks = entries.filter(([name]) => name.startsWith("data/evaluations/coding-agent/"));
  const configuration = entries.filter(([name]) =>
    name.startsWith(".github/") || ["AGENTS.md", "CLAUDE.md"].includes(name));
  return {
    suiteHash: sha256(JSON.stringify(tasks)),
    configurationHash: sha256(`${model}\n${JSON.stringify(configuration)}`),
  };
}

function smokeSource(item) {
  return `import assert from "node:assert/strict";
import test from "node:test";
import { ${item.function} as candidate } from "./${item.id}.mjs";
const examples = ${JSON.stringify(item.smoke)};
for (const [index, example] of examples.entries()) {
  test("public smoke " + index, async () => {
    if (example.throws) await assert.rejects(async () => candidate(...example.args));
    else assert.deepEqual(await candidate(...example.args), example.undefined ? undefined : example.value);
  });
}
`;
}

export function prepare(directory, { revision, model }) {
  assert.match(revision, /^[0-9a-f]{40}$/);
  assert.ok(typeof model === "string" && /^[A-Za-z0-9_.:/-]{1,120}$/.test(model));
  const suite = loadSuite(directory);
  mkdirSync(path.join(directory, workPath), { recursive: true });
  for (const item of suite.cases) {
    const fixture = readRegular(directory, `data/evaluations/coding-agent/fixtures/${item.id}.mjs`);
    writeFileSync(path.join(directory, workPath, `${item.id}.mjs`), fixture, { flag: "wx" });
    writeFileSync(path.join(directory, workPath, `${item.id}.test.mjs`), smokeSource(item), { flag: "wx" });
  }
  const protectedFiles = snapshot(directory, suite);
  return {
    schemaVersion: 1, suiteId: suite.id, revision, model,
    ...inputHashes(protectedFiles, model),
    protectedFiles, caseIds: suite.cases.map((item) => item.id),
  };
}

export function prepareKit(directory, destination, metadata) {
  mkdirSync(destination);
  for (const relative of [".github", "data/evaluations/coding-agent", helperPath, "AGENTS.md", "CLAUDE.md"]) {
    const source = path.join(directory, relative);
    if (!existsSync(source) && ["AGENTS.md", "CLAUDE.md"].includes(relative)) continue;
    const target = path.join(destination, relative);
    mkdirSync(path.dirname(target), { recursive: true });
    cpSync(source, target, { recursive: true, dereference: false });
  }
  return prepare(destination, metadata);
}

export function collect(directory, outputDirectory, manifest) {
  assert.equal(manifest.schemaVersion, 1);
  const suite = loadSuite(directory);
  assert.deepEqual(manifest.caseIds, suite.cases.map((item) => item.id));
  mkdirSync(outputDirectory);
  const capture = { ...manifest, protectedFiles: undefined, controlsIntact: false, missing: [] };
  try {
    capture.controlsIntact = isDeepStrictEqual(snapshot(directory, suite), manifest.protectedFiles);
  } catch (error) {
    if (error.code !== "ENOENT" && error.code !== "ERR_ASSERTION") throw error;
    capture.controlsIntact = false;
  }
  for (const id of manifest.caseIds) {
    try {
      const solution = readRegular(directory, `${workPath}/${id}.mjs`, 32 * 1024);
      writeFileSync(path.join(outputDirectory, `${id}.mjs`), solution, { flag: "wx" });
    } catch (error) {
      if (error.code !== "ENOENT" && error.code !== "ERR_ASSERTION") throw error;
      capture.missing.push(id);
    }
  }
  writeJson(path.join(outputDirectory, "capture.json"), capture);
  return capture;
}

export function containerArguments(image, directory, name) {
  return [
    "run", "--rm", "--name", name, "--pull=never", "--network=none",
    "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
    "--pids-limit=64", "--memory=128m", "--cpus=1", "--user=65534:65534",
    "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
    "--mount", `type=bind,source=${directory},target=/eval,readonly`,
    "-i", image, "node", "/eval/worker.mjs", "/eval/solution.mjs",
  ];
}

export function runInContainer({ image, solution, invocations }) {
  const directory = mkdtempSync(path.join(tmpdir(), "bc-agent-eval-"));
  const name = `bc-agent-eval-${randomUUID()}`;
  let result;
  try {
    writeFileSync(path.join(directory, "solution.mjs"), solution, { mode: 0o644 });
    writeFileSync(path.join(directory, "worker.mjs"),
      readFileSync(path.join(root, "scripts", "coding-agent-eval-worker.mjs")), { mode: 0o644 });
    // mkdtemp defaults to 0700, but the container runs as an unprivileged user.
    chmodSync(directory, 0o755);
    result = spawnSync("docker", containerArguments(image, directory, name), {
      input: JSON.stringify({ invocations }), encoding: "utf8", timeout: 15_000, maxBuffer: 128 * 1024,
    });
    if (result.error) {
      const cleanup = spawnSync("docker", ["rm", "--force", name], { encoding: "utf8", timeout: 10_000 });
      if (cleanup.error || (cleanup.status !== 0 && !cleanup.stderr?.includes("No such container"))) {
        return { status: "blocked", reason: "container-cleanup-failed" };
      }
    }
    return result;
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

export function evaluateCase(item, assertions, execute, { image, solution }) {
  const result = execute({
    image, solution,
    invocations: assertions.map((check) => ({ function: check.function || item.function, args: check.args })),
  });
  if (result.status === "blocked") return { id: item.id, status: "blocked", reason: result.reason };
  if (result.error?.code === "ENOENT" || result.status === 125) {
    return { id: item.id, status: "blocked", reason: "container-unavailable" };
  }
  if (result.error || result.status !== 0) {
    return { id: item.id, status: "failed", reason: "execution-failed-or-timed-out" };
  }
  let results;
  try {
    ({ results } = JSON.parse(result.stdout));
  } catch {
    return { id: item.id, status: "failed", reason: "invalid-result" };
  }
  if (!Array.isArray(results) || results.length !== assertions.length) {
    return { id: item.id, status: "failed", reason: "incomplete-result" };
  }
  const failures = assertions.flatMap((check, index) => {
    const expected = check.throws ? { kind: "throw" } : check.undefined
      ? { kind: "return", undefined: true } : { kind: "return", value: check.value };
    return isDeepStrictEqual(results[index], expected) ? [] : [check.label || `smoke-${index}`];
  });
  return {
    id: item.id, status: failures.length ? "failed" : "passed",
    checks: assertions.length, failedChecks: failures,
  };
}

export function gateReport(suite, cases, metadata, blockers = []) {
  assert.deepEqual(cases.map((item) => item.id), suite.cases.map((item) => item.id));
  assert.ok(cases.every((item) => ["passed", "failed", "blocked"].includes(item.status)));
  const passed = cases.filter((item) => item.status === "passed").length;
  const passRate = passed / suite.cases.length;
  const blocked = blockers.length > 0 || cases.some((item) => item.status === "blocked");
  return {
    schemaVersion: 1, suiteId: suite.id, ...metadata,
    status: blocked ? "blocked" : passRate >= suite.minimumPassRate ? "passed" : "failed",
    total: suite.cases.length, passed, passRate, minimumPassRate: suite.minimumPassRate,
    blockers, cases,
  };
}

export function summary(report) {
  return [
    "# Coding-agent evaluations", "",
    `Outcome: **${report.status}**. ${report.passed}/${report.total} tasks passed; required ${report.minimumPassRate * 100}%.`,
    `Commit: \`${report.revision}\`. Requested model: \`${report.model}\`.`,
    `Suite: \`${report.suiteId}\` / \`${report.suiteHash}\`.`,
    `Configuration: \`${report.configurationHash}\`.`,
    "", "| Task | Result | Evidence |", "|---|---|---|",
    ...report.cases.map((item) => `| ${item.id} | ${item.status} | ${item.reason || item.failedChecks?.join(", ") || `${item.checks} assertions passed`} |`),
    ...report.blockers.map((reason) => `\nBlocked: ${reason}.`),
    "", "Frozen synthetic coding tasks; not application-model evals or a claim that the full SDLC was tested.", "",
  ].join("\n");
}

export function gradeSubmission(directory, submission, {
  revision, agentResult, checks, execute = runInContainer, runtimeReady,
}) {
  const suite = loadSuite(directory);
  assert.deepEqual(Object.keys(checks).sort(), suite.cases.map((item) => item.id).sort());
  const blockers = [];
  let capture;
  try {
    capture = JSON.parse(readRegular(submission, "capture.json"));
  } catch (error) {
    if (error.code !== "ENOENT" && error.code !== "ERR_ASSERTION" && !(error instanceof SyntaxError)) throw error;
    blockers.push("missing-or-invalid-submission");
  }
  if (agentResult !== "success") blockers.push("agent-did-not-complete");
  if (capture?.controlsIntact !== true) blockers.push("protected-inputs-not-preserved");
  if (capture?.revision !== revision || capture?.suiteId !== suite.id
    || !isDeepStrictEqual(capture?.caseIds, suite.cases.map((item) => item.id))) {
    blockers.push("submission-identity-mismatch");
  }
  const metadataValid = capture?.schemaVersion === 1 && typeof capture.model === "string"
    && /^[A-Za-z0-9_.:/-]{1,120}$/.test(capture.model)
    && [capture.suiteHash, capture.configurationHash].every((value) =>
      typeof value === "string" && /^[0-9a-f]{64}$/.test(value));
  if (!metadataValid) blockers.push("missing-or-invalid-run-metadata");
  else {
    const expected = inputHashes(snapshot(directory, suite, false), capture.model);
    if (capture.suiteHash !== expected.suiteHash || capture.configurationHash !== expected.configurationHash) {
      blockers.push("input-fingerprint-mismatch");
    }
  }
  if (!blockers.length && !runtimeReady(suite.image)) blockers.push("grading-runtime-unavailable");
  const cases = suite.cases.map((item) => {
    if (blockers.length) return { id: item.id, status: "blocked", reason: "grading-prerequisite-failed" };
    let solution;
    try {
      solution = readRegular(submission, `${item.id}.mjs`, 32 * 1024);
    } catch (error) {
      if (error.code !== "ENOENT" && error.code !== "ERR_ASSERTION") throw error;
      return { id: item.id, status: "blocked", reason: "missing-or-unsafe-solution" };
    }
    return evaluateCase(item, [...item.smoke, ...checks[item.id]], execute, { image: suite.image, solution });
  });
  return gateReport(suite, cases, {
    revision, model: metadataValid ? capture.model : "unavailable",
    suiteHash: metadataValid ? capture.suiteHash : "unavailable",
    configurationHash: metadataValid ? capture.configurationHash : "unavailable",
    image: suite.image,
  }, blockers);
}

async function main() {
  const [command] = process.argv.slice(2);
  if (command === "prepare" || command === "pack") {
    const metadata = { revision: process.env.GITHUB_SHA, model: process.env.EVAL_MODEL };
    const manifest = command === "pack"
      ? prepareKit(root, path.join(process.env.RUNNER_TEMP, "coding-agent-kit"), metadata)
      : prepare(root, metadata);
    appendFileSync(process.env.GITHUB_OUTPUT, `manifest=${JSON.stringify(manifest)}\n`);
    return;
  }
  assert.equal(command, "grade", "Use pack, prepare or grade");
  const { checks } = await import("../tests/agent-evals/checks.mjs");
  const submission = path.join(root, "test-results", "coding-agent-evals", "submission");
  const report = gradeSubmission(root, submission, {
    revision: process.env.GITHUB_SHA, agentResult: process.env.EVAL_AGENT_RESULT, checks,
    runtimeReady(image) {
      const pull = spawnSync("docker", ["pull", image], {
        encoding: "utf8", timeout: 120_000, maxBuffer: 128 * 1024,
      });
      return !pull.error && pull.status === 0;
    },
  });
  const output = path.join(root, "test-results", "coding-agent-evals", "report");
  mkdirSync(output, { recursive: true });
  writeJson(path.join(output, "report.json"), report);
  writeFileSync(path.join(output, "report.md"), summary(report), { flag: "wx" });
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary(report));
  console.log(`Coding-agent evals: ${report.status}; ${report.passed}/${report.total} tasks passed.`);
  process.exitCode = report.status === "passed" ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(`Coding-agent evaluation harness failed: ${error.message}`);
    process.exitCode = 1;
  });
}
