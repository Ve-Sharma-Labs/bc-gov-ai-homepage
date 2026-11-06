# Pilot implementation contract

This contract defines the application interfaces of the accepted specification.
It does not expand the pilot's transaction authority or source permissions.
The [as-built architecture](architecture.md) describes the deployed resources,
trust boundaries and end-to-end flows; this document remains the interface contract.

## Ownership and runtime

- Web: `apps/web`, Next.js/React/TypeScript; local port 3000 (overridable).
- API: `apps/api`, Python/FastAPI; local port 8000 (overridable).
- Ingestion: `ingestion`, its own Python package and tests.
- Shared public catalogue: `data/pilot-catalog.json`, content worker-owned.
- Root tooling/infrastructure/documentation: coordinator-owned.
- Each component owns its dependencies and tests; no shared package-manager
  installs at the repository root from parallel workers.

The web app calls same-origin `/api/*`. Its server-only `API_BASE_URL` points to
the Python API. It forwards only explicitly supported API paths/methods and
preserves streaming, cancellation, session cookies, and error status.
The web proxy allows up to 45 seconds for capability discovery, which may need
local CLI credential priming followed by several live agent/source metadata
checks. Other metadata reads remain bounded at 15 seconds and agent streams at
180 seconds. This does not delay sending a chat request behind readiness.

## Public catalogue

JSON uses camelCase. Unknown dates are null; no invented fees or criteria.

Top level:

- `schemaVersion`: 1
- `asOf`: ISO date or date-time describing this curated snapshot
- `sources`: Source[]
- `journeys`: Journey[]
- `locations`: Location[]

Source:

- `id`, `title`, `publisher`, `url`, `description`: strings
- `checkedAt`, `publisherUpdatedAt`: ISO date/date-time or null
- `status`: `available`, `limited`, `pending`, or `blocked`
- `topics`: string[]

Journey:

- `id`: `licence-renewal`, `road-test-booking`, `rental-assistance`,
  `health-coverage`, `pharmacare-registration`, `primary-care`, or `service-bc`
- `title`, `prompt`, `summary`, `category`, `notice`: strings
- `sourceIds`: string[]
- `steps`: objects with `id`, `title`, `description`, `sourceIds`
- `handoffs`: objects with `label`, `url`, `description`, `sourceIds`

Location:

- `id`, `name`, `municipality`, `address`, `hours`: strings
- `services`, `excludedServices`, `sourceIds`: string[]
- `checkedAt`: ISO date/date-time or null

Only explicitly supported services populate `services`. Missing knowledge is
not proof of availability. Exclusions override inclusions. Prefer service keys
`icbc-licensing`, `income-assistance`, `bc-services-card`, and `bceid` where
the source supports them. Coverage must be labelled as a curated snapshot.

All source references must resolve. Official handoff URLs can link to an agency
portal but must never be automatically submitted or represented as completed.
Data contains concise original summaries and citations, not copied full websites.
Raw fetched documents belong in ignored generated directories.

## API

- `GET /healthz`: `{"status":"ok"}`.
- `GET /api/catalog`: the validated public catalogue.
- `GET /api/journeys/{id}`: one Journey; unknown IDs return 404.
- `GET /api/locations?service=...&municipality=...`: `{"locations": Location[]}`.
- `GET /api/capabilities`: `{"mode":"guided"|"foundry",
  "aiConfigured":boolean,"webIqEnabled":boolean,
  "transactionsEnabled":false,"message":string,"journeys":{journeyId:boolean},
  "requestVersions":[1,2,3],"syntheticContextAvailable":boolean,
  "realIdentityIntegrated":false,"realCitizenIdentityConfigured":false}`.
  Older responses without the optional capability additions remain readable by
  the web client.
- `GET /api/demo/personas`: when explicitly enabled, returns only the fixed
  public synthetic persona summaries. It does not create an anonymous or
  context session and never returns fixture facts.
- `POST /api/demo/session`: accepts exactly `{"personaId": DemoPersonaId}` and
  creates or replaces a bounded HttpOnly synthetic-context cookie. Persona
  facts, consent receipts and arbitrary context fields are rejected. The web
  client also sends a random `X-BC-Context-Page` value held only in page memory;
  the server binds the grant to that page instance.
