import { cpSync, existsSync } from "node:fs";
import path from "node:path";
import { root } from "./runtime.mjs";

const web = path.join(root, "apps", "web");
const standalone = path.join(web, ".next", "standalone");
if (!existsSync(path.join(standalone, "server.js"))) {
  throw new Error("Next standalone output is missing. Build apps/web before preparing the runtime.");
}

cpSync(path.join(web, ".next", "static"), path.join(standalone, ".next", "static"), { recursive: true });
cpSync(path.join(web, "public"), path.join(standalone, "public"), { recursive: true });
console.log("Prepared the standalone web runtime with local fonts and static assets.");
