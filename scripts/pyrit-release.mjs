import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";
import { AzurePilot, container, deploymentContext, environment, rollOutPair } from "./azure-pyrit.mjs";
import { pinnedImage } from "./azure-preflight.mjs";
import { fingerprint, validateCandidate, validateCoverage, validateQualification } from "./pyrit-evidence.mjs";

const datasetUrl = new URL("../data/evaluations/pyrit-conversation-cases.json", import.meta.url);

async function jsonFile(filename) {
  const text = await readFile(filename, "utf8");
  assert.ok(Buffer.byteLength(text) <= 1_000_000, "EVIDENCE_TOO_LARGE");
  return JSON.parse(text);
}

function setting(name, env) {
  assert.ok(env[name] && env[name].length <= 32768, `${name}_REQUIRED`);
  return JSON.parse(env[name]);
}

export function releaseContexts(env) {
  const staging = deploymentContext(setting("PYRIT_STAGING_CONTEXT_JSON", env));
  const production = deploymentContext(setting("PYRIT_PRODUCTION_CONTEXT_JSON", env));
  for (const key of ["apiId", "webId", "probeJobId", "frontDoorEndpointId", "origin"]) {
    assert.notEqual(staging[key], production[key], "STAGING_MUST_BE_SEPARATE");
  }
  assert.notEqual(staging.apiId.split("/providers/")[0],
    production.apiId.split("/providers/")[0], "SEPARATE_RESOURCE_GROUPS_REQUIRED");
  return { staging, production };
}

function runIdentity(env) {
  assert.equal(env.GITHUB_ACTIONS, "true", "GITHUB_RUN_REQUIRED");
  assert.equal(env.GITHUB_REF, "refs/heads/main", "TRUSTED_MAIN_REQUIRED");
  assert.ok(/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(env.GITHUB_REPOSITORY || ""), "REPOSITORY_REQUIRED");
  assert.ok(/^[a-f0-9]{40}$/.test(env.GITHUB_SHA || ""), "COMMIT_REQUIRED");
  assert.ok(/^[1-9]\d*$/.test(env.GITHUB_RUN_ID || ""), "RUN_ID_REQUIRED");
  const attempt = Number(env.GITHUB_RUN_ATTEMPT);
  assert.ok(Number.isSafeInteger(attempt) && attempt > 0, "RUN_ATTEMPT_REQUIRED");
  return {
    repository: env.GITHUB_REPOSITORY, commit: env.GITHUB_SHA,
    runId: env.GITHUB_RUN_ID, runAttempt: attempt,
  };
}

function approvals(env, release = false) {
  assert.equal(env.PYRIT_LIVE_APPROVED, "1", "PYRIT_LIVE_APPROVAL_REQUIRED");
  if (release) {
    for (const key of ["PYRIT_RELEASE_ENABLED", "AZURE_DEPLOYMENT_REVIEWED", "AZURE_PRIVATE_ORIGIN_APPROVED"]) {
      assert.equal(env[key], "1", `${key}_REQUIRED`);
    }
  }
}

export function imageManifest(value, identity) {
  assert.deepEqual(Object.keys(value).sort(), ["api", "commit", "version", "web"], "INVALID_IMAGE_MANIFEST");
  assert.equal(value.version, 1, "INVALID_IMAGE_MANIFEST");
  assert.equal(value.commit, identity.commit, "IMAGE_COMMIT_MISMATCH");
  assert.ok(pinnedImage.test(value.api) && pinnedImage.test(value.web), "IMMUTABLE_IMAGES_REQUIRED");
  return value;
}

export function requireMatchingSnapshot(snapshot, candidate) {
  for (const key of ["configurationSha256", "sourceSha256", "modelSha256"]) {
    assert.equal(snapshot[key], candidate[key], "TESTED_CONFIGURATION_CHANGED");
  }
}

