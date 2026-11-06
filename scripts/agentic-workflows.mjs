import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, existsSync, unlinkSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = process.env.GITHUB_WORKSPACE
  ? resolve(process.env.GITHUB_WORKSPACE) : resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const collectorName = "Official source collection";
export const collectorPath = ".github/workflows/official-source-collection.yml";
const bot = (user) => user?.type === "Bot" || user?.login?.endsWith("[bot]");
const hash = (value) => createHash("sha256").update(JSON.stringify(value)).digest("hex");

export function eligibleBug(issue, event, existingPulls) {
  if (!Number.isSafeInteger(issue?.number) || issue.number < 1 || issue.pull_request
    || issue.state !== "open" || bot(issue.user)) return false;
  const bug = issue.labels?.some((label) => (typeof label === "string" ? label : label.name) === "bug");
  const form = /^### Bug report\r?$/m.test(issue.body || "") && issue.title?.startsWith("[Bug]:");
  if (!bug && !form) return false;
  if (event.action && !["opened", "labeled"].includes(event.action)) return false;
  if (event.action === "labeled" && event.label?.name !== "bug") return false;
  if (event.issue && (event.issue.number !== issue.number || event.issue.id !== issue.id)) return false;
  return !existingPulls.some((pr) => bot(pr.user)
    && pr.body?.includes(`<!-- bc-bug-fix:${issue.number} -->`));
}

export function sourceGroups(report) {
  if (report?.schemaVersion !== 1 || report.kind !== "official-source-freshness"
    || !Array.isArray(report.sources) || report.sources.length > 100) {
    throw new Error("Invalid freshness report");
  }
  const groups = new Map();
  for (const row of report.sources) {
    if (!/^[a-z][a-z0-9-]{0,60}$/.test(row.sourceId)
      || !Array.isArray(row.findings) || !Array.isArray(row.journeyIds)) {
      throw new Error("Invalid freshness source row");
    }
    const url = new URL(row.url);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash
      || !["www2.gov.bc.ca", "www.bchousing.org", "www.icbc.com", "www.healthlinkbc.ca",
        "www.workbc.ca", "www.bclaws.gov.bc.ca"].includes(url.hostname)) {
      throw new Error("Invalid freshness publisher");
    }
    const group = groups.get(row.sourceId) || { sourceId: row.sourceId, rows: [] };
    const fields = ["url", "checkedAt", "baselineHash", "observedHash", "httpStatus", "refresh",
      "findings", "journeyIds"];
    group.rows.push(Object.fromEntries(fields.filter((key) => key in row).map((key) => [key, row[key]])));
    groups.set(row.sourceId, group);
  }
  return [...groups.values()].map((group) => ({
    ...group, marker: `<!-- bc-source-watchdog:${group.sourceId} -->`, fingerprint: hash(group.rows),
    actionable: group.rows.some((row) => row.findings.length > 0
      || !["unchanged", "not-requested"].includes(row.refresh)),
  }));
}

export function sourceUpdates(groups, issues) {
  return groups.flatMap((group) => {
    const matches = issues.filter((issue) => !issue.pull_request && bot(issue.user)
      && issue.body?.includes(group.marker));
    if (matches.length > 1) throw new Error("Duplicate source issues require maintainer reconciliation");
    const issue = matches[0];
    if (issue && !issue.title?.startsWith("[Source freshness] ")) {
      throw new Error("Owned source issue title no longer matches the safe-output policy");
    }
    const currentFingerprint = issue?.body?.match(/<!-- bc-source-fingerprint:([0-9a-f]{64}) -->/)?.[1];
    if (currentFingerprint === group.fingerprint) return [];
    if (!issue && !group.actionable) return [];
    return [{
      ...group, issueNumber: issue?.number ?? null, issueState: issue?.state ?? null,
      fingerprintMarker: `<!-- bc-source-fingerprint:${group.fingerprint} -->`,
    }];
  });
}

export function trustedCollection(run, repository, branch) {
  return run?.name === collectorName && run.path === collectorPath
    && run.head_branch === branch && run.head_repository?.full_name === repository
    && ["schedule", "workflow_dispatch"].includes(run.event);
}

