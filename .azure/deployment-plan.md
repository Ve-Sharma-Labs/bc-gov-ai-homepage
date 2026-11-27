# Saskatchewan application hosting preparation

Status: Ready for Validation (API answer-quality release)

## Saskatchewan homepage and link-preview release, 2026-11-26 UTC

The requested web-only release adds editable example questions and an Open
Graph/Twitter preview titled "AI at Government of Saskatchewan". The user
confirmed that the supplied wordmark is authorized for public link-preview
use; this does not establish approval for other uses or imply endorsement.
The existing pilot disclosure remains in the preview.

The linux/amd64 image `sk-web-homepage-local:current`, index
`sha256:69858469ca67565dfbd89e7bed960a93107361b0883d297ce2242e11d6e1c03a`,
was built and locally served the Saskatchewan homepage, examples and both
social images with the public origin. It was pushed to the existing registry as
`gov-platform-web:sk-homepage-69858469ca67` and has not been deployed.
The live web revision remains `ca-skassist-rywtikimq4-web--0000001`.
The live web container has no `SITE_URL` setting. The scoped release must
set it to the existing public Front Door origin so link-preview URLs do not
point to localhost, while preserving all unrelated container settings.

All validation checks pass:
- [ ] Core validation: a validation-only web snapshot passed CLI,
  authentication, Bicep compilation and provider validation. A narrower
  preview reported only one modified web app, but predicted removal of its
  existing secret and could not resolve the secure environment comparison.
  The mirror must not be deployed; it does not prove that the actual PATCH
  preserves all existing configuration.
- [x] Docker build and local image verification.
- [x] Existing web managed identity has `AcrPull` on the registry.
- [ ] Azure Policy validation: eleven existing noncompliant records remain;
  no resource-group exemptions were listed, and the web app itself returned no
  noncompliant policy records. These are not evidence of an Azure denial. The
  required validation workflow is incomplete.

## Saskatchewan web POC released, 2026-11-27 UTC

The latest `origin/main` was fetched at
`94951b4b98e25ff0f9fbe291c0800cfe1a2dc4be` and merged into this branch as
`7ca84588566d7ca1dc4212c422822c634f58aaa9`. The full local worktree was
snapshotted and verified before integration; the original 26 staged BC asset
deletions and all local files were restored. The social card combines the
latest main behavior with the jurisdiction-specific bundled logo. Focused web
tests passed (34), Foundry evaluation tests passed (64), Foundry/release
workflow tests passed (36), and web TypeScript checking passed.

The merged Saskatchewan web image was built for Linux amd64, locally
smoke-tested, and pushed as
`crskassistrywtikimq4.azurecr.io/gov-platform-web@sha256:b590fde153743eb4d37de7aa7e151edf5f01978fc92cc6ec2fb3127fc2a2e2f7`.
Only `ca-skassist-rywtikimq4-web` was updated, to revision
`ca-skassist-rywtikimq4-web--sk94951b4`, with the public `SITE_URL` set to
the Front Door origin. The revision is healthy and receives 100% of web
traffic. A comparison with the prior revision confirmed the template is
unchanged apart from the image and added `SITE_URL`; the
`CLIENT_HASH_KEY` secret reference is intact. The API remains on revision
`ca-skassist-rywtikimq4-api--0000001`; the WAF, framing protection and BC
deployment were not changed.

Cache-busted public checks returned HTTP 200 for the homepage, `/chat`,
`/api/capabilities`, `/opengraph-image` and `/twitter-image`. The live page
shows the title “AI at Government of Saskatchewan,” the Saskatchewan example,
and public canonical/social-image URLs; both image endpoints returned PNG.
Capabilities reported `jurisdiction=sk`, `retrievalReady=true` and 42 usable
documents. `X-Frame-Options: DENY` remains set.

This is the requested POC web release, not completion of the broader Azure
validation workflow. The 11 existing audit/audit-if-not-exists findings and
the approved policy-remediation follow-up remain separate work. Search logs
were not enabled; private networking, image scan state, source refresh,
ownership and evidence expiry were not changed or asserted as resolved.

## Current Saskatchewan image candidates, 2026-11-26 UTC

The user reaffirmed immediate deployment of the public Saskatchewan pilot.
Full PyRIT evaluation is BC-specific and is not a prerequisite for this
Saskatchewan image update. Source refresh, operational ownership, image
scanning and existing policy findings remain real follow-up risks; do not
represent them as completed or extend the existing source evidence.

The merged worktree was built as Linux amd64 images and published to the
existing Saskatchewan registry:

- API index `sha256:102b31eb230ecdb55e5ff4036fec962aa776c750cf072cb834cc3436018ebc34`
- Web index `sha256:349d4788531ce63e6af621eec7b33d1e54ac8bea4d8a1d840673bb01db403410`

The API build used the configured Microsoft package mirror after the PyPI
build dependency download failed TLS. The web image served the Saskatchewan
homepage with the public origin locally; the API health endpoint and
Saskatchewan capabilities responded in development mode. Production startup,
Azure configuration preservation, provider validation and rollback for these
exact images still require verification. The existing public apps have not
been updated. Source evidence begins expiring on 2026-12-01 at 16:06:05 UTC.

## Main integration and current release blockers, 2026-11-26 UTC

The fetched main branch has been merged into the local feature branch; the
prior local work and staged asset deletions were restored. The live application
was not changed. The new PyRIT release tooling is BC-specific: it requires
BC-brand approval, protected main-branch execution, separately provisioned
staging and production contexts, a private probe, matching evidence and a
specific edge topology. It is not yet a Saskatchewan release path and must not
be run against Saskatchewan without a separately validated adaptation.

The current Azure Policy query returned eleven noncompliant resource-policy
records under one assignment, affecting Search, Foundry, ACR and the apps and
private-endpoint subnets. Search log collection can contain user query terms;
the record must not be cleared by enabling unreviewed logging. Defender still
showed 10 unhealthy records for the live web image and 16 for the live API
image, with no records for the final candidate child digests. Missing records
do not establish scan completion. The public homepage returned HTTP 200 and
capabilities reported 42 usable documents, with first expiry
2026-12-01T16:06:05Z.

The public-stage WAF deployment succeeded on 2026-11-25 UTC. The live policy
is in prevention mode with both managed rule sets and the API rate limit.
After initially returning 403 under the previous `ValidationOnly` rule, the
public homepage returned 200 at 05:48 UTC. Live public checks of the homepage,
about, credits, Saskatchewan favicon and five chat questions are described
below. Answer quality, source refresh ownership and public-facing rights
wording remain release limitations.

## Public data-plane checks, 2026-11-25 UTC

- The homepage, `/about`, `/credits` and `/favicon-saskatchewan.ico` returned
  HTTP 200; homepage metadata points both icon relations to the Saskatchewan
  favicon. The homepage contains Saskatchewan content without a BC domain.
- Actual public HTTPS chat requests completed for licence renewal, health card,
  licence fee, Income Support and an unsupported question. The fee response
  withheld conflicting amounts and linked to SGI; the unsupported question
  returned the prescribed navigation response. Income Support included a
  complete list and official source on this run.
- The licence-renewal response included useful guidance and the SGI link but
  also introduced payment options without listing them. The agent instructions
  already prohibit unfinished lists, so prompt instructions alone are not a
  verified fix. These checks do not establish that all questions are reliable.
- The earliest indexed-source expiry remains 2026-12-01T16:06:05Z; ongoing
  Saskatchewan refresh and withdrawal ownership is not established.
- At 2026-11-25 09:22 UTC, the public homepage and capabilities endpoint
  again returned HTTP 200; capabilities reported retrieval ready with 42
  usable documents and the same earliest expiry.
- A read-only Search metadata query on 2026-11-25 returned 157 active chunks
  for 42 distinct documents, with consistent `checkedAt` across each document.
  At the API's default seven-day maximum age, all 42 expire on 2026-12-01,
  between 16:06:05Z and 18:20:22Z. The live container has no explicit
  `SEARCH_MAX_AGE_DAYS` override, and the exact running API image reports a
  seven-day default. This query did not reacquire content or
  authorize a refresh; once all evidence expires, retrieval fails closed.
- Public credits and about copy still describe public-release permission as
  unapproved or unverified despite the user's attestation. Correcting the
  manifest changes the reviewed pack identity and requires a properly rebound
  review, index publication and image deployment; do not bypass the binding.
- Browser approval was denied earlier, so these checks used HTTP and the
  actual public chat protocol rather than an interactive visual browser test.
- A later HTTP recheck returned 200 for the homepage, about, credits, the
  linked Saskatchewan favicon and capabilities. `/favicon.ico` returned 404;
  the page explicitly links `/favicon-saskatchewan.ico`. Canonical and Open
  Graph URLs still point to localhost. Capabilities still reported 42 usable
  documents and the same earliest expiry.
- A separate network freshness monitor is not ready: the existing acquisition
  manifests have exhausted their 15-request limits. Initializing a new monitor
  with an independent budget would not preserve those limits, so the unfinished
  prototype was removed. Durable budget continuity, controlled rendered-source
  capture, review, publication and withdrawal remain unresolved.
- A local watchdog fix prevents a second checkpoint write after an uncertain
  write failure, so an uncommitted reservation cannot be followed by a
  publisher request or an automatic retry of the failed write. The existing
  watchdog remains separate from SK acquisition; this change does not
  authorize a new budget or establish SK refresh. It has not been deployed.
