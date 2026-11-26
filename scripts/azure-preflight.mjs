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
export const pinnedImage = /^[a-z0-9][a-z0-9.-]*\.azurecr\.io\/[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$/;

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

export function deploymentBlockers(env, operation = "prepare") {
  const blockers = [];
  if (!["prepare", "provision", "deploy"].includes(operation)) {
    blockers.push("Select a supported preflight operation.");
  }
  if (operation === "deploy") {
    blockers.push("Generic azd image deployment cannot bypass PyRIT qualification. Use the protected Azure Deployment workflow.");
  }
  if (operation === "provision" && (!env.AZURE_PRODUCTION_ENV_NAME
      || env.AZURE_ENV_NAME === env.AZURE_PRODUCTION_ENV_NAME
      || env.AZURE_DEPLOYMENT_STAGE === "public")) {
    blockers.push("Generic provisioning is restricted to staging; supply the distinct production environment name.");
  }
  if (!["", "true", "false"].includes(env.AZURE_RELEASE_PROBE_ENABLED || "")) {
    blockers.push("AZURE_RELEASE_PROBE_ENABLED must be true or false.");
  }
  if (env.AZURE_RELEASE_PROBE_ENABLED === "true" && !pinnedImage.test(env.AZURE_WEB_IMAGE_NAME || "")) {
    blockers.push("The private release probe requires a reviewed web image digest.");
  }
  if (env.AZURE_RELEASE_COMMIT && !/^[a-f0-9]{40}$/.test(env.AZURE_RELEASE_COMMIT)) {
    blockers.push("AZURE_RELEASE_COMMIT must be the full source commit.");
  }
  if (env.AZURE_RELEASE_COMMIT && env.RELEASE_COMMIT && env.AZURE_RELEASE_COMMIT !== env.RELEASE_COMMIT) {
    blockers.push("AZURE_RELEASE_COMMIT and RELEASE_COMMIT must identify the same source commit.");
  }
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
  const kind = env.AZURE_DEPLOYMENT_KIND || "pilot";
  if (!["pilot", "staging"].includes(kind)) blockers.push("AZURE_DEPLOYMENT_KIND must be pilot or staging.");
  if (env.AZURE_STAGING_IDENTITIES_JSON && env.AZURE_STAGING_IDENTITIES_JSON !== "{}") {
    const identities = jsonValue(env, "AZURE_STAGING_IDENTITIES_JSON", blockers);
    const roles = ["api", "web", "publisher"];
    const group = env.AZURE_RESOURCE_GROUP || "";
    if (kind !== "staging" || !/^rg-bcassist-[a-z0-9]{10}$/u.test(group)
      || !identities || typeof identities !== "object" || Array.isArray(identities)
      || Object.keys(identities).length !== roles.length
      || roles.some((role) => {
        const identity = identities[role];
        const expectedId = `/subscriptions/${env.AZURE_SUBSCRIPTION_ID}/resourceGroups/${group}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-${group.slice(3)}-${role}`;
        return !identity || typeof identity !== "object" || Array.isArray(identity)
          || Object.keys(identity).sort().join(",") !== "clientId,id,principalId"
          || typeof identity.id !== "string" || identity.id.toLowerCase() !== expectedId.toLowerCase()
          || typeof identity.clientId !== "string" || typeof identity.principalId !== "string"
          || !uuid.test(identity.clientId || "") || !uuid.test(identity.principalId || "");
      })
      || new Set(roles.map((role) => identities[role].principalId.toLowerCase())).size !== roles.length
      || new Set(roles.map((role) => identities[role].clientId.toLowerCase())).size !== roles.length) {
      blockers.push("Staging identity metadata must contain three distinct verified identities from the exact staging resource group.");
    }
  }
  const sharedProfile = env.AZURE_SHARED_FRONT_DOOR_PROFILE_NAME || "";
  const sharedGroup = env.AZURE_SHARED_FRONT_DOOR_RESOURCE_GROUP || "";
  if (sharedProfile || sharedGroup) {
    if (kind !== "staging" || !/^[A-Za-z0-9][A-Za-z0-9-]{0,99}$/u.test(sharedProfile)
      || !/^[A-Za-z0-9][A-Za-z0-9._()-]{0,89}$/u.test(sharedGroup)
      || env.AZURE_SHARED_FRONT_DOOR_APPROVED !== "1") {
      blockers.push("Shared Front Door requires staging, an exact profile/resource group, and AZURE_SHARED_FRONT_DOOR_APPROVED=1.");
    }
    if (!/^[a-z][a-z0-9]+$/u.test(env.AZURE_FRONT_DOOR_PRIVATE_LINK_LOCATION || "")) {
      blockers.push("Select AZURE_FRONT_DOOR_PRIVATE_LINK_LOCATION from Front Door's supported regions; it can differ from the application region.");
    }
  }
  if (kind === "staging") {
    if (!env.AZURE_PRODUCTION_ENV_NAME?.trim()
      || env.AZURE_ENV_NAME?.toLowerCase() === env.AZURE_PRODUCTION_ENV_NAME.toLowerCase()) {
      blockers.push("Staging requires a different AZURE_ENV_NAME from the explicitly identified AZURE_PRODUCTION_ENV_NAME.");
    }
    if (stage === "public") blockers.push("Staging must remain closed or validation-only, never public.");
    if (controls?.apiMaxReplicas !== 1 || controls?.webMaxReplicas !== 1) {
      blockers.push("The reviewed manual staging budget permits only one API replica and one web replica.");
    }
    if (stage !== "closed" && (!/^[a-f0-9]{40}$/u.test(env.RELEASE_COMMIT || "")
      || !/^staging-[a-z0-9][a-z0-9-]{0,55}$/u.test(env.RELEASE_ID || ""))) {
      blockers.push("Staging activation requires a pinned RELEASE_COMMIT and a staging-prefixed RELEASE_ID.");
    }
  }
  if ((env.RELEASE_COMMIT && !/^[a-f0-9]{40}$/u.test(env.RELEASE_COMMIT))
    || (env.RELEASE_ID && !/^[a-z0-9][a-z0-9-]{0,63}$/u.test(env.RELEASE_ID))) {
    blockers.push("Release identity must be a full lowercase commit and a bounded deployment label.");
  }
  for (const key of ["AI_CONVERSATION_ENABLED", "TASK_ASSISTANCE_ENABLED", "AI_CONVERSATION_PRIVACY_REVIEWED"]) {
    if (!["", "true", "false"].includes(env[key] || "")) {
      blockers.push(`${key} must be explicitly true or false.`);
    }
  }
  if (env.TASK_ASSISTANCE_ENABLED === "true" && env.AI_CONVERSATION_ENABLED !== "true") {
    blockers.push("TASK_ASSISTANCE_ENABLED requires AI_CONVERSATION_ENABLED=true in the same API revision.");
  }
  if (env.AI_CONVERSATION_ENABLED === "true") {
    if (env.AI_CONVERSATION_PRIVACY_REVIEWED !== "true") {
      blockers.push("Public AI conversation requires an actual privacy review and AI_CONVERSATION_PRIVACY_REVIEWED=true.");
    }
    const conversation = jsonValue(env, "FOUNDRY_CONVERSATION_AGENT", blockers);
    const agents = env.FOUNDRY_AGENTS ? jsonValue(env, "FOUNDRY_AGENTS", blockers) : [];
    const reservedNames = new Set([
      ...(Array.isArray(agents) ? agents.map((agent) => agent?.name) : []),
      ...["FOUNDRY_GENERAL_AGENT", "FOUNDRY_CONTEXTUAL_AGENT"].map(
        (key) => env[key] ? jsonValue(env, key, blockers)?.name : null,
      ),
    ].filter(Boolean));
    if (!conversation || typeof conversation !== "object" || Array.isArray(conversation) ||
        Object.keys(conversation).some((key) => !["name", "version", "modelDeployment", "journeyId"].includes(key)) ||
        ["name", "version", "modelDeployment"].some((key) => typeof conversation[key] !== "string" || !conversation[key].trim()) ||
        conversation.journeyId != null || !/^[1-9]\d*$/.test(conversation.version) ||
        !Array.isArray(models) || !models.some((model) => model?.deploymentName === conversation.modelDeployment) ||
        reservedNames.has(conversation.name)) {
      blockers.push("AI conversation requires a distinct published FOUNDRY_CONVERSATION_AGENT with a pinned version, reviewed model and no journey scope.");
    }
  }
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
    if (!Array.isArray(ranges) || !ranges.length || ranges.some((range) => {
      const parsed = cidr(range);
      return !parsed || (kind === "staging" && parsed.last - parsed.first > 255n);
    })) {
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
  const operation = process.argv.find((arg) => arg.startsWith("--operation="))?.slice(12) || "prepare";
  const blockers = deploymentBlockers(process.env, operation);
  if (blockers.length) {
    console.error(blockers.map((message) => `- ${message}`).join("\n"));
    process.exitCode = 1;
  } else {
    console.log("Explicit approval flags are present. This check does not perform Azure deployment validation.");
  }
}
