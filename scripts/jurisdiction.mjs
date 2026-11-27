import { existsSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { root } from "./runtime.mjs";

export function jurisdictionId(value = process.env.JURISDICTION ?? "bc") {
  if (!/^[a-z][a-z0-9-]{1,31}$/u.test(value)) {
    throw new Error("JURISDICTION must be a lowercase jurisdiction identifier.");
  }
  return value;
}

export function contentPath(relative, repositoryRoot = root) {
  if (typeof relative !== "string" || !relative || relative.includes("\\")
    || relative.startsWith("/") || relative.split("/").some((part) => !part || part === "." || part === "..")
    || relative.includes(":")) {
    throw new Error("Jurisdiction content paths must remain relative to the repository.");
  }
  return path.join(repositoryRoot, ...relative.split("/"));
}

export function loadJurisdiction(value = process.env.JURISDICTION ?? "bc", repositoryRoot = root) {
  const id = jurisdictionId(value);
  const manifest = JSON.parse(readFileSync(path.join(repositoryRoot, "jurisdictions", id, "jurisdiction.json"), "utf8"));
  if (manifest.schemaVersion !== 1 || manifest.id !== id) {
    throw new Error("Jurisdiction manifest version or identity mismatch.");
  }
  for (const key of ["name", "shortName", "inlineName", "siteTitle", "description", "locale", "timeZone"]) {
    if (typeof manifest[key] !== "string" || !manifest[key].trim()) {
      throw new Error(`Jurisdiction manifest requires ${key}.`);
    }
  }
  new Intl.DateTimeFormat(manifest.locale, { timeZone: manifest.timeZone });
  for (const key of ["officialDomains", "researchHosts"]) {
    if (!Array.isArray(manifest[key]) || !manifest[key].length
      || manifest[key].some((host) => typeof host !== "string"
        || !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/u.test(host))) {
      throw new Error(`Jurisdiction manifest requires valid ${key}.`);
    }
  }
  const help = new URL(manifest.helpChannel?.url);
  if (!manifest.helpChannel?.name || help.protocol !== "https:" || help.username || help.password || help.port
    || !manifest.officialDomains.some((domain) => help.hostname === domain || help.hostname.endsWith(`.${domain}`))) {
    throw new Error("Jurisdiction help channel must use an approved HTTPS publisher.");
  }
  if (!manifest.brand || typeof manifest.brand.logo !== "string"
    || !/^\/brand\/[a-z0-9-]+\.png$/u.test(manifest.brand.logo)
    || !Number.isInteger(manifest.brand.logoWidth) || manifest.brand.logoWidth < 1
    || !Number.isInteger(manifest.brand.logoHeight) || manifest.brand.logoHeight < 1) {
    throw new Error("Jurisdiction manifest requires a valid brand asset.");
  }
  for (const key of ["catalog", "groundingPacks", "personas", "programmeRules", "sourceProgramme", "provenance"]) {
    contentPath(manifest.content?.[key], repositoryRoot);
  }
  if (typeof manifest.features?.guidedJourneys !== "boolean"
    || typeof manifest.features?.syntheticContext !== "boolean"
    || manifest.sourcePolicy?.trainingAllowed !== false
    || typeof manifest.sourcePolicy?.approvalStatus !== "string") {
    throw new Error("Jurisdiction feature and source policy flags are required.");
  }
  const status = manifest.sourcePolicy.approvalStatus;
  if ((id === "bc" && status !== "existing-reviewed-snapshots-only")
    || (id !== "bc" && !["pending-rag-permission", "reviewed-operation-grants"].includes(status))) {
    throw new Error("Unknown jurisdiction source approval status.");
  }
  if (status === "reviewed-operation-grants") {
    const review = manifest.sourcePolicy.operationReview;
    if (!review || Object.keys(review).join(",") !== "path") {
      throw new Error("Reviewed source policy requires an operation-review path.");
    }
    const reviewPath = contentPath(review.path, repositoryRoot);
    const packRoot = path.join(repositoryRoot, "jurisdictions", id);
    if (![path.join(packRoot, "content"), path.join(packRoot, "ingestion")]
      .some((directory) => reviewPath.startsWith(directory + path.sep))) {
      throw new Error("Operation review must belong to the selected jurisdiction.");
    }
  }
  return manifest;
}

export function assertReviewedSourcePolicy(pack, env = process.env, repositoryRoot = root) {
  if (pack.id === "bc" || pack.sourcePolicy.approvalStatus === "pending-rag-permission") return;
  if (pack.sourcePolicy.approvalStatus !== "reviewed-operation-grants"
    || !/^[a-f0-9]{64}$/u.test(env.OPERATION_RIGHTS_REVIEW_SHA256 || "")) {
    throw new Error("Reviewed source policy requires an independently pinned operation-rights review.");
  }
  const binary = process.platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python"];
  const virtualPython = path.join(root, "apps", "api", ".venv", ...binary);
  const python = (existsSync(virtualPython) && virtualPython)
    || (process.platform === "win32" ? "python" : "python3");
  // Share the audited Python grant provider rather than maintaining a weaker
  // JavaScript interpretation of source permissions.
  const verification = spawnSync(python, [
    "-B", "-c",
    "import sys\nfrom pathlib import Path\nfrom bc_api.jurisdiction import load_jurisdiction\npack = load_jurisdiction(sys.argv[1], Path(sys.argv[2]))\nif pack.rag_pending:\n raise ValueError('Source permission is pending')\npack.operation_provider\nprint('verified')",
    pack.id, repositoryRoot,
  ], {
    env: {
      ...process.env, ...env, JURISDICTION: pack.id,
      PYTHONPATH: [path.join(root, "apps", "api", "src"), path.join(root, "ingestion")].join(path.delimiter),
    },
    encoding: "utf8", timeout: 15_000, maxBuffer: 16_384, windowsHide: true,
  });
  if (verification.error || verification.status !== 0 || verification.stdout.trim() !== "verified") {
    throw new Error("Reviewed source policy verification failed. Verify Python availability, pinned grant/evidence bytes, source scope and expiry.", {
      cause: verification.error,
    });
  }
}

export function jurisdictionEnvironment(env = process.env) {
  const pack = loadJurisdiction(env.JURISDICTION ?? "bc");
  assertReviewedSourcePolicy(pack, env);
  return {
    ...env,
    JURISDICTION: pack.id,
    CONTENT_CATALOG_PATH: env.CONTENT_CATALOG_PATH || contentPath(pack.content.catalog),
  };
}
