# Isolated PyRIT staging

Status: Validated

Prepared: November 14, 2026.

Completed checkpoint: **identity bootstrap only** using
`infra\staging-identities.bicep` and the ignored `identity-parameters.json`.
It creates the new staging resource group and three managed identities, with
no role assignments, compute, model deployments, data services, or public access.
The complete platform must be revalidated afterwards. This lets what-if resolve
the real principal IDs instead of accepting 11 unresolved role-assignment IDs.
It is now deployed successfully. Current validation/execution selection is the
**closed full staging platform** in `rg-bcassist-jrxx4g4iwu`, Canada East, using
`infra\main.bicep`. No public exposure or production modification is selected.
Recipe for the completed checkpoint: Bicep via Azure CLI. The application phase retains
the AZD/Bicep package and deployment flow.

### Identity bootstrap validation proof

The standard `azure-validate` deployment script passed CLI/auth, Bicep compile,
target-scope ARM validation, and what-if for `infra\staging-identities.bicep`
in Canada East. No platform services or production resources are in that file.
The new resource group was confirmed absent before the checkpoint.
The exact structured resource list and template/parameter hashes must be saved
before execution. No roles or credentials are granted in this phase.
Structured preview: exactly four creates, zero Modify/Delete/Unsupported.
Static role review: the bootstrap contains no role assignments, secrets, or
service access. The intentionally unprivileged identities receive only the
separately verified role assignments in the later platform phase.
Proof and exact template/parameter SHA-256 values are recorded in the ignored
`.azure\bc-pyrit-staging\identity-validation-proof.json`.

### Section 7: Validation Proof - current identity checkpoint

| Check | Command/review performed | Result | Date |
|---|---|---|---|
| Compile, authentication, ARM/provider validation and preview | `validate-deployment.ps1 -Scope sub -Location canadaeast -Template infra\staging-identities.bicep -Parameters .azure\bc-pyrit-staging\identity-parameters.json -Subscription ad92e163-a85e-40cc-bb50-054b0b8197a8` | PASS | 2026-11-15 UTC |
| Exact preview | `az deployment sub what-if` with those inputs, `--result-format FullResourcePayloads --no-pretty-print` | Succeeded; four creates only | 2026-11-15 UTC |
| Resource boundary | `node scripts\verify-staging-plan.mjs` against `identity-what-if.json`, the reviewed profile, `rg-bcassist-jrxx4g4iwu`, and `bcassist-jrxx4g4iwu` | PASS | 2026-11-15 UTC |
| Static identity/role review | Read both bootstrap Bicep files and the complete four-resource preview | Three new unprivileged identities; no role or secret creation | 2026-11-15 UTC |

## 1. Goal and current state

Add a staging environment for manual testing through the local CoPyRIT UI.
This is an addition to the existing application, not a replacement deployment.

Azure currently has one BC assistant web/API pair in
`rg-bcassist-xufhsendpx`. The web app uses Single revision mode with 100% of
traffic assigned to its latest revision. Its Front Door hostname is the public
pilot, not staging. No staging endpoint was found in the subscription inventory.

CoPyRIT 1.2.0 is running at `http://127.0.0.1:18765`; no target is registered.
The `PyRIT integration` session has an uncommitted, offline-tested adapter and
staging infrastructure draft. It has not deployed that work. Reuse its relevant
parts after review; do not import its broader CI/CD or production-promotion work
as part of this task.

The focused transport primitives, manual target/initializer, release-identity
headers, and shared-edge Bicep path are now implemented in this worktree.
Offline checks passed. Cloud deployment and live activation remain unapproved.

## 2. Confirmed requirements

| Decision | Selection |
|---|---|
| Classification and scale | Small development staging for manual CoPyRIT use; synthetic test data only |
| Subscription | `ME-MngEnvMCAP744360-sharmave-1` (`ad92e163-a85e-40cc-bb50-054b0b8197a8`), confirmed by the user |
| Region | `canadaeast`, selected under the user's alternate-region permission after actual Redis B0 capacity checks failed in Canada Central and East US 2 |
| Total staging budget | US$500/month for additional staging infrastructure and model usage, clarified by the user on November 14 |
| Shared component | Existing Front Door Premium profile only, explicitly selected to avoid another US$330/month base fee |
| Isolation | Separate URL, routing, WAF policy, apps, identities, mutable state, data services, and registry |
| Production | Preserve its endpoint, routes, WAF policy, apps, identities, source index, budgets, and traffic |
| Execution boundary | Staging deployment and required identity/permissions are approved after validation; only the approved current-connection IPv4 /32 may access it. No production promotion or automated attack campaign |

