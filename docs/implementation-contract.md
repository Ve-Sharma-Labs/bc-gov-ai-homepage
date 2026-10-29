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
