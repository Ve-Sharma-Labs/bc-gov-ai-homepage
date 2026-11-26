import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, rmdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { isIP } from "node:net";
import { fingerprint } from "./pyrit-evidence.mjs";
import { pinnedImage } from "./azure-preflight.mjs";
import { assertReleaseCapabilities, releaseTarget } from "./verify-pilot-chat.mjs";

const execute = promisify(execFile);
const APP_VERSION = "2025-01-01";
const EDGE_VERSION = "2025-06-01";
const MODEL_VERSION = "2025-06-01";
const environmentSpecific = new Set([
  "RELEASE_COMMIT", "RELEASE_ID", "API_ALLOWED_ORIGINS", "API_ALLOWED_HOSTS",
  "AZURE_CLIENT_ID", "REDIS_ENDPOINT", "REDIS_CLIENT_ID", "API_CONTROL_NAMESPACE",
  "API_AUTH_TENANT_ID", "API_AUTH_AUDIENCE", "API_AUTH_CALLERS", "FOUNDRY_PROJECT_ENDPOINT",
  "AZURE_SEARCH_ENDPOINT", "AZURE_OPENAI_ENDPOINT", "APPLICATIONINSIGHTS_CONNECTION_STRING",
  "API_BASE_URL", "API_AUTH_SCOPE", "FRONT_DOOR_ID", "CLIENT_HASH_KEY",
  "API_DAILY_RUN_LIMIT", "API_DAILY_TOKEN_LIMIT", "API_DAILY_COST_LIMIT_MICROUSD",
  "API_TOKEN_PRICE_MICROUSD",
]);

export function deploymentContext(value) {
  const fields = [
    "subscriptionId", "apiId", "webId", "probeJobId", "foundryAccountId",
    "frontDoorEndpointId", "wafPolicyId", "registryName", "origin",
  ];
  assert.ok(value && typeof value === "object" && !Array.isArray(value), "INVALID_AZURE_CONTEXT");
  assert.deepEqual(Object.keys(value).sort(), fields.sort(), "INVALID_AZURE_CONTEXT");
  assert.ok(/^[a-f0-9-]{36}$/i.test(value.subscriptionId), "INVALID_SUBSCRIPTION");
  const prefix = `/subscriptions/${value.subscriptionId}/resourceGroups/`;
  for (const [field, type] of Object.entries({
    apiId: "Microsoft.App/containerApps", webId: "Microsoft.App/containerApps",
    probeJobId: "Microsoft.App/jobs", foundryAccountId: "Microsoft.CognitiveServices/accounts",
    frontDoorEndpointId: "Microsoft.Cdn/profiles", wafPolicyId: "Microsoft.Network/frontdoorWebApplicationFirewallPolicies",
  })) {
    assert.ok(typeof value[field] === "string" && value[field].toLowerCase().startsWith(prefix.toLowerCase())
      && /^[A-Za-z0-9/()._-]+$/.test(value[field])
      && value[field].includes(`/providers/${type}/`), "RESOURCE_OUTSIDE_REVIEWED_CONTEXT");
  }
  assert.notEqual(value.apiId, value.webId, "DISTINCT_APPS_REQUIRED");
  assert.ok(/^[a-z0-9]{5,50}$/.test(value.registryName), "INVALID_REGISTRY");
  assert.equal(releaseTarget(value.origin).origin, value.origin, "EXACT_ORIGIN_REQUIRED");
  assert.ok(value.origin.startsWith("https://"), "HTTPS_REQUIRED");
  return value;
}

export function container(template) {
  assert.ok(template && Array.isArray(template.containers) && template.containers.length === 1,
    "SINGLE_REVIEWED_CONTAINER_REQUIRED");
  return template.containers[0];
}

export function environment(template) {
  const entries = container(template).env || [];
  assert.equal(new Set(entries.map((entry) => entry.name)).size, entries.length, "DUPLICATE_ENVIRONMENT_KEY");
  return Object.fromEntries(entries.map((entry) => [entry.name, entry.value ?? { secretRef: entry.secretRef }]));
}