- `DELETE /api/demo/session`: idempotently clears the synthetic persona,
  consent metadata and contextual server state, invokes derived-state
  invalidation hooks, and expires the synthetic-context cookie. Reload and
  `Start over` use this route.
- `POST /api/context/consents`: accepts
  `{"action":"grant"|"revoke","scopes": ConsentScope[]}`. The server chooses the
  active persona's allowlisted purpose, rejects scopes outside that flow's exact
  required/optional contract, and returns a strict replacement or revoked
  `ConsentReceipt`.
- `GET /api/context/summary`: returns a redacted `ContextSummary` containing
  only categories covered by the current, unexpired receipt.
- `GET /api/discovery`: when discovery is enabled, returns the current page's
  `DiscoverySummary` or null. No query parameters or client profile are accepted.
- `DELETE /api/discovery`: invalidates that page's discovery state, cancels local
  in-flight discovery runs, and prevents a late commit from recreating it.
- `POST /api/agent`: standard AG-UI RunAgentInput and SSE output when Foundry is
  actually configured. If not configured, return 503 with the error below;
  never fake a streamed model answer.
- `POST /api/runs/{runId}/cancel`: cancel a run only for its originating session.

Error shape: `{"error":{"code":"CODE","message":"Safe user-facing message"}}`.
Do not include credentials, prompts, traces, or sensitive provider bodies.
Handle malformed input, excessive size, unsupported roles, unknown services,
unavailable content, timeouts, and upstream failures explicitly.

Environment contract:

- `APP_ENV=development|production`
- `API_BASE_URL` (web only; default loopback for local development)
- `CONTENT_CATALOG_PATH` (optional override; otherwise repository data catalogue)
- `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_AGENTS` (seven pinned
  `journeyId`/`name`/`version`/`modelDeployment` bindings; single-agent settings
  are development-only compatibility)
- `AZURE_CLIENT_ID` (optional user-assigned managed identity)
- `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_INDEX`
- `FOUNDRY_GENERAL_AGENT` (separate pinned general name/version/model, no journey)
- `FOUNDRY_CONTEXTUAL_AGENT` (separate pinned contextual-demo
  name/version/model, no journey)
- `SYNTHETIC_CONTEXT_ENABLED=false` by default. Enabling it exposes only the
  fixed synthetic session, consent and contextual runtime; it does not configure
  real identity and still requires the separate contextual binding plus reviewed
  source retrieval before version-3 agent runs can start.
- `SYNTHETIC_CONTEXT_SESSION_TTL_SECONDS` and
  `SYNTHETIC_CONTEXT_CONSENT_TTL_SECONDS`; consent must not outlive the bounded
  server session.
- `CONVERSATION_DISCOVERY_ENABLED=false` by default; advertises request version 4
  and `discoveryAvailable:true` only when enabled.
- `CONVERSATION_CONTEXT_TTL_SECONDS` (60-3600; default 1800), with bounded
  page-owned memory/Redis state. This is a fixed expiry, not a permanent profile.
- `CONVERSATION_DISCOVERY_PRIVACY_REVIEWED=false` by default. Production startup
  refuses enabled discovery without this separate review acknowledgment.
- V1 keeps `AZURE_SEARCH_INDEX=bc-pilot-public`,
  `AZURE_SEARCH_METADATA_ENABLED=false`, `AZURE_SEARCH_METADATA_REVIEWED=0`.
  The future v2 revision must atomically set `bc-pilot-public-v2`, `true`, `1`;
  partial combinations fail startup and deployment preflight.
- `WEBIQ_ENABLED=false`, plus separate approval/configuration requirements
- `APPLICATIONINSIGHTS_CONNECTION_STRING` (optional, no payload logging)
- Production: Redis shared controls, tenant/audience/caller identity settings
  and positive daily run/token/estimated-cost allowances; see the
  [API configuration contract](../apps/api/README.md)

Guided mode means an honestly labelled, deterministic source-backed preparation
plan selected from the catalogue, not artificial intelligence. It must remain
useful when the model is unconfigured. Free-form AI chat clearly explains the
connection requirement and preserves the person's draft on failure.

