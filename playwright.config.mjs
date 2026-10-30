import { defineConfig, devices } from "@playwright/test";

const webPort = 3310;
const apiPort = 8310;

export default defineConfig({
  testDir: "./tests/browser",
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
      API_AGENT_RUNS_PER_MINUTE: "30",
      APP_ENV: "development",
      NEXT_TELEMETRY_DISABLED: "1",
      WEBIQ_ENABLED: "false",
      SYNTHETIC_CONTEXT_ENABLED: "true",
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
