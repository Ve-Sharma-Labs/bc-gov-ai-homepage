# BC Government service assistant

A pilot for a conversation-first BC service experience: Next.js/React, light and
dark themes, sourced preparation plans, and a Microsoft Agent Framework/Foundry
backend. This is not a live government transaction service.

See the [as-built architecture](docs/architecture.md) for the Azure topology,
chat/cancellation flow, reviewed-content lifecycle and current release boundaries.
The [agentic workflows guide](docs/agentic-workflows.md) covers the official-source
freshness watchdog and automatic bug-report regression tests and draft fixes.

The reference-led interface includes locally hosted Unsplash BC photography,
editorial serif/BC Sans typography, a compact adaptive composer, a persistent
menu, both themes and four illustrated How-it-works scenes. Drafts and checklist
progress survive internal navigation in memory only. See [the design](DESIGN.md)
and [asset provenance](apps/web/ASSETS.md).

A homepage question opens a dedicated `/chat` view immediately, with one
bottom-pinned composer, real processing status, progressive validated answers,
exact-page citations, preparation/location results and explicit Stop/retry.
Unavailable AI is shown in the chat without inventing an answer. Conversation
state survives internal navigation but not reload or Start over.
Stop cancels the active response and restores the question without resending it;
only an explicit Send or retry starts another run.

## Run locally

Prerequisites: Node.js 24, Python 3.14 with `venv`, and npm. Development
dependencies are isolated in each Python component's `.venv`.

From PowerShell in the repository root:

```powershell
.\scripts\setup.ps1
npm run dev
```

The runner checks ports and starts the API and web app on loopback only:

- Website: `http://127.0.0.1:3000`
- API: `http://127.0.0.1:8000`

Stop both with Ctrl+C. If a port is occupied, set `WEB_PORT` or `API_PORT`; the
runner does not kill unrelated processes. Optional `.env` values are loaded by
the runner, and existing environment variables take precedence.

For an optimized local web build:

```powershell
npm run build
npm start
```

On other platforms, create `.venv` in `apps/api` and `ingestion`, install the API
using `requirements-dev.lock` and editable source, and ingestion with its `azure` extra, run
`npm --prefix apps/web ci` and `npm ci` at the root, then use the same npm commands.

### Guided plans are not simulated AI

Without a configured Foundry connection, the catalogue, official links, and seven
source-backed preparation journeys remain available. They are deterministic,
dated guidance, not generated model answers. Main chat defaults to general B.C.
government questions; the seven pathways are optional, visible context. Strict
greetings and generic clarification can respond without a model or source lookup.
Factual answers still require evidence, and unavailable topics receive an honest
official handoff rather than an answer from model memory.

The pilot does not renew a licence, book an appointment, register a patient,
determine benefit eligibility, or submit a government form. It prepares people
and hands them off to the appropriate official service.

### AI-led conversations

With `TASK_ASSISTANCE_ENABLED=true`, the conversation continues through practical
preparation steps instead of reposting the full checklist. A B.C. renewal starts
with identification preparation; "I have my ID" moves to office selection, and
a chosen city/town filters the reviewed office snapshot. Repeated requests and
"are you helping?" stay with the active task. Chat is text-first: follow-ups
appear as messages and accept typed replies. The full guide, progress, context,
and sharing preferences stay available in optional **Details**, never a
required answer panel.

Four examples on the homepage and empty chat cover licence renewal,
guardianship, disability support, and job loss. Selecting an example only
fills/focuses the composer; Send is explicit, existing drafts need confirmation
before replacement, and no fictional persona or sharing preference is activated.
During a conversation, **Examples** reopens the same suggestions.

Sharing and step-review controls use a non-model, revision-checked endpoint.
They do not insert invented user messages or clear a pending intake question.
Progress means **reviewed or reported ready by the user**, never a completed
government transaction. Task state shares the page session's expiry and can be
cleared with Start over or reload.

