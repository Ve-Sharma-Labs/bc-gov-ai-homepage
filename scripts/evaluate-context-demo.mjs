import { spawnSync } from "node:child_process";
import path from "node:path";
import { pythonFor, root } from "./runtime.mjs";

const result = spawnSync(
  pythonFor(path.join("apps", "api")),
  [path.join(root, "scripts", "evaluate-context-demo.py"), ...process.argv.slice(2)],
  {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, PYTHONPATH: path.join(root, "apps", "api", "src") },
  },
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