## Shared verification

The seven journey IDs, source references, date fields, and error shape are contract
tests. Unit tests may use explicitly identified fixtures and mocked providers;
the shipped application must not present fixture/model output as a live service.
The coordinator verifies real catalogue delivery, journey interaction, theme
switching, responsive layout, AI-unconfigured behavior, and native integration
imports before handoff.

## Implemented integration choices

The web client uses published `@ag-ui/client` directly with BC React components,
rather than an additional CopilotKit runtime. The API wraps the native Foundry
and Agent Framework AG-UI adapters; neither side simulates a live model.

Node 24 and Python 3.14 are the verified runtime combination. Catalogue plans
work without Azure; AI requires both the approved agent definition and a
nonempty reviewed index. Web IQ is planned but has no enabled HTTP transport.

`API_ALLOWED_ORIGINS` and `API_ALLOWED_HOSTS` are the API's actual connection
settings. Development run and synthetic-context metadata are opaque and
process-local unless Redis is configured. Synthetic facts are always reloaded
from the reviewed repository fixture and are never copied into session state.
Root run tooling sets origins to the selected loopback web port. No session
signing-secret setting is used. Public Azure configuration instead requires
Redis shared controls and managed-identity service authentication; context
metadata uses the same replica-safe control plane and there is no silent
local-state fallback. The web proxy verifies private Front Door context, uses
the socket-IP header for an opaque rate identity and replaces untrusted
forwarded identity headers.

The redesigned web client now owns draft, selected journey, checklist and
conversation/run state in a shared client provider. Internal route navigation
retains that tab-memory state; reload/Start over clear it. The theme remains the
only browser-storage preference. A single adaptive composer appears at a page
anchor or in the viewport dock; it never creates a second interactive input or
changes the API's message, source, cancellation or authority contracts.

## Expanded chat and incremental output

A valid homepage question navigates immediately to `/chat`, without waiting for
capability discovery, SDK import or inference. Missing AI, rate limits and
errors keep the question visible with explicit recovery. Chat uses the same
provider/run/composer, a compact BC header and a bottom-pinned follow-up input.
Guided plans remain separately labelled and usable. The normal and compact
footers include the requested BC/GitHub attribution.

`forwardedProps` accepts only an optional `bc` object with `version:1`, a
supported `journeyId` and a strict boolean `researchRequested`. These are hints
and an opt-in request, never model/tool overrides or evidence of Web IQ approval.
Unsupported ambiguous intent receives `JOURNEY_REQUIRED` for explicit topic
selection.

### Version 2 conversation scope

The general-chat contract adds explicit `forwardedProps.bc` version 2 options:
`mode: "general"` carries no journey scope; `mode: "pathway"` requires a supported
`journeyId`. Version 1 remains accepted with its existing shape. Mixing a general
mode with a retained journey is rejected rather than silently narrowing chat.
These remain routing hints, not authority to change sources, tools or policy.

The separate `FOUNDRY_GENERAL_AGENT` setting pins a general agent's name, version
and model deployment without changing the five-journey registry. Configuration,
verified general readiness and retrieval readiness are distinct. Capabilities
can report `generalChatConfigured`, `retrievalReady` and `requestVersions`; older
clients can ignore the added fields. This contract does not imply that a new
general binding has already been published to an environment.

Server-owned `CUSTOM/bc.response` metadata carries version 1, a response kind
(`dialogue`, `grounded` or `handoff`) and origin (`application` or `model`).
It allows the UI to distinguish genuine dialogue and deterministic navigation
from sourced model answers. Clients cannot select these fields, and native model
events cannot declare this metadata to bypass output validation.

Modern source references can carry a nested `metadata` object with version 1,
`sourceIds`, `documentType`, `language`, `contentHash`, `extractionHash`,
`reviewHash`, `rightsReviewId`, `rightsHash`, `legalStatus`, `effectiveFrom`,
`effectiveTo`, `consolidationDate`, `repealedAt`, `legalSectionId` and
`isHistorical`. Unknown optional values remain null. This is provenance, not a
client-selectable authority grant. Current legal retrieval requires a verified
in-force interval; the B.C. calendar date is not inferred from UTC midnight.

