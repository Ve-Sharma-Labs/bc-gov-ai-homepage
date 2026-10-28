import assert from "node:assert/strict";
import test from "node:test";
import { sourcePlatformBlockers } from "../source-preflight.mjs";

const parameters = {
  name: "bc-fixture",
  location: "canadacentral",
  storageAccountName: "fixturestorage",
  environmentName: "fixture-environment",
  virtualNetworkName: "fixture-vnet",
  registryName: "fixtureregistry",
  publisherIdentityName: "fixture-publisher",
  imageName: `fixtureregistry.azurecr.io/ingestion@sha256:${"a".repeat(64)}`,
};

test("initialization can be reviewed without authorizing acquisition or deployment", () => {
  assert.deepEqual(sourcePlatformBlockers(parameters), []);
  assert.deepEqual(sourcePlatformBlockers({
    ...parameters,
    publicationImageName: `fixtureregistry.azurecr.io/ingestion@sha256:${"c".repeat(64)}`,
  }), []);
  assert.deepEqual(sourcePlatformBlockers({
    ...parameters, acquisitionJobName: "job-bcassist-replacement",
  }), []);
  assert.ok(sourcePlatformBlockers(parameters, { execute: true }).length);
  assert.deepEqual(sourcePlatformBlockers(parameters, { execute: true, approved: true }), []);
});

test("source namespace, image and approval inputs fail closed", () => {
  for (const change of [
    { imageName: "fixtureregistry.azurecr.io/ingestion:latest" },
    { publicationImageName: "fixtureregistry.azurecr.io/ingestion:latest" },
    { registryName: "anotherregistry" },
    { name: "a-name-that-is-far-too-long-for-the-jobs" },
    { acquisitionJobName: "INVALID_JOB" },
    { candidateContainerName: "reviewed-content" },
    { candidateContainerName: "same-container", rightsContainerName: "same-container" },
    { runPrefix: "../new-run" },
    { rightsBlob: "reviews/../../override.json" },
    { acquisitionEnabled: "true" },
    { acquisitionEnabled: true },
    { requestBudget: 0 },
    { byteBudget: Number.MAX_SAFE_INTEGER },
    { arbitraryAdminRole: true },
    { tags: { "azd-service-name": "api" } },
  ]) assert.ok(sourcePlatformBlockers({ ...parameters, ...change }).length, JSON.stringify(change));
  assert.deepEqual(sourcePlatformBlockers({
    ...parameters, acquisitionEnabled: true, rightsSha256: "b".repeat(64),
  }), []);
});
