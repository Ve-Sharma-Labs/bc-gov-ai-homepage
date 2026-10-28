import { spawnSync } from "node:child_process";
import path from "node:path";
import { pythonFor, root } from "./runtime.mjs";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const checks = [
  [process.execPath, ["--test", "scripts/tests/*.test.mjs"], root],
  [pythonFor(path.join("apps", "api")), ["-m", "pytest", "-q", "--basetemp=.build/integration-pytest"], path.join(root, "apps", "api")],
  [pythonFor("ingestion"), ["-m", "unittest", "discover", "-s", "tests", "-q"], path.join(root, "ingestion")],
  [npm, ["--prefix", "apps/web", "run", "typecheck"], root],
  [npm, ["--prefix", "apps/web", "test"], root],
];

for (const [command, args, cwd] of checks) {
  console.log(`\n> ${path.basename(command)} ${args.join(" ")}`);
  const result = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
    shell: process.platform === "win32" && command === npm,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
  });
  if (result.error || result.status !== 0) {
    console.error(result.error?.message || `Check failed with exit code ${result.status}.`);
    process.exit(result.status || 1);
  }
}