The wire additions retain standard AG-UI SSE:

- `CUSTOM/status`: version 1, server-owned phase and safe message. No invented
  progress or hidden chain of thought.
- `CUSTOM/bc.artifact`: version 1, stable ID, `preparation` or `locations`,
  canonical catalogue data and actual cited sources.
- `CUSTOM/annotations`: original page title/URL plus available
  document/version/chunk identity and distinct check/publisher timestamps.

Complete self-contained sections pass the final validator before emission.
Unfinished links or unverified citations remain buffered; completion does not
replay committed text. Failure/cancellation never emits `RUN_FINISHED`, and the
client labels a partial answer as incomplete. Raw tool payloads, hidden reasoning
and generated state are withheld. API-owned safety checks remain necessary but
are not proof of semantic correctness; independently reviewed live evaluation
is required before public release.

The HTTP response explicitly owns and closes the streaming iterator on normal
completion or disconnection. Native SDK iteration stays in one producer task;
ASGI-shielded cleanup persists the shared terminal outcome rather than depending
on garbage collection. The authenticated cancellation endpoint is session-bound
and works across replicas. A 202 acknowledgement is not itself proof of terminal
cancellation.

### Version 3 synthetic context contract

The citizen-context demo uses
`forwardedProps.bc: {"version":3,"mode":"contextual-demo"}`. Version 3 accepts no
journey ID, facts, persona record, consent receipt, state, tool definition or
research request. Persona and consent state are bound to the opaque anonymous
session, the synthetic-context cookie, and the in-memory
`X-BC-Context-Page` value. A reload creates a different page value, so the old
grant is unusable even if best-effort unload cleanup has not completed. The
repository stores only the fixed persona ID, consent scopes and receipt
metadata, revision and bounded expiry; facts are reloaded by allowlisted persona
ID. `/api/agent` routes version 3 only after the feature flag, active persona,
purpose-bound minimum consent, distinct `FOUNDRY_CONTEXTUAL_AGENT`, reviewed
source scope and rule versions validate. Any missing or changed authority fails
closed; version 3 never falls through to an anonymous, general or pathway
agent.

Shared Python/Pydantic and TypeScript/Zod contracts now define:

- The three opaque demo persona IDs, redacted summaries and six context
  categories.
- Scalar context facts with category-bound consent scopes, synthetic or citizen
  provenance, verification time, sensitivity and correction metadata.
- Purpose-bound consent proposals, short-lived receipts and scoped revocations.
- Program screening results with the four approved statuses, rule versions,
  policy dates, matching source versions and disjoint satisfied, missing and
  disqualifying fact lists.
- Review-only application previews whose field provenance is explicit and whose
  `submissionEnabled:false` and `requiresHumanReview:true` values are literals.
- Value-free context summaries, consent requests and audit receipts.

The AG-UI contract keeps the existing `version`, stable `id` and `kind`
envelope and adds strict `context-summary`, `program-matches`,
`application-preview`, `consent-request` and `audit-receipt` payloads. Artifact,
fact, field, program, source and audit-event identifiers are bounded and unique
within their collections. The existing preparation and location artifacts are
unchanged. The API builds these five artifacts deterministically, validates their
exact order and content, buffers contextual model text until final revalidation,
and emits them only as server-owned `CUSTOM/bc.artifact` events. A client that has
not yet merged renderers may ignore the known events; API contract tests remain
the authority for their wire shapes.

The distinct contextual prompt agent exposes only
`read_consented_context(scopes)`, `evaluate_program_rules(flow_id)`,
`build_application_preview(flow_id)` and source-scoped
`search_approved_sources()`. Its query is derived only from the allowlisted flow
and reviewed source titles; neither the model nor context values enter Search.
Persona, facts, rules, source IDs and consent
receipts are derived from server state. There is no submit, sign, pay, book or
confirmation tool or route. Revocation or persona replacement cancels a local
in-flight run and every tool plus final artifact emission revalidates the
session, consent, rule set and reviewed source versions.

The version-3 admission categories are fixed server policy:

- `guardianship-intake`: household, disability/caregiving and existing-program
  scopes are required; region/preferences is optional.
