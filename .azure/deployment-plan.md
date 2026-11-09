# Optional IQ rollout

Status: Blocked

Current execution selection: paused before public research activation. Both IQ
flags remain disabled and the original API/web image digests have been restored.
Provider connectivity passed, but ordinary-chat release verification failed and
the unchanged daily processing allowance cannot admit another model run.

## Current release blocker and safe state

- The new API/web revisions reached ready state, passed private web-to-API health,
  and retained the original configuration, identities, scale and budgets.
- The ordinary public release command, `node scripts/verify-pilot-chat.mjs
  --url=https://bcassist-xufhsendpx-ddabgxfdera9azbp.b01.azurefd.net/
  --live-approved`, stopped at `job-loss starter`, turn 1, with
  `CONVERSATION_DECISION_INVALID`. Research was disabled throughout.
- Metadata-only logs show `Planner schema validation failed (attempt 1):
  ['value_error']`. The IQ commit does not change the default conversation
  policy, parser or planner method. The available evidence does not establish
  the cause; no raw model proposal or transcript was retained.
- A read-only ledger check for UTC day 20766 reported 19 billable runs,
  250447 charged tokens, and 4509682 microUSD in conservative processing charges.
  The remaining 490318 microUSD is below the unchanged 883584 microUSD worst-case
  model reservation. No counters were reset and no uncertain charges refunded.
  This accounting is not an assertion about the actual Azure invoice.
- The approved rollback restored the original API and web image digests in
  ready revisions ending `iq-rollback-1794211435`. Only revision suffix metadata
  differs from the original templates; configuration, identity and scale hashes
  were preserved. Private home/API checks returned HTTP 200, with research off.
- Front Door was restored to its prior `Enabled` state. The daily admission
  limit still applies to normal model-backed chat; guided preparation remains.
  Public-edge propagation briefly returned HTTP 404 before home and capabilities
  returned HTTP 200. The read-only release verifier then passed with all four
  baseline documents ready and research disabled; no model calls were made.
- Both candidate images remain in ACR. The approved Web IQ resource, identity
  binding, two role assignments, research agent and IQ definitions are preserved.
  These prerequisites do not mean the optional public features are activated.
- Temporary ACR credentials, the pip mirror configuration and injected
  validation secret values were removed. Ignored, ACL-protected rollback
  snapshots remain available.

Resume only after the normal daily reset and a fresh validation checkpoint.
Create new snapshots of the current rollback revisions; do not overwrite the
original rollback files or reuse their stale raw-template hashes. Use one
post-activation matched latency set rather than duplicate paid benchmarks.
Do not enable either research action until ordinary-chat checks and both actual
supplement-generation flows pass within the existing USD 5/day limit.

## Stage C1 candidate and rollback

- Candidate source: `90506663a7b56dad3162e7e2628a6c1db5d17a3a`.
- API: `crbcassistxufhsendpx.azurecr.io/bc-government-assistant/api-bc-pilot@sha256:ceeb08f15d2b76ae2de9d62c6092266918cdb9398275e4530513740efa15a706`.
- Web: `crbcassistxufhsendpx.azurecr.io/bc-government-assistant/web-bc-pilot@sha256:9ed9b2c4cacd4ba237da985ebc64cf9bfc6edc105cc29a435fddf48c4fddc6f5`.
- Both registry digests match the inspected Linux amd64, non-root images and
  their source revision labels. Offline target-platform smoke checks passed.
- The API build used the verified Microsoft package mirror as a temporary
  BuildKit secret after the default wheel endpoint failed TLS negotiation.
  Certificate validation was not disabled and no mirror config is baked in.
- Private rollback snapshots and compare-before-write hashes are recorded in
  `.azure/iq-rollout`. Changes are exactly image and revision suffix; all other
  template settings, source index, budgets, scale and auth values are preserved.
- Existing API rollback digest: `16c9d7b74770c6a3d7ab7a7268101863af389159fa83a1e61e85c4317013f960`.
- Existing web rollback digest: `a0c29628b5756939c1a57eda7424538aa3721d43aad589f5fb8daf6f48a86319`.
- Preserve the protected exposure procedure: temporarily close Front Door for
  image replacement, verify private health, restore its prior enabled state,
  and validate the ordinary public conversation before enabling research.

