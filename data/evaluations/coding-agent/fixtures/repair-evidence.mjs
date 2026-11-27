export function validateRepairEvidence(evidence, context, changedFiles) {
  if (!evidence || evidence.issueNumber !== context.number
    || !/^[0-9a-f]{40}$/.test(evidence.baseSha)
    || !Number.isInteger(evidence.beforeExitCode)
    || evidence.afterExitCode !== 0 || evidence.failureKind !== "assertion"
    || !Array.isArray(evidence.command) || !evidence.command.length
    || !evidence.command.every((part) => typeof part === "string" && part.length > 0 && part.length <= 1000)
    || !["node", "npm", "python", "python3", ".venv/bin/python",
      "apps/api/.venv/bin/python", "ingestion/.venv/bin/python"].includes(evidence.command[0])
    || !Array.isArray(evidence.regressionFiles) || !evidence.regressionFiles.length
    || !evidence.regressionFiles.every((path) => typeof path === "string"
      && /^(?:apps\/(?:api|web)\/tests\/|ingestion\/tests\/|scripts\/tests\/|tests\/browser\/)/.test(path)
      && !path.includes("..") && changedFiles.includes(path))
    || ![evidence.beforeSummary, evidence.afterSummary].every((value) =>
      typeof value === "string" && value.trim().length > 0 && value.length <= 4000)) {
    throw new Error("Missing valid failing-before/passing-after regression evidence");
  }
}
