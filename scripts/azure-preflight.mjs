import { pathToFileURL } from "node:url";
import { isIP } from "node:net";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const journeys = new Set([
  "licence-renewal",
  "road-test-booking",
  "rental-assistance",
  "health-coverage",
  "pharmacare-registration",
  "primary-care",
  "service-bc",
]);
const pinnedImage = /^[a-z0-9][a-z0-9.-]*\.azurecr\.io\/[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$/;

function jsonValue(env, key, blockers) {
  try {
    return JSON.parse(env[key]);
  } catch {
    blockers.push(`${key} must contain explicitly reviewed JSON.`);
    return null;
  }
}

function cidr(value) {
  if (typeof value !== "string") return null;
  const [address, bits, extra] = value.split("/");
  if (extra || isIP(address) !== 4 || !/^\d+$/.test(bits) || +bits < 1 || +bits > 32) return null;
  const number = address.split(".").reduce((result, octet) => (result << 8n) + BigInt(octet), 0n);
  const size = 1n << BigInt(32 - +bits);
  return number % size === 0n ? { first: number, last: number + size - 1n } : null;
}

export function deploymentBlockers(env) {
  const blockers = [];
  if (env.AZURE_PROVISIONING_APPROVED !== "1") {
    blockers.push("Azure provisioning is not approved. No resources will be created from guessed context.");
  }
  for (const key of ["AZURE_SUBSCRIPTION_ID", "AZURE_LOCATION", "AZURE_ENV_NAME", "AZURE_SEARCH_INDEX"]) {
    if (!env[key]?.trim()) blockers.push(`${key} must be explicitly selected.`);
  }
  if (env.AZURE_DEPLOYMENT_REVIEWED !== "1") {
    blockers.push("Complete subscription policy, capacity, cost, networking, privacy, and source-access review first.");
  }
  if (env.AZURE_SUBSCRIPTION_ID && !uuid.test(env.AZURE_SUBSCRIPTION_ID)) blockers.push("AZURE_SUBSCRIPTION_ID must be a subscription GUID.");
  if (!uuid.test(env.AZURE_API_APPLICATION_CLIENT_ID || "")) blockers.push("Select the approved internal API Entra application client ID.");
  for (const key of ["AZURE_SEARCH_SKU", "AZURE_REDIS_SKU"]) {
    if (!env[key]?.trim()) blockers.push(`${key} must be selected after regional availability and cost review.`);
  }
  const models = jsonValue(env, "AZURE_MODEL_DEPLOYMENTS", blockers);
  if (!Array.isArray(models) || !models.length || models.length > 4 ||
      models.some((model) => !model || ["deploymentName", "modelName", "modelVersion", "sku"].some((key) => typeof model[key] !== "string" || !model[key].trim()) || !Number.isSafeInteger(model.capacity) || model.capacity < 1) ||
      new Set(models.map((model) => model.deploymentName)).size !== models.length) {
    blockers.push("Model deployments must pin unique names, model versions, SKUs and positive reviewed capacity.");
  }
  const controls = jsonValue(env, "AZURE_PILOT_CONTROLS", blockers);
  if (!controls || typeof controls !== "object" || Array.isArray(controls) ||
      ["runLimit", "tokenLimit", "costLimitMicrousd", "tokenPriceMicrousd", "apiMaxReplicas", "webMaxReplicas"].some((key) => !Number.isSafeInteger(controls[key]) || controls[key] <= 0) ||
      controls.apiMaxReplicas > 8 || controls.webMaxReplicas > 8 ||
      controls.tokenLimit < 147264 || controls.costLimitMicrousd < 147264 * controls.tokenPriceMicrousd) {
    blockers.push("Reviewed control budgets must admit at least one bounded run and cap replica counts.");
  }
  const network = cidr(env.AZURE_NETWORK_PREFIX);
  const apps = cidr(env.AZURE_APPS_SUBNET_PREFIX);
  const endpoints = cidr(env.AZURE_PRIVATE_SUBNET_PREFIX);
  if (!network || !apps || !endpoints ||
      apps.first < network.first || apps.last > network.last ||
      endpoints.first < network.first || endpoints.last > network.last ||
      !(apps.last < endpoints.first || endpoints.last < apps.first)) {
    blockers.push("Select valid, non-overlapping application/private-endpoint subnets inside the reviewed VNet.");
  }
  const dimension = Number(env.AZURE_OPENAI_EMBEDDING_DIMENSIONS || "0");
  const metadataEnabled = env.AZURE_SEARCH_METADATA_ENABLED || "";
  const metadataReviewed = env.AZURE_SEARCH_METADATA_REVIEWED || "";
  const metadataIndexSelected = env.AZURE_SEARCH_INDEX === "bc-pilot-public-v2";
  if (!["", "true", "false"].includes(metadataEnabled) ||
      !["", "0", "1"].includes(metadataReviewed)) {
    blockers.push("Search metadata settings must use explicit true/false and 0/1 values.");
  }
  if ((metadataIndexSelected || metadataEnabled === "true" || metadataReviewed === "1") &&
      !(metadataIndexSelected && metadataEnabled === "true" && metadataReviewed === "1")) {
    blockers.push("Switch AZURE_SEARCH_INDEX=bc-pilot-public-v2, AZURE_SEARCH_METADATA_ENABLED=true and AZURE_SEARCH_METADATA_REVIEWED=1 together in one reviewed API revision.");
  }
  if (!Number.isSafeInteger(dimension) || dimension < 0 || dimension > 3072 ||
      (dimension > 0 && (!Array.isArray(models) || !models.some((model) => model?.deploymentName === env.AZURE_OPENAI_EMBEDDING_DEPLOYMENT)))) {
    blockers.push("Hybrid retrieval requires matching explicit dimensions and a selected embedding deployment.");
  }
  const stage = env.AZURE_DEPLOYMENT_STAGE || "closed";
  if (!["closed", "validation", "public"].includes(stage)) blockers.push("Choose closed, validation or public deployment stage.");
  const syntheticContextEnabled = env.SYNTHETIC_CONTEXT_ENABLED || "false";
  if (!["false", "true"].includes(syntheticContextEnabled)) {
    blockers.push("SYNTHETIC_CONTEXT_ENABLED must be explicitly true or false.");
  }
  if (syntheticContextEnabled === "true") {
    const contextual = jsonValue(env, "FOUNDRY_CONTEXTUAL_AGENT", blockers);
    const agents = env.FOUNDRY_AGENTS ? jsonValue(env, "FOUNDRY_AGENTS", blockers) : [];
    const general = env.FOUNDRY_GENERAL_AGENT
      ? jsonValue(env, "FOUNDRY_GENERAL_AGENT", blockers)
      : null;
    const reservedNames = new Set([
      ...(Array.isArray(agents) ? agents.map((agent) => agent?.name) : []),
      general?.name,
    ].filter(Boolean));
    if (env.AZURE_SYNTHETIC_CONTEXT_APPROVED !== "1") {
      blockers.push("Public synthetic citizen context requires AZURE_SYNTHETIC_CONTEXT_APPROVED=1.");
    }
    if (!contextual || typeof contextual !== "object" || Array.isArray(contextual) ||
        Object.keys(contextual).some((key) => !["name", "version", "modelDeployment", "journeyId"].includes(key)) ||
        ["name", "version", "modelDeployment"].some((key) => typeof contextual[key] !== "string" || !contextual[key].trim()) ||
        contextual.journeyId != null || !/^[1-9]\d*$/.test(contextual.version) ||
        !Array.isArray(models) || !models.some((model) => model?.deploymentName === contextual.modelDeployment) ||
        reservedNames.has(contextual.name)) {
      blockers.push("Synthetic context requires a distinct published FOUNDRY_CONTEXTUAL_AGENT with a pinned version, reviewed model and no journey scope.");
    }
  }
  if (stage !== "closed") {
    for (const key of ["AZURE_API_IMAGE_NAME", "AZURE_WEB_IMAGE_NAME"]) {
      if (!pinnedImage.test(env[key] || "")) {
        blockers.push(`${key} must pin the reviewed ACR image by SHA-256 digest before traffic is enabled; never expose bootstrap images.`);
      }
    }
    const general = jsonValue(env, "FOUNDRY_GENERAL_AGENT", blockers);
    const agents = env.FOUNDRY_AGENTS ? jsonValue(env, "FOUNDRY_AGENTS", blockers) : [];
    if (!general || typeof general !== "object" || Array.isArray(general) ||
        Object.keys(general).some((key) => !["name", "version", "modelDeployment", "journeyId"].includes(key)) ||
        ["name", "version", "modelDeployment"].some((key) => typeof general[key] !== "string" || !general[key].trim()) ||
        general.journeyId != null || !/^[1-9]\d*$/.test(general.version) ||
        !Array.isArray(models) || !models.some((model) => model?.deploymentName === general.modelDeployment) ||
        (Array.isArray(agents) && agents.some((agent) => agent?.name === general.name))) {
      blockers.push("General chat requires a distinct published FOUNDRY_GENERAL_AGENT with a pinned version, reviewed model and no pathway scope.");
    }
  }
  if (stage === "validation") {
    const ranges = jsonValue(env, "AZURE_VALIDATION_CIDRS", blockers);
    if (!Array.isArray(ranges) || !ranges.length || ranges.some((range) => !cidr(range))) {
      blockers.push("Validation exposure requires an explicit, nonempty IPv4 CIDR allowlist.");
    }
  }
  if (stage !== "closed" && env.AZURE_PRIVATE_ORIGIN_APPROVED !== "1") blockers.push("Verify and approve the exact private Front Door origin connection before enabling traffic.");
  if (stage === "public") {
    for (const key of ["AZURE_PUBLIC_PREVIEW_APPROVED", "AZURE_LIVE_EVALUATION_APPROVED", "AZURE_SOURCE_PUBLICATION_APPROVED", "AZURE_BC_BRAND_APPROVED"]) {
      if (env[key] !== "1") blockers.push(`${key} is required before anonymous public exposure.`);
    }
    const agents = jsonValue(env, "FOUNDRY_AGENTS", blockers);
    if (!Array.isArray(agents) || agents.length !== journeys.size ||
        agents.some((agent) => !agent || !journeys.has(agent.journeyId) || !agent.name || !agent.version || !agent.modelDeployment) ||
        new Set(agents.map((agent) => agent.journeyId)).size !== journeys.size) {
      blockers.push("Public release requires the seven actually published and pinned agent bindings.");
    }
  }
  return blockers;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const blockers = deploymentBlockers(process.env);
  if (blockers.length) {
    console.error(blockers.map((message) => `- ${message}`).join("\n"));
    process.exitCode = 1;
  } else {
    console.log("Explicit approval flags are present. This check does not perform Azure deployment validation.");
  }
}
