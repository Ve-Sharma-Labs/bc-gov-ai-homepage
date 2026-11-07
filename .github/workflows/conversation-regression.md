---
name: BC Gov Agents - PR Conversation QA
run-name: >-
  BC Gov Agents - PR Conversation QA | ${{ github.event_name == 'pull_request' && format('PR #{0}', github.event.pull_request.number) || format('{0} | {1}', github.event_name, github.ref_name) }}
description: |
  Runs bounded, advisory Playwright exploration against a trusted pull request build.
  It combines deterministic browser fixtures with agent-led usability checks and reports
  reproducible conversation regressions without changing code.

on:
  pull_request:
    types: [opened, synchronize, reopened]
    paths:
      - "apps/api/**"
      - "apps/web/**"
      - "data/evaluations/**"
      - "scripts/**"
      - "tests/browser/**"
      - "package.json"
      - "package-lock.json"
      - "playwright.config.mjs"
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

max-turns: 15
max-ai-credits: 500
max-daily-ai-credits: 2000

steps:
  - uses: actions/checkout@v7
    with:
      persist-credentials: false
  - uses: actions/setup-node@v7
    with:
      node-version: "24"
      cache: npm
      cache-dependency-path: |
        package-lock.json
        apps/web/package-lock.json
  - uses: actions/setup-python@v7
    with:
      python-version: "3.14"
  - name: Prepare the isolated browser candidate
    run: bash scripts/prepare-agentic-qa.sh

tools:
  playwright:
    browsers: [chromium]
  github:
    toolsets: [default]
  bash:
    - "npm run test:e2e"
    - "npx --no-install playwright test *"
    - "node scripts/agentic-qa-budget.mjs *"
    - "cat /tmp/agentic-qa-server.log"
    - "git diff *"

network:
  allowed:
    - defaults
    - node
    - python
    - playwright

safe-outputs:
  add-comment:
    max: 1
  upload-artifact:
    allowed-paths:
      - "/tmp/gh-aw/*.md"
      - "/tmp/gh-aw/*.png"
      - "/tmp/gh-aw/*.json"
    max-uploads: 3
    retention-days: 7
  noop:

timeout-minutes: 30
---

# BC Gov Agents - PR Conversation QA

Act as an advisory QA engineer for the exact checked-out candidate revision. Do not edit files.

Read `.github/aw/instructions.md`, `data/evaluations/agentic-conversation-smoke.json`,
the changed-file diff, and the existing browser tests before selecting checks.

## Required checks

1. Run the existing deterministic AI conversation fixture:

   `PILOT_BASE_URL=http://127.0.0.1:3310 AI_CONVERSATION_ENABLED=true npx --no-install playwright test tests/browser/ai-conversation.spec.mjs`

2. Run any additional existing browser spec directly related to the changed files. Do not
   run the entire suite unless the diff makes broad behavior uncertain.
3. Use `playwright-cli` against `http://127.0.0.1:3310` to inspect the actual candidate
   at desktop and mobile widths. Check entry into chat, composer usability, Details,
   sources presentation, Stop/retry/start-over controls when present, focus, overflow,
   and visible errors.
4. Do not call a live model. The isolated candidate intentionally has no Foundry,
   Search, Redis, identity, or telemetry bindings. Fixture replies prove presentation
   behavior only.
5. If a browser test fails, reproduce the smallest safe sequence once and capture a
   screenshot under `/tmp/gh-aw/`. Do not retry repeatedly or suppress the failure.

## Reporting

Classify each result as pass, confirmed failure, needs review, blocked/incomplete, or
not applicable. A command completing is not sufficient evidence of a pass.

For a confirmed actionable regression, request one consolidated PR comment containing:

- tested commit and browser profile
- affected scenario and exact minimal reproduction
- expected versus observed behavior
- smallest useful sanitized evidence
- confidence and whether causality to this pull request is confirmed or only plausible

Search the current PR discussion before commenting and do not repeat an equivalent
finding. If there is no actionable new finding, use `noop`. Never request a fix,
approval, merge, or deployment.