export function previousCollection(runs, currentId, repository, branch) {
  const candidates = runs.filter((run) => run.id !== currentId && trustedCollection(run, repository, branch)
    && !["queued", "waiting", "pending", "requested"].includes(run.status));
  return candidates.sort((a, b) => b.id - a.id)[0];
}

export function validateRepairEvidence(evidence, context, changedFiles) {
  if (!evidence || evidence.issueNumber !== context.number || evidence.baseSha !== context.baseSha
    || !/^[0-9a-f]{40}$/.test(evidence.baseSha)
    || !Number.isInteger(evidence.beforeExitCode) || evidence.beforeExitCode <= 0
    || evidence.afterExitCode !== 0 || evidence.failureKind !== "assertion"
    || !Array.isArray(evidence.command) || !evidence.command.length
    || !evidence.command.every((part) => typeof part === "string" && part.length > 0 && part.length <= 1000)
    || !["node", "npm", "python", "python3", ".venv/bin/python",
      "apps/api/.venv/bin/python", "ingestion/.venv/bin/python"].includes(evidence.command[0])
    || !Array.isArray(evidence.regressionFiles) || !evidence.regressionFiles.length
    || !evidence.regressionFiles.every((path) => typeof path === "string"
      && /^(?:apps\/(?:api|web)\/tests\/|ingestion\/tests\/|scripts\/tests\/|tests\/browser\/)/.test(path)
      && !path.includes("..") && changedFiles.includes(path))
    || ![evidence.beforeSummary, evidence.afterSummary].every((value) =>
      typeof value === "string" && value.trim().length > 0 && value.length <= 4000)) {
    throw new Error("Missing valid failing-before/passing-after regression evidence");
  }
}

function gh(args, { json = true } = {}) {
  const value = execFileSync("gh", args, {
    encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], maxBuffer: 8 * 1024 * 1024,
  });
  return json ? JSON.parse(value) : value;
}

function api(path, paginate = false) {
  if (!paginate) return gh(["api", path]);
  return gh(["api", "--paginate", "--slurp", path]).flat();
}

function save(path, data) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
}

function noop(message) {
  if (!process.env.GH_AW_SAFE_OUTPUTS) throw new Error("Missing GH-AW safe output path");
  writeFileSync(process.env.GH_AW_SAFE_OUTPUTS, JSON.stringify({ type: "noop", message }) + "\n", { flag: "a" });
}

function artifact(runId, name, directory, repository) {
  const result = api(`repos/${repository}/actions/runs/${runId}/artifacts?per_page=100`);
  const matches = result.artifacts.filter((item) => item.name === name && !item.expired);
  if (matches.length !== 1) throw new Error(`Missing unique trusted ${name} artifact; recovery required`);
  gh(["run", "download", String(runId), "--repo", repository, "--name", name, "--dir", directory], { json: false });
}