### All validation checks pass (Stage C1)

- [x] Core validation: CLI, authentication, Bicep compilation, ARM validation
  and what-if through the shared Azure validation helper.
- [x] Docker builds: both immutable Linux amd64 candidates passed offline smoke
  checks, including non-root execution and the web image's native addon.
- [x] Azure policy: effective assignments were retrieved; target-scope validation
  passed without policy denials. Resource type, location, tags, identity,
  configuration, network and scale remain unchanged in the actual patch.
- [x] Structured what-if modifies only the two existing Container Apps, with no
  creates or deletes. The actual patch omits configuration and identity.
- [x] Static role verification: no new role assignments; existing API/web
  user-assigned identities and resource-scoped AcrPull bindings are preserved.
- Deployment precondition: compare live template hashes immediately before PATCH and verify no unrelated
  settings changed afterwards. Do not overwrite a concurrent deployment.
- Research activation is a separate, later configuration step after this code-only
  rollout and positive end-to-end checks.

## 7. Current validation proof (Stage C1)

Target-scope proof captured at `2026-11-09T07:35:19.0270792Z`.

- The shared validation helper returned `OVERALL: PASS` for the C1 mirror and
  its private secure parameters in the confirmed subscription/resource group.
  Command: `validate-deployment.ps1 -Scope group -ResourceGroup
  rg-bcassist-xufhsendpx -Template .\infra\app-image-update.bicep -Parameters
  .\.azure\iq-rollout\image-update.parameters.json -Subscription
  ad92e163-a85e-40cc-bb50-054b0b8197a8`.
- The initial secure-array type error was fixed by using a secure object.
  Existing secret references required their existing values for ARM validation;
  those values were handled only in an ACL-protected, ignored parameter file,
  never displayed and never included in the actual template-only PATCH.
- Structured what-if confirms exactly two Modify resources: the existing API
  and web apps. There are zero Create or Delete resources. Mirror normalization
  also appears under configuration/workloadProfileName; neither property is
  included in the actual PATCH, which is not the full Bicep mirror.
- Local image inspection reconfirmed Linux amd64, non-root users, the full
  `90506663a7b56dad3162e7e2628a6c1db5d17a3a` source label and both pushed digests.
- Offline API (857 tests), focused final API/agent checks (61), web tests,
  current typecheck, tooling (73 tests), target-platform builds and smokes passed.
- This proof covers the code-only update with research disabled, not public
  research activation. At the time this proof was captured, no live application
  template had changed. The execution and subsequent rollback are recorded above.

## Completed provider validation

- `bc-service-research:1` is published with no tools on `bc-fast`; exact policy
  SHA256: `e1021c167912eba1a82e089ccef6b3f322bff8caf5c6aef13f4b400181b08d93`.
- `bc-public-iq-source` and `bc-public-iq-preview` were conditionally created and
  read back. The API identity can read both definitions (HTTP 200).
- The indexed corpus is unchanged before/after: 20 active chunks, four documents,
  SHA256 `c2e587e78dfe24cea80244a1f1550922cee039fa79ea171c9ea504c15ad3f685`.
- Live preview retrieval succeeded with `maxOutputSize=8192`: one planning
  activity, three Search subqueries preserving the exact source filter, five
  references and five valid evidence rows. Planner usage: 906 input/46 output
  tokens; distinct service reasoning units: 52804. Search knowledge retrieval
  remains on its existing free billing mode. No model capacity was added.
- Two preceding request-shape errors were corrected. Their conservative
  validation reservations remain charged; no allowance was reset or bypassed.
- The matched default-answer baseline contains six samples after one excluded
  warmup: p95 first validated content 3398 ms and completion 4120 ms. This is a
  small sample, not a population-wide latency guarantee.

## Stage B2 metadata preparation

- Publish an immutable, tool-free `bc-service-research` prompt-agent version
  using the existing `bc-fast` deployment and the reviewed research instructions.
- Create `bc-public-iq-source` and `bc-public-iq-preview` using the pinned
  `2026-08-01-preview` contract, low single-pass planning and extractive output.
  The only source is the existing `bc-pilot-public` index with its existing
  `bc-public-guidance` semantic configuration. No ingestion or index writes.