export function stampedTemplate(template, image, commit, suffix, changes = {}) {
  assert.ok(pinnedImage.test(image) && /^[a-f0-9]{40}$/.test(commit)
    && /^[a-z0-9][a-z0-9-]{0,63}$/.test(suffix), "INVALID_RELEASE_IMAGE");
  const updated = structuredClone(template);
  const target = container(updated);
  target.image = image;
  updated.revisionSuffix = suffix;
  const values = { RELEASE_COMMIT: commit, RELEASE_ID: suffix, ...changes };
  target.env = (target.env || []).filter((entry) => !Object.hasOwn(values, entry.name));
  target.env.push(...Object.entries(values).map(([name, value]) => ({ name, value })));
  return updated;
}

export function activeRevision(app) {
  const traffic = app.properties.configuration.ingress.traffic;
  assert.ok(Array.isArray(traffic), "EXPLICIT_TRAFFIC_REQUIRED");
  const active = traffic.filter((item) => item.weight > 0);
  assert.ok(active.length === 1 && active[0].weight === 100, "AMBIGUOUS_PRODUCTION_TRAFFIC");
  const revision = active[0].revisionName
    || (active[0].latestRevision === true ? app.properties.latestReadyRevisionName : "");
  assert.ok(typeof revision === "string" && revision.startsWith(`${app.name}--`), "UNKNOWN_ACTIVE_REVISION");
  return revision;
}

export function appFingerprint(app) {
  return fingerprint({
    identity: app.identity, environmentId: app.properties.environmentId,
    configuration: app.properties.configuration, template: app.properties.template,
    workloadProfileName: app.properties.workloadProfileName,
  });
}

function contains(actual, expected) {
  if (Array.isArray(expected)) {
    return Array.isArray(actual) && actual.length === expected.length
      && expected.every((value, index) => contains(actual[index], value));
  }
  if (expected && typeof expected === "object") {
    return actual && typeof actual === "object"
      && Object.entries(expected).every(([key, value]) => contains(actual[key], value));
  }
  return actual === expected;
}

export function configurationFingerprint(apiTemplate, webTemplate) {
  const normalized = (template) => Object.fromEntries(
    Object.entries(environment(template)).filter(([name]) => !environmentSpecific.has(name)).map(([name, value]) => {
      if (/^FOUNDRY_.*AGENTS?$/.test(name) && typeof value === "string" && value) {
        const bindings = JSON.parse(value);
        const policyBinding = (binding) => {
          assert.ok(binding && binding.name && binding.version && binding.modelDeployment, "INVALID_AGENT_BINDING");
          return { modelDeployment: binding.modelDeployment, journeyId: binding.journeyId ?? null };
        };
        value = Array.isArray(bindings) ? bindings.map(policyBinding) : policyBinding(bindings);
      }
      return [name, value];
    }),
  );
  return fingerprint({ api: normalized(apiTemplate), web: normalized(webTemplate) });
}

