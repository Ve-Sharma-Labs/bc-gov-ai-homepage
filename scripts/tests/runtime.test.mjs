import assert from "node:assert/strict";
import test from "node:test";
import { deploymentBlockers } from "../azure-preflight.mjs";
import { localSettings, portFrom } from "../runtime.mjs";

const reviewedEnvironment = {
  AZURE_PROVISIONING_APPROVED: "1",
  AZURE_DEPLOYMENT_REVIEWED: "1",
  AZURE_SUBSCRIPTION_ID: "11111111-1111-4111-8111-111111111111",
  AZURE_LOCATION: "reviewed-location",
  AZURE_ENV_NAME: "fixture",
  AZURE_API_APPLICATION_CLIENT_ID: "22222222-2222-4222-8222-222222222222",
  AZURE_SEARCH_SKU: "reviewed-search-sku",
  AZURE_SEARCH_INDEX: "bc-pilot-public",
  AZURE_SEARCH_METADATA_ENABLED: "false",
  AZURE_REDIS_SKU: "reviewed-redis-sku",
  AZURE_MODEL_DEPLOYMENTS: JSON.stringify([{ deploymentName: "fixture", modelName: "fixture", modelVersion: "pinned", sku: "reviewed-sku", capacity: 1 }]),
  AZURE_PILOT_CONTROLS: JSON.stringify({ runLimit: 20, tokenLimit: 1000000, costLimitMicrousd: 1000000, tokenPriceMicrousd: 1, apiMaxReplicas: 2, webMaxReplicas: 2 }),
  AZURE_NETWORK_PREFIX: "10.42.0.0/16",
  AZURE_APPS_SUBNET_PREFIX: "10.42.0.0/23",
  AZURE_PRIVATE_SUBNET_PREFIX: "10.42.4.0/24",
};

test("local ports default to loopback addresses", () => {
  const settings = localSettings({});
  assert.equal(settings.webUrl, "http://127.0.0.1:3000");
  assert.equal(settings.apiUrl, "http://127.0.0.1:8000");
});

test("ports reject invalid input and collisions", () => {
  for (const value of ["-1", "3000oops", "0", "80", "65536", "3.5"]) {
    assert.throws(() => portFrom(value, 3000, "WEB_PORT"));
  }
  assert.throws(() => localSettings({ WEB_PORT: "8000", API_PORT: "8000" }));
  assert.equal(portFrom("43000", 3000, "WEB_PORT"), 43000);
});

test("Azure preflight fails closed without explicit review and context", () => {
  assert.ok(deploymentBlockers({}).length >= 5);
  assert.ok(deploymentBlockers({
    AZURE_PROVISIONING_APPROVED: "1",
    AZURE_SUBSCRIPTION_ID: "example",
    AZURE_LOCATION: "example",
    AZURE_ENV_NAME: "example",
  }).some((message) => message.includes("review")));
});

test("Azure approval flags are necessary, not proof of deployment validation", () => {
  assert.deepEqual(deploymentBlockers(reviewedEnvironment), []);
  assert.ok(deploymentBlockers({ ...reviewedEnvironment, AZURE_SEARCH_METADATA_ENABLED: "true" }).length);
  assert.ok(deploymentBlockers({ ...reviewedEnvironment, AZURE_SEARCH_METADATA_ENABLED: "invalid" }).length);
  assert.deepEqual(deploymentBlockers({
    ...reviewedEnvironment,
    AZURE_SEARCH_INDEX: "bc-pilot-public-v2",
    AZURE_SEARCH_METADATA_ENABLED: "true",
    AZURE_SEARCH_METADATA_REVIEWED: "1",
  }), []);
  for (const change of [
    { AZURE_SEARCH_INDEX: "bc-pilot-public-v2" },
    { AZURE_SEARCH_METADATA_ENABLED: "true", AZURE_SEARCH_METADATA_REVIEWED: "1" },
    { AZURE_SEARCH_METADATA_REVIEWED: "1" },
  ]) {
    assert.ok(deploymentBlockers({ ...reviewedEnvironment, ...change }).some(
      (message) => message.includes("one reviewed API revision")
    ));
  }
});

test("malformed budgets, overlapping networks and moving model defaults fail closed", () => {
  for (const change of [
    { AZURE_MODEL_DEPLOYMENTS: "null" },
    { AZURE_MODEL_DEPLOYMENTS: JSON.stringify([{ deploymentName: "fixture", modelName: "fixture", sku: "sku", capacity: 1 }]) },
    { AZURE_PILOT_CONTROLS: "null" },
    { AZURE_PILOT_CONTROLS: JSON.stringify({ runLimit: 1, tokenLimit: 1, costLimitMicrousd: 1, tokenPriceMicrousd: 1, apiMaxReplicas: 1, webMaxReplicas: 1 }) },
    { AZURE_PRIVATE_SUBNET_PREFIX: "10.42.0.0/24" },
  ]) assert.ok(deploymentBlockers({ ...reviewedEnvironment, ...change }).length);
});

test("public exposure needs real release gates beyond resource creation approval", () => {
  const blockers = deploymentBlockers({ ...reviewedEnvironment, AZURE_DEPLOYMENT_STAGE: "public", FOUNDRY_AGENTS: "[null]" });
  assert.ok(blockers.some((message) => message.includes("LIVE_EVALUATION")));
  assert.ok(blockers.some((message) => message.includes("seven actually published")));
  assert.ok(deploymentBlockers({ ...reviewedEnvironment, AZURE_DEPLOYMENT_STAGE: "validation", AZURE_VALIDATION_CIDRS: "[]" }).length);
});

