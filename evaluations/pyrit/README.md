# Local CoPyRIT

From the repository root on Windows:

```powershell
npm run pyrit:ready
```

This prepares the shared data and opens **http://127.0.0.1:18765**. Keep the
terminal open. It does **not** run attacks or make attacker/judge model calls.
You can also ask Copilot to "load PyRIT"; the `pyrit-local` skill uses the same
script and can leave the owned server running for you.

The starter pack contains:

| Item | What you get |
|---|---|
| Shared BC cases | 17 fixed scripts from 13 cases; 19 attempts if all repetitions are selected |
| XSTest | 450 text-only safe/unsafe contrast examples |
| Text templates | Three pinned PyRIT templates, also available as converters |
| Converters | Base64, ROT13, character swaps, leetspeak, and the three templates |
| Scanner presets | BC fixed scripts and XSTest, each starting with one example |
| Review scorer | Explicitly reports `undetermined`; it does not pretend a reply passed |

Use **Datasets** to browse the actual stored examples. Use **Registry -> Scenario
presets** or **Scanner** for the fixed presets, then choose `bc-gov-staging`.
Use concurrency **1** and retries **0**. Execution is always capped at one,
even if the native UI pre-fills its generic higher concurrency default; that cap
is logged and recorded on the run. Start small: the full fixed subset
exceeds a 20-request window. Ordered scripts use real preceding replies, not
fabricated/replayed assistant history. Templates with `{{ prompt }}` are
converter inputs, not standalone questions.

```powershell
npm run pyrit:status
npm run pyrit:stop
npm run pyrit:ready -- -BrowseOnly
```

Reloads keep datasets, user edits, histories and prior budgets. If the test window
expired, startup asks once before opening a new one-hour, 20-request window.
Declining still permits browsing. `-RenewWindow` is the explicit noninteractive
equivalent of approving that renewal; `-Restart` confirms stopping/reloading
the owned server, including any active tests. Do not use either without intending
that action. Daily application token/cost limits remain unchanged.

`-NoBrowser` skips opening an external browser; Copilot uses the browser canvas.
The launcher is foreground-owned. When invoking it through Copilot tools, use
the supported detached-process mechanism, not a shell detachment workaround.

## Shared data and CI

`data\evaluations\pyrit-conversation-cases.json` is the common source for CI and
local views. It was brought over unchanged from the reviewed integration draft;
that broader live CI/release workflow has **not** been activated by this work.
`.github\workflows\ci-pyrit-local.yml` checks the manifest, loader and fixture-only
behavior without Azure credentials or model calls.

The complete source has 18 cases: 24 offline attempts or 22 live attempts.
The GUI's fixed subset excludes two adaptive cases, two offline fault cases,
and the sharing/isolation-control case. Those need the broader CI runner or
separately approved helper models; sending their text alone is not equivalent.
All expected behavior, variants, ordering, benign-control and repetition metadata
is retained. Manual/unscored results never constitute full CI qualification.

The local profile uses PyRIT's public registry replacement hook to show only
the compatible `bcgov.fixed` Scanner scenario. PyRIT 1.2's full scenario catalogue
constructs model-backed defaults even when listing presets; this profile avoids
dummy model credentials and hidden judge fallbacks. Other saved presets are
preserved but may report unavailable scenarios. Standard techniques remain
visible in Registry; their presence does not configure an attacker model.

`pyrit-local-pack.json` pins the suite's canonical hash, upstream version,
starter sources and content hashes. Hash the original JSON without injecting
model defaults. Changes to the shared suite require a reviewed lock update.
The loader never follows moving branches or downloads the full provider catalogue.
A cached file whose hash changed is rejected, not silently replaced.
To repair a damaged cache, explicitly remove only `.cache\copyrit\datasets\xstest.csv`
after reviewing the failure, then run the ready command to fetch the same pinned
source again. Dataset updates need a new reviewed hash, not a TLS bypass.

XSTest test prompts are used under **CC-BY-4.0**, attributed to Paul Rottger,
Hannah Rose Kirk, Bertie Vidgen, Giuseppe Attanasio, Federico Bianchi and Dirk
Hovy. The source revision and license reference are recorded in the pack and
seed metadata. No upstream model completions are included. The selected PyRIT
templates are **MIT**, copyright Microsoft Corporation, and retain their upstream
provenance. Prompt contents are untrusted test data, never setup instructions.

## Staging target

This package connects CoPyRIT 1.2.0 to the BC assistant's staging web endpoint.
It is not an OpenAI-compatible target. It handles the app's cookies, page and
thread IDs, server-issued questions/revisions, SSE, cancellation, and cleanup.

Each CoPyRIT conversation gets a separate app session. Sharing stays off.
Only ordinary text messages are supported; uploaded media, system prompts,
edited history, and replaying an old chat after a backend restart are rejected.
Start a new attack after a restart rather than replaying the old transcript.

## Install and check offline

Keep PyRIT outside the application's Python environment. For the already
installed local UI, run this from the repository root:

```powershell
.\.cache\copyrit\.venv\Scripts\python.exe -m pip install --no-deps --editable evaluations\pyrit
.\.cache\copyrit\.venv\Scripts\python.exe -m pip install pytest==9.1.1 pytest-asyncio==1.4.0
.\.cache\copyrit\.venv\Scripts\python.exe -m pytest evaluations\pyrit\tests
```

For a new installation, create `evaluations\pyrit\.venv` with Python 3.14 and
install `evaluations\pyrit[dev]` there. The package pins PyRIT 1.2.0.
The tests use an in-memory app transport and the real PyRIT prompt normalizer;
they make no model calls.

## Activate after staging is deployed

