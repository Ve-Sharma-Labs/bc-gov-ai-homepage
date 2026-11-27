import assert from "node:assert/strict";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { assertReviewedSourcePolicy, contentPath, jurisdictionEnvironment, jurisdictionId, loadJurisdiction } from "../jurisdiction.mjs";
import { deploymentBlockers } from "../azure-preflight.mjs";
import { webDistDirectory } from "../runtime.mjs";

function reviewedSkEnvironment() {
  const pack = loadJurisdiction("sk");
  return {
    JURISDICTION: "sk",
    OPERATION_RIGHTS_REVIEW_SHA256: createHash("sha256")
      .update(readFileSync(contentPath(pack.sourcePolicy.operationReview.path))).digest("hex"),
  };
}

test("BC remains the default and Saskatchewan selects separate content and publishers", () => {
  const bc = loadJurisdiction("bc");
  const sk = loadJurisdiction("sk");
  assert.equal(bc.content.catalog, "data/pilot-catalog.json");
  assert.equal(sk.timeZone, "America/Regina");
  assert.deepEqual(sk.officialDomains, ["saskatchewan.ca", "sgi.sk.ca", "ehealthsask.ca"]);
  assert.equal(sk.sourcePolicy.approvalStatus, "reviewed-operation-grants");
  assert.notEqual(jurisdictionEnvironment({ JURISDICTION: "bc" }).CONTENT_CATALOG_PATH,
    jurisdictionEnvironment(reviewedSkEnvironment()).CONTENT_CATALOG_PATH);
});

test("reject unknown packs, traversal and invalid identifiers", () => {
  for (const id of ["../bc", "BC", "", "sk/../bc", "sk\\..\\bc"]) {
    assert.throws(() => jurisdictionId(id));
  }
  assert.throws(() => loadJurisdiction("missing"));
  for (const relative of ["../data/a.json", "/data/a.json", "C:/data/a.json", "data\\a.json", "data/../a.json"]) {
    assert.throws(() => contentPath(relative));
  }
});

test("Saskatchewan release rejects foreign resources and unavailable guided features", () => {
  const blockers = deploymentBlockers({
    ...reviewedSkEnvironment(),
    AZURE_SEARCH_INDEX: "bc-pilot-public",
    API_CONTROL_NAMESPACE: "bc-pilot",
    AZURE_DEPLOYMENT_STAGE: "validation",
    SYNTHETIC_CONTEXT_ENABLED: "true",
    TASK_ASSISTANCE_ENABLED: "true",
  });

  assert.ok(blockers.includes("The Search index must belong to the selected jurisdiction."));
  assert.ok(blockers.includes("The control namespace must belong to the selected jurisdiction."));
  assert.ok(!blockers.some((message) => message.includes("Publisher RAG/embedding permission is unresolved")));
  assert.ok(blockers.some((message) => message.includes("Synthetic context is not available")));
  assert.ok(blockers.some((message) => message.includes("Reviewed guided journeys are not available")));
  assert.match(deploymentBlockers({ JURISDICTION: "../bc" })[0], /Invalid deployment jurisdiction/u);
});

test("separate web output directories cannot escape the selected web root", () => {
  assert.equal(webDistDirectory({}), ".next");
  assert.equal(webDistDirectory({ NEXT_DIST_DIR: ".next-sk" }), ".next-sk");
  for (const directory of ["..\\bc", "../bc", "/tmp/build", "C:\\build", ".next/sk", ".next-SK"]) {
    assert.throws(() => webDistDirectory({ NEXT_DIST_DIR: directory }));
  }
});

for (const [id, photo] of [["bc", "vancouver-waterfront-800.webp"], ["sk", "saskatchewan-fields-800.webp"]]) {
  test(`missing ${id} source photography fails without deleting existing public assets`, (t) => {
    const directory = mkdtempSync(path.join(os.tmpdir(), "jurisdiction-web-"));
    t.after(() => rmSync(directory, { recursive: true, force: true }));
    const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
    const web = path.join(directory, "apps", "web");
    mkdirSync(path.join(web, "scripts"), { recursive: true });
    mkdirSync(path.join(directory, "jurisdictions"), { recursive: true });
    cpSync(path.join(root, "apps", "web", "scripts", "prepare-jurisdiction.mjs"),
      path.join(web, "scripts", "prepare-jurisdiction.mjs"));
    for (const brand of new Set(["bc", id])) {
      cpSync(path.join(root, "apps", "web", "brand-assets", brand), path.join(web, "brand-assets", brand), { recursive: true });
      cpSync(path.join(root, "jurisdictions", brand), path.join(directory, "jurisdictions", brand), { recursive: true });
    }
    const run = () => spawnSync(process.execPath, ["--input-type=module", "-e",
      `import { prepareJurisdiction } from ${JSON.stringify(pathToFileURL(path.join(web, "scripts", "prepare-jurisdiction.mjs")).href)}; prepareJurisdiction();`],
    { encoding: "utf8", env: { ...process.env, JURISDICTION: id, JURISDICTION_PACKS_ROOT: path.join(directory, "jurisdictions") } });

    assert.equal(run().status, 0);
    const sentinel = path.join(web, "public", "keep.txt");
    writeFileSync(sentinel, "keep");
    rmSync(path.join(web, "brand-assets", id, "public", "images", id, photo));
    const result = run();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Missing jurisdiction source assets:/u);
    assert.ok(result.stderr.includes(photo));
    assert.ok(existsSync(sentinel));
  });
}

test("a reviewed status alone cannot authorize source use", () => {
  const pack = loadJurisdiction("sk");
  const reviewed = { ...pack, sourcePolicy: { ...pack.sourcePolicy, approvalStatus: "reviewed-operation-grants" } };
  assert.throws(() => assertReviewedSourcePolicy(reviewed, {}), /independently pinned/u);
  assert.throws(() => assertReviewedSourcePolicy({
    ...pack, sourcePolicy: { ...pack.sourcePolicy, approvalStatus: "typo-approved" },
  }, {}), /independently pinned/u);
  assert.throws(() => assertReviewedSourcePolicy(reviewed, { OPERATION_RIGHTS_REVIEW_SHA256: "0".repeat(64) }),
    /verification failed/u);
});

test("pack loading rejects unknown approval statuses and foreign review locators", (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "jurisdiction-policy-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const packDirectory = path.join(directory, "jurisdictions", "sk");
  mkdirSync(packDirectory, { recursive: true });
  const pack = loadJurisdiction("sk");
  const writePolicy = (sourcePolicy) => writeFileSync(path.join(packDirectory, "jurisdiction.json"),
    JSON.stringify({ ...pack, sourcePolicy }));
  for (const approvalStatus of ["typo-approved", "existing-reviewed-snapshots-only"]) {
    writePolicy({ ...pack.sourcePolicy, approvalStatus });
    assert.throws(() => loadJurisdiction("sk", directory), /approval status/u);
  }
  for (const operationReview of [undefined, { path: "data/review.json" },
    { path: "jurisdictions/sk/content/review.json", approved: true }]) {
    writePolicy({ ...pack.sourcePolicy, approvalStatus: "reviewed-operation-grants", operationReview });
    assert.throws(() => loadJurisdiction("sk", directory), /review|selected jurisdiction/u);
  }
});
