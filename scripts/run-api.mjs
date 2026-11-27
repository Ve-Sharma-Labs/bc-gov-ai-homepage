import { spawn } from "node:child_process";
import path from "node:path";
import { jurisdictionEnvironment } from "./jurisdiction.mjs";
import { assertPortAvailable, loadLocalEnvironment, localSettings, pythonFor, root } from "./runtime.mjs";

try {
  loadLocalEnvironment();
  const { apiPort, webPort, webUrl } = localSettings();
  const python = pythonFor(path.join("apps", "api"));
  await assertPortAvailable(apiPort);
  const child = spawn(python, [
    "-m", "uvicorn", "bc_api.main:app", "--host", "127.0.0.1", "--port", String(apiPort),
    "--workers", "1", "--no-access-log",
  ], {
    cwd: path.join(root, "apps", "api"),
    stdio: "inherit",
    env: {
      ...jurisdictionEnvironment(),
      APP_ENV: process.env.APP_ENV || "development",
      API_ALLOWED_ORIGINS: process.env.API_ALLOWED_ORIGINS || `${webUrl},http://localhost:${webPort}`,
    },
  });
  child.once("error", (error) => { console.error(error.message); process.exitCode = 1; });
  child.once("exit", (code) => { process.exitCode = code ?? 1; });
  process.once("SIGINT", () => child.kill("SIGINT"));
  process.once("SIGTERM", () => child.kill("SIGTERM"));
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
