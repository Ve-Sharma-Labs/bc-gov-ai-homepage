# BC pilot API

Read-only FastAPI service with explicit general chat and optional guided pathways.
Without a verified general binding, factual general requests fail honestly; the
curated catalogue and strictly classified application greetings remain available.
Default startup can warm agent/index metadata, but never generates answers, deploys,
registers agents or crawls content. The explicit local-evaluation profile can
also check its finite registry of licensed sources. A separate, explicitly approved operator
command publishes managed prompt-agent versions. Resident transactions and Web IQ
transport remain unimplemented.

For deployment boundaries and the end-to-end request lifecycle, see the
[as-built architecture](../../docs/architecture.md), including the
[chat and cancellation sequence](../../docs/architecture.md#3-chat-grounding-and-cancellation).
This guide remains the detailed API configuration and safety contract.

## Run locally

Run from the repository root with Python **3.14**. No global Python packages are
needed. Dependencies and native transport tests were verified on Python 3.14.0.

```powershell
New-Item -ItemType Directory -Force apps\api\.build,apps\api\.cache | Out-Null
$env:TEMP = Join-Path (Get-Location) 'apps\api\.build'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path (Get-Location) 'apps\api\.cache'
python -m venv apps\api\.venv
apps\api\.venv\Scripts\python.exe -m pip install -r apps\api\requirements-dev.lock -e apps\api
apps\api\.venv\Scripts\python.exe -m uvicorn bc_api.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

If the venv already exists, skip its creation. `bc_api.main:app` is the entry
point; `create_app(settings, runtime=...)` is the test factory. The component does
not automatically load `.env`; use the root development script or explicitly
pass Uvicorn `--env-file .env`. `.env.example` lists the component's settings.
`API_BASE_URL` belongs **only to the web proxy**, not this API.

Prefer `npm run dev` (both services) or `npm run dev:api` (API only) at the
repository root when using the root `.env`; these also derive the local CORS
origins from `WEB_PORT`. For a direct Uvicorn launch, `--env-file` is relative to
the current directory, and the port must still be passed explicitly. Match
`API_ALLOWED_ORIGINS` to the actual local website when using non-default ports.
Keep a separate editable `.venv` per worktree so Python imports that worktree's
source, not another checkout's implementation.

`CONTENT_CATALOG_PATH` overrides the catalogue path (`SOURCE_CATALOG_PATH` is an
accepted compatibility alias). Otherwise the resolver finds the repository's
`data/pilot-catalog.json` relative to the installed module, with
`/app/data/pilot-catalog.json` as the container fallback. It is independent of the
working directory. Empty environment values are ignored. No fixture catalogue
is shipped as application data.

## HTTP contract

| Route | Behaviour |
|---|---|
| `GET /healthz` | `{"status":"ok"}`; liveness only, no Azure call |
| `GET /api/catalog` | Strictly validated camelCase catalogue; no stale cache after invalid replacement |
| `GET /api/journeys/{id}` | One of five sourced preparation journeys; unknown ID is 404 |
| `GET /api/locations?service=...&municipality=...` | Explicit supported capabilities; exclusions win; unknown service is 400 |
| `GET /api/capabilities` | Independent general-agent, per-pathway and retrieval readiness; supported request versions |
| `POST /api/agent` | AG-UI `RunAgentInput` and SSE, or honest error JSON before streaming |
| `POST /api/runs/{runId}/cancel` | Originating session only; 202 `cancelling`, 200 when already cancelled, 404 for another session/unknown run, 409 when finished |

All non-streaming errors use `{"error":{"code":"...","message":"..."}}`.
After SSE begins, failures use `RUN_ERROR`; failures and cancellations never emit
`RUN_FINISHED`. There is no arbitrary URL fetch route.

An AG-UI request must provide `threadId`, `runId`, plain-text `messages`,
`tools:[]`, `context:[]`, `state:{}`, and either `forwardedProps:{}` or
`forwardedProps:{"bc":{"version":1,"journeyId":"licence-renewal","researchRequested":false}}`.
Version 2 makes scope explicit: `{"bc":{"version":2,"mode":"general"}}` forbids
a retained journey, while `{"bc":{"version":2,"mode":"pathway","journeyId":"licence-renewal"}}`
requires one. General chat never silently falls back to a specialist. Version 1
keeps its original routing shape and cannot carry `mode`.
The optional legacy journey hint must name one of the five supported journeys; the
research flag is an explicit request, not permission to enable Web IQ. Only `user` and
`assistant` message roles are accepted, with unique IDs and a final user message.
System/developer messages, caller-selected tools, model/agent overrides, remote
session identifiers, resume controls, attachments and nonempty state are rejected.
Client assistant history remains untrusted context, never tool authorization.
The browser sends completed user turns and only exact model clarification dialogue
back on later requests. It does not retransmit factual model answers or cited
source prose. The API constructs bounded follow-up retrieval queries from prior
user turns, retrieves fresh evidence and does not rely on provider conversation
state. This reduces payload/token exposure and avoids treating generated prose
as authoritative context.

The API issues the opaque `bc_pilot_session` cookie (`HttpOnly`, `SameSite=Strict`,
`Path=/api`, `Secure` in production). The web proxy must preserve `Cookie`,
`Set-Cookie`, original `Origin`, errors, stream chunks, and request cancellation.
The first chat POST establishes the session. Public metadata GETs remain authenticated
and rate-limited but do not issue session cookies: a late capability response must
not replace the cookie that owns an immediately submitted run. Run IDs
are correlation IDs, not permission tokens or provider conversation identifiers.

## Foundry configuration and remaining service gates

The optional AI-led conversation front door uses `AI_CONVERSATION_ENABLED=true`
and a **distinct** `FOUNDRY_CONVERSATION_AGENT` binding. Export its definition
with `publish_agents --conversation-only --prefix <isolated-prefix>
--model-deployment <existing-approved-deployment>`. Publish only with the
existing approval/endpoint controls; `--subscription` pins the CLI credential
without changing global account state. Set `AZURE_CLI_SUBSCRIPTION` for the same
local runtime pin. Production remains managed-identity-only.

This agent returns one typed proposal; the API validates and renders the next
turn. It can understand typos and ask an essential follow-up before any Search
request, while factual generation retains the original evidence checks.
Planner and answer stages share an aggregate budget and owned cancellation.
The live evaluation script in the root uses synthetic cases and fails on the
first error; CI runs offline protocol and browser fixtures.

Whole canonical answers to the current question bypass the planner and commit
through the same page/revision safeguards. In particular, the application's
own "Issued somewhere else" and "Planning a move" labels are authoritative
answers, not suggestions that a model or regex may discard. Non-B.C. licensing
gets a separate renewal-versus-exchange clarification. Public guardianship
and disability topic choices use internal bounded state and the existing
intent-question wire shape; no fictional records are activated.

### Local grounded evaluation

Version 6 uses separate pinned planner/writer bindings. With
`LOCAL_EVIDENCE_EVALUATION_ENABLED=true`, the API rejects production mode,
non-loopback hosts/origins, non-loopback request peers/listener addresses, and
forwarded requests. The web proxy validates its loopback configuration and
supplies `X-BC-Evaluation-Scope: local-noncommercial`; clients cannot turn the
source profile on themselves. Keep both services bound to loopback.

`local_evidence.py` has no arbitrary URL or crawl operation. Named CiviX reads
pin validated public DNS addresses to HTTPS while retaining certificate/host
verification, reject redirects and unsupported/compressed media, and cap
responses at 2 MB. Selected statutory sections retain their qualifiers and
publisher consolidation dates. Fee-table currency comes from its published
column heading. Neither a consolidation date nor a runtime check declares
personal eligibility or all provisions in force for a person.

Dated Canada.ca copies are separately identified as copies, with original
titles, authors, URLs, and acquisition dates. Their optional local manifest
must match a pinned SHA-256 digest and the exact named registry, and expires
after seven days. The local assumption is non-commercial evaluation only;
public/commercial reuse and original ICBC/PGT acquisition remain unapproved.
The existing project catalogue is identified as project preparation material,
not a fresh copy of the ICBC website.

The grounded writer only receives `read_programme_sources(topic)`. The server
owns programme selection, topic-to-query mapping, source scope, evidence
budgets, and registered navigation links. Other journeys keep their existing
general-agent/tool contract. A substantive core answer is buffered until
source validation succeeds. One output correction is permitted for an invalid
link or critical quotation; it reuses the same budget, exposes all usage for
accounting, and never replays rejected prose. Cancellation still closes the
owned native stream before state commit.

Set all of:

- `FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>`
- `FOUNDRY_AGENTS`: a JSON array of seven distinct managed-agent bindings, each
  containing `journeyId`, `name`, pinned `version` and `modelDeployment`
- `FOUNDRY_GENERAL_AGENT`: a separate JSON object containing `name`, pinned
  `version` and `modelDeployment`, with no journey scope
- `FOUNDRY_CONTEXTUAL_AGENT`: a distinct JSON object containing the pinned
  contextual-demo prompt-agent `name`, `version` and `modelDeployment`
- `AZURE_SEARCH_ENDPOINT=https://<service>.search.windows.net`
- `AZURE_SEARCH_INDEX=bc-pilot-public` with metadata mode/review disabled, or the
  reviewed v2 triple described below

Without the corresponding binding, factual AI requests return HTTP 503
`FOUNDRY_NOT_CONFIGURED` (legacy/pathway), `GENERAL_AGENT_NOT_CONFIGURED`, or
`CONTEXT_AGENT_NOT_CONFIGURED`;
all catalogue and guided routes continue to work. Version-2 greeting, thanks and
generic-help full matches produce application-authored dialogue without Search
or model calls. A social prefix attached to a factual question never short-circuits.
Incomplete or failed service verification does not become a mock answer.

`APP_ENV=development` uses **AzureCliCredential**, requiring the operator's
existing Azure CLI login. `APP_ENV=production` uses **ManagedIdentityCredential**
only, optionally selected with `AZURE_CLIENT_ID`. There is no production
credential fallback, key-based authentication, or browser credential exposure.
Grant the identity least-privilege Foundry invocation/definition-read permissions,
Search Index Data Reader, and optionally Cognitive Services OpenAI User for the
approved embedding deployment. This application does not grant permissions.
The development CLI timeout defaults to 15 seconds and can be set within 5--30
using `AZURE_CLI_PROCESS_TIMEOUT_SECONDS`. Only the development credential-unavailable
plus timeout exception chain becomes `LOCAL_CREDENTIAL_TIMEOUT`; provider bodies
and token diagnostics are not returned.

Each managed agent must have its exact scoped policy and function declarations.
The seven pathway agents can search approved sources and build preparation plans;
the separate contextual agent has only consented-context read, deterministic rule,
review-only preview and source-retrieval tools. To export the pathway definitions
without authentication or network requests:

Contextual runs also use a separate value-free audit trail. Local preview keeps
bounded events in process; shared deployments use the existing Redis control
plane with the same ordering, idempotency and session-aligned expiry rules.
`SYNTHETIC_CONTEXT_AUDIT_MAX_EVENTS` and
`SYNTHETIC_CONTEXT_AUDIT_MAX_BYTES` bound each session. Audit records contain
only opaque references, consent scopes, actor/tool names, pinned versions and
outcomes; context values, preview values, prompts, tokens and downstream
payloads are not stored.

```powershell
apps\api\.venv\Scripts\python.exe -m bc_api.publish_agents --model-deployment <reviewed-deployment-name>
```

Add `--general-only` to export only the separate general definition. Its scoped
publication emits `FOUNDRY_GENERAL_AGENT` rather than replacing `FOUNDRY_AGENTS`.
Add `--contextual-only` to export the separate versioned contextual definition;
it emits `FOUNDRY_CONTEXTUAL_AGENT`. Export is review-only unless the explicit
`--publish --approved --project-endpoint` controls are also supplied.

After the target, model, permissions and bundle are reviewed, adding `--publish
--approved --project-endpoint <approved-project-endpoint>` creates immutable
versions using the operator's Azure CLI identity. It emits the actual
`FOUNDRY_AGENTS` value; copy that array into the deployment configuration rather
than guessing version numbers. Partial failures report created names/versions
and do not delete them or silently retry publication.

The export command does **not** publish anything. The API reads `agents.get_version`
and compares the name/version, active prompt kind, stored instructions, function
names, parameter schemas, descriptions, and strictness. Hosted tools, remote
skills, mismatched schemas and unapproved extra tools fail closed. Passing a
local callable is not represented as registering a remote tool.

Definitions are checked independently: `/api/capabilities` includes `journeys`,
`generalChatConfigured`, `retrievalReady` and `requestVersions`. A verified general
agent does not imply a complete or available corpus. Version-2 requests return
SSE activity before readiness/authentication completes; metadata warming never
blocks application startup. Legacy routing uses current intent before prior
context and can return `JOURNEY_REQUIRED`. Explicit version-2 pathway selection
is preserved until the person changes or clears it.
The old `FOUNDRY_AGENT_NAME`/`FOUNDRY_AGENT_VERSION` pair is development-only
compatibility, not a production deployment registry.

Native integration uses installed `agent_framework_foundry.FoundryAgent` 1.15.0,
`agent_framework_ag_ui.AgentFrameworkAgent` 1.6.0, framework core 1.22.0,
`azure-ai-projects` 2.7.0 and `ag-ui-protocol` 0.1.22. The package combination was
selected from compatible published releases actually available in the package
registry, rather than guessing APIs from older examples.

**Each environment requires verified identity and evidence:** real agent/model
bindings, approved indexed documents, source-owner review, live evaluation and
end-to-end ingress/SSE verification. The currently deployed pilot has a general binding,
five pathway bindings; the next release adds road-test and PharmaCare bindings,
and four explicitly approved snapshots; public cited answers, follow-ups,
terminal cancellation and no-source abstention have been exercised. This does
not approve the remaining source sample or certify every possible answer.
An empty index cannot produce factual model answers.
An index that has not yet been published returns the same `SOURCES_UNAVAILABLE`
code for pathway requests, rather than being misreported as an agent-binding
failure. General chat can return a clearly labelled application handoff instead.
Neither case enables unsourced model facts or reports retrieval readiness.

## Retrieval and answer safety

- Reads the ingestion contract: `id`, `documentId`, `sourceId`, `title`,
  `publisher`, `url`, `content`, `section`, `checkedAt`, `publisherUpdatedAt`,
  `status`, `journeyIds`, `documentVersion`; ingestion also retains `topics` and
  `contentHash`.
- Filters `status eq 'active'`, registered available/limited sources, and a
  validated journey where applicable. Retired, unknown, wrong-publisher,
  wrong-host, stale, future-dated and instruction-like records are rejected.
- Retrieves ten ranked candidates, removes duplicate chunks, then prefers new
  sources and documents before filling a final five-evidence budget. Selected
  evidence remains in original relevance order. Intact chunks are limited to
  8,000 characters; oversized chunks are rejected, not truncated across
  criteria/exceptions.
- `SEARCH_MAX_AGE_DAYS` defaults to 7 (maximum 30). Publisher update and check
  dates remain separate; unknown publisher dates remain null.
- V1 uses `AZURE_SEARCH_INDEX=bc-pilot-public`,
  `AZURE_SEARCH_METADATA_ENABLED=false` and
  `AZURE_SEARCH_METADATA_REVIEWED=0`. A future v2 API revision must switch all
  three settings together to `bc-pilot-public-v2`, `true` and `1`; startup and
  deployment preflight reject partial combinations. Metadata mode requires every
  selected provenance field and complete version-1 source, content, extraction,
  review and rights metadata. Missing, malformed or unreviewed metadata is
  withheld. Legacy approved rows remain readable only while metadata mode is off.
- BC Laws is excluded until metadata-aware retrieval is enabled. Statutory
  evidence needs a known in-force version, explicit nonhistorical status and an
  effective interval containing the B.C. calendar day. Intervals have an inclusive
  start and exclusive end; repeal also ends validity. Consolidation and check dates
  never stand in for effective dates. `tzdata` supplies portable Vancouver time.
  Historical, future and unknown-effective legal versions are not current answers.
- Default retrieval is **lexical**, not falsely labelled hybrid. Optional
  `AZURE_SEARCH_SEMANTIC_CONFIG=bc-public-guidance` enables the ingestion schema's
  semantic configuration.
- Real hybrid retrieval requires `AZURE_SEARCH_VECTOR_ENABLED=true`,
  `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, and explicit
  `AZURE_OPENAI_EMBEDDING_DIMENSIONS` matching the index (1–3072). It generates a
  real query embedding with the native OpenAI v1 API and Entra identity, then
  combines `search_text` with `VectorizedQuery(fields="contentVector")`. Missing,
  wrong-dimension, all-zero, or failed embeddings **do not** fall back silently.
  The approved index must actually contain the corresponding published vectors.

Initial retrieval is mandatory before factual model generation. Broad searches
use all eligible registered sources, not an inferred five-journey filter.
When a question explicitly names a known source area, a source/topic filter
keeps broad government pages from masquerading as evidence for that programme.
This does not select a journey or require a menu choice. A generic business or
fishing licence is not classified as an ICBC driver licence. Reviewed modern
multi-source tags remain usable; unversioned tags cannot override this filter.
Recognized short follow-ups can include bounded prior user context without an
extra rewriting model; a newly named topic does not inherit an earlier topic.
Identical search requests can reuse the per-run evidence bundle, never a shared
conversation cache. A native context provider
injects source data, not client instructions. Local function results are typed
`EvidenceBundle`, `GuidedPlan`, and `LocationsResponse` data. These functions
have per-run call/error budgets and perform no external writes.

For general-chat knowledge gaps, the API can return a deterministic limitation
and catalogue-verified official navigation without invoking the model. This is
not a source-backed answer or an assertion that the site was indexed. Provider,
authentication and timeout failures remain errors, not knowledge-gap fallbacks.
Generated source-free clarification is limited to the reviewed question templates
in `dialogue.py`; added factual content still requires evidence and citations.

Real retrieval status and keepalives stream immediately. Complete, self-contained
answer sections pass the same citation/critical-claim checks used at completion
and then stream while generation continues. Incomplete Markdown or late-only
citations remain held until verifiable. Already emitted text is not replayed at
completion; a later error leaves the validated partial answer explicitly incomplete.

`CUSTOM/status` carries `{version:1,phase,message}` using server-owned phase
labels, including real `Thinking...` and source lookup. `CUSTOM/bc.artifact`
carries a versioned canonical `preparation` or `locations` result checked against
the actual catalogue, not model-authored card text. Raw tool arguments/results,
transcript snapshots and hidden reasoning do not reach the browser.
`CUSTOM/annotations` retains exact page URLs and verified document/version/chunk
identity; conflicting content or versions are rejected. Numeric `CUSTOM/usage`
events are retained. Multiple supported chunks from one page remain distinct.
Server-only `CUSTOM/bc.response` precedes text and distinguishes `dialogue`,
`grounded` and `handoff`, with `application` or `model` origin. Native model events
cannot forge this metadata. Application dialogue stays subject to session
ownership, replay, rate, concurrency and cancellation controls, but does not
consume the model allowance.

Metadata-only timing distinguishes admission, readiness/authentication, retrieval,
model invocation, first model text, first response and first validated factual
content. A canned greeting or model clarification is never counted as faster
grounded model output. Raw questions, histories and tool contents are not logged.
Rejected planner responses log only allowlisted status/incomplete-reason labels,
function-call counts and fixed validation-rule labels. Unknown provider values
remain `unknown` or `unclassified`; proposals, arguments and input values are
never diagnostic payloads.

Unknown citations, unsafe links/HTML, unvalidated generated state, unsupported
transaction claims, missing citations, and unverified critical fee/deadline/
eligibility assertions fail closed. Monetary amounts, payment terms/obligations
(including waived or free service claims), rates, deadlines and eligibility
requirements need complete matching quotation units. A cited expense-category
description such as "dispensing fees" is not by itself a fee amount or a personal
coverage decision. Matching tolerates extraction whitespace before punctuation,
but preserves inline-link words and rejects truncated amounts, signs and
qualifications. This conservative deterministic gate is **not** a proof
of semantic correctness: domain-reviewed evaluation is still a release gate.

## Local and public-preview controls

- `API_ALLOWED_ORIGINS`: comma-separated exact web origins. Development defaults
  to `http://localhost:3000,http://127.0.0.1:3000`. Production has **no** default
  origins and requires explicit HTTPS origins. Mutating requests require an
  allowed `Origin`; there is no wildcard CORS or arbitrary forwarded-host trust.
- `API_ALLOWED_HOSTS`: comma-separated API hostnames, default
  `localhost,127.0.0.1,::1,api`. Add the actual trusted container/ingress hostname
  before any future deployment.
- Defaults: 64 KiB request bodies (including chunked requests), 24 messages,
  4,000 characters/message, 16,000 characters/conversation, four concurrent runs,
  one run/session, 60 seconds/run and 15 seconds/upstream operation.
- Limits are configurable through the corresponding `API_MAX_*`,
  `API_RUN_TIMEOUT_SECONDS`, and `API_UPSTREAM_TIMEOUT_SECONDS` settings in
  `config.py`. Safety upper bounds remain enforced.
- Per direct peer IP: 180 requests/minute, eight AI requests/minute and 60
  cancellation requests/minute. `X-Forwarded-For` is not trusted. A local web
  proxy therefore shares a preview budget across its visitors.
- At most 1,000 anonymous sessions (one-hour inactivity expiry), 2,048 recent
  run records (ten-minute replay protection), and 4,096 rate buckets.
- Local development uses **one process and one replica** with in-memory state.
  Public deployments require Redis-backed sessions, atomic reservations/rate
  limits, replay protection and cross-replica cancellation. Store failure stops
  model work; there is no memory fallback in production. Redis contains opaque
  ownership/counter/expiry data, not conversation, source or tool bodies.
- Production requires `REDIS_ENDPOINT`, optional `REDIS_CLIENT_ID`,
  `API_AUTH_TENANT_ID`, `API_AUTH_AUDIENCE`, JSON `API_AUTH_CALLERS`, and positive
  `API_DAILY_RUN_LIMIT`, `API_DAILY_TOKEN_LIMIT`, `API_DAILY_COST_LIMIT_MICROUSD`
  and `API_TOKEN_PRICE_MICROUSD`. The callers are allowed service-principal
  **object IDs**, not client IDs. Missing controls deny `/api/*`; `/healthz`
  remains a liveness check, not a public-readiness assertion.
- Web-to-API requests use managed identity and a tenant-bound, audience-checked
  RS256 token. The separate internal API Entra application must expose the
  expected `api://<application-client-id>` identifier and issue v2 access tokens
  with that client ID as audience. IaC does not create that registration.
- The web service uses `API_AUTH_SCOPE`, `AZURE_CLIENT_ID`, `FRONT_DOOR_ID` and a
  secret `CLIENT_HASH_KEY`. It replaces caller-controlled identity headers,
  verifies Front Door context and hashes **`X-Azure-SocketIP`**, not the
  user-overwritable `X-Azure-ClientIP`/`X-Forwarded-For`. This requires the private
  origin boundary; a header alone is not proof of trusted ingress.
- Admission reserves conservative per-run token/estimated-cost allowances
  before inference, with UTC-day accounting. Completed runs with verified usage
  may refund unused reservations. Source/preflight failures release token and
  cost reservations only when the runtime proves model work never started;
  the run count still applies. Failed, cancelled or unknown-usage runs that
  might have reached a model retain their reservations, including uncertain
  embedding work. Model middleware also bounds calls, serialized input and output tokens.
  These controls are not an Azure invoice guarantee: model prices, service charges
  and billing monitoring still need operator review.
- Run iterators stay in one producer task, preserving native SDK context
  variables. The API retains the native `ResponseStream` and closes it in that
  same task even when AG-UI is paused at a yielded event. Cancellation and
  disconnection close the real native HTTP stream, not just the browser
  subscription. Cleanup is shielded from ASGI disconnect cancellation so Redis
  finalization and terminal cancellation status are not interrupted. The HTTP
  response explicitly closes its iterator on both disconnect protocols instead
  of waiting for garbage collection; disconnecting before the first event also
  releases a proven unused reservation. Native
  cleanup has a five-second deadline; timeout/failure is logged without provider
  details and does not refund uncertain model work. Tool and run limits are not
  delegated to the model.

Provider/prompt/tool-body and access-query logging are disabled. Explicit
metadata-only telemetry records generated trace references, outcome, timing and
numeric usage. Azure metric export requires `API_METRICS_ENABLED=true`, the
connection string and managed-identity monitoring permissions. There is no
automatic HTTP/prompt/tool-body instrumentation. Requests use `store=False` and no provider conversations, but
this is **not** a promise about provider operational retention or approved
residency. A basic identifier detector is an extra safeguard, not a PIA or a
general-purpose personal-data guarantee.

## Optional per-answer research

Both providers remain disabled by default. Ordinary `/api/agent` requests use
the existing direct Search pipeline; versions 1-6 keep their existing contracts,
and the legacy `researchRequested` flag still cannot enable research.

When a provider is separately approved and configured, completed eligible
answers carry a `bc.research.offer` with a parent run/message, public topics,
available actions and expiry. The descriptor is recorded during existing run
finalization; ordinary chat adds no IQ call, planning call or capability probe.
`POST /api/research` accepts only version 1, action (`corpus-explore` or
`web-check`), run/thread/parent identifiers and an enumerated geography.
`x-bc-research-page` binds it to the originating page. Session ownership, source
scope and expiry are checked before admission and each subsequent provider step.
It returns separate `bc.research.progress` and `bc.research.result` SSE events.
It never changes conversation facts, task progress or the original answer.

The existing cancellation endpoint owns optional runs too. `DELETE /api/research`
revokes the current page's offers; the browser rotates that page binding on
Start over. Normal Send does not await research unless an optional run must first
be cancelled. Supplements stay in tab memory and never enter `historyForAgent`.
Synthetic context and local non-commercial evidence mode do not use these paths.

### Foundry IQ preview

`foundry_iq.py` pins `2026-08-01-preview`, `low` single-pass planning and
`extractiveData`. The live preview contract requires `maxOutputSize`; it rejects
the GA-style `maxOutputSizeInTokens` argument. Requests bound extractive output
with `maxOutputSize=8192` (the service rejects values at or below 5000) and
runtime; the client bounds response bytes/references and retains at most
five validated evidence items without relying on a server-side document-cap
argument. It reads back the selected knowledge-base/source definitions
and verifies the existing index, source data fields and approved planning model.
Returned activity must preserve the application's source/rights/legal filter;
references pass the same evidence-row validation used by direct Search.
Additional knowledge sources, Web sources, answer synthesis, partial responses,
missing source identity and unexpected planning are not accepted.

Configure `FOUNDRY_IQ_KNOWLEDGE_BASE`, `FOUNDRY_IQ_KNOWLEDGE_SOURCE`,
`FOUNDRY_IQ_MODEL_DEPLOYMENT`, `FOUNDRY_IQ_MODEL_NAME`, the existing Search and
OpenAI endpoints, and real `FOUNDRY_IQ_PREVIEW_APPROVAL_ID`,
`FOUNDRY_IQ_CONTRACT_APPROVAL_ID` and `FOUNDRY_IQ_BUDGET_APPROVAL_ID`.
Do not grant the API write privileges just to make readback pass: verify the
least-privilege metadata-read/retrieval authorization before release.
The Search identity separately needs approved planning-model inference access
and network reachability. Agentic retrieval billing is a distinct service
setting, not implied by semantic ranker billing.

`python -m bc_api.export_research` exports review-only knowledge definitions
and the isolated answer-agent definition, without network or resource changes.
`python -m bc_api.publish_agents --research-only --model-deployment <approved-name>`
exports the answer agent alone. Actual publication retains the existing
`--publish --approved --project-endpoint` approval requirement.
Pin its returned `FOUNDRY_RESEARCH_AGENT` binding; never repoint the normal agents.

### Web IQ

`webiq.py` only calls `https://api.microsoft.ai/v3` with Entra scope
`https://api.microsoft.ai/.default` and the selected AppID. It accepts public
topics and coarse municipalities, never a transcript, free-form search or
address. Search uses bounded passages and post-filters results against reviewed
source IDs and exact host/path prefixes. `WEBIQ_SOURCES` is a JSON array with
`sourceId`, `urlPrefix`, and `quoteLimit` (at most 200); source catalogue status,
publisher identity and the narrower research-host allowlist must also agree.
Listing a source or a link never grants acquisition rights.

Existing AppID, privacy, terms, egress, logging-review and transient-handling
gates remain mandatory. Logging review accepts either Microsoft-approved Zero
Query Logging (`WEBIQ_ZERO_QUERY_LOGGING_APPROVED`) or explicit owner acceptance
of default logging for fixed public topics (`WEBIQ_PUBLIC_QUERY_LOGGING_APPROVED`).
Both default false; neither permits personal details, free-text queries or
transcripts. Owner acceptance must never be recorded as Microsoft ZQL approval.
Additionally record `WEBIQ_RELEASE_APPROVAL_ID`,
`WEBIQ_SOURCE_APPROVAL_ID` and the source permissions. For a known approved
handoff URL, Browse is used only when
`WEBIQ_BROWSE_SOURCE_IDENTITY_APPROVED=true`; otherwise Search is used.
The app cannot inspect the redirect chain followed inside Web IQ. Do not approve
Browse without verifying the service's source-identity contract. Returned Browse
URLs must match the requested page. No direct-fetch or other-provider workaround
exists.

Browse passage requests include a public query. A `202` contains no evidence;
its `retryAfter` is an absolute timestamp, with at most one bounded retry for
that page. A fallback crawl is not a guarantee of a fresh fetch. Retrieval,
crawl and publisher dates are separate; an absent timezone/date stays unknown.

Web results have distinct, non-reviewed provenance: no invented document
versions or review hashes. Raw passages exist only during the logical research
request and are excluded from shared state, caches, logging, evaluation goldens
and later prompts. The answer model uses `store=False`. Only the generated
supplement and displayed source links remain in tab memory, subject to executed
terms. The validator conservatively caps all displayed prose attributed to each
web source (including citation labels) at its approved excerpt allowance, not
just quoted substrings. Source-card labels come from the approved catalogue,
not copied provider titles.
Web IQ is not Foundry Responses web search or a Foundry IQ Web knowledge source.

### Admission, failure and release

Set `RESEARCH_DAILY_RUN_LIMIT` and independent
`FOUNDRY_IQ_PER_RUN_COST_MICROUSD` / `WEBIQ_PER_RUN_COST_MICROUSD` reservations and
their matching `*_DAILY_COST_LIMIT_MICROUSD` limits only after reviewing actual
billing and safe upper bounds. Zero keeps admission closed. These service-cost
reservations are additional to the normal answer-model allowance, included in
the shared aggregate cost cap, and not refunded after uncertain billable work.
Provider budgets and the optional concurrency lane are atomic across replicas.
`RESEARCH_MAX_CONCURRENT_RUNS` defaults to one; optional work leaves a normal-chat
concurrency slot available. A new session cannot reset daily allowances.

Each optional run has at most one IQ retrieval and one answer-generation call.
Web IQ permits at most three HTTP attempts, one Search, five results and
3,000 characters per passage. Response bytes, run time, prompt size and model
output are bounded. Cancellation closes owned tasks/transports. Partial evidence,
timeouts and budget/provider errors produce a supplement-local limitation, not
automatic retries across providers or replacement answers.

Operations record counts, outcomes, timing and separate provider-reported IQ
reasoning units/planning tokens, never queries or content. These units are not
answer tokens or a calculated invoice. No benchmark or live service approval
is established by the offline fixtures.

Release each provider independently: confirm access/terms/privacy/retention,
readback and networking; compare public, independently authored questions against
direct Search on the same corpus/model; check citation correctness, abstention,
complete cost and default-path latency under mixed traffic; then authorize a
canary. Require no more than a 5% default p95 regression in matched measurements.
Do not store actual Web IQ responses as test data. Keep a provider disabled when
benefit or a safe cost bound is unproven. Turning its enable flag off is the kill
switch; it does not change standard chat. Corpus growth, resident identities,
transactions, Work IQ and Fabric IQ remain out of scope.

## Live operational checks

The v1/v2 cutover validator is read-only: it only gets index definitions and
searches both indexes with the same query and OData filter. It verifies every
application-selected v2 field, field type, filter capability, semantic
configuration and returned rights/legal metadata. It never uploads, deletes or
changes index definitions. Review its zero-network plan at any time:

```powershell
apps\api\.venv\Scripts\python.exe scripts\compare-search-indexes.py
```

After reviewed content publication, use `--execute --endpoint
https://<service>.search.windows.net` and optionally `--require-match` and
`--output <report.json>`. The command exits nonzero while the v2 schema, metadata
or selected comparison cases are not ready. It does not switch production.

`data/evaluations/pilot-cases.json` contains five independently authored public
questions and human-review criteria, not harvested Web IQ content.

```powershell
# Review the run count only: no network or model calls.
apps\api\.venv\Scripts\python.exe -m bc_api.evaluate
```

Only after target/spending approval, add `--execute --approved --base-url
<reviewed-website-origin>` and optionally `--repetitions 1` through `10`.
The command checks the same website/cookie/SSE path, runs sequentially without
automatic retries and reports first validated content/completion p50/p95,
protocol outcomes, citation counts and reported usage. Missing usage stays
unknown. It does not save questions, answer text or source URLs in its report.
Domain review is always required: a protocol pass is not grounding/eligibility
correctness, a load test, or permission for public release. Do not enable Web IQ
or send personal/resident records to make this check pass.

## Verification

From the repository root:

```powershell
$env:TEMP = Join-Path (Get-Location) 'apps\api\.build'
$env:TMP = $env:TEMP
apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests --basetemp=apps\api\.build\pytest
apps\api\.venv\Scripts\python.exe -m ruff check apps\api\src apps\api\tests
apps\api\.venv\Scripts\python.exe -m ruff format --check apps\api\src apps\api\tests
apps\api\.venv\Scripts\python.exe -m compileall -q apps\api\src
apps\api\.venv\Scripts\python.exe -m pip check
```

Tests include synthetic fixtures and explicit offline transports, never fake
production callbacks. `test_native_transport.py` exercises the installed native
Azure definition/Search clients, Foundry/OpenAI Responses stream, local function
dispatch, AG-UI annotations/usage, failure redaction, cancellation, disconnection,
and timeout cleanup. `test_embeddings.py` exercises the native embedding HTTP
wire contract, Entra scope and vector validation. No Azure or Web IQ calls occur.

The Dockerfile uses the **repository root** build context, copies the shared
catalogue to `/app/data`, and runs as a non-root user. The Linux amd64 API image
has been built and exercised: real catalogue delivery, disconnected capability
status, production fail-closed controls and absence of the temporary package
mirror secret were verified. The optional `pip_config` BuildKit secret supports
an operator-approved package mirror without embedding its configuration.

The web image also builds for Linux amd64 and works with the packaged API over
HTTP. JavaScript compilation runs on the build host's native architecture, while
production dependencies are installed separately for the target architecture.
The amd64 runtime loads the identity SDK and native image-processing addon;
an ARM64 image is not substituted for the Azure target.

Official API references checked during implementation:

- [Foundry Agent Service integration](https://learn.microsoft.com/agent-framework/integrations/by-component/agent-services/foundry)
- [Agent Framework AG-UI and annotations](https://learn.microsoft.com/agent-framework/integrations/ag-ui/)
- [Azure OpenAI v1 embeddings](https://learn.microsoft.com/azure/foundry/openai/how-to/embeddings)
- [Azure AI Search Python SDK](https://learn.microsoft.com/python/api/overview/azure/search-documents-readme)
