---
description: |
  Reviews changes to approved source metadata and maps them to affected journeys,
  evaluations, and claims without granting acquisition or publication rights.

on:
  pull_request:
    types: [opened, synchronize, reopened]
    paths:
      - "data/provenance.json"
      - "data/source-programme.json"
      - "data/conversation-grounding-packs.json"
      - "data/pilot-catalog.json"
      - "ingestion/**"
      - "scripts/source-preflight.mjs"
  schedule: weekly on monday
  workflow_dispatch:
  permissions:
    pull-requests: read
  steps:
    - id: trusted-source
      env:
        HEAD_REPOSITORY: ${{ github.event.pull_request.head.repo.full_name }}
      run: |
        if [[ "$GITHUB_EVENT_NAME" != "pull_request" ]]; then
          exit 0
        fi
        [[ "$HEAD_REPOSITORY" == "$GITHUB_REPOSITORY" ]]

if: needs.pre_activation.outputs.trusted_source_result == 'success'

permissions:
  contents: read
  issues: read
  pull-requests: read
  copilot-requests: write

engine: copilot

max-turns: 12
max-ai-credits: 350
max-daily-ai-credits: 700

tools:
  github:
    toolsets: [default]
  bash:
    - "git diff *"
    - "node scripts/source-preflight.mjs"
    - "npm run test:tooling"

network: defaults

safe-outputs:
  create-issue:
    max: 3
    title-prefix: "[source impact] "
  add-comment:
    max: 1
  upload-artifact:
    allowed-paths:
      - "/tmp/gh-aw/*.md"
      - "/tmp/gh-aw/*.json"
    max-uploads: 2
    retention-days: 7
  noop:

timeout-minutes: 15
---

# Source-change impact triage

Read `.github/aw/instructions.md`, `ingestion/README.md`, `data/provenance.json`,
`data/source-programme.json`, `data/conversation-grounding-packs.json`,
`data/pilot-catalog.json`, and related evaluation cases.

For a pull request, inspect only the base-to-head diff and report impacts on that PR.
For a scheduled or manual run, inspect expiry/status metadata and recent repository
changes for materially stale or withdrawn evidence.

Map each material source change to affected journeys, grounding packs, evaluation
cases, citations, and user-facing claims. Distinguish:

- content changed or withdrawn
- rights or review state expired/unknown
- fetch or validation failure
- retrieval/index coverage gap
- no material user-facing impact

Deterministic checks own hashes, schema, expiry, link status, budgets, quarantine, and
publication. Run an existing deterministic check only when it directly supports the
analysis. Never modify approved hashes, grant rights, publish content, crawl blocked
sources, infer office services or hours, bypass robots or Terms, or treat fetch failure
as evidence that content is unchanged.

Search for an equivalent open finding using source identity plus content/version hash.
On a PR, request at most one consolidated comment. On a scheduled/manual run, request
at most three issues or update equivalent bot-owned findings with materially new
evidence. Include the affected journeys/tests and a concrete human review checklist.
Use `noop` when no action is required.