export class AzurePilot {
  constructor(context, { run = execute, fetchImpl = fetch, pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) } = {}) {
    this.context = deploymentContext(context);
    this.run = run;
    this.fetch = fetchImpl;
    this.pause = pause;
  }

  async request(id, method = "GET", body, version = APP_VERSION, resource = "https://management.azure.com/") {
    assert.ok(process.env.GITHUB_ACTIONS === "true" && process.env.GITHUB_REF === "refs/heads/main",
      "PROTECTED_GITHUB_RUN_REQUIRED");
    const url = id.startsWith("https://") ? id
      : `https://management.azure.com${id}?api-version=${version}`;
    if (resource === "https://management.azure.com/") {
      assert.ok(url.toLowerCase().startsWith(
        `https://management.azure.com/subscriptions/${this.context.subscriptionId}/`.toLowerCase()),
      "RESOURCE_OUTSIDE_REVIEWED_CONTEXT");
    } else {
      const target = new URL(url);
      assert.ok(resource === "https://search.azure.com" && target.protocol === "https:"
        && target.hostname.endsWith(".search.windows.net") && !target.username && !target.password
        && /^\/indexes\/[a-z0-9-]+\/docs\/search$/.test(target.pathname), "UNAPPROVED_DATA_ENDPOINT");
    }
    let directory;
    try {
      const args = ["rest", "--method", method, "--uri", url,
        "--subscription", this.context.subscriptionId, "--resource", resource, "--output", "json"];
      if (body !== undefined) {
        directory = await mkdtemp(path.join(tmpdir(), "bc-release-"));
        const filename = path.join(directory, "body.json");
        await writeFile(filename, JSON.stringify(body), { mode: 0o600 });
        args.push("--body", `@${filename}`, "--headers", "Content-Type=application/json");
      }
      const output = await this.run("az", args, { maxBuffer: 16 * 1024 * 1024, timeout: 120_000 });
      return output.stdout.trim() ? JSON.parse(output.stdout) : null;
    } catch {
      throw new Error("AZURE_REQUEST_FAILED");
    } finally {
      if (directory) {
        await rm(path.join(directory, "body.json"));
        await rmdir(directory);
      }
    }
  }

  get(id, version) { return this.request(id, "GET", undefined, version); }

  async patchApp(id, previous, properties) {
    const current = await this.get(id);
    assert.equal(appFingerprint(current), appFingerprint(previous), "CONCURRENT_APP_CHANGE");
    await this.request(id, "PATCH", { properties });
    for (let attempt = 0; attempt < 60; attempt++) {
      const updated = await this.get(id);
      if (contains(updated.properties, properties)) return updated;
      await this.pause(2000);
    }
    throw new Error("APP_UPDATE_NOT_OBSERVED");
  }

  async pair() {
    const { apiId, webId } = this.context;
    const [api, web] = await Promise.all([this.get(apiId), this.get(webId)]);
    assert.equal(api.properties.environmentId, web.properties.environmentId, "MISMATCHED_APP_ENVIRONMENTS");
    assert.ok(api.properties.environmentId.toLowerCase().startsWith(
      this.context.apiId.split("/providers/")[0].toLowerCase() + "/"), "ENVIRONMENT_OUTSIDE_OWNED_GROUP");
    assert.equal(api.properties.configuration.ingress.external, false, "API_MUST_REMAIN_PRIVATE");
    const managed = await this.get(api.properties.environmentId);
    assert.equal(managed.properties.publicNetworkAccess, "Disabled", "PRIVATE_ENVIRONMENT_REQUIRED");
    const webRevision = await this.get(`${webId}/revisions/${activeRevision(web)}`);
    const apiBase = new URL(environment(webRevision.properties.template).API_BASE_URL);
    const apiHost = api.properties.configuration.ingress.fqdn;
    let apiName;
    if (apiBase.hostname === apiHost) apiName = activeRevision(api);
    else {
      assert.ok(apiBase.protocol === "https:" && apiBase.hostname.endsWith(apiHost.slice(api.name.length))
        && apiBase.hostname.startsWith(`${api.name}--`), "WEB_API_PAIR_MISMATCH");
      apiName = apiBase.hostname.split(".")[0];
    }
    const apiRevision = await this.get(`${apiId}/revisions/${apiName}`);
    return { api, web, apiRevision, webRevision };
  }

  async publicProbe(commit, suffix) {
    const response = await this.fetch(`${this.context.origin}/api/capabilities`, {
      redirect: "error", headers: { "X-BC-Client-Version": "6" },
      signal: AbortSignal.timeout(50_000), cache: "no-store",
    });
    assert.equal(response.status, 200, "PUBLIC_READINESS_FAILED");
    if (commit) {
      for (const name of ["x-bc-web-release", "x-bc-api-release"]) {
        assert.equal(response.headers.get(name), commit, "PUBLIC_RELEASE_MISMATCH");
      }
      for (const name of ["x-bc-web-deployment", "x-bc-api-deployment"]) {
        assert.equal(response.headers.get(name), suffix, "PUBLIC_REVISION_PAIR_MISMATCH");
      }
    }
    const capabilities = await response.json();
    assertReleaseCapabilities(capabilities);
    return capabilities;
  }

  async capture({ staging = false } = {}) {
    const pair = await this.pair();
    const env = environment(pair.apiRevision.properties.template);
    const endpoint = await this.get(this.context.frontDoorEndpointId, EDGE_VERSION);
    assert.equal(`https://${endpoint.properties.hostName}`, this.context.origin, "EDGE_ORIGIN_MISMATCH");
    assert.equal(endpoint.properties.enabledState, "Enabled", "EDGE_NOT_ENABLED");
    const waf = await this.get(this.context.wafPolicyId, "2024-02-01");
    assert.equal(waf.properties.policySettings.enabledState, "Enabled", "WAF_DISABLED");
    assert.equal(waf.properties.policySettings.mode, "Prevention", "WAF_NOT_PREVENTING");
    if (staging) {
      const guard = waf.properties.customRules.rules.find((rule) => rule.name === "ValidationOnly");
      assert.ok(guard?.action === "Block" && guard.enabledState === "Enabled" && guard.priority === 1
        && guard.matchConditions.length === 1
        && guard.matchConditions.some((condition) => condition.matchVariable === "SocketAddr"
          && condition.operator === "IPMatch" && condition.negateCondition === true
          && Array.isArray(condition.matchValue) && condition.matchValue.length > 0
          && condition.matchValue.every((value) => {
            const [address, bits] = value.split("/");
            return isIP(address) === 4 && /^(?:2[4-9]|3[0-2])$/.test(bits || "");
          })),
      "STAGING_IP_RESTRICTION_REQUIRED");
    }
    const profileId = this.context.frontDoorEndpointId.split("/afdEndpoints/")[0];
    const origin = await this.get(`${profileId}/originGroups/web/origins/container-app`, EDGE_VERSION);
    assert.equal(origin.properties.hostName, pair.web.properties.configuration.ingress.fqdn, "EDGE_APP_MISMATCH");
    assert.equal(origin.properties.enforceCertificateNameCheck, true, "ORIGIN_TLS_REQUIRED");
    assert.equal(origin.properties.sharedPrivateLinkResource?.privateLink?.id,
      pair.web.properties.environmentId, "PRIVATE_ORIGIN_MISMATCH");
    assert.equal(origin.properties.sharedPrivateLinkResource?.status, "Approved", "PRIVATE_ORIGIN_NOT_APPROVED");
    const search = new URL(env.AZURE_SEARCH_ENDPOINT);
    assert.ok(search.protocol === "https:" && search.hostname.endsWith(".search.windows.net")
      && !search.username && !search.password && !search.search && !search.hash
      && ["", "/"].includes(search.pathname), "INVALID_SEARCH_ENDPOINT");
    assert.ok(/^[a-z0-9][a-z0-9-]{0,127}$/.test(env.AZURE_SEARCH_INDEX), "INVALID_SEARCH_INDEX");
    const documents = await this.request(
      `${search.origin}/indexes/${env.AZURE_SEARCH_INDEX}/docs/search?api-version=2024-07-01`,
      "POST", { search: "*", filter: "status eq 'active'", top: 1000, count: true },
      undefined, "https://search.azure.com",
    );
    assert.ok(Array.isArray(documents.value) && documents.value.length > 0
      && documents["@odata.count"] === documents.value.length && !documents["@odata.nextLink"],
    "INCOMPLETE_SOURCE_SNAPSHOT");
    const rows = documents.value.map((row) => Object.fromEntries(
      Object.entries(row).filter(([key]) => !key.startsWith("@"))));
    assert.equal(new Set(rows.map((row) => row.id)).size, rows.length, "DUPLICATE_SOURCE_RECORD");
    rows.sort((a, b) => String(a.id).localeCompare(String(b.id), "en"));
    const inventory = await this.get(`${this.context.foundryAccountId}/deployments`, MODEL_VERSION);
    const accountName = this.context.foundryAccountId.split("/").at(-1);
    assert.equal(new URL(env.FOUNDRY_PROJECT_ENDPOINT).hostname,
      `${accountName}.services.ai.azure.com`, "MODEL_ACCOUNT_MISMATCH");
    assert.ok(Array.isArray(inventory.value) && inventory.value.length > 0
      && !inventory.nextLink, "INCOMPLETE_MODEL_INVENTORY");
    const models = inventory.value.map((item) => {
      assert.equal(item.properties.versionUpgradeOption, "NoAutoUpgrade", "MOVING_MODEL_VERSION");
      return { name: item.name, model: item.properties.model, sku: item.sku.name };
    }).sort((a, b) => a.name.localeCompare(b.name, "en"));
    return {
      pair,
      configurationSha256: configurationFingerprint(pair.apiRevision.properties.template, pair.webRevision.properties.template),
      sourceSha256: fingerprint(rows), modelSha256: fingerprint(models),
      images: {
        api: container(pair.apiRevision.properties.template).image,
        web: container(pair.webRevision.properties.template).image,
      },
    };
  }

  async waitReady(id, name) {
    for (let attempt = 0; attempt < 90; attempt++) {
      const revision = await this.get(`${id}/revisions/${name}`);
      const properties = revision.properties;
      if (properties.provisioningState === "Provisioned" && properties.healthState === "Healthy"
        && properties.runningState === "Running") return revision;
      assert.ok(!["Failed", "Deprovisioned"].includes(properties.provisioningState)
        && properties.healthState !== "Unhealthy", "CANDIDATE_REVISION_FAILED");
      await this.pause(2000);
    }
    throw new Error("CANDIDATE_READINESS_TIMEOUT");
  }

  async privateProbe(pair, apiUrl, image, commit, suffix) {
    const job = await this.get(this.context.probeJobId);
    assert.equal(job.tags?.purpose, "pyrit-private-readiness", "UNOWNED_PROBE_JOB");
    assert.equal(job.properties.environmentId, pair.web.properties.environmentId, "PROBE_ENVIRONMENT_MISMATCH");
    assert.deepEqual(Object.keys(job.identity.userAssignedIdentities).sort(),
      Object.keys(pair.web.identity.userAssignedIdentities).sort(), "PROBE_IDENTITY_MISMATCH");
    const config = job.properties.configuration;
    assert.equal(config.triggerType, "Manual", "PROBE_MUST_BE_MANUAL");
    assert.equal(config.replicaRetryLimit, 0, "PROBE_RETRIES_FORBIDDEN");
    assert.ok(config.replicaTimeout > 0 && config.replicaTimeout <= 120
      && config.manualTriggerConfig?.parallelism === 1
      && config.manualTriggerConfig?.replicaCompletionCount === 1, "UNBOUNDED_PROBE");
    const executions = await this.get(`${this.context.probeJobId}/executions`);
    assert.ok(Array.isArray(executions.value)
      && !executions.value.some((item) => ["Running", "Processing", "Pending"].includes(item.properties.status)),
    "PROBE_ALREADY_RUNNING");
    const webEnv = environment(pair.webRevision.properties.template);
    const code = await readFile(new URL("./private-release-probe.mjs", import.meta.url), "utf8");
    const env = {
      API_BASE_URL: apiUrl, API_AUTH_SCOPE: webEnv.API_AUTH_SCOPE,
      AZURE_CLIENT_ID: webEnv.AZURE_CLIENT_ID, PUBLIC_ORIGIN: this.context.origin,
      RELEASE_COMMIT: commit, RELEASE_ID: suffix,
    };
    assert.ok(Object.values(env).every((value) => typeof value === "string" && value), "INVALID_PROBE_CONTEXT");
    await this.request(this.context.probeJobId, "PATCH", { properties: { template: {
      containers: [{
        name: "probe", image, command: ["node", "--input-type=module", "-e", code],
        env: Object.entries(env).map(([name, value]) => ({ name, value })),
        resources: { cpu: 0.25, memory: "0.5Gi" },
      }],
    } } });
    const started = await this.request(`${this.context.probeJobId}/start`, "POST", {});
    assert.ok(/^[a-z0-9-]+$/.test(started?.name || ""), "PROBE_EXECUTION_ID_REQUIRED");
    for (let attempt = 0; attempt < 120; attempt++) {
      const page = await this.get(`${this.context.probeJobId}/executions`);
      const execution = page.value?.find((item) => item.name === started.name);
      if (execution?.properties.status === "Succeeded") return;
      assert.ok(!["Failed", "Stopped", "Degraded"].includes(execution?.properties.status), "PRIVATE_PROBE_FAILED");
      await this.pause(2000);
    }
    throw new Error("PRIVATE_PROBE_TIMEOUT");
  }
}

