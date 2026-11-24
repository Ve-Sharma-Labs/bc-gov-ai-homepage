# PyRIT red teaming

`PyRIT - Offline red-teaming checks` runs on PRs and main pushes.
`PyRIT - AI red teaming` runs the live staging suite after explicit activation.
Each threat and approach has its own Actions step. The final coverage check fails
if a required case, variant, repetition, or model judgment is missing.

| Threat | Where it runs |
|---|---|
| Direct prompt injection / jailbreak | Offline and live |
| Indirect prompt injection | Isolated retrieval fixtures |
| False completion | Offline and live |
| High-stakes overreach | Offline and live |
| Grounding manipulation | Offline and live |
| Privacy / session isolation | Synthetic offline and live sessions |
| Conversation manipulation | Offline and live |
| Resource exhaustion | Offline faults; live runs enforce limits without generating load |

The suite uses fixed single-turn prompts, scripted conversations, adaptive
multi-turn attacks, wording variants, and bounded repetitions. It starts with
licence renewal and disability assistance. Benign controls check that the app
still helps people instead of refusing every request.

The job summary separates pass, fail, needs review, and incomplete results.
Model-only flags need review. They are not confirmed defects, but they still
block release. A later successful attempt does not erase an earlier failure.
Passing these cases is not a security certification.

## Local offline run

Use Python 3.14 and the existing API environment from `scripts\setup.ps1`.
PyRIT has a separate environment and does not enter the application images.

```powershell
python -m venv evaluations\pyrit\.venv
.\evaluations\pyrit\.venv\Scripts\python.exe -m pip install -r evaluations\pyrit\requirements-dev.lock
.\evaluations\pyrit\.venv\Scripts\python.exe -m pip install --no-deps -e evaluations\pyrit
```

In one terminal, start the real API with fixture inference:

```powershell
$env:PYTHONPATH = (Resolve-Path apps\api\src).Path
.\apps\api\.venv\Scripts\python.exe apps\api\tests\pyrit_fixture.py --port 8012
```

In another terminal:

```powershell
$pyrit = (Resolve-Path evaluations\pyrit\.venv\Scripts\python.exe).Path
$env:PYRIT_API_PYTHON = (Resolve-Path apps\api\.venv\Scripts\python.exe).Path
$run = Join-Path $env:TEMP ("bc-pyrit-" + [guid]::NewGuid())
$state = Join-Path $run run.sqlite
& $pyrit -m bc_pyrit.cli init --profile offline --target http://127.0.0.1:8012 --state $state --commit (git rev-parse HEAD)
& $pyrit -m bc_pyrit.cli run --state $state --threat all
& $pyrit -m bc_pyrit.cli report --state $state --output (Join-Path $run report.json) --require-pass
```

Stop the fixture with Ctrl+C. Offline inference is synthetic; it checks the
adapter and application contracts, not the live model's behavior. Local reports
cannot qualify a production release.

Use `--threat privacy` or another manifest threat ID for a focused run. A focused
run leaves other cases incomplete and cannot pass the full coverage gate.
The CLI refuses to reset an existing ledger or repeat an already attempted case.
Start a new directory for a new run.

## Before live activation

Prepare a separate staging environment with reviewed agent bindings, model
versions, and the same approved source snapshot as the intended production
release. Keep its mutable state and identities separate. Use the existing Bicep
parameters with a different environment name and resource group.

Staging must have private Container Apps ingress, an approved Front Door private
origin, and the `ValidationOnly` WAF rule. The rule must block other socket
addresses and allow only the reviewed runner's IPv4 ranges (`/24` through `/32`).
Use a trusted Linux runner with fixed egress. Do not send untrusted PR jobs to it.

Create protected `pilot-staging` and `pilot` GitHub environments. Restrict their
deployment branches and OIDC trust to reviewed main-branch workflows, and retain
production reviewers. Retire legacy production deployment credentials and old
deployment routes before activation; repository changes cannot revoke historical
workflow runs or Azure permissions.

The idle readiness job uses the web app's managed identity to read the private
API. It makes no model request and does not forge Front Door headers. New staging
can include it with `AZURE_RELEASE_PROBE_ENABLED=true` and a pinned web image.
For the existing production environment, validate and deploy
`infra\release-probe.bicep` separately. That template changes only the manual job,
not the running applications, WAF, network, or shared controls.

The job has no schedule, one replica, no retries, and a bounded execution timeout.
The release controller supplies the tested web image, exact API revision URL,
and expected deployment identity before starting it.

### GitHub variables

