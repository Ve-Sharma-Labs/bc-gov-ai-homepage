import { existsSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export function loadLocalEnvironment() {
  const envFile = path.join(root, ".env");
  if (existsSync(envFile)) process.loadEnvFile(envFile);
}

export function portFrom(value, fallback, name) {
  if (value === undefined || value === "") return fallback;
  if (!/^\d+$/.test(value)) throw new Error(`${name} must be a whole-number port.`);
  const port = Number(value);
  if (port < 1024 || port > 65535) {
    throw new Error(`${name} must be between 1024 and 65535.`);
  }
  return port;
}

export function localSettings(env = process.env) {
  const webPort = portFrom(env.WEB_PORT, 3000, "WEB_PORT");
  const apiPort = portFrom(env.API_PORT, 8000, "API_PORT");
  if (webPort === apiPort) throw new Error("WEB_PORT and API_PORT must differ.");
  return {
    webPort,
    apiPort,
    webUrl: `http://127.0.0.1:${webPort}`,
    apiUrl: `http://127.0.0.1:${apiPort}`,
  };
}

export function pythonFor(component) {
  const executable = process.platform === "win32"
    ? path.join(root, component, ".venv", "Scripts", "python.exe")
    : path.join(root, component, ".venv", "bin", "python");
  if (!existsSync(executable)) {
    throw new Error(`Missing ${component} virtual environment. Run scripts/setup.ps1 or follow README setup.`);
  }
  return executable;
}

export function requireWebRuntime() {
  const executable = path.join(root, "apps", "web", "node_modules", "next", "dist", "bin", "next");
  if (!existsSync(executable)) {
    throw new Error("Web dependencies are missing. Run npm --prefix apps/web ci.");
  }
  return executable;
}

export function assertPortAvailable(port) {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", (error) => {
      reject(new Error(`Port ${port} is unavailable. Choose another port; do not stop unrelated processes.`, { cause: error }));
    });
    server.listen(port, "127.0.0.1", () => server.close(resolve));
  });
}

export async function waitUntilReady(url, child, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let lastFailure = "No response received.";
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error(`Process exited before ${url} became ready.`);
    }
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2_000) });
      await response.body?.cancel();
      if (response.ok) return;
      lastFailure = `HTTP ${response.status}`;
    } catch (error) {
      lastFailure = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Startup timed out for ${url}: ${lastFailure}`);
}