export async function rollOutPair(azure, images, commit, suffix, qualification = null) {
  assert.ok(pinnedImage.test(images.api) && pinnedImage.test(images.web)
  && /^[a-f0-9]{40}$/.test(commit) && /^[a-z0-9][a-z0-9-]{0,63}$/.test(suffix),
  "INVALID_RELEASE_IMAGE");
  const pair = await azure.pair();
  for (const id of [azure.context.apiId, azure.context.webId]) {
  const revisions = await azure.get(`${id}/revisions`);
  assert.ok(Array.isArray(revisions.value) && !revisions.nextLink
    && revisions.value.every((revision) => typeof revision.properties.active === "boolean"),
  "INCOMPLETE_REVISION_INVENTORY");
  assert.ok(revisions.value.filter((revision) => revision.properties.active).length < 3,
    "RETAINED_REVISION_LIMIT");
  }
  const previousTraffic = structuredClone(pair.web.properties.configuration.ingress.traffic);
  const pin = async (id, app) => {
    const configuration = structuredClone(app.properties.configuration);
    configuration.activeRevisionsMode = "Multiple";
    configuration.ingress.traffic = [{ revisionName: activeRevision(app), weight: 100 }];
    return azure.patchApp(id, app, { configuration });
  };
  let api = await pin(azure.context.apiId, pair.api);
  let web = await pin(azure.context.webId, pair.web);
  const apiRevision = `${api.name}--${suffix}`;
  const webRevision = `${web.name}--${suffix}`;
  const apiHost = apiRevision + api.properties.configuration.ingress.fqdn.slice(api.name.length);
  const apiEnv = environment(pair.apiRevision.properties.template);
  const hosts = [...new Set([...(apiEnv.API_ALLOWED_HOSTS || "").split(",").map((host) => host.trim())
    .filter((host) => host && !host.startsWith(`${api.name}--`)), apiHost])].join(",");
  const apiTemplate = stampedTemplate(pair.apiRevision.properties.template, images.api, commit, suffix, { API_ALLOWED_HOSTS: hosts });
  const webTemplate = stampedTemplate(pair.webRevision.properties.template, images.web, commit, suffix, { API_BASE_URL: `https://${apiHost}` });
  let switched = false;
  try {
    api = await azure.patchApp(azure.context.apiId, api, { template: apiTemplate });
    const readyApi = await azure.waitReady(azure.context.apiId, apiRevision);
    assert.equal(container(readyApi.properties.template).image, images.api, "API_IMAGE_MISMATCH");
    web = await azure.patchApp(azure.context.webId, web, { template: webTemplate });
    const readyWeb = await azure.waitReady(azure.context.webId, webRevision);
    assert.equal(container(readyWeb.properties.template).image, images.web, "WEB_IMAGE_MISMATCH");
    await azure.privateProbe(pair, `https://${apiHost}`, images.web, commit, suffix);
    if (qualification) {
      const current = await azure.capture();
      for (const key of ["configurationSha256", "sourceSha256", "modelSha256"]) {
        assert.equal(current[key], qualification[key], "QUALIFICATION_DRIFT");
      }
    }
    const currentApi = await azure.get(azure.context.apiId);
    const currentWeb = await azure.get(azure.context.webId);
    assert.equal(appFingerprint(currentApi), appFingerprint(api), "CONCURRENT_API_CHANGE");
    assert.equal(appFingerprint(currentWeb), appFingerprint(web), "CONCURRENT_WEB_CHANGE");
    const configuration = structuredClone(web.properties.configuration);
    configuration.ingress.traffic = [{ revisionName: webRevision, weight: 100 }];
    web = await azure.patchApp(azure.context.webId, web, { configuration });
    switched = true;
    let verified = false;
    for (let attempt = 0; attempt < 30; attempt++) {
      try {
        await azure.publicProbe(commit, suffix);
        verified = true;
        break;
      } catch {
        await azure.pause(2000);
      }
    }
    assert.ok(verified, "PUBLIC_CUTOVER_FAILED");
    return {
      apiRevision, webRevision,
      previous: { apiRevision: pair.apiRevision.name, webRevision: pair.webRevision.name },
    };
  } catch (error) {
    if (switched) {
      const configuration = structuredClone(web.properties.configuration);
      configuration.ingress.traffic = previousTraffic.map((entry) => (
        entry.latestRevision ? { revisionName: pair.webRevision.name, weight: entry.weight } : entry
      ));
      await azure.patchApp(azure.context.webId, web, { configuration });
      await azure.publicProbe();
    }
    throw error;
  }
}
