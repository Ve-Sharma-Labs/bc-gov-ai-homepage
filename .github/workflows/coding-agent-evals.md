---
name: BC Gov Agents - Coding Agent Evals
run-name: >-
  BC Gov Agents - Coding Agent Evals | ${{ github.event_name == 'pull_request' && format('PR #{0}', github.event.pull_request.number) || format('{0} | {1}', github.event_name, github.ref_name) }}
description: Regression-test the coding agent on frozen repository tasks with independent, blocking outcome checks.
intent: Catch coding-agent configuration regressions before they affect everyday repository repairs.
on:
  pull_request:
    types: [opened, synchronize, reopened]
  schedule: daily
  workflow_dispatch:
  report-blocked-version: false
  permissions:
    pull-requests: read
  steps:
    - id: trusted_source
      env:
        HEAD_REPOSITORY: ${{ github.event.pull_request.head.repo.full_name }}
      run: |
        if [[ "$GITHUB_EVENT_NAME" != "pull_request" ]]; then
          exit 0
        fi
        [[ "$HEAD_REPOSITORY" == "$GITHUB_REPOSITORY" ]]
    - id: config_scope
      uses: actions/github-script@v9
      with:
        script: |
          if (context.eventName !== 'pull_request') return true;
          if (context.payload.pull_request.changed_files > 3000) return true;
          const files = await github.paginate(github.rest.pulls.listFiles, {
            ...context.repo, pull_number: context.payload.pull_request.number, per_page: 100
          });
          const relevant = /^(?:\.github\/|(?:AGENTS|CLAUDE)\.md$|scripts\/coding-agent-eval|scripts\/tests\/coding-agent-evals\.test\.mjs$|tests\/agent-evals\/|data\/evaluations\/coding-agent\/)/;
          return files.some(file => [file.filename, file.previous_filename]
            .some(name => typeof name === 'string' && relevant.test(name)));
    - id: eval_needed
      if: steps.config_scope.outputs.result == 'true'
      run: echo "Coding-agent configuration or evaluation inputs require a run."
if: needs.pre_activation.outputs.trusted_source_result == 'success' && needs.pre_activation.outputs.eval_needed_result == 'success'
permissions:
  contents: read
  copilot-requests: write
engine: copilot
imports:
  - shared/coding-agent-policy.md
strict: true
timeout-minutes: 20
max-turns: 60
max-ai-credits: 300
max-daily-ai-credits: 900
network:
  allowed: []
checkout: false
tools:
  github: false
  bash:
    - "node --test:*"
    - "node --check:*"
safe-outputs:
  staged: true
  noop:
    report-as-issue: false
  report-failure-as-issue: false
  report-failed-jobs: false
  activation-comments: false
  threat-detection:
    report-as-issue: false
steps:
  - name: Download the task-only evaluation workspace
    uses: actions/download-artifact@v8
    with:
      name: coding-agent-kit
      path: ${{ github.workspace }}
  - uses: actions/setup-node@v7
    with:
      node-version: "24"
post-steps:
  - name: Collect bounded submissions without executing candidate code
    id: collect
    if: always() && needs.prepare_evals.result == 'success'
    uses: actions/github-script@v9
    env:
      EVAL_MANIFEST: ${{ needs.prepare_evals.outputs.manifest }}
    with:
      script: |
        const fs = require('node:fs');
        const path = require('node:path');
        const { createHash } = require('node:crypto');
        const { pathToFileURL } = require('node:url');
        const manifest = JSON.parse(process.env.EVAL_MANIFEST);
        const relative = 'scripts/coding-agent-evals.mjs';
        const helper = path.join(process.env.GITHUB_WORKSPACE, relative);
        for (const target of [path.dirname(helper), helper]) {
          if (fs.lstatSync(target).isSymbolicLink()) throw new Error('Untrusted collector path');
        }
        const hash = createHash('sha256').update(fs.readFileSync(helper)).digest('hex');
        if (hash !== manifest.protectedFiles[relative]) throw new Error('Collector was modified');
        const { collect } = await import(pathToFileURL(helper).href);
        collect(process.env.GITHUB_WORKSPACE,
          path.join(process.env.RUNNER_TEMP, 'coding-agent-submission'), manifest);
  - name: Upload only bounded synthetic candidate files
    if: always() && steps.collect.outcome == 'success'
    uses: actions/upload-artifact@v7
    with:
      name: coding-agent-candidates
      path: ${{ runner.temp }}/coding-agent-submission
      if-no-files-found: error
      retention-days: 7
