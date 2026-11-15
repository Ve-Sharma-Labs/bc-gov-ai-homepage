# Manual CoPyRIT target

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
  "max_conversations": 8
}
```

Replace the placeholders with actual deployment outputs. The example is
deliberately invalid until reviewed: `live_use_approved` must become `true`
only after live use and its limits are approved. A request allowance does not
override the app's separate token, cost, concurrency, or daily limits.

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
