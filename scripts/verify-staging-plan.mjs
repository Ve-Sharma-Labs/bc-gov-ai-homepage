import { readFile } from "node:fs/promises";
import { isDeepStrictEqual } from "node:util";
import { pathToFileURL } from "node:url";

export function stagingPlanBlockers(plan, { profileId, stagingGroup, endpointName }) {
  const profile = typeof profileId === "string" && profileId.match(
    /^\/subscriptions\/([a-f0-9-]{36})\/resourceGroups\/([^/]+)\/providers\/Microsoft\.Cdn\/profiles\/([^/]+)$/iu,
  );
  if (!profile || !/^[a-z0-9][a-z0-9-]{0,79}$/iu.test(stagingGroup || "")
    || !/^[a-z0-9][a-z0-9-]{0,49}$/iu.test(endpointName || "")
    || profile[2].toLowerCase() === stagingGroup.toLowerCase()) {
    return ["Select a distinct staging resource group and exact shared profile/endpoint identity."];
  }
  if (plan?.status !== "Succeeded" || !Array.isArray(plan.changes) || !plan.changes.length) {
    return ["A complete, successful, nonempty ARM what-if result is required."];
  }
  const groupId = `/subscriptions/${profile[1]}/resourceGroups/${stagingGroup}`.toLowerCase();
  const edgeId = profileId.toLowerCase();
  const endpoint = endpointName.toLowerCase();
  const edgeGroupId = `/subscriptions/${profile[1]}/resourceGroups/${profile[2]}`.toLowerCase();
  const allowedEdgeCreates = new Set([
    `${edgeId}/afdendpoints/${endpoint}`,
    `${edgeId}/afdendpoints/${endpoint}/routes/application`,
    `${edgeId}/origingroups/${endpoint}-web`,
    `${edgeId}/origingroups/${endpoint}-web/origins/container-app`,
    `${edgeId}/securitypolicies/${endpoint}-validation`,
    `${edgeGroupId}/providers/microsoft.resources/deployments/staging-endpoint-${endpoint}`,
    `${edgeGroupId}/providers/microsoft.resources/deployments/staging-routes-${endpoint}`,
  ]);
  const bootstrappedIdentities = new Set(["api", "web", "publisher"].map(
    (role) => `${groupId}/providers/microsoft.managedidentity/userassignedidentities/id-${endpoint}-${role}`,
  ));
  const blockers = [];
  let createsStaging = false;
  for (const [index, change] of plan.changes.entries()) {
    if (typeof change?.resourceId !== "string" || typeof change.changeType !== "string") {
      blockers.push("The what-if contains an invalid change record.");
      continue;
    }
    const id = change.resourceId.toLowerCase();
    if (change.changeType === "NoChange") continue;
    if (change.changeType === "Ignore"
      && (id === edgeGroupId || id.startsWith(`${edgeGroupId}/providers/`) || bootstrappedIdentities.has(id))
      && !allowedEdgeCreates.has(id)
      && typeof change.before?.id === "string"
      && change.before.id.toLowerCase() === id
      && isDeepStrictEqual(change.before, change.after)) continue;
    if (change.changeType !== "Create") {
      blockers.push(`Change ${index + 1} is not an approved initial resource creation.`);
      continue;
    }
    if (id === groupId || id.startsWith(`${groupId}/providers/`)) {
      createsStaging = true;
    } else if (!allowedEdgeCreates.has(id)) {
      blockers.push(`Change ${index + 1} creates a resource outside the reviewed staging boundary.`);
    }
  }
  if (!createsStaging) blockers.push("The what-if does not create the selected staging environment.");
  return blockers;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [file, profileId, stagingGroup, endpointName] = process.argv.slice(2);
  try {
    if (!file) throw new Error("Provide the saved what-if JSON, profile ID, staging group, and endpoint name.");
    const plan = JSON.parse(await readFile(file, "utf8"));
    const blockers = stagingPlanBlockers(plan, { profileId, stagingGroup, endpointName });
    if (blockers.length) {
      console.error(blockers.join("\n"));
      process.exitCode = 1;
    } else {
      console.log("Initial staging changes stay within the reviewed resource boundary. No deployment was run.");
    }
  } catch {
    console.error("Could not read a valid staging what-if. Provide its JSON file, profile ID, staging group, and endpoint name.");
    process.exitCode = 1;
  }
}
