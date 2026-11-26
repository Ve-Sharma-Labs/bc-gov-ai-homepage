import assert from "node:assert/strict";
import test from "node:test";
import { appFingerprint, environment, rollOutPair } from "../azure-pyrit.mjs";
import { validateStagingProvision } from "../validate-staging-provision.mjs";

const commit = "a".repeat(40);
const images = {
  api: `registry.azurecr.io/api@sha256:${"b".repeat(64)}`,
  web: `registry.azurecr.io/web@sha256:${"c".repeat(64)}`,
};

function application(name, api = false) {
  return {
    name, identity: { type: "UserAssigned", userAssignedIdentities: { "owned-web-identity": {} } },
    properties: {
      environmentId: "/owned/environment",
      configuration: {
        activeRevisionsMode: "Single",
        secrets: [{ name: "hash-key" }],
        ingress: {
          external: !api, fqdn: `${name}${api ? ".internal" : ""}.example.azurecontainerapps.io`,
          traffic: [{ latestRevision: true, weight: 100 }],
        },
      },
      latestReadyRevisionName: `${name}--old`,
      template: {
        revisionSuffix: "old",
        containers: [{
          name, image: `registry.azurecr.io/${name}@sha256:${"d".repeat(64)}`,
          env: api ? [
            { name: "API_ALLOWED_HOSTS", value: `localhost,${name},${name}.internal.example.azurecontainerapps.io` },
            { name: "API_DAILY_TOKEN_LIMIT", value: "800000" },
          ] : [
            { name: "API_BASE_URL", value: "https://api.internal.example.azurecontainerapps.io" },
            { name: "CLIENT_HASH_KEY", secretRef: "hash-key" },
          ],
        }],
        scale: { minReplicas: 1, maxReplicas: 2 },
      },
    },
  };
}

function cloud({ privateFailure = false, publicFailure = false, drift = false, activeCount = 1 } = {}) {
  const apps = { "/api": application("api", true), "/web": application("web") };
  const original = structuredClone(apps);
  const events = [];
  return {
    context: { apiId: "/api", webId: "/web" }, apps, original, events,
    async pause() {},
    async pair() {
      return {
        api: structuredClone(apps["/api"]), web: structuredClone(apps["/web"]),
        apiRevision: { name: "api--old", properties: { template: structuredClone(apps["/api"].properties.template) } },
        webRevision: { name: "web--old", properties: { template: structuredClone(apps["/web"].properties.template) } },
      };
    },
    async get(id) {
      if (id.endsWith("/revisions")) {
        return { value: Array.from({ length: activeCount }, () => ({ properties: { active: true } })) };
      }
      return structuredClone(apps[id]);
    },
    async patchApp(id, previous, properties) {
      assert.equal(appFingerprint(apps[id]), appFingerprint(previous), "CONCURRENT_APP_CHANGE");
      events.push({ id, properties: structuredClone(properties) });
      Object.assign(apps[id].properties, structuredClone(properties));
      return structuredClone(apps[id]);
    },
    async waitReady(id, name) {
      events.push({ ready: name });
      return { properties: { template: structuredClone(apps[id].properties.template) } };
    },
    async privateProbe(_pair, apiUrl, image) {
      events.push({ privateProbe: apiUrl });
      assert.equal(image, images.web);
      assert.equal(apps["/web"].properties.configuration.ingress.traffic[0].revisionName, "web--old");
      if (privateFailure) throw new Error("PRIVATE_PROBE_FAILED");
      if (drift) apps["/api"].properties.template.scale.maxReplicas = 3;
    },
    async publicProbe(source) {
      events.push({ publicProbe: source || "rollback" });
      if (publicFailure && source) throw new Error("PUBLIC_CUTOVER_FAILED");
    },
  };
}

