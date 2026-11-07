---
name: BC Gov Agents - Live Conversation QA
run-name: >-
  BC Gov Agents - Live Conversation QA | ${{ github.event_name }} | ${{ github.event.workflow_run.head_branch || github.ref_name }}
description: |
  Performs bounded browser QA against the approved deployed pilot after successful
  deployments, daily, or manually. It evaluates real synthetic conversations and
  creates deduplicated issues for confirmed failures.

on:
  workflow_run:
    workflows: ["BC Gov App - Azure Deployment"]
    types: [completed]
    branches: [main]
  schedule: daily
  workflow_dispatch:
  permissions:
    actions: read
  steps:
    - id: approved-target
      env:
        GH_TOKEN: ${{ github.token }}
        QA_LIVE_BASE_URL: ${{ vars.QA_LIVE_BASE_URL }}
        QA_LIVE_ENABLED: ${{ vars.QA_LIVE_ENABLED }}
        UPSTREAM_CONCLUSION: ${{ github.event.workflow_run.conclusion }}
        UPSTREAM_RUN_ID: ${{ github.event.workflow_run.id }}
        UPSTREAM_SHA: ${{ github.event.workflow_run.head_sha }}
      run: |
        [[ "$QA_LIVE_ENABLED" == "true" ]]
        [[ "$QA_LIVE_BASE_URL" == "https://bcassist-xufhsendpx-ddabgxfdera9azbp.b01.azurefd.net" ]]
        if [[ "$GITHUB_EVENT_NAME" != "workflow_run" ]]; then
          exit 0
        fi
        [[ "$UPSTREAM_CONCLUSION" == "success" ]]
        artifact_id=$(gh api \
          "/repos/$GITHUB_REPOSITORY/actions/runs/$UPSTREAM_RUN_ID/artifacts" \
          --jq '.artifacts[] | select(.name == "deployment-marker") | .id' | head -n 1)
        [[ -n "$artifact_id" ]]
        gh api "/repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" > /tmp/deployment-marker.zip
        marker=$(unzip -p /tmp/deployment-marker.zip deployment-marker.json)
        [[ "$(jq -r .operation <<<"$marker")" == "deploy" ]]
        [[ "$(jq -r .repository <<<"$marker")" == "$GITHUB_REPOSITORY" ]]
        [[ "$(jq -r .runId <<<"$marker")" == "$UPSTREAM_RUN_ID" ]]
        [[ "$(jq -r .sha <<<"$marker")" == "$UPSTREAM_SHA" ]]
        [[ -n "$(jq -r .environment <<<"$marker")" ]]

if: needs.pre_activation.outputs.approved_target_result == 'success'

permissions:
  actions: read
  contents: read
  issues: read
  pull-requests: read
  copilot-requests: write

engine: copilot

max-turns: 20
max-ai-credits: 600
max-daily-ai-credits: 1200

tools:
  playwright:
    browsers: [chromium]
  github:
    toolsets: [default]
  bash:
    - "node scripts/agentic-qa-budget.mjs *"
    - "cat data/evaluations/agentic-conversation-smoke.json"

network:
  allowed:
    - defaults
    - playwright
    - "bcassist-xufhsendpx-ddabgxfdera9azbp.b01.azurefd.net"
    - "www2.gov.bc.ca"
    - "www.bclaws.gov.bc.ca"
    - "www.canada.ca"
    - "www.icbc.com"

safe-outputs:
  create-issue:
    max: 3
    title-prefix: "[agentic conversation QA] "
  add-comment:
    max: 3
  upload-artifact:
    allowed-paths:
      - "/tmp/gh-aw/*.md"
      - "/tmp/gh-aw/*.png"
      - "/tmp/gh-aw/*.json"
    max-uploads: 3
    retention-days: 7
  noop:

concurrency:
  group: live-conversation-regression
  cancel-in-progress: false

timeout-minutes: 25
---

# BC Gov Agents - Live Conversation QA

Test only `https://bcassist-xufhsendpx-ddabgxfdera9azbp.b01.azurefd.net`. Reject
redirects or navigation to any other application origin. Official source links may be
opened read-only only on the domains in the network allowlist. Do not submit forms or
follow transaction handoffs.

Read `.github/aw/instructions.md` and
`data/evaluations/agentic-conversation-smoke.json`. Initialize the executable budget:

`node scripts/agentic-qa-budget.mjs reset`

Before every submitted chat message, including a retry, run:

`node scripts/agentic-qa-budget.mjs consume 1`

Stop when the command refuses a turn. Never exceed 12 submitted turns across desktop
and mobile sessions.

## Browser protocol

1. Verify the approved origin loads, the real capabilities endpoint completes, and the
   UI presents AI availability honestly before submitting a prompt.
2. Run the smoke scenarios first, then as many rotating scenarios as fit within the
   remaining budget. Use a fresh browser session where scenario state could leak.
3. Inspect desktop and narrow/mobile presentation. Reuse non-chat layout observations
   rather than spending duplicate model turns.
4. Check progressive reply behavior, completion, follow-up consistency, sources,
   Stop/retry/start-over, duplicate submissions, visible errors, and composer recovery.
5. Evaluate replies for relevance, consistency, source support, and honest limits, not
   exact wording or style. Verify a critical factual claim against an allowlisted
   official source when evidence is available.
6. Never use personal data. Do not ask for identifiers, addresses, documents, medical
   histories, credentials, or account details.
7. On a 429, systemic 5xx, missing capability, model outage, cleanup failure, or
   repeated timeout, stop further submissions and classify the run blocked/incomplete.

## Findings

A confirmed defect requires observable evidence and one bounded reproduction. Mark
uncertain answer-quality concerns as needs review, not factual errors.

Search open issues with the title prefix and equivalent scenario/failure signature.
Comment only when there is materially new recurrence evidence; otherwise do not create
a duplicate. Create at most three issues in one run. Put remaining findings in a
sanitized `/tmp/gh-aw/live-conversation-report.md` artifact.

Each issue must include severity, scenario identifier, expected versus actual behavior,
minimal reproduction, target origin, observed deployment identity when known, run URL,
sanitized evidence, and confidence. Never attach raw traces or complete transcripts.
Use `noop` when there is no actionable new finding.
