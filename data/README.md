# Curated pilot catalogue

`pilot-catalog.json` is the shared **camelCase schemaVersion 1** contract. It
contains twelve source registrations, seven read-only preparation journeys and
seven Service BC offices. It is a manually curated dated snapshot, **not a live
index, complete service directory, generated AI answer or eligibility decision**.
The UTC catalogue `asOf` is November 6, 2026 (November 5 in B.C.). This reflects
a navigation-only review renewal of Service BC, housing/tenancy,
family/social supports and employment/business, not a new acquisition of all
documents or a recheck of office rows.

`provenance.json` records the seventeen direct-publisher HTML responses, their
SHA-256 hashes and check dates, six robots-policy endpoints, handoff verification,
and the source-to-journey evidence mapping. Dates not explicitly present in
publisher metadata are null. A stated content-currency date is **not** a
publisher-modified date or legal effective date.
Its `catalogueReviews` records the limited renewal and the commit that made it.
The top-level dates describe the catalogue snapshot; `acquisition.asOf` and
`acquisition.localReviewDate` retain the historical acquisition snapshot dates.
Document hashes and check dates, robots evidence, and location coverage remain
unchanged and must not be interpreted as newly acquired or reviewed content.

## What was actually checked

- Seventeen public documents returned HTTP 200. Ten robots requests were made
  across six hosts, including conservative parser diagnosis/rechecks. No full
  sitemap crawl, PDFs, accounts, forms, registration portals or user uploads were
  collected. All journey handoff URLs are among those seventeen checked pages.
- The outdated Service BC seed remains documented in the source inventory. The
  catalogue and parser use the verified replacement URL, not the 404 seed.
- ICBC delivered useful visible text alongside unresolved dynamic components.
  The catalogue deliberately does not claim complete eligibility, fees, renewal
  capability or an approved rendered feed.
- BC Housing's visible update pause says content is current to **September 22,
  2026**. The catalogue retains that limitation. RAP/SAFER summaries preserve the
  reviewed Medical Services Only exception, but are not full eligibility rules.
- WorkBC's robots response was HTML, so acquisition failed closed. BC Laws'
  general-crawler prohibition was respected. **No content from either source
  was fetched**, and CiviX access/licensing is still pending.
- Raw extraction quality is intentionally stricter than a reviewed short
  navigation description. Eleven raw pages are quarantined (navigation-region,
  freshness or dynamic limitations); six are review-required. None is approved
  for full-text publication. A source marked `available` means the described
  curated guidance is available, not that its entire website has passed ingestion.

## Location interpretation

Only Burns Lake, Kamloops, Kelowna, Nanaimo, Surrey, Vancouver and Victoria were
selected from the canonical page's office table. The table's explicit
**Popular services** links reference its same-page definitions; this is recorded
as publisher-supported inheritance, never inferred from an empty cell.

Exclusions override that group. For example, Nanaimo excludes income assistance;
Kamloops and Kelowna exclude both income assistance and ICBC licensing. Vancouver
and Surrey explicitly have a closed, limited-only service list. Their published
breaks and lack of appointments are retained. Missing municipalities mean **not
in this sample**, not no office in that municipality.

The `bc-services-card` key means digital account setup/identity verification in
this dataset, **not guaranteed photo-card issuance**. BCeID is account
registration/identity support. The four keys are a narrow service-filter
vocabulary, not a list of all services at each office. Addresses are physical
addresses, not mailing addresses. Published hours are not a live-open indicator.

## Refresh and promotion

Recheck office details, notices and time-sensitive requirements before public
release and travel. The intended operational policy is daily office/notice
review and weekly stable-guidance review; **no scheduled refresh is running**.
This file remains explicitly a snapshot if no refresh occurs. Publisher
permission, complete extraction and accountable content review are required
before full-text promotion. Robots permission alone is not a licence grant.

The API's periodic Search health check is monitoring, **not scheduled content
refresh**. It does not update this catalogue, its dates, rules, or source review
records. A dated preparation guide can remain available while missing or
expired detailed evidence is withheld. Do not make a release appear healthy by
advancing snapshot timestamps or increasing the allowed evidence age.

Edit only concise original summaries here; do not paste whole pages. Raw HTML,
extracted text, version ledgers and dry-run plans live in ignored
`ingestion\.generated`. No such cache belongs in a commit. The application reads
only `pilot-catalog.json`; provenance is supporting evidence, not a second API
contract or runtime eligibility engine.

From the repository root:

```powershell
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion validate
.\ingestion\.venv\Scripts\python.exe -m unittest discover -s .\ingestion\tests -q
```

## Synthetic citizen-context personas