test("rollout pins old traffic, validates the paired private API, then switches only web traffic", async () => {
  const azure = cloud();
  const result = await rollOutPair(azure, images, commit, "candidate");
  assert.equal(azure.events[0].properties.configuration.ingress.traffic[0].revisionName, "api--old");
  assert.equal(azure.events[1].properties.configuration.ingress.traffic[0].revisionName, "web--old");
  const probe = azure.events.findIndex((event) => event.privateProbe);
  const switchIndex = azure.events.findIndex((event) =>
    event.properties?.configuration?.ingress.traffic[0].revisionName === "web--candidate");
  assert.ok(probe > 1 && switchIndex > probe);
  assert.equal(environment(azure.apps["/web"].properties.template).API_BASE_URL,
    "https://api--candidate.internal.example.azurecontainerapps.io");
  assert.equal(azure.apps["/api"].properties.configuration.ingress.traffic[0].revisionName, "api--old");
  assert.deepEqual(azure.apps["/web"].identity, azure.original["/web"].identity);
  assert.deepEqual(azure.apps["/web"].properties.configuration.secrets, [{ name: "hash-key" }]);
  assert.deepEqual(environment(azure.apps["/web"].properties.template).CLIENT_HASH_KEY, { secretRef: "hash-key" });
  assert.equal(environment(azure.apps["/api"].properties.template).API_DAILY_TOKEN_LIMIT, "800000");
  assert.equal(result.webRevision, "web--candidate");
});

test("a private probe failure leaves the old web revision serving", async () => {
  const azure = cloud({ privateFailure: true });
  await assert.rejects(rollOutPair(azure, images, commit, "candidate"), /PRIVATE_PROBE_FAILED/);
  assert.equal(azure.apps["/web"].properties.configuration.ingress.traffic[0].revisionName, "web--old");
  assert.ok(!azure.events.some((event) => event.publicProbe));
});

test("failed public verification restores the old named revision without closing Front Door", async () => {
  const azure = cloud({ publicFailure: true });
  await assert.rejects(rollOutPair(azure, images, commit, "candidate"), /PUBLIC_CUTOVER_FAILED/);
  assert.deepEqual(azure.apps["/web"].properties.configuration.ingress.traffic,
    [{ revisionName: "web--old", weight: 100 }]);
  assert.equal(azure.events.at(-1).publicProbe, "rollback");
  assert.ok(azure.events.every((event) => !event.id || ["/api", "/web"].includes(event.id)));
});

test("concurrent changes are detected before public traffic moves", async () => {
  const azure = cloud({ drift: true });
  await assert.rejects(rollOutPair(azure, images, commit, "candidate"), /CONCURRENT_API_CHANGE/);
  assert.equal(azure.apps["/web"].properties.configuration.ingress.traffic[0].revisionName, "web--old");
  assert.equal(azure.apps["/api"].properties.template.scale.maxReplicas, 3);
});

test("invalid images and exhausted retained-revision slots are rejected before writes", async () => {
  const azure = cloud();
  await assert.rejects(rollOutPair(azure, { ...images, api: "registry.azurecr.io/api:latest" }, commit, "candidate"));
  assert.equal(azure.events.length, 0);
  const full = cloud({ activeCount: 3 });
  await assert.rejects(rollOutPair(full, images, commit, "candidate"), /RETAINED_REVISION_LIMIT/);
  assert.equal(full.events.length, 0);
});

test("staging what-if refuses production changes, deletion, and subscription-level writes", () => {
  const prod = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/production/providers/Microsoft.App/containerApps/api";
  const stage = prod.replace("/production/", "/staging/");
  assert.doesNotThrow(() => validateStagingProvision({ status: "Succeeded", changes: [
    { resourceId: stage, changeType: "Create" },
  ] }, prod));
  for (const change of [
    { resourceId: prod, changeType: "Modify" },
    { resourceId: stage, changeType: "Delete" },
    { resourceId: "/subscriptions/00000000-0000-0000-0000-000000000001/providers/Microsoft.Authorization/roleAssignments/role", changeType: "Create" },
  ]) assert.throws(() => validateStagingProvision({ status: "Succeeded", changes: [change] }, prod));
});