- Use conditional creation rather than replacing an unexpected existing
  definition. Read back the source/base and agent version before using them.
- Verify an actual indexed-corpus fingerprint before and after preparation.
  Inference probes must use the existing shared processing budget.
- Azure MCP's Foundry router could not acquire a token from its credential
  chain. The documented SDK fallback using the already authenticated,
  subscription-pinned Azure CLI identity successfully verified that the
  research agent does not yet exist; no identity switch is required.

Stage B2 does not validate app-image deployment or public activation.

## Stage A execution and service onboarding

- Deployment `iq-webiq-onboarding-c6155a97` succeeded. The approved global G3
  account exists and reports `provisioningState: Succeeded`.
- No new resource-level RBAC assignments were created by the account template.
- The portal shows `webiq-bcassist-xufhsendpx - Default` as Production, with Web
  and Browse enabled and 15 QPS. The user approved using the pilot-subscription
  identity for onboarding.
- The user separately approved binding API client ID
  `25171ca8-1a53-4ce0-8014-b56f2ba8e4bc`; the portal confirmed that exact binding.
- The non-secret Web IQ AppID was observed on the approved binding request:
  `6A4A92413D02E443293765A05E5C06CDC4D58C82`. No API key was copied or exposed.
- The first managed-identity probe did not execute: a long console command hit
  the console URL limit. A minimal exec command succeeded. The checksum-protected
  probe was transferred to one fixed replica, but its final execution received
  console HTTP 429 with `Retry-After: 600`. Do not retry before
  `2026-11-09T05:23:21Z`. No Web IQ provider request was launched by these attempts.
- After that retry window, the guarded probe succeeded with HTTP 200: one Web
  IQ call, three results, all three from the approved official host. The existing
  shared processing budget was charged 7,000 microUSD without counting provider
  usage as model tokens. Run: `iq-web-probe-21e21ee69e49fdcc`. The temporary
  transferred script was removed; provider passages were not retained.

## Stage B1: individually approved access

The user explicitly approved both resource-scoped grants:

1. Search service identity `4a9e8a78-adae-4266-a3cc-379c41e4e821` gets Cognitive
   Services OpenAI User on the existing `ai-bcassist-xufhsendpx` account.
2. API identity `a11afbdb-bbf1-4f58-9e2a-100134b6e13c` gets Reader on the existing
   `srch-bcassist-xufhsendpx` service. Existing document-read access is retained.

The payload is `infra/iq-access.bicep` with `.azure/iq-access.parameters.json`.
No model deployment, capacity, service SKU, document, app image or public route
is changed. The main template records equivalent default-off approval switches.

### All validation checks pass (Stage B1 only)

- Run the shared Azure validation helper for this exact resource-group payload:
  CLI/auth, Bicep compilation, ARM validation and structured what-if.
- Confirm exactly the two approved role assignments are created, with zero
  other modifications or deletions.
- Docker build is not applicable to this access-only payload.
- Verify principal IDs and resource scopes statically, then re-read actual role
  assignments after deployment. Role creation alone does not prove propagation.
- This stage does not validate or authorize public activation of the app images.

### Stage B1 validation proof

Proof reviewed at `2026-11-09T05:43:17.3329277Z`.

- The shared validation helper completed with `OVERALL: PASS` for
  `infra/iq-access.bicep`, `.azure/iq-access.parameters.json`, the confirmed
  subscription and `rg-bcassist-xufhsendpx`.
- An initial compile error was corrected by passing the already verified API
  principal ID as a deployment parameter, rather than trying to derive a role
  assignment name from a runtime reference. The corrected payload passes
  compilation, ARM validation and what-if.
- Structured what-if confirms exactly two Create entries and no Modify/Delete:
  role assignment `21bce750-f7c7-572c-925e-501cbecff469` grants OpenAI User on the
  existing Foundry account to the existing Search identity; assignment
  `45e7643b-9b0f-5321-a494-b4a1ac417f6c` grants Reader on Search to the verified
  API principal. Resource scopes and role definition IDs match the approvals.
- Static review confirms no document-write, contributor or administrator grant.
  No resource SKUs, capacity, documents, app images or routes are included.
