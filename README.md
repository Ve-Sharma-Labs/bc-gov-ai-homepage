# BC Government service assistant

A pilot for a conversation-first BC service experience: Next.js/React, light and
dark themes, sourced preparation plans, and a Microsoft Agent Framework/Foundry
backend. This is not a live government transaction service.

See the [as-built architecture](docs/architecture.md) for the Azure topology,
chat/cancellation flow, reviewed-content lifecycle and current release boundaries.

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

Without a configured Foundry connection, the catalogue, official links, and five
source-backed preparation journeys remain available. They are deterministic,
dated guidance, not generated model answers. Main chat defaults to general B.C.
government questions; the seven pathways are optional, visible context. Strict
greetings and generic clarification can respond without a model or source lookup.
Factual answers still require evidence, and unavailable topics receive an honest
official handoff rather than an answer from model memory.

The pilot does not renew a licence, book an appointment, register a patient,
determine benefit eligibility, or submit a government form. It prepares people
and hands them off to the appropriate official service.

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

## Checks

```powershell
npm run check
npm run build
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm run test:e2e
```

The browser suite uses an isolated Edge profile on Windows when the channel is
set. On systems without Edge, install Playwright's Chromium browser and omit
that setting. The suite starts its own local services on ports 3310 and 8310
and must not share a real user conversation or Azure model session.

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
- [Twelve-source discovery inventory](docs/source-discovery.json)
- [America.gov implementation research](docs/america-ui-implementation-research.md)
- [Reference-fidelity UI rebuild specification](docs/ui-fidelity-rebuild.md)

Restricted sources remain restricted. BC Laws needs an approved feed/access
route, WorkBC crawl-policy availability must be resolved, and incomplete ICBC
extraction is not silently treated as a complete knowledge base. The curated
catalogue is a starting point, not the planned 300-500-document reviewed corpus.