`demo-personas.json` is a separate **schemaVersion 1**, server-owned fixture for
the repository citizen-context ADM validation demo. It contains exactly three
hand-authored fictional records: Maya (older-parent care and guardianship
navigation), Alex (disability-support navigation), and Sam (recent job-loss
navigation). Anonymous mode is represented by selecting no persona; it is not a
fourth record.

The public catalogue may use only each record's ID, display name, summary,
available category names, and the constant synthetic marker. Full facts,
provenance, timestamps, sensitivity, consent scopes, and mutability stay
server-side. `missingFactKeys` deliberately exercise follow-up branches without
inventing a value. The fixture contains no identifier numbers, exact addresses,
contact details, account data, or copied production records.

`bc_api.demo_personas` validates the complete JSON shape independently of shared
API and web contracts. It fails closed on unknown persona IDs, duplicate JSON
properties, duplicate facts or categories, category/scope mismatches,
unsupported source labels, unsafe public summaries, and non-deterministic
ordering. Callers may pass only an allowlisted persona ID to the repository;
client-provided fact objects are rejected. This fixture does not add an endpoint,
rule, application form, eligibility decision, or submission capability.

## Synthetic program-screening rules

`demo-program-rules.json` is the separate **schemaVersion 1** deterministic rule
set for the three synthetic flows. Version `2026-11-05.1` contains ordered
navigation indicators for caregiving, disability support, job loss, and related
service discovery. Results are limited to `potential-match`,
`needs-information`, `already-enrolled`, and `not-indicated`. Every result keeps
the notice that screening is not an eligibility decision.

The rules use only typed fact keys from the persona fixture or typed citizen
answers. Conditions support only fixed equality, set-membership, and numeric
`at-least` comparisons. There is no prompt parsing, model call, expression
language, dynamic import, `eval`, or client-supplied rule definition. Numeric
conditions are navigation signals, not benefit or legal thresholds. Missing
facts are returned as reviewed public-safe keys rather than raw values.

Every rule records an owner, version, effective interval, review dates, source
IDs, required facts, optional conditions, explicit missing-fact behaviour,
source coverage, deterministic rationale labels, and the screening notice.
Per-rule and whole-file SHA-256 hashes cover canonical JSON. The loader also
pins each reviewed source to the current `pilot-catalog.json` `asOf`, status,
and `checkedAt` value. Available or limited catalogue entries may support
navigation-only rules; blocked, pending, absent, stale, or mismatched evidence
fails closed and cannot produce a citizen status.

The guardianship flow deliberately returns family/social-support and human
service navigation only; it does not determine capacity, legal authority, or
the need for guardianship. WorkBC and Employment Insurance are not emitted as
potential matches because this snapshot lacks reviewed usable source coverage
for those program-specific recommendations. Related housing, income-support,
and assisted-service examples are phrased as potential navigation, never formal
eligibility.

`bc_api.demo_rules` loads only the repository-owned rules and source catalogue,
combines shared `ContextFact` models, rejects duplicate keys, verifies pinned
rule/source evidence and dates, and returns validated shared `ProgramMatch`
models in exact dataset order. Failures contain safe codes and messages only;
the module does not log fact values. API routes, consent/session enforcement,
agent tools, and UI rendering must call this module from their own separately
reviewed integration work.

From the repository root:

```powershell
.\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\test_demo_rules.py -q
.\apps\api\.venv\Scripts\ruff.exe check apps\api\src\bc_api\demo_rules.py apps\api\tests\test_demo_rules.py
```

## Independent synthetic-context evaluation cases

`citizen-context-evaluation-cases.json` is the machine-readable, model-free
evaluation manifest. It defines the three anonymous-versus-contextual sample
questions, exact required and optional scopes, descriptive comparison measures,
artifact order, red-team cases, and the desktop/mobile accessibility matrix.
The measures cover deterministic clarification needs, consented context use,
program artifacts, and preview availability; they do not score generated answer
quality or claim production eligibility accuracy.

Run the read-only local evaluator from the repository root, using an explicit
historical date for regression:

```powershell
npm run evaluate:context -- --snapshot-date 2026-11-06
```

The evaluator reads repository fixtures and rules, creates only in-memory demo
sessions, makes no network or remote-model calls, writes no files, and returns a
JSON report with `remoteModelCalls: 0`.
Both comparison paths use the same selected UTC instant. Without
`--snapshot-date`, that is the current time and expired rule reviews fail with
a structured, nonzero error. The report includes `evaluationMode`, `evaluatedAt`,
the rules' reviewed date as `fixtureAsOf`, and
`currentSourceReadinessVerified: false`. Neither mode queries deployed source
readiness; a historical pass is not current-source evidence. Runtime source and
rule checks continue to use the real clock.
