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
  "transactionsEnabled":false,"message":string,"journeys":{journeyId:boolean}}`.
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
settings. Development session/run state is opaque and in memory, so local
configuration uses one API process/replica. Root run tooling sets origins to the
selected loopback web port. No session signing-secret setting is used.
Public Azure configuration instead requires
Redis shared controls and managed-identity service authentication; there is no
silent local-state fallback. The web proxy verifies private Front Door context,
uses the socket-IP header for an opaque rate identity and replaces untrusted
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

Unused model reservations are released only when the runtime proves inference
did not begin; run-count limits still apply. Unknown/post-inference work remains
conservatively charged. The current index contains the limited four-snapshot
publication, not full coverage of every configured journey. A ready agent may
still return `SOURCES_UNAVAILABLE` for a particular question.

Azure AI Search is the default evidence path. Foundry IQ is an optional bounded
managed-retrieval comparison, Web IQ a separate disabled-until-approved public
research capability, and Work IQ/Fabric IQ are outside the anonymous pilot.