The new `AI_CONVERSATION_ENABLED=true` mode uses a separately pinned
`FOUNDRY_CONVERSATION_AGENT` to understand requests before retrieval. Ordinary
typos and paraphrases are handled by the model, not an exact-keyword gate.
The API validates the proposed goal, facts, and essential question, then
provides the existing reviewed guide or uses the grounded-answer runtime.
For example, a misspelled driver's-licence renewal request asks whether the
licence was issued in B.C.; a yes answer leads to practical renewal preparation.
Exact question labels and short answers resolve against the server's pending
question without model inference. "Issued somewhere else" is retained and
leads to a different question: renew with the original issuer, or get a B.C.
licence. Unknown/skipped issuers never become an assumed B.C. renewal.
Business licences, BCeID accounts, and motorcycle purchase planning remain
distinct from driver renewal.

The UI discloses Azure processing before sending. Optional personal-context
sharing starts **off**. When enabled, only relevant, explicitly supplied
categories are retained for that page and included in future model requests.
Changing or removing context does not undo earlier model processing.
Identifiers, credentials, documents, addresses, and medical histories remain
prohibited. Reviewed question wording cannot carry uncited model claims.

Use a distinct isolated agent, not an edited public binding. The export-first
publisher supports `--conversation-only`; a live publication still requires
the approved endpoint and `--publish --approved`. The returned binding is the
source of truth for its version. `AZURE_CLI_SUBSCRIPTION` optionally pins local
authentication without changing the CLI's global default. Public enablement
requires `AI_CONVERSATION_PRIVACY_REVIEWED=true` and the applicable review,
not merely a working local model.

After local connection and explicit model-usage approval, run the bounded
synthetic conversation checks:

```powershell
node scripts\evaluate-ai-conversation.mjs --live-approved
```

This exercises all seven journeys plus negative routing cases, respects local
rate limits, fails on the first broken case, and clears its test sessions.
When task assistance is enabled, it also checks repeated help, sharing changes,
user-reported readiness, continued steps, and an official handoff, rather than
stopping after a guide appears. The reported-renewal case includes the full
frustrated-check-in exchange. The additional non-B.C. cases follow the reported
negative answer through both licensing routes. The guardianship, disability,
and job-loss starter cases check public-safe follow-ups and useful official
handoffs, without borrowing fictional records.
`--case="reported renewal typo"` runs only the reported regression.
`--case="reported exact renewal"` checks `please help me renew my drivers license`.
The local evaluator stops after at most 100 synthetic chat turns; its existing
explicit model-usage approval and localhost-only restrictions still apply.
`--from="reported non-BC renewal loop"` runs the five new branch/starter cases.
The separate browser fixture suite uses `AI_CONVERSATION_ENABLED=true` with
`npm run test:e2e`; it does not invoke a model.
Set `TASK_ASSISTANCE_ENABLED=true` to run the text-first task-continuation,
starter/draft, and non-B.C. browser suite.

### Source readiness and conversation release checks

The deployment templates and protected workflow carry the isolated conversation
binding, AI-conversation flag, task-assistance flag, and public privacy-review
flag together. Defaults remain disabled. A successful image deployment is not
proof that the intended conversation mode was enabled or reviewed.

The web container receives the same public conversation/task flags. Its
request-time shell provides a protocol hint, not a readiness claim, so an
immediate Send cannot accidentally choose legacy chat while source checks are
pending. Sending and Stop remain immediate. Active conversations retain their
protocol and non-model task controls through capability-discovery failures.

`/api/capabilities` now separates agent connectivity from `sourceHealth` and
`retrievalReady`. A nonempty Search index is not enough: readiness applies the
same provenance, content, and freshness validation as answer retrieval. Expired
evidence cannot be used to generate facts. Reviewed, explicitly dated
preparation and task-specific official links remain useful when a detail lacks
current evidence; the conversation must not discard the task or restart intake.

With `API_METRICS_ENABLED=true` and Search configured, each API instance checks
source health on startup and every five minutes without a resident request,
embedding, or model call. The bounded check records expiry/coverage metadata,
not prompts or document bodies. It never refreshes dates or publishes content.