export function candidateFromSnapshot(snapshot, contexts, identity, dataset, limits, models) {
  const api = snapshot.pair.apiRevision;
  const web = snapshot.pair.webRevision;
  for (const revision of [api, web]) {
    assert.equal(environment(revision.properties.template).RELEASE_COMMIT, identity.commit,
      "STAGING_COMMIT_MISMATCH");
    assert.ok(pinnedImage.test(container(revision.properties.template).image), "IMMUTABLE_IMAGES_REQUIRED");
  }
  assert.equal(environment(api.properties.template).RELEASE_ID,
    environment(web.properties.template).RELEASE_ID, "STAGING_PAIR_MISMATCH");
  assert.ok(environment(api.properties.template).RELEASE_ID
    && api.name.endsWith("--" + environment(api.properties.template).RELEASE_ID)
    && web.name.endsWith("--" + environment(web.properties.template).RELEASE_ID),
  "STAGING_DEPLOYMENT_ID_MISMATCH");
  const candidate = {
    version: 1, kind: "bc-pyrit-candidate", ...identity, createdAt: new Date().toISOString(),
    stagingOrigin: contexts.staging.origin, productionOrigin: contexts.production.origin,
    images: snapshot.images, stagingRevisions: { api: api.name, web: web.name },
    configurationSha256: snapshot.configurationSha256, sourceSha256: snapshot.sourceSha256,
    modelSha256: snapshot.modelSha256, suiteSha256: fingerprint(dataset),
    limitsSha256: fingerprint(limits), evaluatorSha256: fingerprint(models),
  };
  validateCandidate(candidate, { ...identity, stagingOrigin: candidate.stagingOrigin, productionOrigin: candidate.productionOrigin });
  return candidate;
}