- Bicep compilation is the build for this access-only payload. The updated main
  template also compiles; existing Redis schema warnings are unchanged.
- Live role propagation remains to be verified after creation. This proof
  does not validate app-image activation.

### Stage B1 execution

Deployment `iq-access-c6155a97` succeeded. Direct ARM reads of both assignment
IDs confirm the approved principal IDs, role definitions and resource scopes.
This proves role creation; actual data-plane probes still check propagation.

## Current scope and authorization

Modify the existing pilot only. The user approved validation followed by public
activation of both optional per-answer IQ features, preserving indexed-first
normal chat. The user separately approved creating `webiq-bcassist-xufhsendpx`
in the existing pilot subscription with the global Web IQ location and no
increase to the USD 5/day application-processing budget. Existing Canada Central
hosting remains unchanged. This budget is not an Azure invoice cap.

The user explicitly permits Web IQ's default query logging for fixed public
topics only. Personal details and transcripts remain excluded. This is owner
acceptance of that processing mode, not a claim that Microsoft enabled Zero
Query Logging.

## Current target and recipe

- Subscription: `ad92e163-a85e-40cc-bb50-054b0b8197a8`
- Resource group: `rg-bcassist-xufhsendpx`
- Existing application region: Canada Central; new Web IQ location: global
- Existing model: `bc-fast`, `gpt-5.4-mini`, GlobalStandard, unchanged capacity
- Recipe: Azure CLI with narrowly scoped existing-resource updates and one new
  Web IQ metering account; no whole-stack reprovisioning

## Preparation and validation requirements

- Verify Web IQ provider availability, metering-account creation contract,
  paid-subscription eligibility, AppID connection and managed-identity binding.
- Update the processing policy to accept either verified Zero Query Logging or
  explicit owner approval of default logging for constrained public topics.
- Prepare an isolated Foundry IQ source/base and research answer agent over the
  existing approved index; verify model/region compatibility and read-only
  runtime permissions. Obtain specific approval before any access-role change.
- Preserve current API/web configuration and immutable image digests for rollback.
- Keep each provider disabled until its real access, evidence, budget and
  end-to-end checks pass; do not manufacture approval records or source freshness.
- Perform the Azure validation workflow for the actual deployment payload before
  provisioning or image/configuration updates. Validate each stage independently.

## Stage A: approved metering-account preparation

The approved Stage A payload is `infra/web-iq.bicep` with
`.azure/webiq.parameters.json`: exactly one new global G3
`Microsoft.WebIQ/accounts@2026-06-01-preview` account named
`webiq-bcassist-xufhsendpx`. No existing resource, access role, app image,
model capacity, source index or public exposure setting is changed by this
template. `statisticsEnabled=false` is not a query-logging approval.

The user approved this specific resource, subscription, global location and
unchanged budget. Default query logging is separately approved for fixed
public topics. Provider/AppID enablement and public activation are still
conditional on successful technical validation.

### All validation checks pass (Stage A only)

The following checks must pass before this resource is deployed:

1. Core validation: CLI authentication, compilation, target-scope validation
   and what-if using the shared Azure validation helper.
2. Docker build: not applicable to this account-only payload. The later app
   rollout requires fresh immutable API/web images and its own validation.
3. Azure policy validation through the target-scope provider validation and
   what-if; expected diff is one create, zero modifications and zero deletions.
4. Static role verification: this template declares no role assignments.
5. Record the actual proof and any subscription/service enablement blocker.

Stage B (knowledge definitions, agent, permissions and app images) is not
validated by Stage A and cannot be deployed on the strength of its proof.

## Stage A validation proof

Proof reviewed at `2026-11-09T04:47:32.5716733Z`, before any account creation.
Subscription, existing resource group, global account location and unchanged
budget were explicitly confirmed through the user approval prompts. The
account is still absent. AZD environment creation, ACR/Container Apps updates,
SQL migrations and app-container builds are not applicable to Stage A.

- The Azure validation helper completed with `OVERALL: PASS`, using
  `-Scope group -ResourceGroup rg-bcassist-xufhsendpx -Template
  .\infra\web-iq.bicep -Parameters .\.azure\webiq.parameters.json -Subscription
  ad92e163-a85e-40cc-bb50-054b0b8197a8`.