Check a selected candidate/public deployment without invoking a model:

```powershell
node .\scripts\verify-pilot-chat.mjs --url=https://YOUR-REVIEWED-APP/
```

The check rejects a legacy-only deployment, unusable/expiring baseline sources,
missing preparation guides, or accidental activation of the local-only profile.
After separate model-usage approval, `--live-approved` adds at most 18 synthetic
turns covering the exact renewal, continuation, non-B.C. branch, four starter
outcomes, and a cited health answer. It clears its own page sessions and never
resets usage limits. The protected deployment workflow's `verify` operation
exposes these same checks; HTTP 200 with a generic refusal is a failed outcome.

### Grounded conversation candidate (version 6)

The candidate separates progress from the current information request. A mixed
reply such as "I have my ID ready, what else to bring?" can retain progress and
select additional-requirements evidence instead of replaying the checklist.
EI is a specific programme under job loss; city spelling is resolved against
approved names, and a missing snapshot row leads to ICBC's locator rather than
an assertion that the requested city has no service.

`GROUNDED_CONVERSATION_ENABLED` is **off by default**. Clients opt into
capability discovery with `X-BC-Client-Version: 6` and pin their selected
conversation version until starting over. Version 6 uses separate
`FOUNDRY_GROUNDED_CONVERSATION_AGENT` and `FOUNDRY_GROUNDED_ANSWER_AGENT`
bindings. Export review-only definitions using `publish_agents` with
`--grounded-planner-only` or `--grounded-answer-only`. The policies include
bounded SDK model-assisted refinements; this is not a claim that the managed
MCP prompt optimizer ran.
The same publisher's explicit endpoint/approval requirements still apply.

The new source inventory is **metadata, not a populated or approved corpus**:

```powershell
.\apps\api\.venv\Scripts\python.exe -m bc_api.grounding_packs
```

`data\conversation-grounding-packs.json` records required topics and source
references for all four starter flows, including missing candidate topics.
Every pack remains blocked pending its actual rights and publication review.
ICBC and PGT access restrictions are not bypassed. New B.C. guidance needs an
applicable permission/licence review. Canada.ca's conditional non-commercial
terms require an actual use classification, attribution, and content review;
government ownership or an open-data licence is not a blanket grant.
No new source content or index is published by this feature.

For **local non-commercial evaluation only**, the separate
`LOCAL_EVIDENCE_EVALUATION_ENABLED` profile can use named licensed alternatives:
existing project preparation notes, BC Laws statutory sections under the
King's Printer Licence, and dated Canada.ca copies under its conditional
non-commercial terms. This does not approve the original blocked blueprints
or classify a future public/commercial deployment as permitted.

The profile requires development mode, loopback-only API hosts/origins and
listeners, and the same flag in the web proxy. `npm run dev` binds both services
to loopback. A direct Uvicorn launch must use `--host 127.0.0.1 --no-proxy-headers`;
set `API_ALLOWED_HOSTS=localhost,127.0.0.1,::1`. Optional Canada.ca copies require
an absolute `LOCAL_EVIDENCE_SNAPSHOT_PATH` and its
`LOCAL_EVIDENCE_SNAPSHOT_SHA256`. Copies expire after seven days; stale or
changed evidence fails closed. Source bodies are not committed or published
to Search. Privacy and evaluation notices are kept in optional Details rather
than below the composer. The UI retains dated/live provenance
and the full statutory licence notice.

The grounded writer has one typed, programme-scoped source tool, not legacy
plan or office tools. Free-text public-query copying is not required of the
model. Core grounded answers are checked before display; an invalid citation
or critical quotation gets at most one correction within the same model
budget. Failed text never becomes conversation history. The ICBC locator is
an honest handoff, not a verified office inventory or booking service.

Run the explicitly billable, synthetic outcome suite against this local profile:

```powershell
node .\scripts\evaluate-grounded-conversation.mjs --live-approved
```

It replays the reported renewal and EI conversations plus adult/child
guardianship, disability, and a programme switch, and rejects repeated intake,
missing substantive answers, unverified details, and false transaction claims.