- `disability-support`: identity/residency, employment, disability/caregiving,
  and existing-program scopes are required; region/preferences is optional.
- `job-loss`: identity/residency, household, employment, existing-program and
  region/preference scopes.

The web consent proposal must grant each flow's required scopes before sending
version 3; listed optional scopes may be deselected. Additional granted
categories remain unavailable to contextual tools unless they are part of the
fixed flow scope.

Capabilities distinguish contract support from deployment readiness:
`syntheticContextAvailable` reports only the fixed synthetic data path, while
`realIdentityIntegrated` and `realCitizenIdentityConfigured` are fixed to
`false` in this release. The synthetic capability becomes true only under
explicit server configuration with a valid fixture. Neither request version 3
nor a synthetic capability may be presented as evidence of BC Services Card,
government-record or other real identity integration.

Unused model reservations are released only when the runtime proves inference
did not begin; run-count limits still apply. Unknown/post-inference work remains
conservatively charged. The current index contains the limited four-snapshot
publication, not full coverage of every configured journey. A ready agent may
still return `SOURCES_UNAVAILABLE` for a particular question.

Azure AI Search is the default evidence path. Foundry IQ is an optional bounded
managed-retrieval comparison, Web IQ a separate disabled-until-approved public
research capability, and Work IQ/Fabric IQ are outside the anonymous pilot.

### Version 4 context-first discovery

Version 4 is an opt-in general-conversation contract. Versions 1-3 retain their
existing meaning. The initial `forwardedProps.bc` is:

```json
{
  "version": 4,
  "mode": "general",
  "discovery": { "action": "respond", "revision": 0 }
}
```

Subsequent replies send the last committed revision and the server's pending
`questionId`. Actions are `respond`, `skip`, `general`, `correct`, `remove`,
`explore`, or `refine`; only correction/removal may include an existing
`factKey`. A skip requires the active question ID. No journey scope, raw
profile, client-provided facts, consent receipt, tools, or research flag can be
combined with this mode. Explicit source questions may change topic without
turning the previous question's answer into evidence.

`X-BC-Discovery-Page` is a separate random, in-memory page binding. The API binds
it to the anonymous owner and validates the thread and state revision. Browser
reload and Start over rotate this binding; deletion closes old access even when
an earlier run has not yet committed. Redis uses atomic compare-and-set and
expiry. A repeated answer with the same original command can replay its last
application result without consuming another question. Stale/foreign questions
cannot silently populate a different field.

`CUSTOM/bc.discovery` contains a strict version-1 `DiscoverySummary`: thread,
revision, phase, reviewed goal ID/label, whether the discussion is about the
speaker or someone else, question count, allowlisted facts, pending question,
optional pathway suggestions, optional fictional-demo recommendation, and expiry.
Fact status is `provided`, `unknown`, `declined`, or `disputed`; only `provided`
has a value and its provenance is `citizen-answer`. A recommendation cannot
appear before the plan phase. Question IDs, schemas, permitted fields, and
copy are server-owned. Arbitrary uncited model prose cannot emit this event.

The frontend stages this update until `RUN_FINISHED`, rejects mismatched
thread/revision or duplicate updates, ignores late events after Stop/reset,
and exposes explicit refresh for conflicts. Inline edits, removal, skip, and
general guidance use narrow commands, not generated state. Retries preserve
the original command so a short answer is not reassigned to a new question.

The initial implementation uses reviewed question templates and bounded explicit
answer interpretation. It does not infer a person's sensitive attributes or use
a model to invent persona records. Warm acknowledgments and discovery are
application dialogue; supplied preparation artifacts are canonical catalogue
data, not generated eligibility decisions. Unsupported motorcycle rules receive
an ICBC handoff, not licence-renewal routing or invented numeric criteria.
Immigration-status questions are not enabled by this initial field allowlist.

All discovery turns are excluded from later version-2/pathway/demo histories.
The coordinator retains only allowlisted self-reports and canonical public intent,
not the raw transcript. Factual follow-ups use the existing pinned general
agent with public-intent-only input; Search and tool searches cannot receive
the stored personal answers. Non-factual discovery does not weaken the existing
exact-clarification or substantive-claim source gates. No new Foundry version,
source snapshot, identity integration, or public deployment is authorized here.