- CLI installation and authentication passed for the explicitly confirmed
  subscription. Bicep compilation and target-scope ARM validation passed.
- The helper's compact output counted two Create strings. A separate structured
  `az deployment group what-if --no-pretty-print` inspection confirms exactly
  one resource with `changeType: Create`: the approved Web IQ account. All
  existing resources are Ignore; there are no Modify or Delete entries.
- Bicep reports BCP081 because its local type catalogue lacks this preview
  resource schema. The actual provider advertises `2026-06-01-preview` and
  global, and ARM validation succeeded.
- The template contains no role assignments, secrets, app-image changes,
  source publication or networking changes. Docker build is not applicable
  to this account-only payload.
- The provider is not yet registered. Registration is a prerequisite of the
  approved account creation; it does not establish Microsoft service enablement
  or a working AppID. Account creation and subsequent onboarding still have to
  demonstrate actual service access and paid-subscription eligibility.
- The owner-approved public-query logging alternative passed API lint and
  126 focused tests; the disclosure changes passed web typecheck and nine
  research UI unit tests. These are preparation results, not public activation.

The historical proof below applies only to the prior conversation repair.

## Current evidence

Read-only inspection confirmed the selected subscription matches the existing
deployment, the API's app-processing limit remains USD 5/day and 100 runs/day,
no Foundry IQ knowledge bases exist on the pilot Search service, and no
`Microsoft.WebIQ/accounts` resource exists in this subscription. The public API
still runs the prior `renewal-f7ef408` image; the optional IQ changes are not live.

## Historical conversation repair deployment

The record below is historical evidence only, not validation of this IQ rollout.

Historical status: Validated

Release outcome: Deployed and publicly verified November 6, 2026.

## 1. Scope and authorization

Modify the existing isolated public pilot; do not provision another stack.
The user requested execution of the previously described repair and rollout:
"please execute this then to fix it".
The user subsequently supplied the written authorization:
"I am given full written permission here".
This confirms the described existing-pilot target and the scoped public
conversation/source refresh; it does not authorize unrelated sources or data uses.

The source scope remains the four previously published documents. No new
source programme, Web IQ, real government-record integration, transactions,
quota increase, WAF relaxation, or access-role changes are included.

## 2. Selected Azure context

- Subscription: `ad92e163-a85e-40cc-bb50-054b0b8197a8`
- Resource group: `rg-bcassist-xufhsendpx`
- Existing application region: Canada Central
- API: `ca-bcassist-xufhsendpx-api`
- Web: `ca-bcassist-xufhsendpx-web`
- Registry: `crbcassistxufhsendpx.azurecr.io`
- Search: `srch-bcassist-xufhsendpx`, index `bc-pilot-public`
- Public URL: https://bcassist-xufhsendpx-ddabgxfdera9azbp.b01.azurefd.net/

## 3. Recipe and payload

Recipe: Azure CLI, existing-resource image/configuration update.

The initial rollout used commit `2616376` (including repair `3f98628`) as Linux
amd64 API/web images, followed by API-only correction `f7ef408`. Existing
identities, origins, ingress, secrets, replicas, general/pathway bindings,
budgets, and network protections are preserved.

Enable the reviewed version-5 conversation and task assistance consistently in
the API and web. Keep version 6 and local evidence evaluation disabled. The
isolated conversation candidate is pinned to
`bc-local-2017434d-conversation:4`, deployment `bc-fast`; reverify before use.

## 4. Preparation and review

- Re-read live revisions, image digests, configuration, and access roles.
- Complete the explicit privacy/data-flow review for the existing prototype.
- Review the four exact source candidates and their content/extraction/review
  hashes against the current published records.
- Validate the additive Search schema change without changing semantic/vector
  configuration or enabling the metadata experiment.
- Back up the current published chunks and identify their exact retirement set.
- Build and inspect both candidate images; never rebuild or rewrite source dates
  merely to pass freshness checks.

Preparation completed:

- The existing Canada Central resource group and both running single-revision
  apps were re-read. Their live digests still match the rollback references.
- API/web `AcrPull` assignments on the existing registry are present.
- The source review manifest authorizes exactly four documents and their three
  exact hashes. Its dry run yields 20 uploads, zero deletions and zero withheld
  documents. Every chunk is at most 8,000 characters; the source check dates are
  the actual November 5 acquisitions, not rewritten dates.