For an explicitly billable desktop/mobile UI replay, set `PILOT_BASE_URL` to
the local preview and `LIVE_GROUNDED_EVAL=true`, then run `npm run test:e2e`.
These live tests are excluded from normal fixture runs and never run against
a public host.

The existing version-5 path also has safe compatibility repairs: explicit EI
requests leave the rent/work loop and use an honest official handoff; mixed
document follow-ups request evidence rather than reprinting the ID step; clear
city typos are normalized; and unavailable licensing-office coverage points to
the proper ICBC locator. These fixes do not invent missing instructions or
claim that the four-flow grounding work is complete.
An informational follow-up also preserves the reviewed preparation step and
ignores a planner echo of the already-confirmed city; a genuinely new city still
requires evidence in the current message.

### Original deterministic discovery (version 4)

The repository includes a disabled-by-default conversation increment. To try it
locally with fictional inputs:

```powershell
$env:CONVERSATION_DISCOVERY_ENABLED = 'true'
npm run dev
```

Start with a goal such as planning for a motorcycle next year. The assistant
uses reviewed, application-authored acknowledgments and asks one relevant
question at a time, with at most three questions before a starting plan or
honest official handoff. **Skip this question**, **Give me general guidance**,
and an editable **What I understand** summary keep disclosure optional.
Existing guided plans remain available. Direct factual questions bypass
discovery but still need the configured model and reviewed evidence.

Discovery works without Foundry for its bounded questions and catalogue
handoffs; it is not simulated model output. Motorcycle-specific rules are not
in the approved corpus, so no age eligibility, fees, or licensing outcome is
invented. Age, PHN possession, and other allowlisted answers are temporary
self-reports, not verified government records. PHN numbers, documents, and
credentials must not be entered. Immigration-status questions are not enabled
without a reviewed program-specific purpose and question contract.

**Try fictional context** remains a separate opt-in. A matching conversation
can suggest a fictional scenario, but cannot activate Maya, Alex, or Sam without
the person's explicit choice and consent. Real BCeID/BC Services Card sign-in
and government-record access are not implemented by this increment.

State is bound to the anonymous session and a separate in-memory page token.
It expires after `CONVERSATION_CONTEXT_TTL_SECONDS` (default 1800), and reload
or Start over makes the old page binding unusable. Answers are not put in
browser storage, URLs, telemetry, Search, embeddings, or model prompts.
Factual follow-ups use a bounded public-intent query, not raw discovery history.
Those no-personal-context-to-model guarantees apply to version 4. Version 5
uses its separate disclosure and optional sharing contract; it never imports
facts from an older version-4 session.
Public enablement additionally requires
`CONVERSATION_DISCOVERY_PRIVACY_REVIEWED=true` and the applicable release review.
This code change does not enable or deploy the feature in the public pilot.

## Connect approved Azure services

See `.env.example` for non-secret setting names. The key connections are:

- `FOUNDRY_PROJECT_ENDPOINT`
- `FOUNDRY_AGENTS`: five pinned journey/name/version/model-deployment bindings
- `FOUNDRY_GENERAL_AGENT`: a separate pinned general name/version/model binding
- `AZURE_SEARCH_ENDPOINT` and the reviewed Search index settings. Keep the v1
  defaults until `AZURE_SEARCH_INDEX=bc-pilot-public-v2`,
  `AZURE_SEARCH_METADATA_ENABLED=true` and
  `AZURE_SEARCH_METADATA_REVIEWED=1` can be deployed together.

