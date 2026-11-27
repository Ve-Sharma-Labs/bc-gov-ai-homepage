import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export function validateStagingProvision(report, productionApiId) {
  assert.ok(/^\/subscriptions\/[a-f0-9-]{36}\/resourceGroups\/[^/]+\/providers\/Microsoft\.App\/containerApps\/[^/]+$/i
    .test(productionApiId || ""), "PRODUCTION_CONTEXT_REQUIRED");
  const protectedGroup = productionApiId.split("/providers/")[0].toLowerCase();
  assert.equal(report.status, "Succeeded", "WHAT_IF_INCOMPLETE");
  assert.ok(Array.isArray(report.changes), "WHAT_IF_CHANGES_REQUIRED");
  const groups = new Set();
  for (const change of report.changes) {
    assert.ok(["Create", "Modify", "NoChange", "Ignore"].includes(change.changeType),
      "UNREVIEWED_OR_DESTRUCTIVE_CHANGE");
    if (["NoChange", "Ignore"].includes(change.changeType)) continue;
    const id = String(change.resourceId).toLowerCase();
    assert.ok(id !== protectedGroup && !id.startsWith(protectedGroup + "/"),
      "PRODUCTION_PROVISIONING_FORBIDDEN");
    const group = id.match(/^\/subscriptions\/[a-f0-9-]{36}\/resourcegroups\/[^/]+/i)?.[0];
    assert.ok(group, "SUBSCRIPTION_MUTATION_FORBIDDEN");
    groups.add(group);
  }
  assert.ok(groups.size <= 1, "MULTIPLE_RESOURCE_GROUPS_FORBIDDEN");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const production = JSON.parse(process.env.PYRIT_PRODUCTION_CONTEXT_JSON || "{}");
    validateStagingProvision(JSON.parse(readFileSync(process.argv[2], "utf8")), production.apiId);
    console.log("The what-if contains no production or destructive changes.");
  } catch {
    console.error("STAGING_PROVISION_REVIEW_FAILED");
    process.exitCode = 1;
  }
}
