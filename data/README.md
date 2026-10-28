# Curated pilot catalogue

`pilot-catalog.json` is the shared **camelCase schemaVersion 1** contract. It
contains twelve source registrations, five read-only preparation journeys and
seven Service BC offices. It is a manually curated dated snapshot, **not a live
index, complete service directory, generated AI answer or eligibility decision**.
The UTC `asOf` is October 25, 2026; the checks occurred on October 24 in B.C.

`provenance.json` records the fifteen direct-publisher HTML responses, their
SHA-256 hashes and check dates, six robots-policy endpoints, handoff verification,
and the source-to-journey evidence mapping. Dates not explicitly present in
publisher metadata are null. A stated content-currency date is **not** a
publisher-modified date or legal effective date.

## What was actually checked

- Fifteen public documents returned HTTP 200. Ten robots requests were made
  across six hosts, including conservative parser diagnosis/rechecks. No full
  sitemap crawl, PDFs, accounts, forms, registration portals or user uploads were
  collected. All journey handoff URLs are among those fifteen checked pages.
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
  freshness or dynamic limitations); four are review-required. None is approved
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