Create the ignored repository-root `.env` without overwriting existing settings:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
az account show --query "{subscription:id,tenant:tenantId}" --output json
```

Use an existing Azure CLI sign-in for the approved tenant/subscription (`az login`
if not already signed in). The runner does not select or change subscriptions.
Set `APP_ENV=development`, the existing project endpoint, the complete
`FOUNDRY_AGENTS` and `FOUNDRY_GENERAL_AGENT` JSON from the approved publisher, and the existing Search
endpoint/index in `.env`. Wrap the JSON array in single quotes. Do not use
placeholder versions or republish agents just to start the app.

For a second isolated preview, also set `WEB_PORT=3100` and `API_PORT=8100`.
Run `npm run dev` from the root: it loads `.env` for both processes and wires the
same-origin web proxy and trusted local origins to the selected ports. Existing
shell environment variables override `.env`, including empty values; clear stale
overrides before troubleshooting. `npm run dev:api` also loads the root `.env`;
direct component/Uvicorn launches do not do so automatically.

Check `http://127.0.0.1:<WEB_PORT>/api/capabilities`, not just `/healthz`, before
calling the connection ready. With a verified registry and nonempty index it
reports `mode: "foundry"`, `generalChatConfigured`, `retrievalReady` and per-journey
readiness independently. Then submit a public-service
question in `/chat` and check its cited answer. A missing or empty index remains
unavailable for factual generation; general chat can return an application-authored
handoff while pathway requests report `SOURCES_UNAVAILABLE`. Startup never uploads
data or bypasses source review. Topic/pathway retrieval and answer validation still
apply after the connection check succeeds.

Use local developer authentication only for development. Production uses a
deterministic managed identity with narrowly scoped access. Do not put service
credentials in browser code or `NEXT_PUBLIC_*` variables.

A configured endpoint is not proof that the agent, its declared tools, index,
permissions, or processing geography are approved. Follow the API component's
integration instructions and verify a real request before claiming live AI.
The API independently verifies the pinned agent definition and source readiness.
One general and seven pathway prompt agents use shared
API-owned functions; application startup never registers agents. An explicit
review/export and publication command is described in [the API guide](apps/api/README.md).

Local development uses bounded in-memory controls and one API process. The
public deployment requires shared Redis admission/cancellation, managed-identity
service authentication, verified edge context and explicit daily processing
allowances. Missing public controls fail closed rather than exposing the local
preview configuration.

Web IQ is disabled by default. Its access, public-query policy, transient-data
handling, and privacy review are separate gates. It is not the source of the
maintained search corpus.

The repository also contains a disabled-by-default, synthetic citizen-context
validation implementation. It uses three fixed fictional personas,
purpose-specific consent, deterministic screening, review-only previews and a
value-free audit receipt. The reviewed public pilot enables this synthetic
mode, but it is not connected to BC Services Card, a real citizen identity, or
real government records. See the
[ADM demonstration package](docs/citizen-context-adm-demo.md) and
[forwardable executive brief](docs/citizen-context-executive-brief.md).

## Checks

```powershell
npm run check
npm run build
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm run test:e2e
# Separately exercise the opt-in discovery increment against the real local API.
$env:CONVERSATION_DISCOVERY_ENABLED = 'true'
npm run test:e2e
Remove-Item Env:\CONVERSATION_DISCOVERY_ENABLED
```

The browser suite uses an isolated Edge profile on Windows when the channel is
set. On systems without Edge, install Playwright's Chromium browser and omit
that setting. The suite starts its own local services on ports 3310 and 8310
and must not share a real user conversation or Azure model session.
The discovery flag selects the focused discovery browser suite; the default
suite exercises the unchanged legacy modes. CI runs both configurations.

Agentic browser regression discovery, deployed synthetic QA, source-impact
triage, and maintainer-gated draft fixes are documented in
[GitHub Agentic Workflows](docs/agentic-workflows.md). These agents remain
advisory around the repository's deterministic tests and reviewed deployment
controls.

Pilot checks runs on both pushes and pull requests, so a branch update can show
two runs of the same suite. Browser functional tests share a loopback client and
use a bounded 1,000-request/minute HTTP budget only on their own offline preview.
The application's default remains 180; dedicated API tests verify rejection,
client isolation and recovery at that limit. External previews and live grounded
evaluation do not receive this test override. Browser retries remain disabled.
Inspect the retained trace's API responses when a missing card or banner is
reported; a transport error can be the cause rather than a rendering defect.