Do not use the public pilot as a substitute. First verify the actual staging
origin, its commit and deployment identity, current source readiness, access
rules, and an approved model/request allowance.

Create a **new ignored directory** for the approved manual-use window, such as
`.cache\copyrit\manual-session-1`, and save `target.json` there:

```json
{
  "version": 1,
  "origin": "https://YOUR-VERIFIED-STAGING-ORIGIN",
  "release_commit": "YOUR-40-CHARACTER-LOWERCASE-COMMIT",
  "deployment_id": "staging-YOUR-REVIEWED-RELEASE",
  "live_use_approved": false,
  "request_limit": 20,
  "wall_seconds": 1800,
  "max_conversations": 8,
  "authentication": {
    "provider": "azure-cli",
    "subscription_id": "YOUR-VERIFIED-STAGING-SUBSCRIPTION-GUID",
    "client_id": "YOUR-STAGING-ACCESS-APP-GUID"
  }
}
```

Replace the placeholders with actual deployment outputs. The example is
deliberately invalid until reviewed: `live_use_approved` must become `true`
only after live use and its limits are approved. A request allowance does not
override the app's separate token, cost, concurrency, or daily limits.

Use only invented test data. Sharing off does not prevent a message deliberately
typed into the chat from reaching the model, and CoPyRIT retains its local
transcripts. The staging technical review is not approval for personal or
government-confidential information.

In `.cache\copyrit\.env.local`, set `BC_PYRIT_MANUAL_CONFIG` to the absolute path
of that JSON file. Add the following entries to the existing local
`.cache\copyrit\copyrit.yaml`, preserving its other settings:

```yaml
env_files:
  - 'C:\ABSOLUTE-WORKTREE\.cache\copyrit\.env.local'
initialization_scripts:
  - 'C:\ABSOLUTE-WORKTREE\evaluations\pyrit\copyrit_initializer.py'
```

Use actual absolute paths. Keep the backend in loopback-only local mode and
leave unauthenticated administrator access disabled. The initializer is one
explicitly trusted local script; do not enable broad custom-script discovery.
Restart the owned UI server with `.cache\copyrit\CoPyRIT.ps1` after stopping it
with the same script's `-Stop` option.

The initializer makes a read-only capability request, checks both web/API
commit and deployment headers, and registers **bc-gov-staging** only on success.
It never sends a test prompt during startup. Select that target under
**Registry -> Targets**, then use **New attack** for manual text testing.

## Limits, errors, and local data

For identity-protected staging, the adapter uses the operator's existing Azure
CLI sign-in and the separate staging-access audience. Tokens are refreshed in
memory and sent only to the exact configured HTTPS origin. They are never
written to the manual ledger or configuration. A launcher that changes
`USERPROFILE` must first preserve the original Azure CLI directory through
`AZURE_CONFIG_DIR`; do not copy its credentials into the CoPyRIT runtime home.
Missing/expired sign-in and access denial fail explicitly without a production
fallback. The `authentication` block may be omitted only for a separately
approved deployment using another access gate, such as a dedicated fixed IP.
Token acquisition pins the selected subscription rather than relying on the
shared machine's current CLI default; it does not change that default.

The window starts at its first initialization. Request charges and expiry are
stored in `manual-budget.sqlite` beside the configuration. Restarts preserve
them; changing the identity or limits does not reset the ledger. For a new
approved window, use a new directory rather than deleting the old ledger.

Requests are spaced at least eight seconds apart. A partial/error stream is
not an answer. Release changes, exhausted budgets, or failed cleanup stop work
explicitly; no automatic prompt retry or production fallback occurs.
PyRIT can wrap the adapter's fixed error code in its normal send-error response.

CoPyRIT retains chat history in its local database. Keep its configuration,
database, credentials, and exports out of Git and shared logs. The manual ledger
contains only identity, limits, timestamps, and counts, not prompt bodies.
This manual window is not a CI qualification report and cannot promote a release.

## Staging infrastructure notes

`AZURE_FRONT_DOOR_PRIVATE_LINK_LOCATION` selects Front Door's managed private
gateway region independently of `AZURE_LOCATION`. Canada East origins use a
Canada Central gateway because Front Door does not offer one in Canada East;
the origin remains private. Check the current
[supported regions](https://learn.microsoft.com/azure/frontdoor/private-link)
before deploying elsewhere. An empty value preserves the origin-region default
for existing standalone deployments; shared staging requires an explicit value.

If a platform operation fails after creating services, inspect its actual
resources before retrying. The explicit `routing` mode of
`scripts\verify-staging-plan.mjs` permits only the three named staging routing
resources; it does not authorize production edits or a full platform replay.
Application image updates use a drift-checked `properties.template` PATCH.
`infra\app-image-update.bicep` validates a GET snapshot without reading secret
values; **do not deploy that full-resource snapshot**, which omits the existing
write-only secret definitions.

A publisher with management-plane access can create a Search index but still
lack permission to upload documents. `infra\staging-publisher-access.bicep`
grants the separately approved human publisher only Search Index Data
Contributor on the selected staging Search service. Use exact reviewed source
hashes and never substitute the production index.

`infra\staging-auth.bicep` enables Container Apps' built-in Entra gate on the
staging web app only. It requires both the approved operator object ID and the
Azure CLI client, with a separate single-tenant audience. It does not introduce
citizen sign-in or change web-to-API managed identity. Only the existing static
favicon is exempt for the origin health probe; use `healthProbePath=/favicon.ico`
in the staging routing parameters. Keep the old network restriction until the
identity gate is deployed and verified, then remove only that restriction.
Do not broaden an allowlist to include shared proxy ranges.