| Variable | Purpose |
|---|---|
| `PYRIT_RUNNER_LABEL` | Reviewed Linux runner label, available at repository scope |
| `PYRIT_LIVE_ENABLED` | `true` enables live workflow entry points; leave unset until approved |
| `PYRIT_LIVE_APPROVED` | `1` records approval for the selected target, helpers, and limits |
| `PYRIT_RELEASE_ENABLED` | `1` enables the reviewed release path |
| `PYRIT_ALLOWED_ORIGIN` | Exact staging HTTPS origin; also set at repository scope for report validation |
| `PYRIT_STAGING_CONTEXT_JSON` | Staging resource context emitted as `PYRIT_CONTEXT` by Bicep |
| `PYRIT_PRODUCTION_CONTEXT_JSON` | The corresponding reviewed production resource context |
| `PYRIT_LIMITS_JSON` | Whole-run application and helper-model limits |
| `PYRIT_MODELS_JSON` | Approved attacker and judge configuration |
| `PYRIT_CLIENT_ID` | Separate OIDC evaluation identity |
| `AZURE_PRODUCTION_ENV_NAME` | Protects production from generic staging provisioning |

Keep the two contexts and evaluation settings consistent in the protected
environments. Resource context contains the subscription, API/web/probe job IDs,
Foundry account, Front Door endpoint, WAF policy, registry name, and origin.
Copy actual reviewed values; do not infer them from the CLI's current account.

The evaluation identity needs staging ARM metadata read access, Search Index Data
Reader, and inference access only to the approved helper models. It must not be a
deployment or publication identity. Deployment identities need their scoped app,
registry, and probe-job permissions plus source-read access for fingerprinting.
Production digest import also needs access to the staging registry.

Existing privacy, source-publication, private-origin, public-preview, brand, and
deployment approval requirements remain in place. These variables record reviews;
setting a flag is not a substitute for one.

### Models and budgets

`PYRIT_MODELS_JSON` contains `attacker` and `judge` objects. Each has:

```json
{
  "endpoint": "https://YOUR-APPROVED-RESOURCE.openai.azure.com/openai/v1",
  "deployment": "YOUR-APPROVED-DEPLOYMENT",
  "response_model": "EXACT-REVIEWED-RESPONSE-MODEL-ID"
}
```

Authentication uses the job's Entra identity. No API keys belong in these values.
The helper transport rejects redirects, truncated replies, unexpected model
identities, and invalid JSON.

`PYRIT_LIMITS_JSON` has `app`, `wall_seconds`, `attacker`, and `judge` fields.
Each helper limit requires `calls`, `tokens`, `cost_microusd`, `input_bytes`,
`output_tokens`, and `token_price_microusd`. Values must be positive for live use.
There is no default live spending allowance.

```powershell
.\evaluations\pyrit\.venv\Scripts\python.exe -m bc_pyrit.cli estimate --profile live
```

Review the estimate before choosing limits. The runner reserves the maximum
input/output allowance before each helper call and does not refund uncertain
work. Every Actions step shares one ledger. A budget shortfall stops the run
instead of dropping cases. App-side admission controls still apply.

These are per-run evaluation limits, not an Azure invoice cap. Workflow reruns
can spend again; provider billing, app daily limits, and subscription monitoring
remain separate controls.

## Release path

The manual Azure workflow requires offline checks, builds the images once, deploys
their digests to staging, and invokes the live suite. Both fixed and adaptive
checks must pass. Missing services, expired evidence, model flags, and cleanup
failures block promotion.

After production approval, the controller rechecks source, model, configuration,
image, and run identity. It creates a new API/web revision pair at zero public
traffic, probes the private API with the web identity, and switches web traffic.
The new web revision calls its matching API revision. Existing Front Door and WAF
settings stay in place. Failed public verification restores the previous web
traffic mapping.

This is an image-only release path. It does not publish agents or sources, enable
research, widen access, or raise production budgets. Configuration drift and
independent Azure edits stop the operation rather than being overwritten.

Old revisions remain available for streams and rollback. A rollout refuses to
add another revision when an app already has three active revisions. Review and
drain obsolete zero-traffic revisions before the next release. Preserve the API
revision still used by any retained web revision, including a legacy web revision
that calls the API's base hostname.

Qualification is tied to one commit, image pair, suite, configuration, source
snapshot, model inventory, and workflow attempt. Old or partial reports cannot
qualify a new release. Qualification expires one hour after candidate capture;
queueing or delayed approval can require a new run. Standalone scans require staging to contain the selected
main commit; they do not supply the same-run offline evidence needed for promotion.

Repository validation does not prove a live cutover. Demonstrate private access,
conversation continuity, streaming drain, and rollback during the separately
approved activation before using this path for production.

## Findings and retention

The existing live conversation GH-AW workflow reviews sanitized reports from
trusted producers. It checks repository, workflow path, branch, commit, run
attempt, suite, and target before handing findings to the agent. Report-only runs
do not submit more prompts.

Only deterministic failures can create confirmed findings. Model flags remain
needs review. Findings are deduplicated and limited to three issues/comments per
run. Reports retain case IDs, counts, reason codes, and fingerprints for seven
days. They exclude cookies, credentials, full transcripts, and raw provider errors.
