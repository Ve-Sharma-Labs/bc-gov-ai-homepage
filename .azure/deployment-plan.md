# Conversation repair deployment

Status: Validated

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
