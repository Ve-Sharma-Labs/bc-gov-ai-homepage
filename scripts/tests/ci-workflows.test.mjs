import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { collectorName, collectorPath } from "../agentic-workflows.mjs";
import { root } from "../runtime.mjs";

const directory = path.join(root, ".github", "workflows");
const ci = {
  "ci-web-tests.yml": "BC Gov Web - Unit & Component Tests",
  "ci-api-tests.yml": "BC Gov API - Unit & Integration Tests",
  "ci-ingestion-tests.yml": "BC Gov Ingestion - Tests",
  "ci-web-build.yml": "BC Gov Web - Build",
  "ci-e2e.yml": "BC Gov App - E2E Tests",
  "ci-containers.yml": "BC Gov App - Container Build & Smoke Tests",
  "automation-validation.yml": "BC Gov Automation - Tooling & Workflow Validation",
};
const operations = {
  "azure-pilot.yml": "BC Gov App - Azure Deployment",
  "official-source-collection.yml": "BC Gov Sources - Collection",
};
const agents = {
  "conversation-regression.md": "BC Gov Agents - PR Conversation QA",
  "live-conversation-regression.md": "BC Gov Agents - Live Conversation QA",
  "source-impact-triage.md": "BC Gov Agents - Source Impact Review",
  "official-source-watchdog.md": "BC Gov Agents - Source Freshness Triage",
  "bug-regression-fix.md": "BC Gov Agents - Bug Fix (Automatic)",
  "bug-to-regression-fix.md": "BC Gov Agents - Conversation Bug Fix (Opt-in)",
};

const source = (file) => readFileSync(path.join(directory, file), "utf8").replaceAll("\r\n", "\n");
const workflowName = (text) => text.match(/^name: "?([^"\n]+)"?$/m)?.[1];

// Check authored contracts here; the compiler and actionlint validate YAML semantics.
function section(text, key) {
  const lines = text.split("\n");
  const start = lines.findIndex((line) => line.startsWith(`${key}:`));
  assert.notEqual(start, -1, `Missing ${key}`);
  let end = start + 1;
  while (end < lines.length && !/^\S/.test(lines[end])) end++;
  return lines.slice(start, end).join("\n").trimEnd();
}

test("every repository workflow has a unique, descriptive name and contextual run title", () => {
  const expected = { ...ci, ...operations, ...agents };
  const files = readdirSync(directory).filter((file) =>
    file.endsWith(".md") || (file.endsWith(".yml") && !file.endsWith(".lock.yml")));
  assert.deepEqual(files.sort(), Object.keys(expected).sort());
  const names = files.map((file) => {
    const text = source(file);
    assert.equal(workflowName(text), expected[file], file);
    const title = section(text, "run-name");
    assert.ok(title.includes(expected[file]), file);
    assert.ok(title.includes("${{"), file);
    return workflowName(text);
  });
  assert.equal(new Set(names).size, names.length);
});

test("ordinary CI runs once per PR update and on main pushes with read-only permissions", () => {
  for (const file of Object.keys(ci)) {
    const text = source(file);
    assert.equal(section(text, "on"), "on:\n  push:\n    branches: [main]\n  pull_request:", file);
    assert.equal(section(text, "permissions"), "permissions:\n  contents: read", file);
    const jobs = section(text, "jobs");
    const count = [...jobs.matchAll(/^  [\w-]+:\n/gm)].length;
    assert.ok(count > 0, file);
    assert.equal([...jobs.matchAll(/^    name: BC Gov .+$/gm)].length, count, file);
  }
});

test("expanded CI check names identify components instead of matrix commands and paths", () => {
  const names = Object.keys(ci).flatMap((file) => {
    const text = source(file);
    return [...text.matchAll(/^    name: (.+)$/gm)].flatMap(([, name]) =>
      name.includes("${{ matrix.label }}")
        ? [...text.matchAll(/^            label: (.+)$/gm)].map(([, label]) =>
          name.replace("${{ matrix.label }}", label))
        : [name]);
  });
  assert.deepEqual(names.sort(), [
    "BC Gov Automation - Tooling Tests",
    "BC Gov Web - Unit & Component Tests",
    "BC Gov API - Unit & Integration Tests",
    "BC Gov Ingestion - Tests",
    "BC Gov Web - Type Check & Build",
    "BC Gov App - Browser E2E (Desktop & Mobile)",
    "BC Gov App - API Container",
    "BC Gov App - Web Container",
    "BC Gov App - Ingestion Container",
    "BC Gov Automation - Compile & Validate Workflows",
  ].sort());
});