- All 12 old live keys match the previously captured publication. Full private
  content/schema and container configuration rollback snapshots are saved.
- The schema merge adds 29 fields without modifying existing field types,
  semantic settings or vector settings.
- The technical privacy review and user authorization are recorded separately
  in the ignored `.azure/conversation-review.json`.
- No new resources or larger SKUs/replica limits are requested. Existing resource
  allocation is unchanged; quota expansion is not applicable.
- Both images were built. The API dependency TLS failure was resolved using
  the verified Microsoft package mirror as a temporary BuildKit secret, with
  certificate validation preserved.

## 5. Execution boundaries

Use the existing protected exposure procedure for image replacement. Preserve
the current live image/configuration tuple before any change. Prefer reversible
superseding of exact old source chunks rather than destructive index deletion.
Only the selected four documents may be refreshed.

Do not treat a container health check or HTTP 200 as proof of conversational
success. Reopen/retain the public candidate only with the intended capabilities,
usable sources, and the real bounded conversation checks.

## 6. Verification and rollback

Run the bounded release probe, including the exact reported renewal question,
issuer confirmation, readiness/location continuation, non-B.C. routing, starter
handoffs, and a cited health answer. Preserve normal model/rate limits. Clear
only the probe's own synthetic sessions.

Rollback uses the immediately preceding verified API/web digests and complete
configuration snapshots. Source replacements retain the prior chunks for
recovery; no unrelated resource is deleted.

## 7. Validation proof

Validation recorded at `2026-11-06T05:10:10Z`; detailed command-completion
timestamps and evidence paths are in the ignored `.azure/validation-proof.json`.

All validation checks pass:

1. Core validation: CLI authentication, compilation, ARM validation and what-if
   for `.azure/app-update.bicep`, containing only the two existing apps.
2. Docker build and image inspection for both Linux amd64 candidates.
3. Azure policy validation through the target-scope validation/what-if and
   preservation of existing location, tags, identities, ingress and limits.
4. Static and live role verification for unchanged registry, Foundry, Search,
   Redis, API authentication and telemetry access.

The code work already passed API regression/lint, web build/typecheck, targeted
and full web unit checks (one timeout passed in isolated rerun), 14 task-browser
cases, Bicep compilation, and release-probe tests. These do not replace fresh
Azure identity, resource, source, image, and live-outcome checks.

Fresh results:

- The Azure validation helper reports `OVERALL: PASS`: authentication, Bicep
  compilation, target-scope validation, and what-if completed successfully.
- Structured what-if identifies only the two existing Container Apps as modified.
  Actual rollout bodies are more narrowly restricted to `properties.template`;
  a separate exact comparison proves all other environment values, scale and
  resource allocations are retained. Configuration, secrets, identity, network
  and tags are not included in the live patch.
- The provider validation required removing response-only `imageType` and
  `ephemeralStorage` fields and the duplicate empty value on a secret reference.
  The existing secret was used only as a secure validation parameter and is
  absent from the actual rollout patch.
- Both built images are Linux amd64 and non-root, labelled with the verified
  source commit. The API image imports successfully and serves health plus all
  seven guides. The web image serves HTTP and renders the runtime version-5
  bootstrap correctly.
- Source publication dry run: 20 uploads, zero deletions, zero withheld
  documents. The old 12 keys and schema are backed up; additive-schema validation
  preserves all existing definitions. Check dates are unchanged from acquisition.
- Registry authentication works using a scoped, temporary credential file after
  the desktop credential helper failed. This file must be removed after push.

Role Assignment Verification: Passed. Existing API/web registry-pull identities,
API Foundry/Search/Redis/telemetry access, and web-to-API audience/caller checks
are retained. No role, credential, privilege or network expansion is planned.

### API-only follow-up correction

The corrected API is commit `f7ef408c13d48c5fef2b52aafa3aabef38b8f87d`,
image `sha256:16c9d7b74770c6a3d7ab7a7268101863af389159fa83a1e61e85c4317013f960`.
The deployed web image is unchanged.

- Core validation again reports `OVERALL: PASS`; see
  `.azure/api-followup-validation.log`.
