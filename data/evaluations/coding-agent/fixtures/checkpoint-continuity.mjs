const collectorName = "BC Gov Sources - Collection";
const collectorPath = ".github/workflows/official-source-collection.yml";

export function trustedCollection(run, repository, branch, { allowLegacyName = false } = {}) {
  return (run?.name === collectorName || (allowLegacyName && run?.name === "Official source collection"))
    && run.path === collectorPath
    && run.head_branch === branch && run.head_repository?.full_name === repository
    && ["schedule", "workflow_dispatch"].includes(run.event);
}

export function previousCollection(runs, currentId, repository, branch) {
  const candidates = runs.filter((run) => run.id !== currentId
    && trustedCollection(run, repository, branch, { allowLegacyName: true })
    && run.conclusion === "success"
    && !["queued", "waiting", "pending", "requested"].includes(run.status));
  return candidates.sort((a, b) => b.id - a.id)[0];
}
