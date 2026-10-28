import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const imageDigest = /^[a-z0-9][a-z0-9.-]*\.azurecr\.io\/[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$/;
const name = /^[a-z][a-z0-9-]+[a-z0-9]$/;
const blobName = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,1023}$/;

export function sourcePlatformBlockers(parameters, { execute = false, approved = false } = {}) {
  const errors = [];
  if (!parameters || typeof parameters !== "object" || Array.isArray(parameters)) {
    return ["Provide an explicit source-platform parameter object."];
  }
  const allowed = new Set([
    "name", "location", "storageAccountName", "environmentName", "virtualNetworkName",
    "registryName", "publisherIdentityName", "imageName", "publicationImageName", "acquisitionJobName", "tags", "privateSubnetName",
    "candidateContainerName", "rightsContainerName", "runPrefix", "acquisitionEnabled",
    "rightsBlob", "rightsSha256", "requestBudget", "byteBudget", "maxCandidates",
  ]);
  if (Object.keys(parameters).some(key => !allowed.has(key))) errors.push("Unexpected source-platform parameter.");
  if (parameters.tags && (typeof parameters.tags !== "object" || Array.isArray(parameters.tags) ||
      Object.hasOwn(parameters.tags, "azd-service-name"))) {
    errors.push("Source jobs must not reuse the web/API service-discovery tag.");
  }
  for (const key of ["name", "location", "storageAccountName", "environmentName", "virtualNetworkName", "registryName", "publisherIdentityName", "imageName"]) {
    if (typeof parameters[key] !== "string" || !parameters[key].trim()) errors.push(`${key} must identify the reviewed existing resource or image.`);
  }
  if (!name.test(parameters.name || "") || parameters.name?.length > 20) errors.push("The source prefix must produce valid job names of at most 32 characters.");
  if (parameters.acquisitionJobName !== undefined && (
      typeof parameters.acquisitionJobName !== "string"
      || !name.test(parameters.acquisitionJobName)
      || parameters.acquisitionJobName.length > 32)) {
    errors.push("The replacement acquisition job name must be a valid Container Apps job name.");
  }
  if (!imageDigest.test(parameters.imageName || "") ||
      !parameters.imageName?.startsWith(`${parameters.registryName}.azurecr.io/`)) {
    errors.push("The job image must be an actual reviewed digest in the existing registry.");
  }
  if (parameters.publicationImageName !== undefined && (
      !imageDigest.test(parameters.publicationImageName)
      || !parameters.publicationImageName.startsWith(`${parameters.registryName}.azurecr.io/`)
  )) {
    errors.push("The publisher image must remain an actual reviewed digest in the existing registry.");
  }
  const candidates = parameters.candidateContainerName || "bc-ingestion-candidates";
  const rights = parameters.rightsContainerName || "bc-ingestion-rights";
  const validContainer = value => typeof value === "string" && /^[a-z0-9](?:[a-z0-9]|-(?!-)){1,61}[a-z0-9]$/.test(value);
  if (!validContainer(candidates) || !validContainer(rights) || candidates === rights || [candidates, rights].includes("reviewed-content")) {
    errors.push("Use distinct private candidate/rights containers, not the existing published-content container.");
  }
  for (const [key, value] of Object.entries({
    runPrefix: parameters.runPrefix || "bc-full-v1",
    rightsBlob: parameters.rightsBlob || "reviews/bc-full-v1.json",
  })) {
    if (typeof value !== "string" || !blobName.test(value) || value.split("/").some(part => !part || part === "." || part === "..")) {
      errors.push(`${key} must stay inside the reviewed Blob namespace.`);
    }
  }
  if (parameters.acquisitionEnabled !== undefined && typeof parameters.acquisitionEnabled !== "boolean") {
    errors.push("acquisitionEnabled must be an explicit boolean.");
  }
  if (parameters.acquisitionEnabled && !/^[a-f0-9]{64}$/.test(parameters.rightsSha256 || "")) {
    errors.push("Acquisition requires the exact SHA-256 of an actual approved rights file.");
  }
  for (const [key, maximum] of [["requestBudget", 200000], ["byteBudget", 100000000000], ["maxCandidates", 1000000]]) {
    if (parameters[key] !== undefined && (!Number.isSafeInteger(parameters[key]) || parameters[key] < 1 || parameters[key] > maximum)) {
      errors.push(`${key} must be a positive, bounded reviewed limit.`);
    }
  }
  if (execute && !approved) errors.push("New private connectivity, job costs and role scopes require explicit source-platform approval.");
  return errors;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const file = process.argv[2];
    if (!file) throw new Error("Provide the reviewed JSON parameter file.");
    const document = JSON.parse(readFileSync(file, "utf8").replace(/^\uFEFF/, ""));
    const parameters = document.parameters
      ? Object.fromEntries(Object.entries(document.parameters).map(([key, value]) => [key, value.value]))
      : document;
    const errors = sourcePlatformBlockers(parameters, {
      execute: process.argv.includes("--execute"),
      approved: process.env.AZURE_SOURCE_PLATFORM_APPROVED === "1",
    });
    if (errors.length) throw new Error(errors.join("\n"));
    console.log("Source-platform parameters passed. This does not grant source rights or publish content.");
  } catch (error) {
    console.error(error instanceof Error ? error.message : "Source-platform preflight failed.");
    process.exitCode = 1;
  }
}