async function main() {
  const [command] = process.argv.slice(2);
  const repository = process.env.GITHUB_REPOSITORY;
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository || "")) throw new Error("Invalid repository");
  const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, "utf8"));
  const branch = event.repository?.default_branch;
  if (!branch) throw new Error("Missing default branch");
  const working = join(root, "ingestion", ".generated", "freshness");
  if (command === "restore-source-state") {
    const currentId = Number(process.env.GITHUB_RUN_ID);
    const current = api(`repos/${repository}/actions/runs/${currentId}`);
    if (!trustedCollection(current, repository, branch) || current.run_attempt !== 1) {
      throw new Error("Source refresh requires an unreplayed trusted default-branch run");
    }
    const runs = gh(["api", "--paginate", "--slurp",
      `repos/${repository}/actions/workflows/official-source-collection.yml/runs?branch=${encodeURIComponent(branch)}&per_page=100`])
      .flatMap((page) => page.workflow_runs);
    const previous = previousCollection(runs, currentId, repository, branch);
    const initialize = event.inputs?.initialize === "true";
    mkdirSync(working, { recursive: true });
    if (previous) {
      if (previous.status !== "completed") throw new Error("Another collection is still running");
      artifact(previous.id, "official-source-state", working, repository);
      if (!existsSync(join(working, "checkpoint.json"))
        && !existsSync(join(working, "uninitialized.json"))) throw new Error("Checkpoint artifact is incomplete");
      if (!existsSync(join(working, "checkpoint.json"))) {
        const marker = JSON.parse(readFileSync(join(working, "uninitialized.json"), "utf8"));
        if (marker.schemaVersion !== 1 || marker.initialized !== false) throw new Error("Invalid initialization marker");
      }
    }
    // The marker makes a never-initialized installation distinguishable from lost state.
    if (!existsSync(join(working, "checkpoint.json"))) {
      save(join(working, "uninitialized.json"), { schemaVersion: 1, initialized: false });
    }
    if (initialize && existsSync(join(working, "checkpoint.json"))) {
      throw new Error("Initialization cannot reset an existing checkpoint");
    }
    if (initialize) writeFileSync(process.env.GITHUB_OUTPUT, "initialize=true\n", { flag: "a" });
  } else if (command === "finalize-source-state") {
    if (existsSync(join(working, "checkpoint.json"))) {
      if (existsSync(join(working, "uninitialized.json"))) unlinkSync(join(working, "uninitialized.json"));
    } else if (!existsSync(join(working, "uninitialized.json"))) {
      throw new Error("No checkpoint or explicit uninitialized marker can be persisted");
    }
  } else if (command === "source-context") {
    const run = event.workflow_run;
    if (!trustedCollection(run, repository, branch) || run.conclusion !== "success") {
      throw new Error("Watchdog accepts only successful trusted source-collection runs");
    }
    artifact(run.id, "official-source-report", working, repository);
    const groups = sourceGroups(JSON.parse(readFileSync(join(working, "report.json"), "utf8")));
    const issues = api(`repos/${repository}/issues?state=all&per_page=100`, true);
    const updates = sourceUpdates(groups, issues);
    save(join(root, "test-results", "source-watchdog-context.json"), { updates });
    if (!updates.length) noop("Source findings have not changed.");
  } else if (command === "bug-context") {
    if (process.env.GITHUB_REF !== `refs/heads/${branch}`) throw new Error("Bug repair must run trusted default-branch code");
    const number = Number(event.issue?.number ?? event.inputs?.issue_number);
    if (!Number.isSafeInteger(number) || number < 1) throw new Error("Invalid issue number");
    const issue = api(`repos/${repository}/issues/${number}`);
    const pulls = api(`repos/${repository}/pulls?state=all&per_page=100`, true);
    if (!eligibleBug(issue, event, pulls)) {
      noop("Not an eligible open bug report, or a repair PR already exists.");
      return;
    }
    if (typeof issue.body !== "string" || issue.body.length > 24000 || issue.title.length > 300) {
      throw new Error("Bug report exceeds bounded context; maintainer triage required");
    }
    save(join(root, "test-results", "bug-fix-context.json"), {
      number, title: issue.title, body: issue.body, marker: `<!-- bc-bug-fix:${number} -->`,
      repository, baseSha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
    });
  } else if (command === "bug-evidence") {
    const outputs = readFileSync(process.env.GH_AW_SAFE_OUTPUTS, "utf8").split("\n")
      .filter((line) => line.trim()).map((line) => JSON.parse(line));
    if (!outputs.some((item) => item.type === "create_pull_request")) return;
    const number = Number(event.issue?.number ?? event.inputs?.issue_number);
    if (!Number.isSafeInteger(number) || number < 1) throw new Error("Invalid evidence issue");
    const context = { number, baseSha: process.env.GITHUB_SHA, marker: `<!-- bc-bug-fix:${number} -->` };
    const evidence = JSON.parse(readFileSync(join(root, "test-results", "bug-fix-evidence.json"), "utf8"));
    const changed = execFileSync("git", ["diff", "--name-only", context.baseSha, "HEAD"], { encoding: "utf8" })
      .trim().split("\n");
    validateRepairEvidence(evidence, context, changed);
    for (const output of outputs.filter((item) => item.type === "create_pull_request")) {
      if (!output.body?.includes(context.marker)) throw new Error("PR must retain its exact bug marker");
    }
  } else {
    throw new Error("Unknown agentic workflow preflight");
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => {
    console.error("Agentic workflow preflight failed. Check trusted inputs, artifact continuity, and permissions.");
    process.exitCode = 1;
  });
}