### Version 5 AI-led conversation

`AI_CONVERSATION_ENABLED` advertises request version 5 and
`conversationAvailable`. `conversationAgentReady` separately reports a
verified, isolated `FOUNDRY_CONVERSATION_AGENT` binding. Production startup
requires `AI_CONVERSATION_PRIVACY_REVIEWED` before enabling this mode.
Existing request versions and their disclosure/data-use boundaries remain
unchanged.

`retrievalReady` is independently determined by currently usable Search
evidence, not by an index document count or the presence of a pathway agent.
The optional, backward-compatible `sourceHealth` object reports `status`
(`unknown`, `ready`, `expiring`, `expired`, `empty`, `unusable`, `unavailable`),
`checkedAt`, `usableDocuments`, `expiredDocuments`, `rejectedChunks`,
`nextExpiryAt`, `coveredSourceIds`, `missingSourceIds`, and a nullable bounded
`errorCode`. Document counts deduplicate chunks by source, document, and version.
An expiry within one day is `expiring`; the seven-day default eligibility window
itself is unchanged. Coverage is not a promise that every question can be answered.

Source degradation must not disable the version-5 planner or catalogue
preparation. It also must not permit stale factual answers. An already-selected
task retains its progress when a detail requires an official handoff.
`TASK_ASSISTANCE_ENABLED` requires `AI_CONVERSATION_ENABLED`; production still
requires the separate actual privacy review and verified isolated binding.

The browser sends exactly one current user message and:

```json
{
  "version": 5,
  "mode": "general",
  "conversation": {
    "action": "respond",
    "revision": 0,
    "noticeVersion": "ai-conversation-v1",
    "shareContext": false
  }
}
```

`questionId` binds an answer/skip to a server-owned pending question. Other
actions are `general`, `correct`, `remove`, `explore`, and `sharing`; only
correction/removal may name an existing `factKey`. No browser profile, model
choice, generated tool, arbitrary source URL, or consent receipt is accepted.
`X-BC-Conversation-Page` is separate from both the version-4 discovery page
token and the fictional-persona context token.

The server decodes complete displayed labels, canonical values, and explicitly
allowed short replies against that pending question. These answers use an
application decision with no planner invocation; stale question IDs and
revisions still fail. A label must not depend on a separate regex to be accepted.
Longer or genuinely ambiguous text remains model-interpreted and validated.
Corrections use the named existing fact; a new service request is not consumed
as a substring match for the old question.

`GET /api/conversation` returns the active page's strict `ConversationSummary`
or null. `DELETE /api/conversation` invalidates the page state and prevents a
late request from recreating it. Neither route accepts query parameters.
Memory and Redis use the same typed, expiring compare-and-set repository with
an isolated namespace. Corrections, consent changes, and conflicts do not
automatically resend the user's message.

`CUSTOM/bc.conversation` carries the goal, phase, essential intent/context
question, explicit facts and subject, sharing choice, optional guide/demo
references, limitation kind, origin, revision, and expiry. The client stages it
until `RUN_FINISHED`, rejects mismatched/duplicate updates, and ignores late
events after cancellation. All v5 turns are excluded from legacy histories.
`bc.response.decisionOrigin` distinguishes AI decisions rendered with reviewed
wording from no-model application dialogue; the existing `origin` still names
the authority that produced the displayed text.

The licensing-route, guardianship-scope, and disability-kind follow-ups reuse
`kind:"intent"`, `factKey:null`, string `choices`, and an empty `candidates`
list. Their bounded answers and pending-question purpose are internal
`StoredConversation` state, not new public fact keys. The model may propose
`serviceAnswer:{key,value,status,quote}` only for the active goal with
current-message evidence; the application owns the final route. This changes
the pinned planner definition, not the version-5 browser response schema.
Unknown/skipped licence issuers never initialize a B.C. renewal task. An
outside-B.C. issuer asks renewal-versus-B.C.-licensing once, then provides the
appropriate reviewed navigation without inventing foreign requirements.