test("traffic stages preserve reviewed images rather than reverting to bootstrap", () => {
  const validation = {
    ...reviewedEnvironment,
    AZURE_DEPLOYMENT_STAGE: "validation",
    AZURE_VALIDATION_CIDRS: '["192.0.2.10/32"]',
    AZURE_PRIVATE_ORIGIN_APPROVED: "1",
    FOUNDRY_GENERAL_AGENT: JSON.stringify({ name: "fixture-general", version: "1", modelDeployment: "fixture" }),
    AZURE_API_IMAGE_NAME: `fixture.azurecr.io/api@sha256:${"a".repeat(64)}`,
    AZURE_WEB_IMAGE_NAME: `fixture.azurecr.io/web@sha256:${"b".repeat(64)}`,
  };
  assert.deepEqual(deploymentBlockers(validation), []);
  for (const value of ["", "fixture.azurecr.io/web:latest", "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest", "fixture.azurecr.io/web@sha256:invalid"]) {
    assert.ok(deploymentBlockers({ ...validation, AZURE_WEB_IMAGE_NAME: value }).some((message) => message.includes("AZURE_WEB_IMAGE_NAME")));
  }
  for (const binding of [
    null,
    { name: "fixture-general", version: "latest", modelDeployment: "fixture" },
    { name: "fixture-general", version: "1", modelDeployment: "unreviewed" },
    { name: "fixture-general", version: "1", modelDeployment: "fixture", journeyId: "service-bc" },
    { name: "fixture-general", version: "1", modelDeployment: "fixture", tools: [] },
  ]) {
    const failures = deploymentBlockers({ ...validation, FOUNDRY_GENERAL_AGENT: JSON.stringify(binding) });
    assert.ok(failures.some((message) => message.includes("FOUNDRY_GENERAL_AGENT")));
  }
  assert.ok(deploymentBlockers({
    ...validation, FOUNDRY_AGENTS: JSON.stringify([{ name: "fixture-general" }]),
  }).some((message) => message.includes("FOUNDRY_GENERAL_AGENT")));
});

test("synthetic context requires explicit approval and a distinct pinned agent", () => {
  const contextual = {
    ...reviewedEnvironment,
    SYNTHETIC_CONTEXT_ENABLED: "true",
    FOUNDRY_AGENTS: JSON.stringify([]),
    FOUNDRY_GENERAL_AGENT: JSON.stringify({
      name: "fixture-general", version: "1", modelDeployment: "fixture",
    }),
    FOUNDRY_CONTEXTUAL_AGENT: JSON.stringify({
      name: "fixture-contextual", version: "1", modelDeployment: "fixture",
    }),
  };
  assert.ok(deploymentBlockers(contextual).some((message) => message.includes("AZURE_SYNTHETIC_CONTEXT_APPROVED")));
  assert.deepEqual(deploymentBlockers({
    ...contextual,
    AZURE_SYNTHETIC_CONTEXT_APPROVED: "1",
  }), []);
  assert.ok(deploymentBlockers({
    ...contextual,
    AZURE_SYNTHETIC_CONTEXT_APPROVED: "1",
    FOUNDRY_CONTEXTUAL_AGENT: JSON.stringify({
      name: "fixture-general", version: "1", modelDeployment: "fixture",
    }),
  }).some((message) => message.includes("FOUNDRY_CONTEXTUAL_AGENT")));
  assert.ok(deploymentBlockers({
    ...reviewedEnvironment,
    SYNTHETIC_CONTEXT_ENABLED: "yes",
  }).some((message) => message.includes("SYNTHETIC_CONTEXT_ENABLED")));
});

test("AI conversation needs reviewed activation and its own pinned agent", () => {
  const conversation = {
    ...reviewedEnvironment,
    AI_CONVERSATION_ENABLED: "true",
    TASK_ASSISTANCE_ENABLED: "true",
    AI_CONVERSATION_PRIVACY_REVIEWED: "true",
    FOUNDRY_GENERAL_AGENT: JSON.stringify({
      name: "fixture-general", version: "1", modelDeployment: "fixture",
    }),
    FOUNDRY_CONVERSATION_AGENT: JSON.stringify({
      name: "fixture-conversation", version: "2", modelDeployment: "fixture",
    }),
  };
  assert.deepEqual(deploymentBlockers(conversation), []);
  for (const change of [
    { AI_CONVERSATION_PRIVACY_REVIEWED: "false" },
    { AI_CONVERSATION_ENABLED: "false" },
    { AI_CONVERSATION_ENABLED: "yes" },
    { TASK_ASSISTANCE_ENABLED: "yes" },
    { AI_CONVERSATION_PRIVACY_REVIEWED: "1" },
    { FOUNDRY_CONVERSATION_AGENT: "" },
    { FOUNDRY_CONVERSATION_AGENT: JSON.stringify({ name: "fixture-general", version: "2", modelDeployment: "fixture" }) },
    { FOUNDRY_CONVERSATION_AGENT: JSON.stringify({ name: "fixture-conversation", version: "latest", modelDeployment: "fixture" }) },
    { FOUNDRY_CONVERSATION_AGENT: JSON.stringify({ name: "fixture-conversation", version: "2", modelDeployment: "unreviewed" }) },
    { FOUNDRY_CONVERSATION_AGENT: JSON.stringify({ name: "fixture-conversation", version: "2", modelDeployment: "fixture", journeyId: "licence-renewal" }) },
    { FOUNDRY_CONTEXTUAL_AGENT: conversation.FOUNDRY_CONVERSATION_AGENT },
  ]) {
    assert.ok(deploymentBlockers({ ...conversation, ...change }).some(
      (message) => /CONVERSATION|TASK_ASSISTANCE/.test(message),
    ), JSON.stringify(change));
  }
});