- A read-only checkpoint inspection confirms that both authorized SK acquisition
  runs remain paused at 15 of 15 requests; the preserved synthetic run is
  separately bound to synthetic rights and cannot be reused for live sources.
  The deployed API has source metrics enabled, but no metric or scheduled-query
  alerts were listed in the SK resource group. Metrics are not a refresh process
  or a substitute for an assigned operator and notification route.

## Prepared source-health alert

Prepare a separately scoped scheduled log alert against the existing SK
Application Insights metrics and Log Analytics workspace. It must warn before
evidence expiry, on unhealthy or missing source telemetry, and never fetch
publisher content or change a source budget. Require an existing action group
with an assigned operator rather than silently creating a notification-free
alert. This alert incurs Azure Monitor charges; verify price, the query, action
group, privacy, policy compliance and exact resource-only what-if before
deployment. It does not approve or refresh evidence.
The prepared `infra\sk-source-health-alert.bicep` uses the SK API's exact
Application Insights resource and role, a 15-minute observation window and a
72-hour expiry threshold. The rule defaults to requiring the new expired-document
and missing-source metrics, and alerts when they are absent. A temporary
`requirePartialLossMetrics=false` compatibility mode can use the live API's
baseline metrics to detect imminent expiry, missing baseline telemetry,
unhealthy status or total loss; it cannot detect every partial source loss.
Switch to strict mode after deploying the updated API.

