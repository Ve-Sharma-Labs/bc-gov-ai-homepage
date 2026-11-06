import { defineConfig, devices } from "@playwright/test";

const webPort = 3310;
const apiPort = 8310;
const discovery = process.env.CONVERSATION_DISCOVERY_ENABLED === "true";
const taskAssistance = process.env.TASK_ASSISTANCE_ENABLED === "true";
const aiConversation = process.env.AI_CONVERSATION_ENABLED === "true" || taskAssistance;
const liveGrounded = process.env.LIVE_GROUNDED_EVAL === "true";
if (liveGrounded && (!process.env.PILOT_BASE_URL
  || !["127.0.0.1", "localhost"].includes(new URL(process.env.PILOT_BASE_URL).hostname))) {
  throw new Error("Live grounded UI evaluation requires an explicitly selected loopback preview.");
}

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: liveGrounded ? "**/grounded-live.spec.mjs" : taskAssistance ? "**/task-progress.spec.mjs" : aiConversation ? "**/ai-conversation.spec.mjs" : discovery ? "**/discovery.spec.mjs" : undefined,
  testIgnore: liveGrounded ? [] : [
    "**/grounded-live.spec.mjs",
    ...(taskAssistance ? [] : aiConversation ? ["**/discovery.spec.mjs", "**/task-progress.spec.mjs"] : discovery ? ["**/ai-conversation.spec.mjs", "**/task-progress.spec.mjs"] : ["**/discovery.spec.mjs", "**/ai-conversation.spec.mjs", "**/task-progress.spec.mjs"]),
  ],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: process.env.PILOT_BASE_URL || `http://127.0.0.1:${webPort}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["iPhone 13"], browserName: "chromium" } },
  ],
  webServer: process.env.PILOT_BASE_URL ? undefined : {
    command: "npm run build && npm start",
    url: `http://127.0.0.1:${webPort}/api/catalog`,
    reuseExistingServer: false,
    timeout: 180_000,
    env: {
      WEB_PORT: String(webPort),
      API_PORT: String(apiPort),
      API_ALLOWED_ORIGINS: `http://127.0.0.1:${webPort},http://localhost:${webPort}`,
      API_ALLOWED_HOSTS: "localhost,127.0.0.1,::1,api",
      // Both browser projects share a loopback client; API tests cover the production limits.
      API_REQUESTS_PER_MINUTE: "1000",
      API_AGENT_RUNS_PER_MINUTE: "30",
      APP_ENV: "development",
      NEXT_TELEMETRY_DISABLED: "1",
      WEBIQ_ENABLED: "false",
      SYNTHETIC_CONTEXT_ENABLED: "true",
      CONVERSATION_DISCOVERY_ENABLED: discovery ? "true" : "false",
      CONVERSATION_DISCOVERY_PRIVACY_REVIEWED: "false",
      AI_CONVERSATION_ENABLED: aiConversation ? "true" : "false",
      TASK_ASSISTANCE_ENABLED: taskAssistance ? "true" : "false",
      GROUNDED_CONVERSATION_ENABLED: "false",
      LOCAL_EVIDENCE_EVALUATION_ENABLED: "false",
      LOCAL_EVIDENCE_SNAPSHOT_PATH: "",
      LOCAL_EVIDENCE_SNAPSHOT_SHA256: "",
      FOUNDRY_GROUNDED_CONVERSATION_AGENT: "",
      FOUNDRY_GROUNDED_ANSWER_AGENT: "",
      AI_CONVERSATION_PRIVACY_REVIEWED: "false",
      FOUNDRY_CONVERSATION_AGENT: "",
      FOUNDRY_PROJECT_ENDPOINT: "",
      FOUNDRY_AGENT_NAME: "",
      FOUNDRY_AGENT_VERSION: "",
      FOUNDRY_AGENTS: "[]",
      FOUNDRY_GENERAL_AGENT: "",
      AZURE_SEARCH_ENDPOINT: "",
      AZURE_SEARCH_INDEX: "",
      AZURE_SEARCH_VECTOR_ENABLED: "false",
      AZURE_OPENAI_ENDPOINT: "",
      AZURE_OPENAI_EMBEDDING_DEPLOYMENT: "",
      REDIS_ENDPOINT: "",
      APPLICATIONINSIGHTS_CONNECTION_STRING: "",
      API_AUTH_TENANT_ID: "",
      API_AUTH_AUDIENCE: "",
      API_AUTH_CALLERS: "[]",
      API_AUTH_SCOPE: "",
      FRONT_DOOR_ID: "",
      CLIENT_HASH_KEY: "",
    },
  },
});
