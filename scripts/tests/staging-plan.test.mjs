import assert from "node:assert/strict";
import test from "node:test";
import { stagingPlanBlockers } from "../verify-staging-plan.mjs";

const subscription = "11111111-1111-4111-8111-111111111111";
const productionGroup = `/subscriptions/${subscription}/resourceGroups/production`;
const stagingGroup = `/subscriptions/${subscription}/resourceGroups/staging`;
const context = {
  profileId: `${productionGroup}/providers/Microsoft.Cdn/profiles/shared`,
  stagingGroup: "staging",
  endpointName: "bc-staging",
};
const create = (resourceId) => ({ resourceId, changeType: "Create" });
const plan = (changes) => ({ status: "Succeeded", changes: [create(stagingGroup), ...changes] });

test("initial staging permits only its new resources and named shared-edge children", () => {
  assert.deepEqual(stagingPlanBlockers(plan([
    create(`${stagingGroup}/providers/Microsoft.App/containerApps/staging-api`),
    create(`${context.profileId}/afdEndpoints/bc-staging`),
    create(`${context.profileId}/afdEndpoints/bc-staging/routes/application`),
    create(`${context.profileId}/originGroups/bc-staging-web`),
    create(`${context.profileId}/securityPolicies/bc-staging-validation`),
    { resourceId: context.profileId, changeType: "NoChange" },
  ]), context), []);
});

test("a production mutation, unknown change, or unrelated edge child stops staging", () => {
  for (const change of [
    { resourceId: context.profileId, changeType: "Modify" },
    { resourceId: `${context.profileId}/afdEndpoints/production`, changeType: "Delete" },
    { resourceId: `${stagingGroup}/providers/Microsoft.App/containerApps/new`, changeType: "Ignore" },
    create(`${context.profileId}/originGroups/web`),
    create(`${productionGroup}/providers/Microsoft.App/containerApps/another-app`),
    create(`${stagingGroup}-different/providers/Microsoft.App/containerApps/another-app`),
  ]) assert.ok(stagingPlanBlockers(plan([change]), context).length, JSON.stringify(change));
});

test("incomplete evidence and production/staging identity overlap cannot qualify", () => {
  for (const value of [null, {}, { status: "Failed", changes: [] }, { status: "Succeeded", changes: [] }]) {
    assert.ok(stagingPlanBlockers(value, context).length);
  }
  assert.ok(stagingPlanBlockers(plan([]), { ...context, stagingGroup: "production" }).length);
  assert.ok(stagingPlanBlockers({ status: "Succeeded", changes: [
    { resourceId: context.profileId, changeType: "NoChange" },
  ] }, context).length);
  const messages = stagingPlanBlockers(plan([create("untrusted?credential=secret-value")]), context);
  assert.ok(messages.length);
  assert.ok(messages.every((message) => !message.includes("secret-value")));
});

test("Ignore is accepted only for byte-equivalent existing resources outside staging writes", () => {
  const before = { id: context.profileId, properties: { enabledState: "Enabled" } };
  const unchanged = { resourceId: context.profileId, changeType: "Ignore", before, after: structuredClone(before) };
  assert.deepEqual(stagingPlanBlockers(plan([unchanged]), context), []);
  for (const change of [
    { ...unchanged, after: null },
    { ...unchanged, after: { ...before, properties: { enabledState: "Disabled" } } },
    { ...unchanged, before: null },
    { ...unchanged, before: { id: 1 } },
    { resourceId: `${context.profileId}/afdEndpoints/bc-staging`, changeType: "Ignore", before, after: before },
  ]) assert.ok(stagingPlanBlockers(plan([change]), context).length);
  const identityId = `${stagingGroup}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-bc-staging-api`;
  const identity = { id: identityId, properties: { principalId: "verified-bootstrap-principal" } };
  assert.deepEqual(stagingPlanBlockers(plan([{
    resourceId: identityId, changeType: "Ignore", before: identity, after: structuredClone(identity),
  }]), context), []);
  assert.ok(stagingPlanBlockers(plan([{
    resourceId: identityId, changeType: "Ignore", before: identity, after: { ...identity, properties: {} },
  }]), context).length);
});