test("each component test suite runs once in its own workflow with fixed setup", () => {
  const allCi = Object.keys(ci).map(source).join("\n");
  for (const [file, command] of [
    ["ci-web-tests.yml", "npm --prefix apps/web test"],
    ["ci-api-tests.yml", "python -m pytest -q"],
    ["ci-ingestion-tests.yml", "python -m unittest discover -s tests -q"],
  ]) {
    const text = source(file);
    assert.ok(text.includes(`run: ${command}\n`), file);
    assert.equal(allCi.split(`run: ${command}\n`).length - 1, 1, command);
    assert.equal([...section(text, "jobs").matchAll(/^  [\w-]+:\n/gm)].length, 1, file);
    assert.doesNotMatch(text, /matrix\.|strategy:|npm run build|test:e2e|docker build|gh aw compile|npm run test:tooling/);
  }
  const web = source("ci-web-tests.yml");
  assert.ok(web.includes('node-version: "24"'));
  assert.ok(web.includes("cache-dependency-path: apps/web/package-lock.json"));
  assert.ok(web.includes("run: npm --prefix apps/web ci"));
});

test("API and ingestion tests preserve Python version, locked installs and component directories", () => {
  for (const [file, component, extra] of [
    ["ci-api-tests.yml", "apps/api", "dev"],
    ["ci-ingestion-tests.yml", "ingestion", "azure"],
  ]) {
    const text = source(file);
    assert.ok(text.includes('python-version: "3.14"'));
    assert.deepEqual([...text.matchAll(/^        working-directory: (.+)$/gm)].map(([, value]) => value),
      [component, component], file);
    for (const command of [
      "if [ -f requirements-dev.lock ]; then",
      "python -m pip install -r requirements-dev.lock -e .",
      "elif [ -f requirements.lock ]; then",
      "python -m pip install -r requirements.lock",
      "python -m pip install --no-build-isolation --no-deps -e .",
      `python -m pip install -e ".[${extra}]"`,
    ]) assert.ok(text.includes(command), `${file}: ${command}`);
    assert.doesNotMatch(text, /setup-node|npm /);
  }
});

test("web build retains type checking and production packaging without running test suites", () => {
  const build = source("ci-web-build.yml");
  assert.ok(build.includes('node-version: "24"'));
  assert.ok(build.includes("cache-dependency-path: apps/web/package-lock.json"));
  assert.ok(build.includes("npm --prefix apps/web ci"));
  assert.ok(build.includes("npm --prefix apps/web run typecheck"));
  assert.ok(build.includes("npm run build"));
  assert.doesNotMatch(build, /test:e2e|apps\/web test|test:tooling|docker build|azd deploy/);
});

test("tooling runs only in automation and independently of the compiler job", () => {
  const validation = source("automation-validation.yml");
  const allCi = Object.keys(ci).map(source).join("\n");
  assert.equal(allCi.split("run: npm run test:tooling\n").length - 1, 1);
  assert.match(validation, /  tooling:\n    name: BC Gov Automation - Tooling Tests\n/);
  assert.ok(validation.includes('node-version: "24"'));
  assert.ok(validation.includes("run: npm run test:tooling"));
  assert.deepEqual([...section(validation, "jobs").matchAll(/^  ([\w-]+):\n/gm)].map(([, id]) => id),
    ["tooling", "agentic-workflows"]);
  assert.doesNotMatch(validation, /^    (?:needs|if):/m);
});

test("browser CI retains all four offline profiles and failure evidence", () => {
  const browser = source("ci-e2e.yml");
  assert.equal([...browser.matchAll(/run: npm run test:e2e$/gm)].length, 4);
  for (const label of ["Baseline", "Context Discovery", "AI Conversation", "Task Assistance"]) {
    assert.ok(browser.includes(`- name: ${label}\n        run: npm run test:e2e`));
  }
  for (const flag of ["CONVERSATION_DISCOVERY_ENABLED", "AI_CONVERSATION_ENABLED", "TASK_ASSISTANCE_ENABLED"]) {
    assert.ok(browser.includes(`${flag}: "true"`), flag);
  }
  assert.ok(browser.includes("npx --no-install playwright install --with-deps chromium"));
  assert.ok(browser.includes("if: failure()"));
  assert.ok(browser.includes("name: browser-failure-evidence"));
  assert.ok(browser.includes("retention-days: 7"));
  assert.doesNotMatch(browser, /LIVE_GROUNDED_EVAL|PILOT_BASE_URL|azd deploy/);
});