## 3. Components and deployment method

| Component | Technology and location |
|---|---|
| Web and same-origin API proxy | Next.js, `apps\web`; existing Linux amd64 Dockerfile |
| Application API | Python 3.14/FastAPI/AG-UI, `apps\api`; existing Linux amd64 Dockerfile |
| Chat transport | `POST /api/agent`, cookie ownership, page/thread IDs, server-owned question/revision state, SSE |
| PyRIT transport | Existing `evaluations\pyrit` draft in the integration worktree; separate Python environment |
| Local UI | CoPyRIT 1.2.0 under `.cache\copyrit`; loopback only |

Use **AZD with Bicep**, consistent with `azure.yaml` and `infra`.
Proposed AZD environment: `bc-pyrit-staging`. Resource names come from the
template's subscription/environment/region suffix, not a guessed hostname.
Never initialize over this repository or select the existing production AZD
environment for staging.

## 4. Architecture and isolation

Local CoPyRIT -> staging HTTPS endpoint on the shared Front Door profile ->
staging private web origin -> staging internal API -> staging data/model services.

| Resource | Proposed configuration |
|---|---|
| Resource group | One new staging group; no replacement of the pilot group |
| Front Door | Reference `afd-bcassist-xufhsendpx` as existing; add one uniquely named endpoint, origin group/origin, route, and security policy |
| WAF | Separate staging Premium policy in Prevention mode; keep managed/bot/rate rules and `ValidationOnly` socket-IP restriction |
| Hosting | New private workload-profile Container Apps environment; Consumption profile; separate web/API apps |
| App sizing | Each app: 0.5 vCPU, 1 GiB, one minimum and maximum replica initially; no dedicated profile or GPU |
| Network | New VNet and two subnets; no production peering; private Redis and Blob endpoints/DNS; Front Door-managed private origin |
| Identity | Separate web, API, and publisher identities; a separate internal-API Entra registration/audience |
| Foundry | Separate S0 account/project; propose the same pinned `gpt-5.4-mini`, version `2026-03-17`, GlobalStandard, capacity 50, NoAutoUpgrade |
| Search | Separate Basic service, one replica/partition; independently published approved source snapshot |
| State | Separate Managed Redis Balanced_B0 with HA, TLS, Entra, NoEviction, and persistence disabled |
| Registry and storage | Separate Basic ACR and Standard_LRS Blob account; no registry admin credentials or Blob shared keys/public containers |
| Observability | Separate Log Analytics/Application Insights, metadata-only application logging, bounded retention |

Sharing Front Door means sharing a control-plane and service-failure boundary;
this is not complete infrastructure isolation. The existing profile object,
production endpoint, routes, security-policy association, WAF, and traffic must
not be rewritten. Add staging-only child resources through a separate module
scoped to the profile's group. A what-if containing production Modify/Delete
operations stops deployment.

The shared path uses `shared-edge-endpoint.bicep` and references the existing
profile. `edge-profile.bicep` remains the default for standalone pilot deployments.
The existing shared-profile access diagnostics remain unchanged and can include
staging access metadata; only application telemetry gets a separate workspace.

App ingress and mutable state remain private. As in the pilot, Foundry/Search
can use Entra-protected service endpoints and Basic ACR cannot use Private Link.
This is not an all-PaaS-private design. GlobalStandard inference is not a promise
of Canada-only processing; only synthetic prompts are in scope.

Use managed identities and the application's Container App secret mechanism.
Do not introduce API keys or copy production secrets. A new Key Vault service
is not needed for the existing keyless design.

### Policy and access prerequisites

The subscription-level policy query returned three Defender initiatives; it is
not proof that every inherited restriction permits this deployment. Existing
pilot records include inherited governance diagnostics. Run actual scoped ARM
validation and review its effects before any write.

Before opening staging, review the operator's exact egress IPv4 CIDR, the new
internal API registration, scoped deployment/publication rights, and the
Front Door private-origin connection. No broad IP allowlist, forged Front Door
headers, API-auth bypass, or production credential reuse is permitted.

