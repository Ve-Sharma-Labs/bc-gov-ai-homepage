const bot = (user) => user?.type === "Bot" || user?.login?.endsWith("[bot]");

export function eligibleBug(issue, event, existingPulls) {
  if (!Number.isSafeInteger(issue?.number) || issue.number < 1 || issue.pull_request
    || issue.state !== "open" || bot(issue.user)) return false;
  const bug = issue.labels?.some((label) => (typeof label === "string" ? label : label.name) === "bug");
  const form = /^### Bug report\r?$/m.test(issue.body || "") && issue.title?.startsWith("[Bug]:");
  if (!bug && !form) return false;
  if (event.action && !["opened", "labeled"].includes(event.action)) return false;
  if (event.action === "labeled" && event.label?.name !== "bug") return false;
  if (event.issue && (event.issue.number !== issue.number || event.issue.id !== issue.id)) return false;
  return !existingPulls.some((pr) => pr.state === "open" && bot(pr.user)
    && pr.body?.includes(`<!-- bc-bug-fix:${issue.number} -->`));
}