test("container CI retains all three offline target-platform smoke checks and never publishes", () => {
  const containers = source("ci-containers.yml");
  assert.deepEqual([...containers.matchAll(/- component: (.+)$/gm)].map(([, component]) => component),
    ["api", "web", "ingestion"]);
  for (const dockerfile of ["apps/api/Dockerfile", "apps/web/Dockerfile", "ingestion/Dockerfile"]) {
    assert.ok(containers.includes(`dockerfile: ${dockerfile}`));
  }
  assert.ok(containers.includes("docker build --platform linux/amd64"));
  assert.equal([...containers.matchAll(/docker run --rm --network none/g)].length, 3);
  assert.doesNotMatch(containers, /docker (?:push|login)|azd deploy|--push/);
});

test("workflow validation covers every generated workflow with the existing compiler pin", () => {
  const validation = source("automation-validation.yml");
  assert.ok(validation.includes("gh extension install github/gh-aw --pin v0.89.21"));
  assert.ok(validation.includes("run: gh aw compile --strict --validate --no-check-update\n"));
  assert.ok(validation.includes("git diff --exit-code -- '.github/workflows/*.lock.yml' .github/aw/actions-lock.json"));
  for (const [file, name] of Object.entries(agents)) {
    assert.equal(workflowName(source(file.replace(".md", ".lock.yml"))), name, file);
  }
});

test("renamed producers and compiled downstream triggers still match", () => {
  for (const [producer, consumer] of [
    ["azure-pilot.yml", "live-conversation-regression"],
    ["official-source-collection.yml", "official-source-watchdog"],
  ]) {
    const name = workflowName(source(producer));
    assert.ok(source(`${consumer}.md`).includes(`workflows: ["${name}"]`));
    const downstream = section(source(`${consumer}.lock.yml`), "on")
      .match(/^    workflows:\n((?:      - .+\n?)+)/m);
    assert.ok(downstream, consumer);
    assert.deepEqual([...downstream[1].matchAll(/^      - "?([^"\n]+)"?$/gm)].map(([, value]) => value),
      [name]);
  }
  assert.equal(workflowName(source("official-source-collection.yml")), collectorName);
  assert.equal(collectorPath, ".github/workflows/official-source-collection.yml");
});

test("deployment remains manual with separate provision, deploy and reviewed verification operations", () => {
  const deploy = source("azure-pilot.yml");
  const triggers = section(deploy, "on");
  assert.match(triggers, /^on:\n  workflow_dispatch:/);
  assert.doesNotMatch(triggers, /^  (?:push|pull_request|schedule|workflow_run):/m);
  assert.ok(triggers.includes("options: [provision, deploy, verify]"));
  assert.match(triggers, /live_checks:\n        type: boolean\n        default: false/);
  assert.ok(deploy.includes("if: inputs.operation != 'verify'"));
  assert.ok(deploy.includes("if: inputs.operation == 'verify'"));
  assert.ok(deploy.includes("if: inputs.operation == 'provision'"));
  assert.ok(deploy.includes("if: inputs.operation == 'deploy'"));
  assert.ok(deploy.includes('if [ "$state" != "Disabled" ]; then'));
  assert.ok(deploy.includes('if [ "$AZURE_LIVE_EVALUATION_APPROVED" != "1" ]; then'));
  assert.equal([...deploy.matchAll(/^    environment: pilot$/gm)].length, 2);
  assert.ok(deploy.includes("name: deployment-marker"));
});

test("post-deploy live QA still rejects provision-only and verification-only runs", () => {
  const live = source("live-conversation-regression.md");
  for (const gate of [
    '[[ "$QA_LIVE_ENABLED" == "true" ]]',
    '[[ "$UPSTREAM_CONCLUSION" == "success" ]]',
    '[[ "$(jq -r .operation <<<"$marker")" == "deploy" ]]',
    '[[ "$(jq -r .repository <<<"$marker")" == "$GITHUB_REPOSITORY" ]]',
    '[[ "$(jq -r .runId <<<"$marker")" == "$UPSTREAM_RUN_ID" ]]',
    '[[ "$(jq -r .sha <<<"$marker")" == "$UPSTREAM_SHA" ]]',
  ]) assert.ok(live.includes(gate), gate);
});

test("source collection keeps its serialized state and manual initialization contracts", () => {
  const collection = source("official-source-collection.yml");
  const triggers = section(collection, "on");
  assert.ok(triggers.includes('cron: "23 13 * * *"'));
  assert.match(triggers, /initialize:[\s\S]*default: false/);
  assert.doesNotMatch(triggers, /^  (?:push|pull_request):/m);
  assert.equal(section(collection, "concurrency"),
    "concurrency:\n  group: official-source-collection\n  cancel-in-progress: false");
  for (const contract of [
    "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)",
    "node scripts/agentic-workflows.mjs restore-source-state",
    "node scripts/agentic-workflows.mjs finalize-source-state",
    "name: official-source-state",
    "name: official-source-report",
    "retention-days: 90",
  ]) assert.ok(collection.includes(contract), contract);
});
