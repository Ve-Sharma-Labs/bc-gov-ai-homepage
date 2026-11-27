# Government jurisdiction packs

One shared codebase, one selected government per build/process/deployment.
`JURISDICTION` defaults to `bc`; unknown or malformed IDs fail explicitly.
Repository package names and compatibility headers remain unchanged. BC's
existing CI/CD and source publication controls are not replaced.

## Contract

Each directory has a versioned `jurisdiction.json` with public identity, locale,
timezone, official publisher domains, help links, brand assets, feature flags
and repository-relative content paths. JavaScript and Python consumers validate
the selected pack. Source permissions remain per publisher/snapshot, not a
blanket grant from the manifest's domain list.

BC retains the existing `data` files as its authoritative content while current
workflows depend on them. New governments keep content in their own pack.
Do not maintain duplicate editable BC datasets during migration.

Endpoint URLs, credentials, deployment index names, managed identities, agent
bindings and budgets are private environment configuration, not public brand
data. Select isolated resources and confirm their jurisdiction before activating
model capabilities. No resident-controlled government or index switching.

## Local selection

```powershell
$env:JURISDICTION = "bc" # Existing BC experience
npm run dev

$env:JURISDICTION = "sk" # Saskatchewan pilot
npm run dev
```

Stop the first preview before changing the pack, or use separate web/API ports.
Build separately with the same selection; a build for one pack must not run as
another. Docker build arguments and Compose propagate the selected government.
Changing `.env` without rebuilding does not rebrand a production web bundle.
Sequential local builds may use separate validated output directories, such as
`NEXT_DIST_DIR=.next-sk`. Standalone preparation requires matching selected-pack
assets and build stamps. Generated public files are shared in one checkout;
prepare each pack before its build rather than building packs concurrently.

## Activating reviewed sources

BC retains `existing-reviewed-snapshots-only`. Other packs accept only
`pending-rag-permission` or `reviewed-operation-grants`; unknown statuses fail
closed. A reviewed status requires a selected-pack `operationReview.path` and an
independently supplied `OPERATION_RIGHTS_REVIEW_SHA256`. Root launch/preflight
uses Python and the API's shared v3 grant validator to check exact evidence,
scope, revocation and expiry. A missing interpreter or failed review blocks
activation, never supplies a grant. See `apps\api\README.md` for the complete
review contract. Pending packs can still run an honest, non-model local pilot.

## Saskatchewan identity

The user-supplied Saskatchewan wordmark and provincial flag are visual references
for a local pilot. Track originals, dimensions, attribution, usage status and
alt text. Do not claim these assets or this app are officially endorsed or
approved for public release. Exact website design tokens require verified
reference review; accessible green/yellow pilot styling is not an official
design-system certification.

## Broad source programme

Target permitted public pages and linked PDFs across resident, business and
government topics. Begin discovery from the publisher's advertised sitemap,
`https://www.saskatchewan.ca/sitemap-xml`. External publishers and subdomains
are discovery candidates requiring separate review, not automatic crawl targets.

The robots response inspected November 23, 2026 signals
`search=yes,ai-train=no,use=reference`; its search definition excludes
AI-generated summaries and gives no affirmative `ai-input` permission.
**Search indexing permission does not establish permission for embeddings/RAG.**
Review current terms and permitted reference use, obtain any necessary permission,
and record the review before model ingestion. Do not train or fine-tune.

Respect current robots rules, budgets and checkpoints. Keep discovery,
acquisition, extraction, exact-snapshot review and publication separate. Retain
canonical URLs, PDF page references, hashes, dates, publisher/language identity,
superseded versions and withheld/failed reasons. Exclude personal/account,
submission/payment and executable content. Treat retrieved pages as evidence,
never instructions to tools or models.

Publish approved snapshots only into Saskatchewan's separately configured index.
Report discovered, eligible, extracted, reviewed and indexed documents by
topic/publisher/format; chunk totals alone do not demonstrate coverage or answer
quality. Validate exact citations, long-tail queries, archived/current evidence,
missing-evidence handoffs, source injection resistance and BC/SK isolation.

Live bulk acquisition, Search publication, agent creation and cloud/public
deployment remain separate approval-gated operations.