Context regression tests use an explicit historical clock. To reproduce their
offline comparison, run `npm run evaluate:context -- --snapshot-date 2026-11-06`.
The report labels this as `evaluationMode: "snapshot"` and records `evaluatedAt`;
it is not evidence that sources are current. Without `--snapshot-date`, the
evaluator uses one current UTC instant for both sides of the comparison and
returns a nonzero, structured error for expired reviews. Do not extend
`reviewDue` dates just to make checks pass: current readiness requires genuine
source re-review. The source watchdog's catalogue-age checks do not yet monitor
the separate demo-rule review deadlines.

## Containers and Azure deployment

`docker compose up --build` is an alternative local launch when a Docker engine
is running. It binds exposed ports to loopback and does not provision Azure.
Host developer credentials are not mounted into containers automatically.

The isolated Azure pilot now has real application images, six versioned
Foundry agents, Search, private Redis, protected application ingress, managed
identity and metadata-only monitoring. The general-chat release is available at
[the BC service assistant](https://bcassist-xufhsendpx-ddabgxfdera9azbp.b01.azurefd.net/).
Real public-browser chat, exact source citations, same-thread follow-ups,
Stop/cancellation, both themes and tab-state behavior are verified. Messages and
navigation no longer wait for capability discovery. Typed dialogue, sourced
answers and official handoffs are presented differently, without fake typing.

Public access does not require an IP allowlist. Front Door's WAF, API rate
controls, managed identity and private origin remain enabled. Requests rejected
before model work release their unused token/cost reservation; post-inference
cancellation retains its conservative allowance.

The initial published corpus contains four explicitly reviewed snapshots:
Service BC, Health Connect Registry, MSP and Fair PharmaCare. Held BC Housing
and ICBC material remains excluded. Web IQ remains disabled.
The seven curated guided journeys remain available, but agent readiness does
not imply that every question has approved evidence. Unavailable evidence is
reported explicitly rather than replaced with an unsourced answer.

The full permitted-source programme now has resumable acquisition, exact-hash
review, an optional lease/ETag-safe Blob store and coverage accounting. This is
not a claim that twelve sites have been crawled or published. Source rights,
private job infrastructure and additional snapshot approval remain separate
activation gates. See `data/source-programme.json` and the ingestion guide.

`azure.yaml` and `infra/` retain fail-closed provisioning/deployment hooks for
each environment. The pilot's target, billing, public access and exact initial
source packet were explicitly approved; those approvals do not authorize
additional sources or a different deployment target. See the
[Azure rollout and remaining gates](infra/README.md) before any cloud operation.
Template compilation is not a substitute for deployment validation.

## Repository

| Path | Responsibility |
|---|---|
| `apps/web` | Next.js interface, same-origin API proxy, chat client |
| `apps/api` | FastAPI, Foundry/Agent Framework integration, policy and APIs |
| `ingestion` | Controlled publisher acquisition and Azure Search publishing |
| `data` | Dated, source-backed public catalogue and provenance |
| `scripts` | Local setup, lifecycle, checks, and deployment guard |
| `infra` | Protected Azure hosting and staged release controls |

## Product and evidence

- [As-built architecture and diagrams](docs/architecture.md)
- [Product requirements](PRODUCT.md)
- [Pilot specification](docs/pilot-specification.md)
- [Implementation contract](docs/implementation-contract.md)
- [Citizen-context ADM demonstration package](docs/citizen-context-adm-demo.md)
- [Citizen-context executive brief](docs/citizen-context-executive-brief.md)
- [Twelve-source discovery inventory](docs/source-discovery.json)
- [America.gov implementation research](docs/america-ui-implementation-research.md)
- [Reference-fidelity UI rebuild specification](docs/ui-fidelity-rebuild.md)

Restricted sources remain restricted. BC Laws needs an approved feed/access
route, WorkBC crawl-policy availability must be resolved, and incomplete ICBC
extraction is not silently treated as a complete knowledge base. The curated
catalogue is a starting point, not the planned 300-500-document reviewed corpus.