The prior strict-only template passed provider validation and a resource-only
what-if showing one alert creation. After adding compatibility mode, Bicep
build and lint passed and the exact KQL passed 24 synthetic cases across both
modes, including missing baseline and partial-loss metrics. Against live
telemetry the strict query returned one alert row and the compatibility query
returned none. Provider validation of compatibility mode succeeded. A
full-resource what-if showed only one creation, `sk-source-health`; its
evaluated query used `False` for compatibility mode and returned no alert row
against live telemetry. The synthetic cases also passed with the provider's
boolean spelling. This preview does not clear policy, cost, ownership or
notification-delivery checks. No action group exists
in the SK resource group; the subscription's `AGOwner` group was used only as
a validation placeholder, and its suitability has not been established.
The KQL integration cases are now retained in
`infra\tests\test_source_health_alert.py`, opt-in via a workspace customer ID;
both configured and unconfigured test paths were checked.
The API source-health tests also cover the inspected mixed case: one current
document, one expired document with duplicate chunks and a missing source
produce the corresponding partial-loss telemetry while status remains ready.
The Azure Retail Prices API returned USD $1.50 per month for the Canada
Central five-minute log-alert meter on 2026-11-25. The rule has no dimension
split; Microsoft says the first time series is included. This is a retail
estimate, not the subscription's invoice price, and excludes separately billed
telemetry ingestion and notifications.
Notification delivery, alert-engine behavior, price, responsible ownership and
Azure Policy compliance remain unverified. Neither change is deployed.
Application Insights metrics were present; no Container Apps console records
were observed in the workspace over the checked period.
The existing `AGOwner` group is enabled and has an email receiver and an
Azure Owner role receiver. The signed-in account does not match the direct
email receiver. A read-only role-assignment check found one directly assigned
subscription-level Owner user, who is not the signed-in user; two further
direct Owner assignments are service principals. Microsoft documents that
[role-based email notifications](https://learn.microsoft.com/azure/azure-monitor/alerts/action-groups)
require a subscription-level user or group assignment, and can include other
eligible role members. This does not establish a responsible operator,
effective delivery or an approved source-health notification route.

## Private-link investigation

The existing Foundry account reports private-link group `account` and requires
the `privatelink.cognitiveservices.azure.com`, `privatelink.openai.azure.com`,
and `privatelink.services.ai.azure.com` DNS zones. Search reports group
`searchService` and zone `privatelink.search.windows.net`. The existing VNet
uses Azure-provided DNS and has a separate private-endpoint subnet. On
2026-11-25 UTC, Search reported Basic tier and both Search and Foundry reported
public network access enabled in Canada Central. The `/24` private-endpoint
subnet reported one existing endpoint, Redis. No matching Search or Foundry
private DNS zones appeared in the subscription zone listing. These are
read-only findings, not proof of working private connectivity. Before changing
access, validate DNS and authenticated API, agent, image-pull and ingestion
paths from their actual networks, including rollback and costs. Do not disable
public access before those checks or affect public Front Door access.
Microsoft's Foundry guidance distinguishes inbound private endpoints from
outbound agent network injection and says an existing deployment cannot have
outbound VNet injection added without redeployment:
https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/configure-private-link

Prepare a separate, Search-only private endpoint and DNS integration candidate
against the existing VNet and Search service. It must not change Search public
access, the Foundry account, Container Apps, or the index. This is preparation
and provider preview only, not authorization to apply the template: linking
the private DNS zone could redirect live application traffic. Before any
deployment, check exact-scope what-if, policy, costs, DNS conflicts, client and
publisher connectivity, ownership and rollback, then complete the required
Azure validation workflow.
`infra\sk-search-private-endpoint.bicep` now compiles and lints. Provider
validation succeeded against the SK resource group. Its full-resource what-if
reported exactly four creations: the Search private endpoint, DNS zone,
VNet link and endpoint DNS zone group, with no other non-ignored resources.
This is not a connectivity test or policy approval, and no deployment occurred.
[Microsoft's Search guidance](https://learn.microsoft.com/azure/search/service-create-private-endpoint)
supports private endpoints on the existing Basic tier; it also confirms the
endpoint is separately billable. A VNet link may affect DNS for other Search
services, so inventory and test all consumers before enabling it.
The live VNet has an apps subnet delegated to the Saskatchewan Container Apps
environment and a private-endpoint subnet containing Redis. The SK resource
group lists the API and web apps in that environment; this inventory does not
establish every DNS consumer or publisher network. The subscription currently
lists 19 private DNS zones and no `privatelink.search.windows.net` zone.
Azure retail pricing lists a global Standard Private Endpoint at US$0.01/hour
and private DNS zones at up to US$0.50 per zone-month for the first 25 zones.
At 730 hours, these are approximately US$7.80/month for this endpoint and zone,
excluding data processing, DNS queries, taxes and subscription-specific
discounts. This is not a quote or a complete network-isolation estimate.

## Prepared API answer-quality update

### API-only release preview investigation

A session-only Bicep probe targeting just the existing API compiled and
produced a resource-group what-if on 2026-11-25 UTC using the live image as a
no-op input. The API was the only non-ignored resource, but what-if reported
modifications to identity, configuration, template, workload profile and
tags despite supplying the live state as a secure object. It did not
provide a sufficiently granular preservation proof. This preview did not
deploy anything and is not release validation; do not deploy the probe.
The live API was in single-revision mode with one `main` container and no
configured secrets at the time of the check. A scoped release still needs a
reliable preview, concurrency protection, rollback verification and the
other validation gates described in this plan.

A separate **redacted, preview-only** probe removed null and unsupported
read-only fields from the live response before submission. The provider
accepted it. With the current image, what-if reported only the 71 deliberately
redacted environment values; with the previously pushed image candidate, it
reported those same redactions plus the image change, and no other property
changes. Both previews targeted only the API resource. The helper is
`files\sk-api-redacted-whatif.ps1` in the session workspace. The old candidate
has known Defender findings and is not the final patched image. These probes
do not establish preservation of actual environment values, protect against
concurrent changes, validate the final image, or clear the policy gate. The
redacted probe must never be deployed.

A second session-only probe passed the actual environment as a secure
parameter and used a writable-only snapshot for the other fields. Its
what-if identified only an unresolved secure environment expression with
the current image, and that expression plus the final API candidate image
with the candidate digest. No other resource or property changes appeared.
The helper is `files\sk-api-secure-whatif.ps1`. The secure environment is
not evaluated by what-if, so this is not proof of environment preservation
or provider acceptance of those values, nor protection from concurrent
changes. This probe is not a deployable release template and does not clear
the policy or Defender gates.

The Container Apps update API documents JSON Merge Patch, but its `containers`
field is an array, so supplying only an image would replace the array rather
than merge an individual container's fields. On 2026-11-25 UTC, read-only GETs
of both live apps using API version `2025-01-01` returned no `etag` in the
resource body or HTTP ETag header. Their latest revisions were both `--0000001`.
These observations do not establish an atomic concurrency guard; do not assume
an `If-Match` header protects a release or submit a partial container array.

The user approved fixes and continued deployment. Build a Saskatchewan API
image from the previously verified release snapshot with only the tested
incomplete-options safeguard and its associated test and documentation
changes. Retain the existing source-rights pin, knowledge index, web image,
public Front Door stage, WAF rules, private origin and deployment identities.
Validate the exact image and scoped deployment before replacing the API
revision. Smoke-test public chat and preserve rollback to the prior immutable
API image. Do not deploy the former `closed` parameter file as-is: it would
disable the public endpoint.
The new immutable image is
`crskassistrywtikimq4.azurecr.io/gov-platform-api@sha256:a2c0aee4fb59f52b36f080ee7836a40df17bf6350b4d28eb17cc786413e89884`.
This image predates the subsequent local safeguard refinement requiring the
promised number of options when the introduction specifies one through ten.
An offline local image `sk-api-options-count:local` was derived from that
verified baseline by replacing only its installed `bc_api/output.py` with the
tested source. Its local image ID is
`sha256:9707012057da5ec397e095ee696a785d114e7ed59bf7439a00b17dad0f22aa7f`;
this is not a pushed registry digest. A later regression exposed that a list
immediately following its introduction without a blank line could bypass the
count. The corrected candidate `sk-api-options-inline:local`, local ID
`sha256:d077912cd7f55fd9b6ce1835be0539e539b88e12f9c9ea182efcf469c89fc217`,
was rebuilt offline for linux/amd64 from the same verified baseline. Its
installed `output.py` SHA-256 is
`fb74ab9e5d128f714c709b7aee82929a3f08f9192a1a551fa5a5a4ad71cf6a53`.
Offline checks confirmed it holds an incomplete adjacent list and accepts a
complete one; 56 focused streaming, retry and evidence-boundary tests and
the changed API files' Ruff checks passed. This candidate is not pushed or
deployed; its context is `files\sk-options-inline-20261125`. Earlier offline
image checks verified the module
hash, selected Saskatchewan pack, rights binding and option-count behavior.
This image also predates the new source-health metrics and cannot support the
revised alert. A new offline candidate `sk-api-source-metrics:local`, local ID
`sha256:15aeb0ec63f8bf4246301011e83bf5f37e27cb37ec2395ed0f3e74e38db897f1`,
was built for linux/amd64 from it by replacing only `bc_api/telemetry.py`.
The installed telemetry SHA-256 is
`dc885acc4a48951192bfe8c61c2840500cf22302f29703b8225a23f74eed4840`,
and the output safeguard hash remains unchanged. An offline image check
verified the new source-count emissions. This is not a pushed registry digest
or a validated deployment; exporter delivery and the exact combined release
still need verification.
The normal source Docker build failed while pip attempted to install isolated
build dependencies; the derived build retains the baseline dependencies and is
recorded separately. Reproduce and publish the exact image before validating a
release; do not claim the earlier image contains the refinement.
The original API image is retained for rollback. The release snapshot differs
from the previously verified snapshot only in the two API files, their focused
regression test and API documentation. The image was built for linux/amd64 and
its selected SK jurisdiction, rights pin and options safeguard were checked.
The 54 focused streaming, retry and evidence-boundary tests and API lint pass.
Use `files\sk-options-fix-validation-parameters.json` for read-only validation;
it contains a placeholder key and must never be used unchanged for deployment.
The deployment has **not** been applied: provider validation and Bicep lint
passed, but Azure Policy reports existing noncompliance in this resource group
for Redis diagnostics, ACR image vulnerabilities and network isolation, and
Search/Foundry diagnostics and network isolation. Search and Foundry currently
have public network access enabled; the ACR is Basic and publicly reachable
with authentication. The proposed full-hosting what-if also affects 18 resources,
including the Front Door origin, WAF and Redis assignment; it is not sufficiently
scoped for an API-only change. No resource deletions were returned in the
structured what-if, but property removals and six unsupported role-assignment
predictions require separate review. Do not mark this release validated or
deploy it until the policy findings and deployment scope are resolved.

The public homepage also emitted `localhost:3000` for canonical and social URLs.
The Saskatchewan-only hosting configuration now supplies `SITE_URL` from the
Front Door public origin, leaving BC unchanged. The released web image was
verified locally with that runtime variable: canonical, Open Graph and Twitter
image URLs used the public HTTPS origin. The local Bicep compiles and the
Azure what-if includes the new web variable. This configuration is not deployed.
Local web changes also replace unavailable guided-plan recovery messages and
links with official-services guidance when guided journeys are disabled;
the existing BC recovery is retained. These web changes require a newly built
and validated Saskatchewan web image and are not deployed. The Saskatchewan
production web build completed locally using the existing dependencies.
Focused web tests
cover both jurisdictions, stream and HTTP errors, and recovery links. A later
policy-state query still returned the same ten noncompliant records, so the
release gate remains blocked.
The local Saskatchewan homepage also reports when reviewed source answers are
unavailable, including when source loss makes AI configuration report false;
BC's guided-plan status is unchanged. This change postdates all previously
pushed web candidates, which do not include it and must not be represented as
the current web release.
The updated source-status web image was subsequently built for linux/amd64,
served the Saskatchewan homepage locally with the public origin and no runtime
npm, and pushed for scanning on 2026-11-25. Its index is
`sha256:96328085789ac2b015964728f0a3e9d0b4c1dbb42c0c818038b4050e5c4f2930`,
its linux/amd64 manifest is
`sha256:a91d5e329fba4583f09a4b372e488f2fe586a1913b14138dbb0d1303c4b1ad18`,
and its tag is `sk-source-status-96328085789a`. It is not deployed; Defender
scan coverage and the release gates remain unverified. A follow-up Resource
Graph query still found no individual assessments for the previous no-npm web
candidate, the latest web candidate, or the patched API candidate, while returning 10 and 16 unhealthy
assessments for the running web and API images respectively; absence is not
proof that a candidate was scanned clean.
The Azure validation workflow is at recipe-specific checks. A fresh
resource-group policy-state query still reports ten noncompliant records, so
the release is not validated. The proposed full-hosting template and existing
preview-only API probes do not yet constitute an exact, concurrency-safe
release for the latest image digests.
Search diagnostic logs can include query terms; do not enable them merely to
clear the policy finding without preserving the application's privacy controls.
The Search service currently exposes only `OperationLogs` as a log category;
`AllMetrics` is metrics-only. The assigned Search logging policy requires at
least one enabled log category, so metrics alone do not satisfy it. The separate
AI-services diagnostic policy checks for a log setting. No privacy-preserving
Search log destination or filter has been verified.
Microsoft's [Search monitoring guidance](https://learn.microsoft.com/azure/search/search-monitor-queries#return-query-strings-entered-by-users)
explicitly demonstrates extracting user query strings from `Query_s` after
resource logging is enabled. It does not establish that the current SDK's
POST requests exclude query text from those records.
The live Foundry account already has an inherited `allLogs` diagnostic setting
to the management-group governance workspace, whose reported retention is 30
days. A field-name-only query over its 265 recent `RequestResponse` records
showed metadata keys, including `path` and token counts, but no prompt or
response-payload key; this sample does not establish that logs can never
contain sensitive data. The governance workspace's access controls and
potential contents of path or other values remain unverified. Do not copy raw
logs into reports or assume the application controls this destination.

For a separate Redis audit remediation, `infra\sk-redis-diagnostics.bicep`
targets only the existing Redis database and existing Log Analytics workspace.
The inherited management-group policy requires an enabled `allLogs` category
group, not merely a named category. The live Redis database currently exposes
only `ConnectionEvents` in that group. Microsoft documents that these events
contain connection and authentication metadata, including client IP addresses,
not Redis command bodies. The group can expand in future, so category membership,
workspace access and retention must be reviewed before deployment and monitored
afterward. A read-only check on 2026-11-25 found the pilot Log Analytics
workspace has 30-day default retention and public ingestion and query endpoints
enabled. Inherited subscription and management-group roles include Owners,
Contributors and a Log Analytics Contributor; principal identities, group
membership, effective data access and any future table-specific retention remain
unverified. The Redis resource exposed `ConnectionEvents` at that check, and
no Redis-named table was present in the workspace table listing. These facts
do not establish acceptable access or retention for future logs. The validation
helper passed compilation, provider validation and
what-if for this template on 2026-11-25 UTC. The structured full-resource
what-if identified exactly one creation: the database diagnostic setting;
it identified no other modifications or deletions. Bicep emitted BCP081 for
the existing Redis API types, which provider validation accepted. The helper's
text summary counted two creates; the structured result is authoritative.
This is not a completed policy validation or deployment: all policy failures
and the privacy implications remain open.

The Search service currently exposes only `OperationLogs` and `AllMetrics`.
Microsoft documents that Search operation logs can capture query strings and
that this log category does not support ingestion-time transformations. Do not
enable it or claim redaction without a separately verified privacy-preserving
design. The retrieval path currently supplies the user's query as
`search_text`; `logging_enable=False` disables SDK logging but is not evidence
that Azure resource diagnostics omit it. Microsoft's query-log documentation
shows `Query_s` containing query strings, and does not establish that POST
request bodies are excluded in all service logs. A change to POST alone is not
a proven privacy control. The two assigned Search logging policies require log entries in a
diagnostic setting, with one explicitly requiring an enabled log; metrics
alone do not satisfy them. The service currently exposes no separate audit-log
category. References: [Search query logs](https://learn.microsoft.com/azure/search/search-monitor-queries#return-query-strings-entered-by-users),
[Search monitoring data](https://learn.microsoft.com/azure/search/monitor-azure-cognitive-search-data-reference#resource-logs),
and [Redis connection logs](https://learn.microsoft.com/azure/redis/monitor-diagnostic-settings#contents-of-the-connection-logs).
The latest policy-state query found ten noncompliant records across Redis, ACR,
Search and the AI account. Defender for Containers is Standard with registry
vulnerability assessment enabled, but the registry assessment queried by the
policy was not found in the prior registry-level query. A later subscription
assessment query found unhealthy image-level findings. Manifest inspection maps
16 findings to the running API's linux/amd64 image and 10 to the running web's
linux/amd64 image; these include findings rated Critical in OS packages. The
previously pushed API candidate has 16 image-level findings and is not a clean
replacement. These are scanner findings, not proof of exploitability. The local
web dependencies now pin Next.js 16.4.5 and Azure Identity 4.14.1, resolving
MSAL Node 7.2.2. The API lock updates oauthlib, OpenTelemetry and soupsieve to
scanner-recommended fixed versions. Python and Node base images were refreshed;
the web runtime upgrades Alpine packages. The built linux/amd64 API image
`sha256:59d333ea075684cfb67842960a5430ae44998e4498a243df627ac43af5a89c5d`
contains the updated Python packages and Debian versions meeting the observed
OS fix versions, and passed `pip check` and a development-mode health check. The
web image `sha256:a2f919901a9301de9ceb0d6e484b7fa4718553fba22753c19c8238932c97fb83`
contains the updated Node packages, Alpine OpenSSL 3.5.9-r1 and zlib 1.4-r0.
The final web image served the SK homepage with the configured origin locally.
Both SK and BC images built, and 69 focused web tests and 82 focused API tests
passed locally. These images came from the current worktree, not the previously
verified release snapshot. A file-by-file SHA-256 comparison found the API's
installed API modules, six ingestion modules and all 27 selected jurisdiction
files identical to the preceding prepared source-metrics candidate; dependency
and base-image changes remain intentional. The images were pushed to the SK
registry for Defender scanning on 2026-11-25 UTC, but are **not deployed**:

- API index `sha256:59d333ea075684cfb67842960a5430ae44998e4498a243df627ac43af5a89c5d`,
  linux/amd64 manifest `sha256:2ee208a4121d25fd1724ddbaaffa9961a31e9ac38111ab0b059543a9522a9d6e`,
  tag `sk-security-59d333ea075684cf`.
- Web index `sha256:a2f919901a9301de9ceb0d6e484b7fa4718553fba22753c19c8238932c97fb83`,
  linux/amd64 manifest `sha256:b641dfeb81a0a002279053c631384aab5e09acdeb2e217db796a0701395996e5`,
  tag `sk-security-a2f919901a9301de`.

A subsequent Resource Graph inspection found the subscription exposes
individual `microsoft.security/assessments` rather than subassessments; prior
zero-subassessment queries could not establish scan coverage. The web
candidate's linux/amd64 digest has six unhealthy individual findings, three
rated High: `brace-expansion`, `minimatch` and `undici`. The remaining three
are rated Medium. All six detected package versions were verified under the
globally installed npm in the previous web image. No individual assessment for the API
candidate was found; that does not prove a completed clean scan.

The final web runtime now removes the unused globally installed npm and its
`npm`/`npx` entry points after dependencies have been installed in the separate
target-platform stage. Both SK and BC linux/amd64 images built and served their
respective homepage locally; the SK homepage used the configured origin. The
new web index digest is
`sha256:cdd46f98ad849dead4bf44f1ed39a2b36742d6813321c600546b14ac39eb3996`
and its linux/amd64 manifest is
`sha256:9e69240d761dd1c34dff11d2129b67289bfbfb7bbd394447b7f643dab4a5960d`,
tagged `sk-security-no-npm-cdd46f98ad84`. It was pushed for scanning and is
**not deployed**. Independent Defender coverage, any remaining findings,
live-backend behavior, policy convergence and release validation remain open.
The legacy
ContainerRegistry pricing entry is Free and is not evidence that the enabled
Containers plan is off.

An isolated, offline branding re-review has been prepared under
`files\sk-brand-review-source`: it records the user's permission attestation
without claiming independent publisher verification, and rebinds the changed
manifest to a new rights review. Its plan covers 42 documents and 157 chunks,
retaining the original acquisition timestamps; this is not a fresh collection.
The first plan contains 157 prior-index deletion candidates and must **not**
be published to a shadow index as-is. A separate offline
`brand-shadow-20261125` plan has 42 documents, 157 chunks and no deletions;
source identities, content hashes and checked times match the live baseline.
An authenticated read-only Search lookup returned 404 for the proposed
`sk-pilot-brand-review` index and 200 for `sk-pilot-public`, confirming the
shadow index did not exist at that check. The staged API validates the new
review pin, authorizes the reviewed hosts and matches every staged row's
rights hash. The production manifest, review and Search index remain untouched.
Before publication, recheck the target, retain the previous index for rollback,
deploy an API with the new exact pin, and verify both index and live chat.

## Scope

Prepare the Saskatchewan web/API deployment using the shared monorepo and the
existing isolated Saskatchewan Search and Foundry resources. Preserve BC
production, staging, source indexes, and CI/CD. The user has approved deployment.

## Requirements and proposed Azure context

| Attribute | Proposed value |
| --- | --- |
| Classification | Small Saskatchewan assistant pilot; not a transaction service |
| Approach | Modify the shared platform; add isolated SK hosting |
| Subscription | `ME-MngEnvMCAP744360-sharmave-1` (`ad92e163-a85e-40cc-bb50-054b0b8197a8`) |
| Region | Canada Central, matching the existing SK Search and Foundry resources |
| Resource group | Reuse `rg-skassist-rywtikimq4`; no BC resource-group writes |
| Budget | Balanced pilot. Front Door Premium is approximately US$330/month before usage; registry, Redis, compute, monitoring, Search and model costs are additional. Actual subscription pricing may differ. |
| Exposure | Closed bootstrap, then protected validation and an anonymous HTTPS pilot after operational and safety checks |

The user approved the Saskatchewan subscription and the deployment plan,
including Canada Central; the user subsequently approved any region, including
US regions. The closed hosting bootstrap and application images have been deployed.
Public access was released with WAF prevention mode; the later API and web
updates described above have not been released.

The user has now explicitly approved a public deployment and asked that the
application work end to end. Release the existing Front Door WAF policy in
`public` stage, removing the temporary IP-validation rule while retaining
prevention mode, managed rules, and the API rate limit. This release modifies
only the existing SK WAF policy; the already-enabled endpoint and deployed
images remain unchanged. Validate the exact public-stage policy and its
what-if before deployment, then check live homepage, favicon, API and grounded
chat over HTTPS. The user attests to written branding and AI/RAG permissions;
existing public-facing wording still describes those permissions as
unverified and needs a separately reviewed correction without breaking the
source-review binding.

---

## Previous deployment plans from merged branches

# Isolated PyRIT staging

Status: Deployed and connected

Prepared: November 14, 2026.

## Verified outcome

CoPyRIT 1.2.0 is running on `http://127.0.0.1:18765` with
`bc-gov-staging` registered and selected in the browser. Its existing Microsoft
sign-in is acquired automatically for the dedicated staging audience. A bounded
manual text turn completed through the real CoPyRIT UI and staging BFF; local
conversation contents remain outside Git. The backend reports `ready: true`
and `state: ready`; the registry contains the configured target.

Authenticated staging capabilities return HTTP 200 with matching API/web source
commit `4d28d57fb13a8c9766e5374e3b3042b966509c92` and deployment
`staging-pyrit-20261115-4d28d57`. Version-5 conversation, task assistance and
reviewed-source retrieval are ready. Anonymous and invalid-token capability
requests return HTTP 401; the static favicon health probe returns HTTP 200.
All six protected production configurations remain unchanged.

The current manual window began November 15 at 23:11:55 UTC and expires
November 16 at 00:11:55 UTC. It permits 20 requests; one was used for the
connection check. No ledger stop is set. Restarts preserve that window and its
charges. The independent application allowance remains US$1.90/day, 300000
tokens/day and 20 model-backed runs/day, with conservative per-run admission.
This is not a guaranteed US$500 Azure invoice cutoff. No attacker/judge model,
automated scan, production promotion, or GitHub workflow activation was added.

Start the owned local server with `.cache\copyrit\CoPyRIT.ps1`; stop it using
the same launcher with `-Stop`. It verifies process ownership and binds only
to loopback. Runtime configuration, Azure credentials, local chat history,
manual ledger, and detailed deployment artifacts remain ignored.

## Completed follow-up: identity-based staging access

The user selected identity-based authentication after the IP restriction was
shown to block the local testing tools. Front Door WAF diagnostics matched the
exact failing request references: `ValidationOnly` blocked rotating shared
proxy egress addresses, whereas the public IP discovery service reported the
previously approved home address. Broadening that shared range is not authorized.
The deployed apps, sources, private connection, and preserved production
configuration remain as recorded below. The initially unregistered target is
now connected as verified above.

Preparation scope: evaluate Container Apps' built-in Microsoft Entra bearer-token
validation on the **staging web app only**, restrict authorization to the verified
operator identity, and add corresponding credential handling to the local
manual target. Use a separate staging-access application/audience, not the
internal API audience. Retain the current IP block until authenticated access
is configured and validated; only then replace that IP gate. Keep managed WAF
rules, private origins, synthetic-only processing, and all cost limits.
No public-pilot auth changes, citizen sign-in implementation, new paid service,
attacker/judge model, or attack campaign is included.

Implemented access plan, based on the current Microsoft Container Apps
authentication and `Microsoft.App/containerApps/authConfigs@2025-01-01` reference:

1. Create one separate single-tenant staging-access app registration exposing
   only its own delegated access scope. Preauthorize the existing Azure CLI
   client for that scope; no Graph permissions, credentials, or public browser
   redirects are added.
2. Enable built-in Container Apps authentication on the existing staging **web**
   app. Require HTTPS, validate the dedicated audience and tenant issuer, and
   require both the Azure CLI client application and the verified operator's
   object ID. Anonymous/invalid requests are rejected. This is a platform gate,
   not a replacement of the app's existing internal API identity or cookie logic.
3. Exempt only the existing static `/favicon.ico` from authentication and use
   it for the staging Front Door origin health probe. No application API or
   page is anonymously exempt. No application-image rebuild is needed.
4. Extend the local manual adapter with opt-in Azure CLI bearer authentication,
   bounded token acquisition, in-memory refresh, and an exact-origin check.
   Preserve the real Azure CLI config directory when CoPyRIT isolates its
   runtime home. Never write tokens to the manual ledger, YAML, or Git.
5. Configure and read back the auth gate before removing `ValidationOnly`.
   Preserve managed WAF protections, the API rate limit, private routing, and
   the US$1.90/day application allowance. No shared proxy range is allowlisted.
6. Verify anonymous and invalid-token rejection, valid operator access,
   exact release/source capabilities, and one bounded manual CoPyRIT turn.
   Stop on a tenant-consent or sign-in blocker rather than disabling identity
   validation. Other tenant users are not authorized by this deployment.

The local CoPyRIT browser UI remains the manual testing interface. It uses the
operator's existing Azure CLI sign-in to reach staging. A direct unauthenticated
browser visit to the staging URL returns an authorization error; a separate
interactive sign-in experience on that site is not included in this proposal.
No additional paid Azure service or higher model/replica limit is required.
The user selected identity-based staging authentication and then asked to make
the experience simpler. Proceed with the existing-sign-in CoPyRIT path only:
no second UI, browser login implementation, or password-management step.

The dedicated secretless registration now exists:
`c80d0189-bd20-4757-a057-5d9702fc0786`, in the approved staging tenant.
It has only its own delegated scope, with Azure CLI preauthorized, and no Graph
permissions, secrets, certificates, or redirect URIs. The shared machine's
default Azure account changed during preparation; the guarded operation stopped
before creating anything in that other context. All credential acquisition now
pins the approved staging subscription without changing global defaults.
The manual adapter's origin-bound authentication, caching/refresh, failure
privacy, preflight, chat, cleanup and ledger tests pass (18 tests).

All validation checks pass - identity transition:

- [x] Compile, ARM/provider validation and exact what-if for staging auth,
  staging origin health probe, and staging WAF IP-rule removal.
- [x] Offline manual adapter tests and Ruff checks.
- [x] Verify the existing sign-in can acquire the dedicated audience token.
- [x] Static scope review: only the operator's object ID and Azure CLI client;
  no subscription/Graph permissions or application-secret grants.
- [x] Freeze exact inputs and confirm no production writes.
- [x] Deploy/read back the identity gate before applying the WAF transition.

### Section 7: Validation Proof - current identity transition

The standard `validate-deployment.ps1` script passed compilation, authenticated
target-scope ARM/provider validation, and what-if for all three exact payloads
on November 15, 2026 UTC. No inherited policy was exempted or relaxed.

| Template / parameters | Exact structured result |
|---|---|
| `infra\staging-auth.bicep` / `staging-auth-parameters.json` | One staging auth configuration Create, 28 identical Ignore |
| `group-snapshot-update.bicep` / `identity-group-parameters.json` | One staging origin-group Modify; only the favicon health-probe path; 37 identical Ignore |
| `edge-snapshot-update.bicep` / `identity-waf-parameters.json` | One staging WAF Modify; removes only `ValidationOnly`; 27 identical Ignore |

The dedicated audience token was acquired using the existing sign-in, without
another login or a saved credential. Its tenant, operator, client application,
audience and delegated scope matched the reviewed configuration. Authorization
is enforced by the platform's signature/issuer/audience and allowed-principal
checks, not by local diagnostic decoding of those claims.

Ruff and 18 isolated manual-target tests passed. All identities/scopes were
reviewed statically; no Graph permission, secret, model allowance, or production
resource is changed by these templates. Exact payload hashes and UTC verification
time are saved in `staging-access-validation-proof.json`. The auth gate must
be deployed and read back before the approved WAF transition is allowed.

Earlier checkpoint: **staging application activation and restricted edge**.
The route repair succeeded, the user approved its exact private connection,
and the approved four-source bundle is published: 20 chunks, zero deletions.
Source document identities and actual November 15 acquisition timestamps were
read back from the new staging index. Neither sources nor source dates were
copied into production.

All validation checks pass - application/edge activation:

- [x] Core validation: CLI, authentication, Bicep build, ARM/provider validation,
  and what-if for the two app templates and separate WAF/endpoint scopes.
- [x] Build verification: validate the real API image's proposed runtime settings
  offline; preserve the already-built immutable API/web artifacts.
- [x] Policy validation: unchanged inherited policy, no exemptions, successful
  actual target-scope provider validation for each proposed payload.
- [x] Static role review: no role changes in this phase; retain reviewed
  per-service managed identities and their resource-scoped access.
- [x] Save exact proposed payload hashes, inspect every Modify, and reject any
  production mutation or nonidentical ignored resource.
- [x] Verify WAF access restriction before enabling the staging endpoint.

### Section 7: Validation Proof - current application activation

Actual checks on November 15, 2026 UTC:

| Check | Result |
|---|---|
| Standard validation script for `infra\app-image-update.bicep` and `activation-parameters.json` | Compile, provider validation, and what-if PASS; two staging app Modify resources, 26 identical Ignore |
| Same script for ignored `edge-snapshot-update.bicep` and `waf-snapshot-parameters.json` | PASS; one staging WAF Modify, 27 identical Ignore; adds only `ValidationOnly` |
| Same script and `endpoint-snapshot-parameters.json` | PASS; one staging endpoint Modify, 36 identical Ignore; changes only `enabledState` |
| API immutable image, networking disabled, proposed settings | PASS; seven pathway bindings, conversation/task enabled, controls ready, 147264-token reservation |
| Manual CoPyRIT compatibility tests | 15 passed |
| Staging runtime/boundary tests | 17 passed |
| Static role review | No new role assignments in activation; Foundry project/model, Search reader, metrics and ACR grants remain at their reviewed resource scopes |

The first app validation rejected GET-redacted secret entries. The corrected
validation-only template omits those entries; the full-resource preview therefore
shows removal of the web secret list. **That full-resource operation is not
authorized or executed.** The real rollout sends only `properties.template`
with a pre-write drift check; it never sends `configuration` or secret values.
Existing secret names/configuration are compared again after the new revision
is ready. Provider `NoEffect` identity fields are not permission changes.

The initial generic edge-module preview would remove provider-default fields.
The selected edge snapshots instead preserve those values and remove only
read-only backlink/status fields from the request. The final WAF delta is one
new rule; the final endpoint delta is only Disabled to Enabled. The existing
security-policy association is not rewritten. No production mutation or
resource Create/Delete is selected.

Final payload hashes and structured counts are frozen in
`.azure\bc-pyrit-staging\activation-validation-proof.json`; the rollout script
checks them again before writing. The WAF readback gate passed before endpoint activation.

### Application activation outcome

Both real image revisions are ready:
`ca-bcassist-jrxx4g4iwu-api--stg-4d28d57-v1` and
`ca-bcassist-jrxx4g4iwu-web--stg-4d28d57-v1`. Readback confirmed unchanged
managed identities, ingress, secret references, environment, and one-replica
scaling. The staging WAF adds only the approved `ValidationOnly` socket-IP
restriction; its managed rules and original API rate limit were unchanged.
The existing staging-only security-policy association was verified, not rewritten.
The private connection is Approved. The staging endpoint became Enabled at
approximately 21:46 UTC on November 15. The later identity-protected path became
usable at 23:10 UTC after its queued WAF propagation completed.
The API's actual source-health logs report four usable documents, no expired
documents or rejected chunks, and first expiry at November 22, 03:21:57 UTC.
These sources cover Service BC and health topics, not all seven pathway topics.

All six protected production configurations match the original baseline.
The first raw comparison differed only because Azure SDK output adds
resource-group annotations and null SKU fields; those derived annotations were
validated against resource IDs before normalizing. Exact baseline/current hashes
and the comparison result are retained in `production-preservation-proof.json`.

The two real images are immutable ACR digests from source
`4d28d57fb13a8c9766e5374e3b3042b966509c92`. Their release identity will remain
that source SHA even if the infrastructure repair is committed later.
The application deployment ID is `staging-pyrit-20261115-4d28d57`.
Both apps currently run bootstrap images. The proposed PATCH changes only
`properties.template`: the image, revision suffix, release fields, actual
published agent bindings, and version-5/task feature flags. Existing identities,
ingress, secrets, budgets, one-replica sizing, and service endpoints are preserved.
`infra\app-image-update.bicep` is for provider validation only, not a full PUT.

### Synthetic-only technical privacy review

Reviewed on November 15, 2026 against the deployed source SHA above:
`manual.py` keeps sharing off and uses independent app sessions per conversation;
`conversation.py` removes personal facts when sharing is disabled and constructs
the current-message/context payload; `foundry.py` sends conversation decisions
with `store=False`, explicit bounded output, and no client retry; `telemetry.py`
exports explicit metrics rather than prompts, HTTP bodies, or tool results.
Version-5 processing can still send text that an operator deliberately types
to the model. Therefore **only invented/synthetic messages are authorized**;
do not enter personal, government-confidential, or credential data. Foundry
GlobalStandard is not a guarantee of Canada-only processing. CoPyRIT stores
manual chat history locally; its database and configurations remain ignored.
No PIA, legal review, human privacy-officer certification, or public-release
approval is implied. `AI_CONVERSATION_PRIVACY_REVIEWED=true` records this
restricted technical review only. Version 6, contextual demos, embeddings,
live research, real sign-in, and transactions remain disabled.

Before enabling the staging endpoint, deploy and read back the staging-only
`ValidationOnly` WAF restriction for the exact user-approved current-connection
IPv4 /32. Its existing managed rules and API rate limit must remain. Verify the
existing association covers only the staging endpoint and `/*`. Enable only
that endpoint, never the shared profile. A failed capability/source/identity
check leaves CoPyRIT unregistered; do not use the public pilot as fallback.

Completed checkpoint: **identity bootstrap** using
`infra\staging-identities.bicep` and the ignored `identity-parameters.json`.
It creates the new staging resource group and three managed identities, with
no role assignments, compute, model deployments, data services, or public access.
The complete platform was revalidated afterwards. This let what-if resolve
the real principal IDs instead of accepting 11 unresolved role-assignment IDs.
It deployed successfully. The next, now completed, recovery selection was the
**narrow staging route and publication-access repair**. The platform services,
both apps, nine canonical agent versions, and two source-stamped images exist.
The original platform operation failed only on the new staging route's unsupported
Front Door Private Link region. The staging endpoint remained Disabled throughout that recovery.
No full-stack replay, public exposure, or production modification is selected.

The application stays in Canada East. Its Front Door managed Private Link
endpoint uses supported Canada Central, as documented by Microsoft for origins
in a different region. `AZURE_FRONT_DOOR_PRIVATE_LINK_LOCATION` makes this
distinction permanent in Bicep. The route repair contains only the three new
staging origin-group/origin/route resources.

The authenticated publisher can manage the new Search schema but document
access returned HTTP 403. A separate Bicep operation grants that verified human
only Search Index Data Contributor on the new staging Search service. It does
not elevate the API, grant subscription access, or change production permissions.
The separate approved publication later acknowledged all 20 source chunks.
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
the original `identity-what-if.json` and actual `identity-deployment.json`.
The standalone bootstrap hash record was inadvertently superseded during the
later access-checkpoint recording; it is not represented as preserved evidence.

### Historical validation proof - identity checkpoint

| Check | Command/review performed | Result | Date |
|---|---|---|---|
| Compile, authentication, ARM/provider validation and preview | `validate-deployment.ps1 -Scope sub -Location canadaeast -Template infra\staging-identities.bicep -Parameters .azure\bc-pyrit-staging\identity-parameters.json -Subscription ad92e163-a85e-40cc-bb50-054b0b8197a8` | PASS | 2026-11-15 UTC |
| Exact preview | `az deployment sub what-if` with those inputs, `--result-format FullResourcePayloads --no-pretty-print` | Succeeded; four creates only | 2026-11-15 UTC |
| Resource boundary | `node scripts\verify-staging-plan.mjs` against `identity-what-if.json`, the reviewed profile, `rg-bcassist-jrxx4g4iwu`, and `bcassist-jrxx4g4iwu` | PASS | 2026-11-15 UTC |
| Static identity/role review | Read both bootstrap Bicep files and the complete four-resource preview | Three new unprivileged identities; no role or secret creation | 2026-11-15 UTC |

## 1. Goal and current state

Add a staging environment for manual testing through the local CoPyRIT UI.
This is an addition to the existing application, not a replacement deployment.

At the initial investigation Azure had one BC assistant web/API pair in
`rg-bcassist-xufhsendpx`. The web app uses Single revision mode with 100% of
traffic assigned to its latest revision. Its Front Door hostname is the public
pilot, not staging. A separate staging platform now exists in
`rg-bcassist-jrxx4g4iwu`; its endpoint is restricted to the approved connection.

CoPyRIT 1.2.0 is running at `http://127.0.0.1:18765`; `bc-gov-staging` is registered.
The relevant transport primitives from the coordinating session were reviewed
and imported. Its broader CI/CD and production-promotion work is not part of
this task.

The focused transport primitives, manual target/initializer, release-identity
headers, and shared-edge Bicep path are now implemented in this worktree.
Offline checks passed. The user subsequently approved staging deployment and
restricted manual activation; the connection is now verified as recorded above.

### All validation checks pass - narrow recovery

- [x] Core validation: CLI, authentication, Bicep build, ARM/provider validation,
  and what-if for both exact group-scoped recovery payloads.
- [x] Focused staging preflight and boundary regression suite: 17 passed.
- [x] Policy assignments retrieved through Azure MCP, including inherited
  baseline, governance deny/audit/modify, and MFA controls. Both exact payloads
  passed provider validation; no policy exemption or relaxation is requested.
- [x] Static role review: one data-plane role on the new Search service only;
  the existing application identity permissions are not changed.
- [x] Exact structured preview and immutable input hashes recorded.

### Historical validation proof - route/publication recovery

Both runs of the standard `validate-deployment.ps1` script returned
`OVERALL: PASS` on November 15, 2026 UTC.

| Scope | Template and parameters | Structured what-if |
|---|---|---|
| Shared edge group, staging children only | `infra\modules\edge-routes.bicep`, `route-parameters.json` | 3 Create, 37 identical Ignore; no Modify/Delete/Unsupported |
| New staging Search only | `infra\staging-publisher-access.bicep`, `publisher-parameters.json` | 1 Create, 25 identical Ignore; no Modify/Delete/Unsupported |

`scripts\verify-staging-plan.mjs` passed in explicit `routing` mode. The
publisher preview was checked against the exact Search-scoped assignment ID,
verified operator object ID, and Search Index Data Contributor role definition.
Static Bicep review confirms `principalType: User`, resource-level scope, and
no application, subscription-wide, or production permission changes.
The proof, actual UTC timestamp, and input SHA-256 digests are saved in
`.azure\bc-pyrit-staging\recovery-validation-proof.json`.

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

---

# PyRIT release preparation

Status: Ready for Validation

Prepare isolated staging, required fixed and adaptive PyRIT checks, and paired
Container Apps revisions for production promotion. Implementation is limited to
repository changes and offline validation. Do not provision resources, change
GitHub environment settings, enable schedules, or make paid model calls.

Staging needs separately approved Azure context, model capacity, source
publication, OIDC identities, spending limits, and a fixed-egress runner. Keep
production traffic on its current revisions until the exact candidate passes.
Preserve private ingress, WAF rules, identities, secrets, and admission budgets.

Offline implementation now includes the isolated harness, threat-level Actions
steps, exact-candidate evidence checks, separate staging configuration, a private
managed-identity readiness job, paired revision promotion, and rollback.

The local offline campaign completed all 24 cases without model calls. Harness,
API transport, web proxy, workflow contract, and mocked rollout checks have run.
Bicep compilation succeeds; the installed compiler still warns about the
repository's pre-existing Redis API version types.

Validation scope remains offline only. Cloud validation, cutover, conversation continuity, and rollback remain
unverified until a separately approved activation. The earlier IQ record below
is retained as historical evidence; it does not qualify this release path.

## All validation checks pass

This gate is not complete. Azure activation was explicitly deferred.

| AZD validation step | Current scope |
|---|---|
| AZD installation | Local CLI verified |
| Schema validation | Bicep compiled; workflow semantics checked |
| Environment setup | Deferred to approved staging activation |
| Authentication check | Deferred; no account or subscription inferred |
| Subscription/location check | Deferred to the operator's selected context |
| Aspire pre-provisioning checks | Not applicable |
| Provision preview | Deferred; no cloud preview requested |
| Build verification | Local tests, type checking, and build checks |
| Docker build context validation | Existing locked manifests and target-platform dependency stages preserved |
| Package validation | Azure packaging deferred |
| Azure Policy validation | Deferred |
| Aspire post-provisioning checks | Not applicable |

## PyRIT validation proof

| Check | Result |
|---|---|
| Full offline threat campaign | 24/24 cases passed against the real API with fixture inference |
| Evaluator unit/integration checks | 42 passed |
| Repository tooling and workflow contracts | 115 passed |
| API release identity and native transport | 27 passed |
| Web proxy | 44 passed on Node 24 |
| Web production build and type checking | Passed |
| New/changed Bicep | Compiled; pre-existing Redis API type warnings remain |
| Ordinary Actions workflows | Actionlint passed |
| GH-AW reporting workflow | Strict compilation passed; generated output references verified |

The installed standalone actionlint predates GH-AW's `copilot-requests` permission
and `concurrency.queue` fields. Only those two known generated-feature diagnostics
were filtered when checking the compiled workflow; ordinary workflows used no
filters. Cloud environment, IAM, policy, packaging, paid scans, and live cutover
checks remain deferred. This plan is not marked `Validated`.

# Optional IQ rollout

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
- [ ] 1. Core Validation (CLI, auth, build, validate, what-if) for the API release.
- [ ] 2. Bicep linting.
- [ ] 3. Azure Policy Validation.

The earlier public WAF policy validation is recorded in Validation Proof below;
it does not validate this new image release.

## Existing state and components

The Saskatchewan application runs locally and in protected Azure hosting. Its reviewed knowledge
index contains 42 documents and 157 chunks. The general Foundry prompt agent is
bound to immutable version 4. The final 25-case chat run completed: 23 cases
passed, including all six core service topics across three rounds, licence
follow-up, angling, hunting and unsupported-question navigation. Income Support
failed critical-claim validation before emitting an answer. The fee case
quoted contradictory SGI payment guidance instead of withholding the amounts.
The user explicitly accepted these known chat-quality failures for the pilot.
Safeguards for the contradictory fee and initial validation failure have since
been added. One live in-process check returned the SGI fee handoff without an
amount, and one Income Support check returned a cited answer. The full
25-case run has not been repeated; do not represent the prior run as passing.
The previous PyRIT plan is preserved in
`deployment-plan-pyrit-preserved-before-sk.md`.

| Component | Technology | Existing path or resource |
| --- | --- | --- |
| Web/BFF | Next.js on Node 24 | `apps\web` |
| Read-only API | FastAPI/Python | `apps\api` |
| Knowledge | Azure AI Search, lexical retrieval | `srch-skassist-rywtikimq4`, index `sk-pilot-public` |
| Model/agent | Foundry prompt agent | Project `sk-service-pilot`, `sk-service-general` version `4`, model `sk-fast` |
| Source refresh | Reviewed Python ingestion | `ingestion`; retain original ledgers and evidence |

The SK resource group includes the provisioned hosting environment, registry,
web/API apps, Redis, Front Door and monitoring, in addition to the existing
Search and Foundry resources. The Front Door endpoint is enabled but restricted
by the public-stage WAF policy and serves the public pilot. The prepared
post-release fixes and operational safeguards remain outstanding.

## Recipe and hosting architecture

Proposed recipe: dedicated Bicep plus guarded Azure CLI release preparation,
reusing the repository's proven modules and Dockerfiles. Do not redirect the
existing BC `azure.yaml` or its CI/CD into Saskatchewan.

Use a hosting-only entry point rather than deploying `infra\main.bicep`
unchanged. `infra\modules\ai-services.bicep` still hard-codes
`bc-service-pilot`; invoking it would provision the wrong project under the SK
account rather than reuse `sk-service-pilot`. Reference the existing SK account,
project and Search as existing resources. Do not recreate, reconfigure or
republish their models or index as a hosting side effect.

Proposed additions:

- One private, VNet-connected Container Apps environment and two apps: web/BFF
  on port 3000 and an internal API on port 8000. Initially cap each at one
  replica, using the existing 0.5 vCPU / 1 GiB allocation.
- An SK-only Basic container registry with administrator access disabled and
  authenticated access over its public registry endpoint. The Container Apps
  environment, not this registry endpoint, has public network access disabled.
  Build SK `linux/amd64` images explicitly; use managed identity for pulls.
- Separate SK web and API managed identities; no BC identity reuse. Add a
  publisher identity only if the hosting release also includes a separately
  approved scheduled refresh job.
- A private, Entra-only Azure Managed Redis instance with high availability and
  no eviction for shared rate, budget, replay, cancellation and run ownership
  controls. Canada Central capacity was unavailable; use Canada East for the
  Redis service and keep the private endpoint with the Canada Central VNet.
  The user has approved use of other regions.
- A dedicated Front Door Premium profile, private origin and WAF. Do not share
  or modify BC's existing profile, routes, policies or diagnostics.
- SK-only Log Analytics/Application Insights, preserving metadata-only
  application telemetry and no prompt/transcript payload logging.
- A dedicated secretless internal API Entra application/audience. Only the SK
  web identity can call the internal API. No citizen authentication,
  transactions or directory-data permissions are included.

No additional Search, Foundry project, model deployment, embeddings, Web IQ,
guided journeys, contextual demos, custom government domain or Blob staging is
proposed. Canada Central hosting does not imply that the existing GlobalStandard
model inference remains within Canada.

The user attested to written permission for Saskatchewan branding and RAG.
The existing brand attribution still says public release is unapproved; reconcile
that record with the user attestation before public exposure without asserting
that the written permission was independently verified.

## Capacity inventory and evidence

Read-only checks were run against the explicit SK subscription, not the
machine's incidental default. The `Microsoft.App`, `Microsoft.Cache` and
`Microsoft.ContainerRegistry` providers list Canada Central. Regional
capacity and policy can change, and an environment-specific core quota cannot
be queried until the environment exists.

| Resource | Proposed addition | Observed usage | Proposed total | Limit / remaining verification |
| --- | --- | --- | --- | --- |
| Container Apps environments | 1 | 4 | 5 | 50; confirmed through `az quota` |
| Virtual networks | 1 | 2 | 3 | 1000; confirmed through `az quota` |
| Private endpoints | 1 explicit Redis endpoint | 5 | 6 | 65536; confirmed through `az quota`; review platform-created network resources separately |
| Network interfaces | 1 explicit endpoint NIC | 5 | 6 | 65536; confirmed through `az quota` |
| Container Apps | 2 | 7 | 9 | One 0.5-core replica each; verify Consumption core quota after the new environment exists |
| Container registries | 1 | 4 | 5 | Quota API returned BadRequest; verify Basic availability and exact ARM validation |
| Azure Managed Redis | 1 Balanced B0 in Canada East | 1 Managed Redis | Separate instance | Canada East provider validation passed; actual capacity remains subject to provisioning |
| Managed identities | 2 | 15 | 17 | Tenant directory headroom is not exposed by the regional quota API |
| Front Door profiles | 1 | 1 | 2 | Verify Premium and Private Link availability in exact-scope ARM validation |
| WAF policies | 1 | 2 | 3 | Verify dedicated-profile associations in exact-scope ARM validation |
| Log Analytics workspaces | 1 | 4 | 5 | Confirm retention and exact-scope ARM validation |
| Application Insights components | 1 | 3 | 4 | Confirm exact-scope ARM validation |
| Search services / Foundry accounts / projects / model deployments | 0 | Existing SK resources | Unchanged | No model quota increase or service recreation proposed |

Regional counts above combine Canada Central resources and global resources
where applicable. They are not tenant-wide object counts. Read-only policy
discovery also found inherited management-group policies, including MFA for
writes and restrictions on classic resources, VM/AKS/SQL and other services.
No policy exemptions or network-policy relaxation is authorized; nested
resources still require policy evaluation during closed deployment.

References:
https://learn.microsoft.com/azure/azure-resource-manager/management/azure-subscription-service-limits
https://learn.microsoft.com/azure/container-registry/container-registry-skus

## Release preparation and execution sequence

1. Confirm the existing SK subscription and region and obtain approval of this
   plan before generating hosting code. Recheck service availability and
   capacity during exact-scope validation.
2. Keep citation and critical-claim gates intact, verify that ambiguous SGI fee
   amounts are withheld, and preserve the failed acceptance evidence. The
   user has accepted remaining chat-quality failures for this pilot.
3. Prepare a hosting-only Bicep entry point, an existing-resource access module,
   SK-only parameters and a guarded release preparation command. Preserve
   default BC behaviour and existing workflow definitions.
4. Build and smoke-check both SK container images before deploying application
   images. Explicitly pass
   `JURISDICTION=sk`; pass the current exact review SHA to the API build.
   The root `azure.yaml` currently does not express those build arguments and
   must not silently produce BC-default images. Record the exact build source,
   immutable image digests and agent binding before deploying application images without
   committing unrelated worktree changes.
5. Validate production configuration using managed identity, not the local
   Azure CLI credential. Require Redis and internal API bearer validation,
   SK namespaces, correct allowed hosts/origin, correct source-review pin, and
   matching baked/runtime jurisdiction. Preserve lexical retrieval; normalize
   infrastructure metadata-review flags to `0` rather than local `false`.
6. Set status to Ready for Validation and invoke `azure-validate`. Require Bicep
   compilation, exact-scope ARM/provider validation and what-if for the closed
   bootstrap. Image provenance, source freshness, chat safety and operational
   checks remain mandatory before releasing images or opening access. Record
   accepted chat-quality failures rather than misreporting them as passing.
   Reject any BC writes, model/index changes, or unexpected deletions.
7. Invoke `azure-deploy` after validation. Bootstrap
   closed, approve/read back the exact private origin, then run protected
   validation using the deployed managed identities. Verify health, readiness,
   chat, citation checks, disconnect/cancellation and rate/budget controls.
8. Open anonymous pilot access only after operational, security and source
   safety checks pass; do not set approval flags merely to bypass preflight.
   Record the user's attestation of written brand and RAG permission without
   claiming independent verification. Retain immutable images for rollback.

Source freshness is a separate operational requirement: the earliest current
source expiry reported by the API is December 1, 2026. Revalidate before rollout
and define refresh/withdrawal ownership; do not extend an expiry by configuration
alone or reset charged budgets.

## Files proposed after approval

| File | Purpose |
| --- | --- |
| `infra\sk-hosting.bicep` | Hosting-only SK entry point referencing existing AI resources |
| `infra\modules\government-ai-access.bicep` | Scoped access to an existing government Foundry project/Search |
| `scripts\prepare-sk-release.ps1` | Explicit SK image builds, provenance and release parameter preparation |
| `jurisdictions\sk\deployment.env.example` | Correct deployment-only settings and truthful current source policy |
| `infra\README.md` | Isolated SK rollout, validation and rollback instructions |
| Existing deployment/jurisdiction tests | Focused regressions for SK identity, existing-resource selection and BC preservation |

Finalize paths and module reuse after approval; do not create redundant wrappers
if existing tooling supplies the required boundary.

## Validation proof and current status

Validation in this section applies to the closed infrastructure bootstrap and
the closed candidate image release, not to public traffic.

### All validation checks pass

- [x] 1. Core Validation (CLI, auth, build, validate, what-if) for the cross-region revision.
- [x] 2. Linting for the cross-region revision.
- [x] 3. Azure Policy and provider validation for the Canada East Redis module, subject to live provisioning.

Confirmed: existing SK resource inventory and healthy resource group, enabled
subscription, Container Apps environment headroom, VNet/private-endpoint/NIC
headroom, existing provider registrations, the completed local 25-case
acceptance with its two recorded failures, focused API regression checks, and
the two in-process live checks described above.

Not yet performed: subscription-specific price quote, environment-specific
Consumption core check, full acceptance rerun, production managed-identity
validation, complete nested-resource what-if, or an application-image release. The local
API process has not been restarted to load the latest safeguards.

The user approved the Saskatchewan subscription, deployment plan and deployment.
The `linux/amd64` SK API image was built and its jurisdiction and review pin
verified; the SK web image returned HTTP 200 with Saskatchewan content. Template
and provider validation with placeholder parameters succeeded, as did a scoped
what-if after using a distinct parent deployment name. The what-if skipped the
nested AI access, Redis, hosting and route modules, so it is not complete proof
of those resources. Production image registry digests, protected deployment validation, and an
application-image release remain pending.
The attempted closed bootstrap failed because Azure reported insufficient
Canada Central capacity for Managed Redis `Balanced_B0`. Independent provider
validation also rejected `Balanced_B1`, `Balanced_B3`, `Balanced_B5`,
`MemoryOptimized_M10`, and `ComputeOptimized_X3` for lack of capacity. The SK
network, two managed identities, disabled Front Door endpoint and WAF, and the
dedicated API Entra application were created; the web/API hosting was not.
These resources may incur charges. The public endpoint remains closed.
The attempted Azure Cache for Redis Standard C1 fallback was rejected during
creation because Azure no longer permits new legacy instances in this
subscription. The replacement uses Managed Redis in Canada East and a private
endpoint in Canada Central. The closed bootstrap subsequently succeeded; Redis
and its database are provisioned, the private endpoint is approved, public
Redis access and database access keys are disabled, and transport is encrypted.
Live application authentication remains unverified.

On November 25, the Front Door endpoint was confirmed disabled and its WAF
enabled in prevention mode. Both application identities have the registry
`AcrPull` role; the API identity also has the expected Search, Foundry and
metrics roles. Placeholder images remain in both apps. The final source archive
SHA-256 is `ec9847f30b9671beb5a853f689cd736aefcfc4163b56f23ee9b39a51319c404c`;
all 2,431 archived files matched the build directory, with no extra files.
The resulting local `linux/amd64` image IDs are API
`sha256:8c1f6d1f719dae209ce5d23f262e6b67d3fd70e9f50371151b8f80cc0812f902`
and web `sha256:52c4288e8637d9121e5223e70152c6d817f6eddb7be1a4f85416b86e702f8157`.
The API reported Saskatchewan and the expected review pin; the web served
Saskatchewan content and the supplied favicon. These observations do not
validate an image deployment or public release.

The closed image deployment subsequently succeeded. Both immutable image
revisions report healthy, each with one running replica. The API startup source
check reported 42 usable documents, zero expired documents, and coverage of
the Saskatchewan, SGI and eHealth sources; the next expiry is
2026-12-01T16:06:05Z. The reviewed private Front Door connection was approved.
The IP-restricted validation deployment succeeded, with the enabled WAF
configured to restrict requests to the validation address. Front Door's
endpoint and route still report `NotStarted` deployment status despite
successful provisioning, and requests to the default hostname returned 404
with `CONFIG_NOCACHE`. Edge enforcement, Redis authentication and grounded
chat are not verified; this is not a working public pilot.

Subsequent checks on 2026-11-25 UTC confirmed that the WAF is actively blocking
requests outside the validation allowlist. The local IP-check service reported
`209.91.110.210`, but Front Door WAF logs recorded different, rotating source
addresses for requests from the same host. Three requests from the private API
container also used two different outbound addresses (`20.200.119.159` and
`20.200.119.172`). Therefore the current
one-address rule does not provide a reliable end-to-end validation path. It
has not been widened or disabled. Endpoint, route and origin deployment status
still report `NotStarted`, despite successful provisioning.

An isolated validation client with its own static egress could provide a
testable `/32` without admitting a shared Azure outbound range. Azure Container
Instances requires a NAT gateway for stable egress; that additional
infrastructure is not part of this approved hosting plan and has not been
provisioned. A browser-based validation attempt was not approved by the
browser, so it was not retried through another browser.

From inside the API container, the production `SharedControls` client
authenticated to private Managed Redis using its configured managed identity
and returned `PING True`. A private service-to-service test reached the
Saskatchewan homepage and completed three chat cases for licence renewal,
health card application, and withholding contradictory licence fees. The chat
test simulated the Front Door identity and socket-IP headers inside the private
environment; it did not test real Front Door routing or validate external
access. A request without those trusted headers returned 502 as expected from
the web proxy's ingress checks, not proof of an API connectivity failure.
Two further private cases returned a cited Income Support answer and the
expected navigation response for an unsupported question. The Income Support
answer ended with an incomplete "provide ALL of this information" sentence;
the citation check alone does not establish that the answer is complete.

The approved Front Door private connection was rechecked on 2026-11-25 UTC.
`OriginHealthPercentage` reported 100% in each hourly bucket from 02:17
through 04:17 UTC. The governance workspace's latest individual probe log was
earlier, at 02:10 UTC, and showed an origin error; no newer individual probe
records were available there. The aggregate metric does not replace an
end-to-end request through the WAF.

## Functional verification

The local SK application and chat were exercised as described above; the user
accepted the recorded chat-quality limitations. Release-image checks confirmed
the API jurisdiction and pinned source-review SHA, and the web image served
Saskatchewan content over HTTP. Private managed-identity Redis authentication and three grounded chat cases
have passed as described above. The existing public Front Door and its live
images have since served the public checks recorded above. The newer candidate
images and their intended production release remain unverified and undeployed.

## Section 7: Validation Proof

- On 2026-11-25 UTC, the Bicep validation helper passed CLI, authentication,
  compilation, provider validation and what-if for `infra\modules\edge-policy.bicep`
  with `sk-waf-public-parameters.json`; Bicep lint passed. The full-resource
  preview showed one WAF policy modification and 24 ignored resources, with
  no resource deletions. The intended change removes the `ValidationOnly`
  restriction and retains `ApiRateLimit` and managed rule sets. Provider-default
  properties are also reported as removed. This policy template contains no
  RBAC changes. `az policy state list` returned no records for this WAF;
  provider validation passed, but the empty list is not proof of compliance.
- Validation date: 2026-11-24, Canada Central target.
- For the prior legacy-cache template on 2026-11-24, the Bicep validation helper passed CLI, authentication,
  compilation, provider validation and what-if against the SK resource group
  using the dedicated API application ID, the existing policy-assigned subnet
  NSG and a placeholder hash key. A separate full-resource what-if showed no
  resource deletions and preserved the subnet NSG. Some role assignments were
  reported as Unsupported; live RBAC and policy validation remain required.
  The helper's deletion count includes property-level changes, not just
  resource deletions; observed remaining removals concern provider-returned
  default properties on the endpoint, identities, WAF and VNet.
- The prior template passed `az bicep lint --file infra\sk-hosting.bicep`.
- Azure Policy assignment review found inherited management-group controls in
  addition to subscription policies. Their known deny rules cover classic
  resources, VM/AKS/SQL and other services rather than the planned resource
  types; unresolved nested resources still require live evaluation.
- Static identity review confirmed the SK API's Foundry User, Cognitive
  Services OpenAI User and Search Index Data Reader role definitions, scoped
  to the existing project/account/index service, Redis access policy, and
  separate web/API managed identities. Image-pull assignments are supplied by
  the Container Apps module; runtime RBAC still requires live verification.
- Local image IDs: API `sha256:43d62e57a4459289e86c65ddad7e74857ef1b700f972e37c0d6631839d4c955f`;
  web `sha256:0f26b3c8b14246f701700edb7a0de4980438207a84111d10dfdea73e9d748a78`.
  The rebuilt API's Saskatchewan jurisdiction and review pin were checked.
  Registry digests and exact source provenance remain release gates.
- `az deployment group validate` passed for the concrete Managed Redis module
  with Canada East cache and Canada Central private endpoint. Live
  provisioning, authentication and policy behavior remain unverified.
- On 2026-11-24, the validation helper passed compilation, provider validation
  and what-if for the cross-region revision. Full-resource what-if showed no
  resource deletions and preserved both policy-assigned subnet NSGs. Its
  unsupported role assignments require live verification after provisioning.
  Bicep emitted BCP081 warnings because its local type library does not yet
  include the Redis API version; direct provider validation passed.
- On 2026-11-25 UTC, the Bicep validation helper passed CLI, authentication,
  compilation, provider validation and what-if for the closed image release,
  using the two immutable image digests and a nondeployment placeholder key.
  `az bicep lint --file infra\sk-hosting.bicep` passed. A separate full-resource
  what-if showed no resource deletions; nine existing resources were ignored
  and six role assignments unsupported. Observed property removals include
  provider-returned defaults; unresolved references affect the Redis identity,
  origin hostname and Log Analytics workspace ID. Live API identity roles and
  the Redis assignment were verified, and the VNet diff did not change subnet
  NSG associations. Runtime connectivity and safety validation remain open.
- Both candidate images were pushed to the SK registry and registry readback
  matched their local digests. The restricted temporary Docker credential file
  was removed. Local API identity/review-pin and web content/favicon checks
  passed. The review pin is baked into the API image; the source archive, not
  an unrelated Git commit, identifies the dirty-worktree build.
- On 2026-11-25 UTC, the Bicep validation helper passed compilation, provider
  validation and what-if for the existing WAF policy with a single current
  IPv4 validation address. A separate full-resource what-if showed one WAF
  modification, no resource deletions and the existing API rate-limit rule
  retained. The plan is to apply and verify this rule while Front Door remains
  disabled, before considering a restricted validation window. The address and
  access rule must be rechecked immediately before use; public release remains
  unvalidated.
- The protected-validation full template was independently validated on
  2026-11-25 UTC using the same immutable images, a placeholder secret and the
  same one-address WAF restriction. Full-resource what-if showed no resource
  deletions, preserved the subnet NSGs and predicted enabling the endpoint with
  the WAF restriction already present. The private-origin connection is
  approved. This validates only restricted testing, not anonymous release.
