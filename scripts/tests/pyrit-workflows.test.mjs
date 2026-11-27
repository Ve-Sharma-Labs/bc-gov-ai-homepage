import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { deploymentBlockers } from "../azure-preflight.mjs";

const root = new URL("../../", import.meta.url);
const read = (file) => readFileSync(new URL(file, root), "utf8");
const dataset = JSON.parse(read("data/evaluations/pyrit-conversation-cases.json"));

test("each required threat and approach has an executable Actions step", () => {
  for (const [file, profile] of [
    [".github/workflows/ci-pyrit.yml", "offline"],
    [".github/workflows/pyrit-ai-red-teaming.yml", "live"],
  ]) {
    const workflow = read(file);
    const required = new Set(dataset.cases.filter((item) => item.profiles.includes(profile))
      .map((item) => `${item.threat}/${item.approach}`));
    const covered = new Set();
    for (const [, threat, approach] of workflow.matchAll(/--threat ([a-z-]+)(?: --approach ([a-z-]+))?/g)) {
      for (const item of required) {
        if (item.split("/")[0] === threat && (!approach || item.split("/")[1] === approach)) covered.add(item);
      }
    }
    assert.deepEqual(covered, required, file);
    assert.equal([...workflow.matchAll(/bc_pyrit\.cli init /g)].length, 1, file);
    assert.ok(workflow.includes("name: Require complete threat coverage"), file);
    assert.ok(workflow.includes("--require-pass"), file);
    assert.doesNotMatch(workflow, /continue-on-error|pull_request_target|--threat all/);
    assert.ok(workflow.includes("!cancelled() && steps.prepare.outcome == 'success'"));
  }
});

test("live execution is separate from PRs and needs explicit activation and drift verification", () => {
  const live = read(".github/workflows/pyrit-ai-red-teaming.yml");
  assert.doesNotMatch(live, /^  pull_request/m);
  assert.ok(live.includes('[[ "$ENABLED" == "true" ]]'));
  assert.ok(live.includes("environment: pilot-staging"));
  assert.ok(live.includes("client-id: ${{ vars.PYRIT_CLIENT_ID }}"));
  assert.ok(live.includes("id: identity_after"));
  assert.ok(live.includes("--code CANDIDATE_IDENTITY_NOT_VERIFIED"));
  assert.ok(live.includes('[[ "$IDENTITY_OUTCOME" == "success" ]]'));
  assert.doesNotMatch(live, /--threat indirect-injection|--threat resource-exhaustion/);
});

test("generic deployment and public provisioning cannot bypass the release workflow", () => {
  assert.ok(deploymentBlockers({}, "deploy").some((message) => message.includes("cannot bypass")));
  for (const env of [
    { AZURE_ENV_NAME: "production", AZURE_PRODUCTION_ENV_NAME: "production" },
    { AZURE_ENV_NAME: "stage", AZURE_PRODUCTION_ENV_NAME: "production", AZURE_DEPLOYMENT_STAGE: "public" },
    { AZURE_ENV_NAME: "stage" },
  ]) {
    assert.ok(deploymentBlockers(env, "provision").some((message) => message.includes("restricted to staging")));
  }
  const hooks = read("azure.yaml");
  assert.ok(hooks.includes("--operation=deploy"));
  assert.ok(hooks.includes("--operation=provision"));
});

test("conflicting release commit inputs are rejected", () => {
  const conflict = deploymentBlockers({ AZURE_RELEASE_COMMIT: "a".repeat(40), RELEASE_COMMIT: "b".repeat(40) }, "prepare");
  assert.ok(conflict.some((message) => message.includes("must identify the same source commit")));
  const matching = deploymentBlockers({ AZURE_RELEASE_COMMIT: "a".repeat(40), RELEASE_COMMIT: "a".repeat(40) }, "prepare");
  assert.ok(!matching.some((message) => message.includes("must identify the same source commit")));
});

test("report-only GH-AW runs consume sanitized artifacts without another scan", () => {
  const report = read(".github/workflows/live-conversation-regression.md");
  assert.ok(report.includes("node scripts/pyrit-report.mjs"));
  assert.ok(report.includes("name: live-qa-input"));
  assert.ok(report.includes("End the report-only run here."));
  assert.match(report, /do not run the\s+browser protocol or reset a chat budget/);
  assert.doesNotMatch(report, /bc_pyrit\.cli run|az login|AZURE_CLIENT_ID/);
});