- The structured what-if has exactly one modified resource, the existing API,
  and no creates or deletes. The actual patch is narrower than the validation
  template: only `properties.template`, with an exact two-field delta of image
  and revision suffix. All environment, scale and resource values are preserved.
- The image is Linux amd64, non-root, and labelled with the source commit.
  An isolated, network-disabled container passed imports, `/healthz`, the seven
  catalogue guides, and presence of the corrected city guard. The smoke uses
  the allowed loopback host, not TestClient's disallowed default `testserver`.
- The 124 targeted API cases and all nine release-probe tests pass.
- The unchanged API identity still has resource-scoped Foundry/OpenAI, Search,
  telemetry and registry-pull roles. No infrastructure access change is needed.
- The pushed registry digest matches the built image. Its temporary registry
  credential file has been removed.

## 8. Execution record

- Published the reviewed four-document replacement: 20 active chunks, with the
  12 exact prior chunks reversibly superseded and none deleted. Runtime source
  health is ready with four usable documents and no expired or rejected active
  chunks. The recorded acquisition timestamps were not modified.
- Deployed API/web `renewal-2616376` revisions, preserving identities, secrets,
  limits and ingress. Version-5/task flags are enabled consistently; version 6
  and local evidence evaluation remain disabled. Private web-to-API readiness
  passed using the existing managed identity.
- The first public live probe passed the reported renewal request and four
  follow-ups, then failed on the additional-requirements question. A regression
  reproduced an unchanged known city being rejected as an unsupported update
  and an informational question rewinding progress. The bounded API correction
  passes 124 targeted task, grounded-compatibility and answer cases.
- Front Door was re-enabled after private readiness. Its configuration reports
  Enabled/Succeeded, but public requests subsequently returned
  `404 CONFIG_NOCACHE`. Routing diagnosis and final acceptance remain open.
- This led to the API-only correction recorded below, preserving the deployed
  web image, settings, source publication and protected exposure procedure.

Follow-up rollout:

- API `renewal-f7ef408` is Healthy at 100% Container Apps traffic, with the web
  still on `renewal-2616376`. Structural comparison verifies no changes to
  configuration, user-assigned identity, tags, environment, scale or resource
  allocations outside the API image/revision suffix.
- The corrected six-turn renewal flow, guardianship and disability starters
  passed privately. An informational job-loss request legitimately used the
  existing reviewed WorkBC handoff rather than asking an intake question.
  The probe was corrected to accept that supported outcome while still
  requiring the explicit follow-up to work; API coverage and ten probe tests
  pass. No application behavior was changed for this probe correction.
- Private continuation then passed job-loss follow-through, the non-B.C. issuer
  route and a genuinely grounded, cited Health Connect Registry answer.
  Synthetic sessions were cleared. The staged private script was removed
  before execution; a transport `Retry-After: 600` was respected.
- Public closure was observed as HTTP 404 before reactivation. The endpoint
  was reopened at `2026-11-06T06:31:04Z`. A bounded read-only observer waited for
  two stable release-contract passes before the one full public 16-turn run.
  No WAF, network, budget or source-policy relaxation is involved.

Final acceptance:

- Public routing recovered at 06:42 UTC. The complete 16-turn public acceptance
  run passed at `2026-11-06T06:45:40Z`: renewal continuation, guardianship,
  disability, job loss, non-B.C. issuer and a cited Health Connect Registry
  answer. All six synthetic conversations were cleared.
- A real-browser replay passed the exact renewal request and four follow-ups.
  Details retained Vancouver and the reviewed ID step after the information
  question. Optional personal sharing remained off. Start over cleared only
  that synthetic conversation and returned to the homepage.
- Final public capabilities expose `[1, 2, 3, 5]`, ready conversation and task
  assistance, and four usable reviewed documents with no expired documents or
  rejected active chunks. Missing ICBC detail still uses its specific official
  handoff; no unsupported requirements, transactions or eligibility decisions
  have been introduced.
- `.azure/public-release-result.json` and
  `.azure/final-public-capabilities.json` retain the actual public results.
  Temporary registry credentials are absent; private rollback and publication
  evidence is retained. No GitHub push, pull request or merge was performed.