## 5. Monthly total budget

USD retail planning figures checked November 14, 2026; assume 730 hours/month,
no subscription free grant, no reservation/discount, and no tax. This is an
incremental staging estimate, not a quote or hard billing cap.

| Item | Calculation or allowance | Monthly USD |
|---|---|---:|
| Additional Front Door base fee | Reuse the existing profile | 0.00 |
| Search Basic | 0.101/hour x 730, one search unit | 73.73 |
| Redis Balanced_B0 HA | 0.017/node-hour x two nodes x 730 | 24.82 |
| ACR Basic | 0.1666/day x 730/24 | 5.07 |
| Web/API compute | Both replicas active all month: 0.000034/vCPU-second and 0.000004/GiB-second | 110.38 |
| Container Apps private-environment charges | Conservative allowance for two 0.10/hour meter components; reconcile current management/private-endpoint billing before deployment | 146.00 |
| Other infrastructure | Reserve for networking, private endpoints, DNS, storage, logs, edge traffic and image operations; not a measured usage quote | 50.00 |
| Planning allocation | Rounded total | 410.00 |
| Model allowance | At most US$1.90/day in conservative application accounting; 31 days | 58.90 |
| Remaining buffer | Against the US$500 total ceiling | 31.10 |

Private Link has charges even on Consumption environments. The price catalog
now lists environment-specific meters while the billing documentation describes
Dedicated Plan Management; the US$146 allowance is conservative, not a claim
that two fees always apply.

The infrastructure allowance uses 730 hours; even 744 hours leaves headroom in
the buffer. Model calls are constrained by separate daily run/token/cost limits,
one web/API replica each, and the existing admission controls. No helper model
or automated campaign is configured. The model allowance can admit only a small
number of conservatively reserved model-backed turns each day.

Semantic-query overages, unexpected egress/log volume, taxes and
agreement-specific charges can change the bill. Confirm a final priced payload
before deployment. Track both the staging resource group and incremental shared
Front Door usage; a resource-group-only budget misses shared-profile charges.
Budget alerts are notifications, not a spending cutoff. Do not widen scaling or
raise limits to make a test pass.