jobs:
  prepare_evals:
    name: BC Gov Agents - Prepare Coding Agent Evals
    needs: [pre_activation]
    if: >-
      needs.pre_activation.outputs.activated == 'true' &&
      needs.pre_activation.outputs.trusted_source_result == 'success' &&
      needs.pre_activation.outputs.eval_needed_result == 'success'
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
    outputs:
      manifest: ${{ steps.prepare.outputs.manifest }}
    steps:
      - uses: actions/checkout@v7
        with:
          ref: ${{ github.sha }}
          persist-credentials: false
      - uses: actions/setup-node@v7
        with:
          node-version: "24"
      - name: Prepare tasks without Git history, reference solutions or private checks
        id: prepare
        env:
          EVAL_MODEL: ${{ vars.GH_AW_MODEL_AGENT_COPILOT || vars.GH_AW_DEFAULT_MODEL_COPILOT || 'auto' }}
        run: node scripts/coding-agent-evals.mjs pack
      - uses: actions/upload-artifact@v7
        with:
          name: coding-agent-kit
          path: ${{ runner.temp }}/coding-agent-kit
          include-hidden-files: true
          if-no-files-found: error
          retention-days: 7
  agent:
    needs: [prepare_evals]
  grade:
    name: BC Gov Agents - Coding Agent Eval Gate
    needs: [agent, activation, pre_activation]
    if: >-
      always() &&
      (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository) &&
      (needs.pre_activation.outputs.config_scope_result != 'success' || needs.pre_activation.outputs.eval_needed_result == 'success')
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
      actions: read
    steps:
      - uses: actions/checkout@v7
        with:
          ref: ${{ github.sha }}
          persist-credentials: false
      - uses: actions/setup-node@v7
        with:
          node-version: "24"
      - name: Download this run's candidate files
        continue-on-error: true
        uses: actions/download-artifact@v8
        with:
          name: coding-agent-candidates
          path: test-results/coding-agent-evals/submission
      - name: Independently grade outcomes and enforce the threshold
        env:
          EVAL_AGENT_RESULT: ${{ needs.agent.result }}
        run: node scripts/coding-agent-evals.mjs grade
      - name: Keep sanitized results even when the gate fails
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: coding-agent-eval-report
          path: test-results/coding-agent-evals/report
          if-no-files-found: warn
          retention-days: 7
---

# BC Gov Agents - Coding Agent Evals

You are the coding agent under evaluation, not the evaluator. Apply the imported
coding-agent policy used by the automatic bug-repair workflow. Read
`.github/aw/instructions.md` and `data/evaluations/coding-agent/suite.json`.

The prepared files under `test-results/coding-agent-evals/work/` are frozen,
synthetic extracts of real repository regressions. For each catalogued task,
repair only `work/CASE_ID.mjs` to satisfy that task's full contract. Keep its
exports and return shapes. Do not copy answers from Git history or retrieve
reference implementations; production source, Git objects and private grading
checks are intentionally absent from this task-only workspace.

Run the public smoke tests before and after the fixes:

`node --test test-results/coding-agent-evals/work/*.test.mjs`

The first run should reproduce assertion failures, not setup failures. Do not
change the smoke tests, fixtures, catalog, instructions, workflows or harness.
Do not install packages, start other agents, make network calls, commit changes,
open issues or PRs, or access any live application.

Each task has additional independent checks on a fresh runner. They test normal,
boundary and negative behavior, not an exact implementation. Passing smoke tests
alone is not a final eval pass. Do not write reports, scores or capture metadata:
trusted Actions steps collect bounded solutions and the independent grader owns
the result. Leave all candidate files in place when finished.

If work cannot be completed, leave the partial files intact and explain the
blocker using `noop`; unavailable tools or an empty submission are not passes.
Otherwise use `noop` to state that the local repairs are ready for independent
grading. No repository write is requested in either case.
