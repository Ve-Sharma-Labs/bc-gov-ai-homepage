import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { runInNewContext } from "node:vm";
import { root } from "../runtime.mjs";

function configFor(overrides = {}) {
  const source = readFileSync(path.join(root, "playwright.config.mjs"), "utf8")
    .replace('import { defineConfig, devices } from "@playwright/test";', "")
    .replace("export default", "globalThis.config =");
  const context = {
    defineConfig: (config) => config,
    devices: { "Desktop Chrome": {}, "iPhone 13": {} },
    URL,
    process: { env: overrides },
  };
  runInNewContext(source, context);
  return { server: context.config.webServer ?? null, retries: context.config.retries };
}

test("offline functional profiles use a bounded test-only HTTP budget without retries", () => {
  for (const profile of [{}, { CONVERSATION_DISCOVERY_ENABLED: "true" },
    { AI_CONVERSATION_ENABLED: "true" }, { TASK_ASSISTANCE_ENABLED: "true" }]) {
    const config = configFor(profile);
    assert.equal(config.server.env.API_REQUESTS_PER_MINUTE, "1000");
    assert.equal(config.server.env.APP_ENV, "development");
    assert.equal(config.server.env.FOUNDRY_PROJECT_ENDPOINT, "");
    assert.equal(config.retries, 0);
  }
});

test("external previews and live evaluation do not receive offline budget overrides", () => {
  for (const live of ["false", "true"]) {
    const config = configFor({
      PILOT_BASE_URL: "http://127.0.0.1:3310",
      LIVE_GROUNDED_EVAL: live,
    });
    assert.equal(config.server, null);
    assert.equal(config.retries, 0);
  }
});