The planner can only call `propose_conversation_turn` with a strict schema.
It does not execute service actions. One shared model-call/input budget spans
planning and any subsequent evidence-backed generation. The API renders known
questions and canonical catalogue artifacts; it does not accept arbitrary
uncited planner text. A missing Search chunk does not hide a supported
preparation guide. Model/authentication errors remain errors.

Every current message is handled under the displayed AI notice; canonical
short answers and controls need no inference. Optional
personal-category retention/reuse requires `shareContext:true`, appropriate
purpose, and an explicit current-message quote. Numbers identifying a person,
credentials, documents, addresses, and medical histories are not requested.
Only canonical service intent is used for Search and embeddings. Turning sharing
off clears stored personal categories before later model input is assembled;
previous processing cannot be undone. Live testing uses synthetic data only.

### Task assistance and non-chat controls

`TASK_ASSISTANCE_ENABLED` advertises `taskAssistanceAvailable` in the existing
capabilities response. Version 5 clients that use this capability accept an
additive `CUSTOM/bc.task` version-1 snapshot alongside `bc.conversation`.
Older request formats and message-authority fields remain unchanged.

The snapshot contains the conversation thread/revision, stable task ID,
catalogue/step versions, current step, user-reported reviewed/skipped IDs,
explicit visit municipality where supplied, current guidance, and approved
source/handoff references. It is staged until terminal success. The frontend
retains the previous validated task/guide on a new run or interruption, and
replaces it only after an authoritative update. Task guides use stable IDs,
not an ID that changes with each chat run.

`POST /api/conversation/control` accepts a unique control ID, current revision,
notice version, and exactly one action:

- `sharing`: a boolean `shareContext`, without task/progress fields.
- `review`: server-owned `taskId`, `stepId`, and boolean `reviewed`.
- `next`, `back`, or `skip`: only the current task/step references.

The response is a strict conversation summary, task snapshot, and status
notice. It is not an SSE/model response and creates no chat messages. The same
ID/body is idempotent; a conflicting ID, stale revision, foreign task/page, or
expired state is rejected. Progress changes do not imply renewal, eligibility,
booking, or submission. `GET /api/conversation/task` refreshes both snapshots
without resending the person's message.

Sharing changes preserve non-personal progress and still-valid pending
questions. Turning sharing off removes personal facts before future model
input and invalidates affected personal questions without resetting the task.
These controls work without a model allowance. Their errors are shown with
explicit retry/refresh actions rather than a fake successful conversation.

Chat does not render mandatory answer widgets or checklists. The current
question and practical next action are ordinary messages; full guides,
progress, context, and sharing preferences live in optional Details. Closing
Details never clears state or disables the composer. Source links and essential
qualifications remain with the answer.

The four shared starter prompts only fill/focus the composer. Selection
does not invoke an agent, reset a task, enable sharing, or load a persona.
A draft is retained until explicit replacement. On Send, the normal
question/revision-bound request carries the full new message for intent
resolution. Browser fixtures cover both empty and active chat plus homepage
selection, keyboard focus, and draft protection.

The planner's task fields select continuation, explanation, repair, explicit
user-reported review, navigation, or full-guide display. Step IDs must belong to
the current task. Review requires a quote from the current message and positive
readiness, not negation, uncertainty, or a future intention. An explicit goal
change is required to leave an active task; greetings and repeated requests
cannot silently reset it. Current-step facts remain subject to the existing
source and privacy boundaries.

If a proposed structure fails schema validation, the runtime may make one
correction attempt using the same pinned agent and aggregate budget. It does
not retry indefinitely or bypass validation. Success-shaped progress is never
manufactured after failure.

### Version 6 grounded-conversation candidate

Version 6 is separately gated by `GROUNDED_CONVERSATION_ENABLED`, requires
AI conversation and task assistance, and has a separate production privacy
review flag. `/api/capabilities` advertises it only to a caller sending
`X-BC-Client-Version: 6`. Old clients receive the existing version list and
response shapes. The frontend pins version 5 or 6 for the page-owned thread;
refreshing capabilities does not silently migrate an active conversation.
The server rejects cross-version reuse of a page state.

