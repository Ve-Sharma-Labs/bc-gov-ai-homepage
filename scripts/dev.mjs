import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import {
  assertPortAvailable,
  loadLocalEnvironment,
  localSettings,
  pythonFor,
  requireWebRuntime,
  root,
  waitUntilReady,
} from "./runtime.mjs";

const children = [];
let stopping = false;

function stop(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  process.exitCode = exitCode;
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
  }
}

function launch(command, args, cwd, env) {
  const child = spawn(command, args, { cwd, env, stdio: "inherit", shell: false });
  children.push(child);
  child.once("error", (error) => {
    console.error(`Could not start ${path.basename(command)}: ${error.message}`);
    stop(1);
  });
  child.once("exit", (code, signal) => {
    if (!stopping) {
      console.error(`${path.basename(command)} exited (${code ?? signal}). Stopping this preview.`);
      stop(1);
    }
  });
  return child;
}

process.once("SIGINT", () => stop());
process.once("SIGTERM", () => stop());

try {
  loadLocalEnvironment();
  const settings = localSettings();
  const python = pythonFor(path.join("apps", "api"));
  const next = requireWebRuntime();
  const production = process.argv.includes("--production");
  const standalone = path.join(root, "apps", "web", ".next", "standalone", "server.js");
  if (production && !existsSync(standalone)) {
    throw new Error("The optimized web build is missing. Run npm run build first.");
  }
  await Promise.all([
    assertPortAvailable(settings.apiPort),
    assertPortAvailable(settings.webPort),
  ]);
  const env = {
    ...process.env,
    APP_ENV: process.env.APP_ENV || "development",
    CONTENT_CATALOG_PATH: process.env.CONTENT_CATALOG_PATH || path.join(root, "data", "pilot-catalog.json"),
    API_BASE_URL: settings.apiUrl,
    API_ALLOWED_ORIGINS: process.env.API_ALLOWED_ORIGINS || `${settings.webUrl},http://localhost:${settings.webPort}`,
    API_ALLOWED_HOSTS: process.env.API_ALLOWED_HOSTS || (
      process.env.LOCAL_EVIDENCE_EVALUATION_ENABLED === "true"
        ? "localhost,127.0.0.1,::1" : "localhost,127.0.0.1,::1,api"
    ),
    NEXT_TELEMETRY_DISABLED: "1",
    WEBIQ_ENABLED: process.env.WEBIQ_ENABLED || "false",
  };
  const api = launch(python, [
    "-m", "uvicorn", "bc_api.main:app",
    "--host", "127.0.0.1", "--port", String(settings.apiPort),
    "--workers", "1", "--no-access-log", "--no-proxy-headers",
  ], path.join(root, "apps", "api"), env);
  await waitUntilReady(`${settings.apiUrl}/healthz`, api);
  if (!stopping) {
    const webArgs = production ? [standalone] : [
      next, "dev",
      "--hostname", "127.0.0.1", "--port", String(settings.webPort),
    ];
    const web = launch(process.execPath, webArgs, path.join(root, "apps", "web"), {
      ...env,
      NODE_ENV: production ? "production" : "development",
      HOSTNAME: "127.0.0.1",
      PORT: String(settings.webPort),
    });
    await waitUntilReady(settings.webUrl, web);
    await Promise.all([
      waitUntilReady(`${settings.webUrl}/api/catalog`, web),
      waitUntilReady(`${settings.webUrl}/api/capabilities`, web),
    ]);
    if (!stopping) {
      console.log(`\nBC service pilot: ${settings.webUrl}`);
      console.log(`Local API: ${settings.apiUrl}`);
      console.log("Azure resources were not provisioned. Press Ctrl+C to stop these services.\n");
    }
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  stop(1);
}