Pricing sources:
[retail pricing API](https://prices.azure.com/api/retail/prices),
[Container Apps billing](https://learn.microsoft.com/azure/container-apps/billing),
[private endpoint billing](https://learn.microsoft.com/azure/container-apps/private-endpoints-with-dns),
[Redis node pricing](https://azure.microsoft.com/pricing/details/managed-redis/).

## 6. Resource inventory and capacity evidence

Read-only snapshot from November 14, 2026. Quota availability is not a capacity
reservation or a successful deployment.

| Resource or quota | Existing | Add | After | Limit/evidence |
|---|---:|---:|---:|---|
| Container Apps environments, Canada Central | 4 | 1 | 5 | 50, `az quota show` and `usage show` |
| VNet, Canada Central | 2 | 1 | 3 | 1,000, quota CLI |
| Storage accounts, Canada Central | 2 | 1 | 3 | 250, quota CLI |
| Regional private endpoints | 5 | 2 | 7 | 65,536, quota CLI; Front Door-managed resources are separate |
| Model GlobalStandard allocation | 60 | 50 | 110 | 2,000 capacity units, Cognitive Services usage API; not invoice tokens |
| Shared-profile endpoints | 1 | 1 | 2 | 25, `az afd profile usage` |
| Shared-profile origin groups/origins/security policies, each | 1 | 1 | 2 | 200 each, profile usage API |
| Search Basic services, Canada Central | 1 | 1 | 2 | 16 documented per tier/region; quota CLI returned an empty list, not unlimited capacity |
| Container Apps, Canada Central | 7 | 2 | 9 | Resource Graph count; new-environment CPU allocation must be checked after closed provisioning |
| Foundry accounts, Canada Central | 3 | 1 | 4 | Resource Graph count; account provisioning remains subject to ARM validation |
| Managed Redis, Canada Central | 1 | 1 | 2 | Resource Graph count; quota CLI returned BadRequest, so no numeric quota is asserted |
| ACR, Canada Central | 4 | 1 | 5 | Resource Graph count; quota CLI returned BadRequest, so no numeric quota is asserted |
| Log Analytics / Application Insights, Canada Central | 4 / 3 | 1 / 1 | 5 / 4 | Resource Graph counts; validate the concrete resources and policy |
| User-assigned identities, Canada Central | 15 | 3 | 18 | Resource Graph count; scoped role and registration permissions remain to be validated |
| Private DNS zones / WAF policies, global | 15 / 1 | 2 / 1 | 17 / 2 | Resource Graph counts; validate the concrete resources and policy |

The Canada Central quota snapshot above did not guarantee physical capacity.
Actual Redis preflight subsequently returned `CacheCapacityUnavailable` in Canada
Central and East US 2. Canada East passed that same provider check, has 1,940
available GlobalStandard model capacity units, and retains the quoted Search,
Redis, and Container Apps rates. The selected region is now Canada East.

The complete Canada East preview succeeded with 35 creates, 37 unchanged
production resources classified as Ignore, and 11 unresolved role-assignment
IDs. No production Modify/Delete was proposed. Only verified identical
before/after Ignore entries outside the staging write set may pass the boundary
guard. Unresolved role assignments remain blocked pending identity bootstrap.

After bootstrap, the platform now takes the three verified identity records as
explicit staging inputs and does not rewrite those resources. Their resource,
principal, and client IDs were compared with fresh ARM reads. The final full
provider preview has **42 creates, 1 NoChange, and 40 verified unchanged Ignore
entries**, with zero Modify, Delete, or Unsupported entries. The boundary guard
passes; production is unchanged.

The numeric hosting, model, network, storage, and shared-edge checks pass for
planning. Redis/registry allocation and the final policy payload are still
deployment-validation gates, not confirmed capacity. Do not fill missing quota
data with zero usage or an invented unlimited value.

The inventory includes two network subnets, Redis database/access configuration,
one Foundry project/model deployment, one Blob container, and resource-scoped
role assignments beneath the services above. The compiled what-if must enumerate
all of these and any platform-managed resources before execution.

[Search limits](https://learn.microsoft.com/azure/search/search-limits-quotas-capacity)
distinguish subscription quota from regional capacity.

## 7. Implementation and verification sequence

1. Review and bring across only the existing adapter, response-identity headers,
   and staging prerequisites from the integration worktree. Record a source
   commit before building candidates. Its current uncommitted state is not a
   reproducible release.
2. Add shared-profile Bicep support with uniquely named staging children.
   Preserve existing production defaults and add focused checks that reject
   production endpoint/routing changes. Create separate staging AZD settings.
3. Add a manual CoPyRIT target around `AppClient/AppSession`: one app session
   per PyRIT conversation, isolated cookies/page/thread IDs, question/revision
   tracking, bounded requests, cancellation, and cleanup. Do not reuse the
   one-case `AppTarget` as a shared multi-conversation target.
4. Disable scripted sharing probes for manual chat. Reject unsupported message
   types, edited histories, and partial/error SSE responses explicitly. Never
   reset server budgets, silently retry a failed turn, or substitute production.
5. Persist a staging-only registry initializer under the ignored local
   configuration. Keep CoPyRIT on loopback; do not enable network access or
   general unauthenticated administrator actions.
6. Verify multiple independent conversations, question/revision changes, errors,
   cancellation, cleanup, and registry restart persistence against local
   fixtures. Make no paid call.
7. After implementation and offline checks, mark the plan `Ready for Validation`.
   Invoke `azure-validate`: build/type checks, Bicep compilation, permission and
   policy checks, image provenance, and scoped what-if. Record actual results.
   Reconcile pricing and any unreported resource limits. Stop on unresolved gates.
8. Present the exact create/update list, immutable images, model/source bindings,
   access rules, and final cost estimate for **deployment approval**.
9. Only after that approval, use `azure-deploy` to provision with staging disabled.
   Establish the new identities/private origin; publish only separately approved
   agents and source snapshots. Never refresh source-review dates by copying.
10. Open only the staging validation endpoint after access approval. Check
    capabilities, source readiness, API/web release and deployment headers, and
    normal BFF ownership without model calls. Register `BC Gov staging` only when
    these match the selected deployment. Confirm its UI and restart persistence.

The user approved a US$500/month total envelope; the model allocation is now
US$1.90/day within it. The approved operator IPv4 /32 is stored only in the
ignored local environment, not in this document.
No attacker model, automated judge, adaptive campaign, GH-AW schedule, production
release gate, or load test is activated by this plan.

### Rollback

Keep staging disabled if provisioning or checks fail. For a later bad staging
revision, restore only its last verified image pair and stop admitting new
staging requests. Never disable the shared profile or change production traffic.
Remove or change only the staging registry entry when its origin is invalid.
Resource deletion and history cleanup require separate approval.

## 8. Files and validation status

| Artifact | Action after plan approval |
|---|---|
| `.azure\deployment-plan.md` | This plan; preserve the historical pilot record below |
| `infra\main.bicep`, `infra\modules\pilot.bicep`, edge modules | Reuse staging inputs; add a narrow shared-profile path |
| `infra\staging.env.example` | Confirmed subscription/region and separate environment; approval flags off, missing identity/budget/image inputs left empty |
| `evaluations\pyrit` and focused tests | Reuse transport; add a manual conversation manager and initializer |
| API/proxy identity-header changes | Reuse the existing draft so the target can verify the actual release |
| `.cache\copyrit` | Local target configuration only; dependencies, credentials and attack history stay out of Git |

### Validation proof recorded November 14, 2026

| Check | Actual result |
|---|---|
| Manual target and native PyRIT normalizer/registry | 15 passed; fixtures only, including session isolation, release drift, errors/cancellation, history rejection, and persisted budgets |
| API ownership and release identity | 43 passed; no model calls |
| Web proxy | 43 passed on Node 24 |
| Repository tooling | 99 passed on Node 24, including staging scope and preflight guards |
| Web type generation/type checking | Passed |
| Web production build | Passed on Node 24 |
| Bicep | `az bicep build --file infra\main.bicep` succeeded |
| Changed Python | Ruff passed |
| AZD project schema | Valid against the official stable `azure.yaml` schema |
| AZD local environment | `bc-pyrit-staging` created locally with the confirmed subscription/region; no remote environment or Azure resources |
| Docker build context | Both Dockerfiles use existing locked manifests; `.dockerignore` excludes local environments, `.azure`, caches and logs |
| Container packaging | API/web Linux amd64 images built and `azd package --no-prompt` passed after Docker became available; both runtime imports/non-root settings checked offline |
| Azure context and quota | Read-only inventory, usage, model availability and retail-price checks recorded above |
| ARM target-scope validation / what-if | Full Canada East provider validation and AZD preview passed with concrete identities; final scoped preview has 42 creates and no Modify/Delete/Unsupported |
| Identity prerequisite | Dedicated single-tenant staging API application/service principal created and verified for v2 tokens; no client secrets or Graph API permissions added |
| Image publication and application provisioning | Approved after completed validation; not yet performed |

`infra\staging.env.example` deliberately does not invent the missing API client
ID, application allowance, image digests, release identity, agent bindings, or
operator egress CIDR. These remain gates to cloud validation/activation.
No staging URL exists, and the running local CoPyRIT registry remains unconfigured.
The saved local AZD environment now has the verified API identity, bounded model
allowance, and approved operator /32. Execution remains gated on real validation.
The existing public pilot's source-health read on November 15 UTC found its four
indexed documents expired; fresh staging snapshots need a new exact-snapshot
review rather than rewritten source dates.
That review is now complete: the user approved the exact refreshed four-snapshot
bundle for staging only. Its publication dry run has 20 uploads, no deletions,
and no withheld documents. It has not been uploaded to any index yet.

### Section 7: Validation Proof - full closed platform

| Check | Actual execution | Result |
|---|---|---|
| Full ARM/provider validation and preview | Standard `validate-deployment.ps1`, `infra\main.bicep`, actual Canada East parameters, confirmed subscription | PASS |
| Scoped structured preview | `what-if-platform.json` plus `verify-staging-plan.mjs` | 42 creates; zero Modify/Delete/Unsupported; existing identities and production remain unchanged |
| AZD recipe preview | `azd provision --preview --no-prompt` in the selected local environment | PASS; no cloud changes |
| Packaging/build | `azd package --no-prompt`, Linux amd64 runtime checks, web/API/evaluator tests | PASS |
| Static roles | API: project/OpenAI use, Search read, Redis access, AcrPull and metrics. Web: AcrPull and internal-API caller. Publisher: scoped project/model, Search publication and staging-container write. | All 11 role assignments use the three verified staging principals and staging-only resource scopes |

The identity bootstrap and full-platform records are separate. Only this full
record can qualify the next application-platform provisioning step.
Full-platform source and parameter fingerprints are saved in the ignored
`.azure\bc-pyrit-staging\platform-validation-proof.json`.

## 9. Approval gates

- [x] Subscription, Canada Central first, US$500 infrastructure budget, and
  sharing only Front Door selected by the user.
- [x] Approve this implementation/preparation plan. The user approved repository
  implementation, offline checks, and read-only deployment validation only.
- [x] Complete focused offline checks and mark `Ready for Validation`.
- [x] Invoke `azure-validate` and record the blocked checks. The workflow remains
  at `RunValidation`; it has not qualified the plan as `Validated`.
- [x] Approve staging deployment and its required identity/permissions, conditional
  on completed validation and the reviewed resource boundary.
- [x] Approve the current-connection IPv4 /32 and the US$500 total monthly envelope.
- [ ] Verify private-origin identity and approved agent/source publication before activation.
- [ ] Deploy, verify the real staging path, and register the CoPyRIT target.

Approval of preparation alone does not authorize deployment, permissions,
public access, model spending, or scans.

## All validation checks pass

Not complete. This is the AZD recipe checklist used by `azure-validate`;
unchecked cloud checks remain blockers, not waived requirements.

- [x] 1. AZD installation: 1.37.3 available.
- [x] 2. Schema validation against the official `azure.yaml` schema.
- [x] 3. Closed-stage environment setup: verified identity, subscription/region,
  model capacity, app budget, and narrow access selection are recorded locally.
- [x] 4. Authentication check: AZD reports an existing authenticated session.
- [x] 5. Subscription/location selected and checked without changing global defaults.
- [x] 6. Aspire pre-provisioning: not applicable to this containerized app.
- [x] 7. Full provider preview after verified identity bootstrap/reuse: 42 creates,
  zero Modify/Delete/Unsupported; boundary guard passed.
- [x] 8. Build verification: API tests, web build/type checks, evaluator and tooling checks.
- [x] 9. Docker build context validation.
- [x] 10. Package validation: both services packaged; no registry publication yet.
- [x] 11. Full platform ARM/provider validation and `azd provision --preview`
  passed in Canada East.
- [x] 12. Aspire post-provisioning: not applicable.

---

## Historical optional IQ rollout

The record below concerns the existing pilot. Its earlier validation and
approvals do not authorize the proposed staging deployment.

Status: Validated

Current execution selection: Stage C2 configuration-only validation. The C1
diagnostic API and web candidates are now deployed and ready, with both research
options still disabled. Public readiness and the real managed-identity BFF's
disabled/strict-schema/ownership checks passed without model calls.
Configuration preparation and ARM validation do not authorize execution without
a fresh full ordinary-chat pass; public activation also requires the actual
private research flows to pass.

## Current Stage C2 payload

- One existing API resource only. Current API image `a46c1f7b...` and web image
  `9ed9b2c4...` are preserved; the web template is not updated.
- Payload and rollback: `.azure/iq-rollout/c2-585cf3b`.
- Validation mirror: `infra/app-image-update.bicep` with
  `.azure/iq-rollout/c2-585cf3b/activation.parameters.json`.
- Actual writes PATCH only API `properties.template`; only reviewed optional
  research environment settings and a new revision suffix change.
- Global USD 5/day, existing token/run limits, identities, access, network, scale
  and indexed source publication remain unchanged.
- C2 payload SHA256: `2fda238a41894460d449baa21b2a6ee340c2ce966a79924e3b110460c5e2aad7`
- Execution requires a successful full ordinary-chat report from the same API
  image, revision and raw template within the previous 30 minutes. Focused
  cases, read-only checks and missing evidence cannot satisfy that gate.
- The activation operator closes public exposure, checks for concurrent edits,
  applies the template, verifies the real research flows through the normal
  web BFF, and rolls back the original disabled configuration on failure.

### All validation checks pass (Stage C2)

- [x] Core validation: CLI/auth, Bicep compile, target-scope validation and
  structured what-if with exactly one existing API Modify.
- [x] Docker build: no new image; both immutable images already passed their
  target-platform checks and are running in the C1 revisions.
- [x] Azure Policy validation through target-scope validation.
- [x] Static role verification: no permission, identity or infrastructure change.
- [x] Local application configuration gates pass for the prepared draft.
- [x] Record current proof and resolve any validation errors.

## 7. Current validation proof (Stage C2)

Proof recorded at `2026-11-09T22:50:09.2456118Z`.

- `validate-deployment.ps1 -Scope group -ResourceGroup rg-bcassist-xufhsendpx
  -Template .\infra\app-image-update.bicep -Parameters
  .\.azure\iq-rollout\c2-585cf3b\activation.parameters.json -Subscription
  ad92e163-a85e-40cc-bb50-054b0b8197a8` returned `OVERALL: PASS`.
- Structured what-if confirms exactly one Modify resource: the existing API.
  There are zero creates/deletes, and the web resource is absent from the payload.
- This is configuration only; the verified API/web image digests are retained.
  Static review confirms no new identity, permission, endpoint exposure, hosting
  scale, model deployment or global budget change.
- Only the application template is patched. The validation mirror itself is
  never deployed.
- No research settings have been applied. Fresh full ordinary-chat proof is
  still mandatory before execution; actual private research checks remain
  mandatory before public activation.
- The activation operator passed eight offline transaction tests covering
  asynchronous readiness, successful closed-exposure verification, rollback,
  concurrent-change rejection and rejection of focused/stale/mismatched proof.
- The live checker was corrected to accept the API's actual ISO date-or-date-time
  review field rather than incorrectly requiring a calendar date. All 34
  release-tool checks passed. The corrected tools were staged in the owned web
  container's `/tmp/iq-c6155a97-v2` directory with checksum
  `1a19df520a451a869a6a4135ced5481d4a33044a5e1ebd2e1ef5346b7ba1c0a4`.
- The deployed API identity re-read `bc-service-research:1` and passed the
  application's exact policy/model/tool-free verification without model calls.

## Completed C1 diagnostic candidate

- API source `585cf3bba8b017a780daab219615e0e6c291f3e1`, immutable image
  `crbcassistxufhsendpx.azurecr.io/bc-government-assistant/api-bc-pilot@sha256:a46c1f7b5ee6fde089c1e19597e9fd0df870048baa5b35c58c479d9b5c1ab823`.
- Web source `90506663a7b56dad3162e7e2628a6c1db5d17a3a`, unchanged candidate
  `crbcassistxufhsendpx.azurecr.io/bc-government-assistant/web-bc-pilot@sha256:9ed9b2c4cacd4ba237da985ebc64cf9bfc6edc105cc29a435fddf48c4fddc6f5`.
- The diagnostic API image was built for Linux amd64, verified as UID 10001,
  smoke-tested with networking disabled, and pushed with the matching source
  label. Production without configured controls still fails closed, all seven
  development guides load, and the temporary mirror file is absent in the image.
- New rollback snapshots, raw-template/configuration/identity hashes and exact
  image-only patches are under `.azure/iq-rollout/c1-585cf3b`. The original
  snapshots were not overwritten. Current rollback revisions end in
  `iq-rollback-1794211435`.
- Validation target: `infra/app-image-update.bicep` with
  `.azure/iq-rollout/c1-585cf3b/image-update.parameters.json`. The mirror must
  never be deployed; actual writes contain only `properties.template`.

### All validation checks pass (current C1 retry)

- [x] Core validation: CLI/auth, Bicep compilation, target-scope validation and
  structured what-if, modifying only the two existing apps.
- [x] Docker build and target-platform offline smoke; immutable pushed digest.
- [x] Azure Policy validation through target-scope validation.
- [x] Static role verification: no new grants; same app identities and AcrPull
  relationships, with no identity/configuration/network/scale change.
- [x] Record current proof and resolve any errors before marking Validated.
- Deployment remains conditional on fresh compare-before-write checks and the
  existing protected-exposure and rollback procedure.

## C1 diagnostic validation proof

Proof recorded at `2026-11-09T09:09:16.2575801Z`.

- `validate-deployment.ps1 -Scope group -ResourceGroup rg-bcassist-xufhsendpx
  -Template .\infra\app-image-update.bicep -Parameters
  .\.azure\iq-rollout\c1-585cf3b\image-update.parameters.json -Subscription
  ad92e163-a85e-40cc-bb50-054b0b8197a8` returned `OVERALL: PASS`.
- The structured what-if has exactly two Modify resources (the existing API
  and web), zero Create and zero Delete resources. The actual patch remains
  narrower than the mirror and excludes configuration and identity.
- Existing secret values were read only for secure ARM validation and were
  neither printed nor included in the actual patch. They must be removed from
  the private parameter file after this validation stage.
- The diagnostic API's registry digest, source label, architecture, non-root
  identity, fail-closed production behavior and seven-guide offline smoke are
  verified. The unchanged web candidate retains its previous verified build.
- Static identity/role relationships are unchanged. No model deployment,
  capacity, quota, network or cost-limit change is included.
- The initial image build encountered the same upstream TLS handshake problem;
  the existing temporary Microsoft mirror restored the pinned dependency
  without disabling certificate validation. The Windows credential-helper error
  was resolved with a private generated Docker auth file, removed after push.
- This validated an image-only retry, not research activation. It was subsequently
  deployed as API/web revisions ending `iq-585cf3b`; private health and public
  read-only checks passed, and both IQ flags remain disabled.

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

### Offline continuation while admission is blocked

- The user directed continued autonomous work. No allowance, access role, model
  capacity or public research flag has been changed.
- Focused release cases now support `--case=job-loss`; the result explicitly
  reports focused coverage and cannot replace the complete release gate.
  Exact known error messages map to static failure-stage labels without echoing
  provider text.
- Planner failure diagnostics now log only allowlisted response status,
  incomplete-reason labels, call counts and fixed cross-field validation-rule
  labels. Unknown values stay unclassified. This improves the next reproduction;
  it does not establish or claim to fix the original planner failure.
- `scripts/verify-optional-research.mjs` now provides a bounded real endpoint
  check for both supplements, rejected page binding, separate provenance,
  immutable ordinary conversation state, cancellation, normal next Send and
  page revocation. It clears only its own synthetic state and makes no live
  calls without both explicit approval flags.
- Offline results: 32 release-tool tests, 55 native/conversation tests and API
  lint passed. The linked workspace's resource-specific console table had no
  retained rows for the narrowly queried failed-case window; no raw model data
  was queried or reconstructed.
- The diagnostic API change requires a new immutable candidate image. The
  existing web candidate is unchanged. That new image and fresh target-scope
  validation are now complete, as recorded in the current C1 section.

### Prepared research configuration (not applied)

`.azure/iq-rollout/research-environment-draft.json` passes the application's
configuration gates locally but has not been applied to any live app.

- Pinned answer agent `bc-service-research:1`, existing `bc-fast` model, and the
  previously verified source/base bindings. No new model or index is proposed.
- Retain the conservative USD 1 provider reservation used for IQ validation,
  capped at USD 2/day for that provider. This is an application processing
  allowance, not a quoted or guaranteed Azure invoice maximum.
- Web IQ reserves USD 0.021/run (three USD 0.007 search-call equivalents), capped
  at USD 0.105/day. The application allows at most five optional runs per
  provider per day, with one optional run concurrently.
- The existing global USD 5/day limit, model reservation, token/run limits,
  normal-chat capacity and hosting scale are unchanged.
- Only `service-bc`, `health`, and `healthlink-bc` use their existing registered
  public source prefixes and 200-character display limits. Browse stays off.
  Owner-approved public-topic logging is true; Zero Query Logging remains false.
- Approval references point to this session's actual owner and technical
  records, not invented Microsoft approvals. Public activation remains
  conditional on the ordinary-chat and actual supplement checks passing.

### Next admitted execution

1. Re-read the shared ledger and current app templates. Do not clear counters,
   refund uncertain work, raise limits, or overwrite a concurrent deployment.
2. Deploy the validated diagnostic image-only payload using the fresh C1
   snapshots and protected-exposure procedure. Wait for public-edge recovery.
3. Run only the focused job-loss case first. If it fails, use the fixed client
   stage and allowlisted server diagnostics to establish the cause before
   changing planner behavior or spending on a full-suite repetition.
4. Require the complete ordinary-chat release suite before executing the
   separately prepared and validated configuration-only payload.
5. Hold public exposure closed while running the actual bounded research
   verifier through the owned web container's normal managed-identity BFF path.
   Never interpret provider connectivity alone as a successful supplement.
6. Only after all gates pass, restore public exposure, verify the live UI, run
   one matched six-sample default-answer latency set and confirm corpus
   immutability. Keep original images/configuration for guarded rollback.

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

## Previous Stage C1 validation proof

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