The version-6 planner schema adds `programmeId`, `answerQuestion`, and
`answerTopics` while retaining the existing progress proposal. These are
server-validated model proposals, not browser-supplied state. A progress update
cannot change which question needs an answer. Bare acknowledgments of an
ambiguous question are not treated as explicit readiness. A review always
applies to the current step, even when the question's focus is another step.

Programme state refines a broad goal (for example job loss to EI) without
inventing an eligibility fact. It is internal server state; the current
`bc.conversation` summary remains compatible. Programme switches retire
obsolete questions and reset irrelevant topic context. Public queries come
from bounded programme/topic vocabulary, never raw personal context.
The grounded writer receives only `read_programme_sources(topic)`, with a
bounded topic enum and a server-owned programme. The server constructs the
public query and source scope; the model cannot supply raw query text, a URL,
or a programme override. Provincial plans and the small Service BC snapshot cannot be used as
an EI, guardianship, disability, or comprehensive ICBC directory.

Substantive task questions enter evidence retrieval/generation instead of
automatically rendering `task_text()`. Canonical interpretation may be
deterministic, but possible downstream generation still reserves model work.
One repeated preliminary-question repair is allowed within the same budget;
if it still repeats, qualified public guidance is selected without assuming
the missing answer. A source failure does not mark the topic covered or
silently replay the same checklist paragraph.

The planner and grounded writer have distinct pinned bindings and verification.
The policies include SDK model-assisted refinements and require evaluation
before activation. No managed optimizer result is fabricated when MCP
authentication is unavailable.
The configured metadata-aware index name may be an explicitly reviewed isolated
target via `AZURE_SEARCH_METADATA_INDEX`; it cannot repurpose `bc-pilot-public`.
Index creation/publication and switching a local binding are separate actions.

`conversation-grounding-packs.json` is a validated, candidate-only source
inventory with no source bodies or approval records. Its validator rejects
adding an invented rights/publication approval. Candidate URL/topic coverage
is not evidence coverage. Canada.ca and trustee.bc.ca are valid official
**link destinations**, not automatically permitted fetch targets. The Web IQ
transport remains unimplemented/fail-closed. Live provider integration and
source publication must wait for actual permission, scope, extraction and
accountable content review; blueprint metadata does not satisfy those gates.

The separate local-only profile does not promote those blueprints. It uses
finite named CiviX statutory sources, existing project notes, and permitted,
dated Canada.ca copies for non-commercial evaluation. Production activation
is rejected, as are non-loopback request boundaries. Optional snapshot files
are digest-pinned and time-bounded, not human publication approvals.

Evidence metadata version 2 distinguishes `official-live`, `official-snapshot`,
and `project-catalogue`; its `useScope` is
`local-noncommercial-evaluation` and `humanReviewed` is false. It carries
attribution, licence/copy notices, source hashes and, for statutes, a
publisher consolidation date/current-collection designation. It does not
replace version-1 indexed evidence or relax ingestion's legal review gates.

Core v6 factual answers are validated before text is released. Invalid links
or critical quotations can trigger one bounded correction using exact allowed
URLs and complete source sentences. Both attempts use the original aggregate
budget; neither failed text nor unsupported progress is committed. A second
failure is surfaced, not silently presented as success. Exact critical quotes
may have a narrowly recognised neutral attribution only when the complete
quotation matches the document cited in that same paragraph; changed amounts,
missing conditions, personal conclusions and cross-document attributions fail.

Critical passages also have server-issued `{{quote:...}}` markers in the
model-only evidence view. The writer selects a marker; the application inserts
the original complete passage and canonical citation before validation.
Unknown markers and excessive expansion fail closed. The immutable ledger,
user-facing source notices and citation provenance are not rewritten.
Repeated topic reads return references to already supplied evidence instead
of duplicating entire source documents in the model context.

Optional malformed or contradictory model fact proposals are withheld, not
repaired into citizen answers. Inapplicable question/topic control fields may
be discarded conservatively; the resulting proposal still undergoes strict
validation and all consent, quote, purpose, revision and progress checks.

Public programme choices survive changes in subject wording; personal context
is still cleared when the person changes. A model's `changeTask` flag alone
cannot turn a PWD practitioner question into a primary-care search. Explicit
service-change language or a clear new service request is required, while
ordinary follow-ups retain the established programme.
