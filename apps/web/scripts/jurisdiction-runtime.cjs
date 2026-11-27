const { readFileSync } = require("node:fs");
const path = require("node:path");
const selected = JSON.parse(readFileSync(path.resolve(__dirname, "..", "jurisdiction.json"), "utf8")).id;
const requested = process.env.JURISDICTION ?? "bc";
if (requested !== selected) {
  throw new Error(`Web build jurisdiction ${selected} does not match runtime JURISDICTION ${requested}. Rebuild the selected pack.`);
}
