import { cpSync, existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { loadJurisdiction } from "./jurisdiction.mjs";
import { root, webDistDirectory } from "./runtime.mjs";

const web = path.join(root, "apps", "web");
const directory = webDistDirectory();
const dist = path.join(web, directory);
const standalone = path.join(dist, "standalone");
if (!existsSync(path.join(standalone, "server.js"))) {
  throw new Error("Next standalone output is missing. Build apps/web before preparing the runtime.");
}
const selected = loadJurisdiction().id;
const stamp = JSON.parse(readFileSync(path.join(dist, "jurisdiction.json"), "utf8"));
const publicStamp = readFileSync(path.join(web, "public", ".jurisdiction"), "utf8");
if (stamp.id !== selected || !publicStamp.startsWith(`${selected}:`)) {
  throw new Error("Web build and public assets must match JURISDICTION. Rebuild the selected pack.");
}

cpSync(path.join(dist, "static"), path.join(standalone, directory, "static"), { recursive: true });
cpSync(path.join(web, "public"), path.join(standalone, "public"), { recursive: true });
cpSync(path.join(dist, "jurisdiction.json"), path.join(standalone, "jurisdiction.json"));
console.log("Prepared the standalone web runtime with local fonts and static assets.");