export async function releaseCommand(command, args, {
  env = process.env, azureFactory = (context) => new AzurePilot(context),
} = {}) {
  const identity = runIdentity(env);
  if (command === "images") {
    const images = imageManifest({
      version: 1, commit: identity.commit, api: env.PYRIT_API_IMAGE, web: env.PYRIT_WEB_IMAGE,
    }, identity);
    await writeFile(args.output, JSON.stringify(images, null, 2) + "\n");
    return images;
  }
  const contexts = releaseContexts(env);
  const context = {
    ...identity, stagingOrigin: contexts.staging.origin, productionOrigin: contexts.production.origin,
  };
  const dataset = await jsonFile(datasetUrl);
  approvals(env, ["stage", "promote"].includes(command));
  if (command === "stage" || command === "capture") {
    const azure = azureFactory(contexts.staging);
    const before = await azure.capture({ staging: true });
    if (command === "stage") {
      const images = imageManifest(await jsonFile(args.images), identity);
      for (const key of ["api", "web"]) {
        assert.ok(images[key].startsWith(`${contexts.staging.registryName}.azurecr.io/`),
          "STAGING_REGISTRY_REQUIRED");
      }
      const suffix = `r-${identity.commit.slice(0, 12)}-${identity.runId}-${identity.runAttempt}`;
      await rollOutPair(azure, images, identity.commit, suffix);
    }
    const after = await azure.capture({ staging: true });
    requireMatchingSnapshot(after, before);
    const candidate = candidateFromSnapshot(
      after, contexts, identity, dataset,
      setting("PYRIT_LIMITS_JSON", env), setting("PYRIT_MODELS_JSON", env),
    );
    const suffix = environment(after.pair.apiRevision.properties.template).RELEASE_ID;
    await azure.publicProbe(identity.commit, suffix);
    await writeFile(args.output, JSON.stringify(candidate, null, 2) + "\n");
    return candidate;
  }
  const candidate = await jsonFile(args.candidate);
  validateCandidate(candidate, context);
  if (command === "check-candidate") {
    const current = await azureFactory(contexts.staging).capture({ staging: true });
    requireMatchingSnapshot(current, candidate);
    assert.deepEqual(current.images, candidate.images, "CANDIDATE_IMAGES_CHANGED");
    assert.deepEqual(
      { api: current.pair.apiRevision.name, web: current.pair.webRevision.name },
      candidate.stagingRevisions, "CANDIDATE_REVISIONS_CHANGED",
    );
    assert.equal(fingerprint(setting("PYRIT_LIMITS_JSON", env)), candidate.limitsSha256, "BUDGET_CHANGED");
    assert.equal(fingerprint(setting("PYRIT_MODELS_JSON", env)), candidate.evaluatorSha256, "EVALUATOR_CHANGED");
    return { checked: true };
  }
  const report = await jsonFile(args.report);
  validateQualification(report, candidate, dataset, context);
  if (command === "qualify") {
    const result = { version: 1, qualified: true, candidateSha256: fingerprint(candidate) };
    if (args.output) await writeFile(args.output, JSON.stringify(result) + "\n");
    return result;
  }
  assert.equal(command, "promote", "UNSUPPORTED_RELEASE_COMMAND");
  for (const flag of [
    "AZURE_PUBLIC_PREVIEW_APPROVED", "AZURE_LIVE_EVALUATION_APPROVED",
    "AZURE_SOURCE_PUBLICATION_APPROVED", "AZURE_BC_BRAND_APPROVED",
  ]) assert.equal(env[flag], "1", `${flag}_REQUIRED`);
  const offline = await jsonFile(args.offline);
  validateCoverage(offline, dataset, "offline");
  for (const key of ["repository", "commit", "runId", "runAttempt"]) {
    assert.equal(offline.identity[key], identity[key], "OFFLINE_EVIDENCE_MISMATCH");
  }
  const azure = azureFactory(contexts.production);
  const current = await azure.capture();
  requireMatchingSnapshot(current, candidate);
  await azure.publicProbe();
  assert.equal(fingerprint(setting("PYRIT_LIMITS_JSON", env)), candidate.limitsSha256, "BUDGET_CHANGED");
  assert.equal(fingerprint(setting("PYRIT_MODELS_JSON", env)), candidate.evaluatorSha256, "EVALUATOR_CHANGED");
  // Both registries must resolve the already-tested content digest; promotion never rebuilds.
  const images = {};
  for (const key of ["api", "web"]) {
    const source = candidate.images[key];
    const repository = source.slice(source.indexOf("/") + 1);
    images[key] = `${contexts.production.registryName}.azurecr.io/${repository}`;
    if (contexts.production.registryName !== contexts.staging.registryName) {
      await azure.run("az", [
        "acr", "import", "--name", contexts.production.registryName,
        "--subscription", contexts.production.subscriptionId, "--source", source,
        "--image", repository.split("@")[0] + ":" + identity.commit, "--force",
      ], { timeout: 180_000, maxBuffer: 1024 * 1024 });
    }
    const result = await azure.run("az", [
      "acr", "repository", "show", "--name", contexts.production.registryName,
      "--subscription", contexts.production.subscriptionId,
      "--image", repository, "--query", "digest", "--output", "tsv",
    ], { timeout: 60_000, maxBuffer: 1024 * 1024 });
    assert.equal(result.stdout.trim(), source.split("@")[1], "IMPORTED_DIGEST_MISMATCH");
  }
  const suffix = `r-${identity.commit.slice(0, 12)}-${identity.runId}-${identity.runAttempt}`;
  const outcome = await rollOutPair(azure, images, identity.commit, suffix, candidate);
  const marker = {
    version: 2, operation: "deploy", environment: "pilot", ...identity,
    sha: identity.commit, candidateSha256: fingerprint(candidate), images, ...outcome,
  };
  await writeFile(args.output, JSON.stringify(marker, null, 2) + "\n");
  return marker;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const { values, positionals } = parseArgs({
      allowPositionals: true,
      options: Object.fromEntries(["images", "candidate", "report", "offline", "output"].map((key) => [key, { type: "string" }])),
    });
    assert.equal(positionals.length, 1, "SELECT_ONE_RELEASE_COMMAND");
    const result = await releaseCommand(positionals[0], values);
    console.log(JSON.stringify({ operation: positionals[0], complete: true, qualified: result.qualified ?? false }));
  } catch (error) {
    const message = error instanceof Error ? error.message.split("\n")[0] : "RELEASE_FAILED";
    console.error(/^[A-Z][A-Z0-9_]{0,80}$/.test(message) ? message : "RELEASE_FAILED");
    process.exitCode = 1;
  }
}
