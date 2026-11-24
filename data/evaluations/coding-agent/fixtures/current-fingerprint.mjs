const bot = (user) => user?.type === "Bot" || user?.login?.endsWith("[bot]");

export function sourceUpdates(groups, issues) {
  return groups.flatMap((group) => {
    const matches = issues.filter((issue) => !issue.pull_request && bot(issue.user)
      && issue.body?.includes(group.marker));
    if (matches.length > 1) throw new Error("Duplicate source issues require maintainer reconciliation");
    const issue = matches[0];
    if (issue && !issue.title?.startsWith("[Source freshness] ")) {
      throw new Error("Owned source issue title no longer matches the safe-output policy");
    }
    if (issue?.body?.includes(`<!-- bc-source-fingerprint:${group.fingerprint} -->`)) return [];
    if (!issue && !group.actionable) return [];
    return [{
      ...group, issueNumber: issue?.number ?? null, issueState: issue?.state ?? null,
      fingerprintMarker: `<!-- bc-source-fingerprint:${group.fingerprint} -->`,
    }];
  });
}
