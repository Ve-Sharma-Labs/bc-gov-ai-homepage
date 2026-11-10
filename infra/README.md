# Protected Azure pilot

The implementation supports an anonymous Azure-hosted preview. No
deployment target, region, model capacity, spending envelope, source publication
or public-release approval is inferred from an authenticated Azure CLI session.
`azure.yaml` gates both provisioning and deployment through
`scripts/azure-preflight.mjs`. Flags are necessary configuration, not evidence
that reviews or live verification happened.

The isolated pilot infrastructure and real application images are deployed.
One general and seven pathway agents, and 12 chunks from four explicitly approved
source snapshots are configured. The private-origin connection is approved, and
the initial real web/API release exercised source-validated Foundry answers
using managed identity.
The [public pilot](https://bcassist-xufhsendpx-ddabgxfdera9azbp.b01.azurefd.net/)
is live, with public-browser answer, follow-up and terminal cancellation
verified for the general-chat release on October 27, 2026. The temporary `ValidationOnly` rule is removed;
WAF Prevention, managed rules, API rate protection and private ingress remain.
These pilot-specific approvals do not authorize another target, new content
snapshots or optional Web IQ processing.

The November 5, 2026 investigation found the public app still advertising only
request versions 1--3, with all four published source reviews beyond their
seven-day runtime freshness limit. The conversation-restoration changes in this
repository are a release candidate, not evidence of public activation or renewed
content approval. Recheck live capabilities and evidence, not this historical
deployment record, before declaring the service ready.

The [as-built architecture](../docs/architecture.md) contains the deployment
diagram, full resource inventory and identity/data-flow relationships. This
guide retains the environment inputs, rollout and rollback procedures.

## Topology

- Separate user-assigned API, web and publisher identities.
- Foundry account/project and explicitly named/versioned model deployments with
  `NoAutoUpgrade`. Managed prompt-agent versions are published separately by the
  [API operator command](../apps/api/README.md).
- Azure AI Search with Entra-only access and an optional non-public Blob staging
  container. Blob public networking and shared-key authentication are disabled
  in the live pilot. Reviewed index/schema/content
  publication is a separate [ingestion operation](../ingestion/README.md).
- Managed Redis with Entra/TLS, a private endpoint/DNS, EnterpriseCluster proxy
  mode, NoEviction and persistence disabled for bounded security state.
- A VNet with distinct delegated Container Apps and private-endpoint subnets.
- A workload-profile Container Apps environment with public network access
  disabled, an internal API and a web app reached through a private Front Door
  origin. Explicit reviewed replica maxima replace the old one-replica cloud
  limitation; local development remains single-process.
- Front Door Premium with WAF managed/bot/rate rules and uncached application
  routing. Public traffic starts disabled.
- Log Analytics/Application Insights with explicit metadata-only API metrics.
  Application prompt/tool/transcript payload logging is not enabled; inherited
  platform/governance diagnostics have a separate boundary.
- Front Door access metadata in the pilot's existing 30-day Log Analytics
  workspace, separately from inherited governance diagnostics. Access records
  include connection IPs, request URLs, status and timing, not chat bodies.
  This setting does not enable WAF matched-body logging. Questions and private
  identifiers must not be placed in URL query strings.

Foundry and Search use Entra-protected **public service endpoints**; ACR also
has public networking enabled with its administrator account disabled. In
contrast, the live storage account has public networking disabled, no bypass
and no observed private endpoint. Optional Blob staging therefore needs a
separately verified approved network path; it is not required for Search
publication or anonymous inference.

This is not an all-PaaS-Private-Link landing zone. Policy-managed restrictions,
subnet NSGs and governance diagnostics can differ from template defaults.
Private app ingress does not itself settle global model processing, operational
retention, privacy, availability or public BC brand approval.

The template retains pinned AVM modules:
`avm/ptn/azd/container-apps-stack:0.4.0`,
`avm/ptn/azd/acr-container-app:0.5.0`,
`avm/res/operational-insights/workspace:0.16.1` and
`avm/res/insights/component:0.8.0`. Module telemetry and registry admin access
are disabled. Identities precede dependent resources to avoid circular bindings.

## Explicit deployment inputs

`main.bicepparam` reads AZD environment values with `readEnvironmentVariable`.
This lets Bicep serialize JSON-valued model, agent and budget settings safely,
rather than injecting unescaped JSON into a quoted JSON parameter-file string.
In particular:

| Input | Required decision |
|---|---|
| `AZURE_SUBSCRIPTION_ID`, `AZURE_ENV_NAME`, `AZURE_LOCATION` | Confirmed target, not the CLI's incidental default |
| `AZURE_MODEL_DEPLOYMENTS` | JSON array of `deploymentName`, `modelName`, `modelVersion`, `sku`, positive `capacity`; actual availability/quota must be checked |
| `FOUNDRY_AGENTS` | Actual seven-pathway publication registry; empty during closed bootstrap only |
| `FOUNDRY_GENERAL_AGENT` | Separate published name/version/model binding without journey scope; required by the new general-chat release preflight before validation/public traffic |
| `FOUNDRY_CONVERSATION_AGENT` | Distinct published name/version/model binding for the version-5 planner; verify its policy and tool declarations before reuse |
| `AI_CONVERSATION_ENABLED`, `TASK_ASSISTANCE_ENABLED` | Explicit `true`/`false`; task assistance requires AI conversation in the same API revision |
| `AI_CONVERSATION_PRIVACY_REVIEWED` | Explicit `true` only after the actual public conversation-processing review; deployment or model-test approval alone is insufficient |
| `AZURE_SEARCH_SKU`, `AZURE_REDIS_SKU` | Reviewed regional SKUs and service costs |
| `AZURE_API_APPLICATION_CLIENT_ID` | Existing internal API Entra application; see identity prerequisites below |
| `AZURE_PILOT_CONTROLS` | JSON `runLimit`, `tokenLimit`, `costLimitMicrousd`, `tokenPriceMicrousd`, `apiMaxReplicas`, `webMaxReplicas` |
| `AZURE_NETWORK_PREFIX`, `AZURE_APPS_SUBNET_PREFIX`, `AZURE_PRIVATE_SUBNET_PREFIX` | Compatible, non-overlapping reviewed address ranges |
| `AZURE_API_IMAGE_NAME`, `AZURE_WEB_IMAGE_NAME` | Full reviewed ACR image references by `@sha256:...` before enabling traffic |
| `AZURE_DEPLOYMENT_STAGE`, `AZURE_VALIDATION_CIDRS` | Closed by default; explicit validation IPs or separately approved public release |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, `AZURE_OPENAI_EMBEDDING_DIMENSIONS` | Optional real hybrid retrieval, matching the index and published vectors |

The default Search index name is `bc-pilot-public`; `AZURE_SEARCH_INDEX` may
override it consistently with the publisher. No model, quota, price or region
is chosen automatically. Estimated model budgets do not cover every Azure
service charge; include Front Door Premium, Search, Redis, minimum replicas,
networking, storage and monitoring in the spending review.

The current pilot retains a USD 5 estimated-model-cost ceiling and 100 model runs
per UTC day. Its token allowance is 800,000, accounted conservatively at USD 6
per million tokens. Microsoft's regular Global Standard `gpt-5.4-mini` meters
were rechecked at USD 0.75 input and USD 4.50 output per million; actual model
metrics report the `default` service tier, and native request tests disallow
an implicit priority opt-in. Reprice the controls before changing models or
enabling priority processing. Existing charged reservations were not reset.
These application controls are not a hard Azure invoice cap or a substitute
for subscription billing monitoring.

The general-chat increment adds no model deployment or automatic priority tier.
Strict application greetings do not consume a model reservation, but still use
shared ownership, replay, concurrency and cancellation controls. This repository's
new general binding and full-source programme are incremental preparation, not
proof that new source content or jobs have already been activated.

The internal API Entra application must have the expected
`api://<application-client-id>` identifier URI and v2 access tokens whose audience
is the client ID. It is not created here. Runtime validates tenant, issuer,
audience and the web identity's service-principal **object ID**. The web uses
managed identity and hashes the trusted Front Door socket-IP with a generated
Container App secret; no secret belongs in the parameter example or repository.

The publisher identity is separate from inference. Its ID/client ID are outputs,
but no job/runner or federation is attached to it. An operator using
`--credential azure-cli` needs explicit scoped publication permissions; it does
not inherit the generated publisher identity's roles.

## Rollout and rollback

For the conversation release, set all four conversation inputs explicitly,
retain the existing general/pathway bindings, and verify the isolated planner's
actual returned version. The template keeps version 6 and local evidence
evaluation off. Do not copy a local privacy setting into production or set a
review flag solely to satisfy preflight.

1. Confirm target, policy, quota, model processing, service costs, internal
   identity and publication permissions. Complete Azure validation and review
   the real provision preview before authorizing resource creation.
2. Provision with `closed` stage: Front Door is disabled. Bootstrap placeholder
   images are allowed only while closed. Deploy the real application images,
   publish reviewed agent versions/content, and apply their actual bindings.
3. Resolve the approved application image digests in ACR. Set both image inputs
   before any subsequent exposure/configuration provision operation. This keeps
   an IaC update from resetting a deployed application to AVM's hello-world image.
4. Verify and approve the exact private-origin connection. `validation` enables
   only the explicitly allowed IPv4 CIDRs; preflight requires private-origin
   approval and pinned application images. Exercise the real browser/API path,
   all seven journeys, streaming, cancellation, budgets, source gates and errors.
5. `public` additionally requires actual source publication, live evaluation,
   public-preview and BC brand approvals plus seven published pathway bindings.
   Privacy, domain and release review cannot be replaced by booleans.

Keep the previous verified image digests, agent registry and corpus
publication record for rollback. Close the edge first if the candidate cannot
be trusted, restore the reviewed bindings/images, and reverify before reopening.
Do not delete source or shared-control resources as an automatic rollback.

**BC Gov App - Azure Deployment** (`.github/workflows/azure-pilot.yml`) is
**manual only**. Its run title and check name identify the selected provision,
deploy, or verify operation. It needs an explicitly
configured/protected `pilot` GitHub environment, OIDC deployment identity and
the reviewed variables above. Provision and image deployment are separate
operations. The separate `verify` operation requires an exact `public_url`;
it checks version-5/task readiness, current baseline evidence, and all seven
preparation guides without a model call by default. `live_checks=true` also
requires `AZURE_LIVE_EVALUATION_APPROVED=1` and performs at most 18 synthetic
turns, clearing its own conversation sessions. It does not create its own GitHub approvals, publish unreviewed
content/agents, or enable Web IQ. Before image replacement it checks the actual
Front Door endpoint is disabled, rather than trusting a stage variable. New
images must pass validation before their immutable digests are promoted and
traffic reopened. No workflow has been run.

For a focused diagnosis, run `scripts/verify-pilot-chat.mjs` with the exact
`--url`, `--live-approved` and a supported `--case` such as `--case=job-loss`.
Focused results explicitly report partial coverage and do not replace the full
release check. Planner failures expose only fixed stage labels, not model text.

After separate research approval and configuration, use
`scripts/verify-optional-research.mjs --url=<reviewed-origin> --live-approved
--research-approved` for the real per-answer flow. It performs at most seven
submissions, plus two cancellation controls: two ordinary indexed answers, both
provider supplements, one cancelled Web IQ run, and two rejected-scope checks.
It verifies unchanged conversation state, separate provenance, next-Send
isolation and page revocation, then clears its own synthetic state. Without live
approval it reads capabilities only. The existing shared budget still applies;
failed or cancelled work can retain its full reservation. Never reset counters
or bypass admission to make a release check pass.

**BC Gov App - Container Build & Smoke Tests** is separate CI: it builds and
checks API, web, and ingestion images without publishing or deploying them.
Renaming the release workflow does not rename the `pilot` environment,
`azure-pilot` concurrency group, deployment marker, or cloud resources. The
downstream **BC Gov Agents - Live Conversation QA** requires a valid `deploy`
marker; provision-only and verification-only runs cannot authorize live QA.

For edge diagnosis, use the pilot profile's resource-context access logs and
the request's `X-Azure-Ref` tracking reference. A validation allowlist uses
`SocketAddr`, so inspect `SocketIP`, not a forwarded client-IP header. If an
inherited governance workspace is not readable, an empty resource-context
query is not proof that no request occurred. `edge-logging.bicep` can be
validated and applied independently to add the owned access-log destination
without reprovisioning routes, WAF, identities or the private origin.

## Validation boundary

### Isolated full-source platform

`source-programme.bicep` is a separate resource-group deployment. It references
the existing Storage account, VNet/private-endpoint subnet, Container Apps
environment, ACR and publisher identity; it does not update the working web/API,
model, WAF, Redis or subnet configuration.

It prepares two private containers, Blob Private Link/DNS, one acquisition
identity and two **manual** jobs. Nothing schedules a crawl automatically.
The acquisition job initializes a durable run by default. Enabling acquisition
requires an actual rights blob and its exact SHA-256; the existing four-source
publication is not that permission.

After the platform exists, use `source-acquisition-job.bicep` for reviewed
initializer/acquisition argument or image changes on the replacement acquisition
job only. That narrow template references the existing environment, registry,
Storage account and acquisition identity; it does not declare the publisher job,
private networking, containers or role assignments. Validate and what-if it
before deployment, and preserve earlier run prefixes as historical evidence.

| Identity | New scoped access |
|---|---|
| Acquisition identity | Candidate-container Data Contributor, rights-container Data Reader, ACR pull |
| Existing publisher identity | Candidate/rights-container Data Contributor and ACR pull; its existing Search publication roles are unchanged |
| Web/API identities | No additional access |

Both jobs use 0.5 vCPU / 1 GiB, one replica, a 300-second limit and no automatic
platform retry. The publisher job defaults to offline catalogue validation,
not publication. Explicit operator execution supplies the reviewed publish
manifest; the acquisition identity never receives Search write permission.
Use `ingestion/Dockerfile` and its pinned runtime lock to build the job image.
The image defaults to offline programme review and is exercised without network
access in CI.

`node scripts/source-preflight.mjs <parameter-file>` checks the isolated inputs.
Adding `--execute` also requires `AZURE_SOURCE_PLATFORM_APPROVED=1`, which records
an actual resource/cost/role approval rather than replacing it. Use immutable
registry digests, distinct candidate/rights containers, a stable run prefix and
explicit cumulative request/byte limits. Never put source-job discovery tags on
the web/API resources or use a new run prefix to reset an exhausted programme.

Current retail inputs (USD, checked October 27, 2026): a Standard Private Endpoint
is $0.01/hour, and a first-tier private DNS zone is $0.50/month: approximately
**$7.80/month fixed** at 730 hours. Job active usage is $0.000034/vCPU-second plus
$0.000004/GiB-second; a 0.5-vCPU/1-GiB, 300-second execution is at most $0.0063
before other services. Inactive manual jobs consume no execution time.
Private Link data is up to $0.01/GB/direction in the initial tier; hot LRS data
is up to $0.02/GB-month, reads $0.0044/10,000 and writes $0.055/10,000.
DNS queries, record-set tiers, registry storage, monitoring and inherited storage
security charges are separate. These figures are estimates, not an invoice cap.

The original approximately $995.60 monthly planning estimate leaves less room
than this fixed addition. Review the incremental allowance before provisioning;
do not silently open public Blob networking to avoid Private Link charges.
The existing environment's Consumption quota was read as 500 vCPUs, 1 in use,
so these two bounded jobs require no new environment or quota increase.

The storage-v2 adapter now uses bounded journals, copy-on-write index pages and
lazy payload validation instead of full-state uploads and full-artifact HEAD
scans on every small batch. Its 500/1,000-record offline cases measured 2.33x
uploaded bytes and 2.24x accounted storage calls when doubling the corpus.
Resume stayed within 15 calls and 116,671 bytes plus fixed rights-input reads;
budget-only saves uploaded no cold-document bytes. The current **216-test**
ingestion suite passes, including the dataset-specific licensed Service BC
candidate adapter and the create-only rights/initializer recovery paths. The
current 65-row candidate remains unapproved and local;
it does not assert hours or service capabilities.
The non-root amd64 image checks pass. Image source files and the programme
registry were also compared with the current workspace, including the ICBC hold.

The isolated platform is now provisioned. The acquisition job is pinned to an
amd64/non-root digest and uses its system identity only for ACR pull; the
acquisition UAMI writes candidates and reads rights. The publisher identity
uploaded the canonical v2 rights file create-only, while its persistent
validation template stayed unchanged. Narrow validation/what-if deployments
updated only `job-bcassist-xufhsendpx-ingest2`.

The historical `bc-full-v1` marker was preserved. `bc-full-v2` was initialized
with the current catalogue/programme, then acquired private candidates in
25-request/120-second resumes without changing the 50,000-request,
10,000,000,000-byte or 100,000-candidate limits. The run is not complete:
the final report has 529 requests, 214,382,267 charged bytes, 4,215 candidates
and 939 pending. Publisher access holds and live-route gaps remain, and Azure
management/auth connectivity failed repeatedly during orchestration. Search
publication was never invoked; the live index remains at 12 documents and the
v2 index remains empty.

Container Apps packaging explicitly targets `linux/amd64`, including when the
developer's computer is ARM64. CI is configured to build the application and
ingestion Dockerfiles on a native x64 runner
and checks non-root execution, required runtime dependencies, real catalogue
delivery and fail-closed disconnected production controls. Emulation failures
must not be reported as successful target-architecture builds.
All three amd64 runtime images are built and exercised locally. The web build compiles
portable JavaScript on `BUILDPLATFORM`, removes build-host native addons from
the standalone output, and installs production dependencies for the target
platform. Runtime checks exercise actual x64 image processing and identity
imports. Do not collapse these stages or copy ARM native addons into a release
image. The CI job itself has not yet run.

For networks that require an approved Python package mirror, the API Dockerfile
accepts the optional BuildKit secret `pip_config`, mounted only during dependency
installation. Pass an operator-owned pip configuration with
`--secret id=pip_config,src=<approved-pip-config-path>`; never bake credentials or
an organization-specific index into an image, disable TLS verification, or use
`--trusted-host` to mask a network failure. Without the secret, ordinary pip
configuration/defaults apply.

`az bicep build` is local compilation, not subscription policy, quota, service
access, image, identity or deployment validation. The installed compiler lacks
the type library for the provider's newer stable Redis `2026-09-01` resources
and emits BCP081 warnings; compilation alone cannot validate their properties.
The warning also persists with an isolated 0.48.1 compiler, and the Azure MCP
schema tool cannot supply these newer types. This is a tooling-metadata gap;
actual Azure validation/what-if against the confirmed target is still required.
For the current isolated pilot, that validation and provisioning subsequently
succeeded; the compiler warning is not an outstanding deployment failure.

The latest recorded configuration keeps both optional IQ features disabled.
The later diagnostic candidates and validated activation draft are distinct
from the earlier rollback; see the
[dated rollout checkpoints](../docs/architecture.md#recorded-iq-rollout-state).
This guide does not constitute a new live status check.

The bounded historical Foundry IQ comparison
is complete and Direct Search remains the default answer path; see the
[architecture decision and its measurement limits](../docs/architecture.md#7-deployment-and-operations).
The comparison's temporary definitions were removed; later optional-research
definitions are separate prerequisites, not activation. Work IQ and Fabric IQ are not
part of this anonymous pilot.

### Optional IQ configuration

`researchConfigJson` defaults to `{}` and passes only explicitly mapped,
server-side settings to the API. It does not change the default chat route or
provision a knowledge base, source, Web IQ resource/AppID or billing consent.
Use the camelCase properties in `modules/hosting.bicep` for the pinned research
answer binding, provider names, genuine approval IDs, public source/path
permissions and reviewed reservations. Zero budgets and missing approvals keep
both providers unavailable even when an enable flag is set.

`foundryIqInferenceApproved` separately controls a default-off Search-identity
model-inference role assignment. Approving this deployment/permission does not
approve preview usage or enable a provider. The API's read-only knowledge
definition/retrieval access and Search-to-model networking must be verified
before recording the contract approval; do not grant contributor rights as a
shortcut. Export proposed definitions with `python -m bc_api.export_research`
and publish the isolated answer agent through the existing review/approval
command, not a normal-agent replacement.

`foundryIqMetadataReadApproved` separately controls Reader on the Search
service for the API identity. `infra/iq-access.bicep` can apply just the two
individually approved access grants without reprovisioning the stack; its role
assignment names match the main template. This grants no document writes or
service-administrator permissions.

Web IQ additionally needs its AppID-to-Entra binding, public egress, executed
terms/privacy review, an explicit logging decision and verified transient
downstream processing. Browse stays separately closed until source-identity
handling is reviewed. Each provider has an independent enable flag/kill switch.
Activation and any live evaluation remain separate authorizations; see
[API setup and release criteria](../apps/api/README.md#optional-per-answer-research).

`infra/web-iq.bicep` is a separate, one-resource metering-account template for
an explicitly approved global G3 account. It does not update the existing stack
or activate an AppID. Registering `Microsoft.WebIQ` is not proof of subscription
access: service enablement and the paid-subscription requirement still apply.
Connect the created resource in the Web IQ portal before binding the API identity.
`statisticsEnabled=false` must not be interpreted as Zero Query Logging.

`app-image-update.bicep` is a **validation-only** mirror of existing Container
Apps, not a deployment template. Use its secure snapshot parameter for ARM
validation and what-if; never deploy the complete mirror. The actual rollout
must compare fresh template hashes and PATCH only `properties.template`,
preserving identity, configuration, networking, scale and spending limits.
Wait for the requested revision to become ready: an accepted asynchronous PATCH
can initially return the old template. Keep the prior image digests for rollback
and verify public-edge recovery after restoring Front Door's enabled state.
Treat snapshot parameters as confidential and remove temporary secret values
after validation.

## References

- [AVM pattern catalogue](https://azure.github.io/Azure-Verified-Modules/indexes/bicep/bicep-pattern-modules/)
- [AZD Container Apps stack](https://github.com/Azure/bicep-registry-modules/tree/main/avm/ptn/azd/container-apps-stack)
- [AZD Container App](https://github.com/Azure/bicep-registry-modules/tree/main/avm/ptn/azd/acr-container-app)
- [Managed-identity image pulls](https://learn.microsoft.com/azure/container-apps/managed-identity-image-pull)
