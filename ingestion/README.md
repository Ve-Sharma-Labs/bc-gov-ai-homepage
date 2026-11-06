# Controlled public-source ingestion

This independent Python package performs controlled public-source acquisition
and explicitly reviewed Azure Search publication. Acquisition is read-only:
it does not collect citizen accounts or file uploads, submit forms, call Web IQ,
authenticate to a publisher, or create Azure resources on startup.
`data\pilot-catalog.json` is the application's curated snapshot; this tool does
not manufacture eligibility results or replace the API.

The initial public release published 12 chunks from four approved snapshots:
Service BC, Health Connect Registry, MSP and Fair PharmaCare. Eleven acquired
documents remained withheld. This is a limited reviewed publication, not an
automatic crawl or blanket approval of the source inventory. See the
[content-lifecycle diagram](../docs/architecture.md#4-reviewed-content-lifecycle)
and [current architecture](../docs/architecture.md).

The November 6, 2026 refresh replaced those same four documents with **20 active
reviewed chunks**: Service BC 11, Health Connect Registry 2, MSP 2, and Fair
PharmaCare 5. The exact 12 prior keys were marked `superseded`, not deleted.
The additive 29-field schema update preserved existing field definitions and
semantic/vector settings. Actual November 5 acquisition timestamps were retained;
the first next-expiry boundary is November 12 at 19:48:35 UTC under the unchanged
seven-day policy. This approval does not extend to ICBC full text, held documents,
or the private full-corpus candidates.

The API rejects evidence outside its configured freshness window even if the
index contains active chunks. Its read-only `sourceHealth` check and operational
metrics now expose that state; they do not authorize a refresh or publication.
For a refresh, reacquire only the reviewed scope, inspect the actual new
content/extraction/review hashes, and obtain a new exact-snapshot approval.
Retain the authoritative publication ledger and validate the old chunk keys
that a replacement will retire. A fresh worktree's empty ledger is not proof
that the live index has no previous versions. Any additive index-schema change
also needs its own explicit review; do not silently drop metadata to fit an old
schema or publish competing active versions.

## Install and verify locally

Run from the repository root; Python 3.11+ is supported and Python 3.14 was tested.

```powershell
python -m venv .\ingestion\.venv
.\ingestion\.venv\Scripts\python.exe -m pip install -e .\ingestion
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion validate
.\ingestion\.venv\Scripts\python.exe -m unittest discover -s .\ingestion\tests -q
```

No Azure packages or credentials are required for the parser, catalogue
validation, acquisition, dry runs or core tests. The native index-schema test
skips if the optional SDK is not installed. To validate the optional adapter:

```powershell
.\ingestion\.venv\Scripts\python.exe -m pip install -e ".\ingestion[azure]"
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion index-schema --index-name bc-pilot-public
```

On Windows with a deeply nested checkout, isolated editable-wheel builds can hit
path-length limits. The verified fallback uses a short **project-local** build
directory and installs the already-declared build requirement:

```powershell
New-Item -ItemType Directory -Force .\ingestion\.b | Out-Null
$env:TEMP = (Resolve-Path .\ingestion\.b).Path
$env:TMP = $env:TEMP
.\ingestion\.venv\Scripts\python.exe -m pip install --no-cache-dir "setuptools>=77"
.\ingestion\.venv\Scripts\python.exe -m pip install --no-cache-dir --no-build-isolation -e ".\ingestion[azure]"
```

## Explicit operations

```powershell
# No requests, no authentication, no generated files.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion dry-run

# Plan an explicit page. This does not test robots or fetch content.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion dry-run --url "health=https://www2.gov.bc.ca/gov/content/health/health-drug-coverage"

# These next two examples make bounded publisher GET requests; rerun only when reviewed.
# Discover collects candidates on selected pages, not an automatic recursive crawl.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion discover --max-pages 2 --url "health=https://www2.gov.bc.ca/gov/content/health/health-drug-coverage"
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion extract --max-pages 2 --url "healthlink-bc=https://www.healthlinkbc.ca/find-care/health-connect-registry"

# Fetch the exact, dataset-specific Open Government Licence record and its
# bounded 100-row DataStore view. This produces a candidate only, never a live
# catalogue update or Search publication.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion open-data-service-bc --execute

# Produces an ignored plan and summary; does not connect to Azure.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion publish
```

Repeat `--url SOURCE_ID=HTTPS_URL` for an explicit list. No URL means no manual
discovery or extraction. The manual sample is capped at **25 document requests**,
including redirects, cumulatively in its ledger. Re-running `extract`/`discover`
against that ledger does not reset the cap. Robots are additional, with a
100-request/128-MB cumulative safety bound for the whole manual sample.
The implementation sample used only fifteen content requests and six robots
endpoints. Do not loop sample commands or create replacement sample ledgers to
evade the cap; use the separately authorized programme mode below.

Generated files must be in a project `.generated` directory, normally
`ingestion\.generated`. `state.json` stores response/content hashes, canonical
documents, aliases, versions, check/fetch/publisher dates, quality gates,
duplicate references and tombstones. The catalogue/provenance files are
independent reviewed deliverables; running extraction does not overwrite them.

### Licensed Service BC office candidate

The official B.C. Data Catalogue record
`service-bc-office-locations` is explicitly published under the
Open Government Licence - British Columbia, marked public/published and
described as an up-to-date authoritative source maintained by Service BC.
`open-data-service-bc --execute` requests only the exact CKAN `package_show`
record and its reviewed DataStore resource, with a 100-row bound.

The current candidate contains 65 unique office codes and is stored at
`ingestion\.generated\open-data\service-bc-office-locations-d60992640b1f.json`.
Its review hash is
`d60992640b1f034cfb1c240bcec3deeb4fc6f9b83e2fe032ec14e92ea18f93a0`;
its normalized content hash is
`30884190d4caaa7d385f3434949a34bfa306cae63e3af2be9a4782d9d693e031`.
It is **not approved or published**. The dataset does not establish current
office hours or service capabilities, 60 website values use legacy HTTP URLs,
three fax values are absent, and the DataStore resource timestamp needs review.
Those limits are explicit candidate flags, not silently filled fields.
The adapter also converts the exact candidate into a sectioned
`service-directory` document plus exact-hash review candidates and chunks under
`ingestion\.generated\open-data\service-directory`. Chunk content is limited to
office identity, address/locality/coordinates and supplied phone, fax, email and
website values. It never creates hours or service-capability claims. Publisher
website strings are preserved exactly, including legacy `http://` values.

## Source-specific adapter contracts

`source_adapters.py` adds composable HTML/feed contracts without widening
`policy.py` or removing any source hold:

- Province `/gov/content` routes retain the broad `bc-content` tag and the
  canonical nested source/topic tag (for example `health` or `service-bc`).
- BC Housing pages carry the explicit update-pause/current-to date and remain
  freshness-review gated. HealthLink BC separates government service navigation
  from Healthwise/WebMD Ignite third-party clinical content and requires
  publisher freshness evidence.
- ICBC accepts only a bounded complete-content JSON publisher feed or an
  explicitly controlled rendered response with one `www.icbc.com` canonical,
  a complete main region and no account, booking, payment, claims or personal
  path. Ordinary fetched client shells remain unsupported.
- WorkBC accepts only approved static guidance/training/career routes, rejects
  live job-board paths/records, and rejects offline or maintenance responses.
- `legal_xml.py` is a dedicated BC Laws CiviX/legal parser, not a sitemap
  parser. It preserves legal identity, consolidation/effective dates,
  amendments, repeal/historical status and exact section locators. Current mode
  fails closed unless the XML explicitly establishes an in-force,
  nonhistorical version.

All alternate adapters are candidate-only and feed the same `Ledger`,
`review-required.json` and bounded `chunks.json` artifacts. Offline fixtures can
be exercised without network or Azure access:

```powershell
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion adapt-source `
  --adapter icbc-rendered `
  --source-url "https://www.icbc.com/driver-licensing/getting-licensed/renew-your-licence-or-id" `
  --response-file .\ingestion\tests\fixtures\icbc_rendered.html `
  --checked-at "2026-10-27T18:30:00Z"

.\ingestion\.venv\Scripts\python.exe -m bc_ingestion adapt-source `
  --adapter bc-laws-civix `
  --source-url "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/24001" `
  --evidence-url "https://www.bclaws.gov.bc.ca/standards/Licence.html" `
  --response-file .\ingestion\tests\fixtures\bc_laws_current.xml `
  --checked-at "2026-10-27T18:30:00Z"
```

Selecting `icbc-rendered` is an operator assertion that the file came from the
approved controlled renderer; the adapter still validates completeness and
canonical identity. These commands do not fetch, publish, clear catalogue
states, or override publisher permission. PDFs, forms, Office files and live
job records remain excluded.

## Source boundary and quality gates

`bc_ingestion\policy.py` registers six publisher hosts and selected path prefixes:

- Government: selected topic roots and the corrected Service BC branch.
- BC Housing: root notice and rental-assistance program branch.
- ICBC: acquisition is now held by the posted Terms section 16 (automation,
  systematic collection and reuse). An opt-in Open Data Licence does not
  authorize ordinary licensing webpages. Archived direct HTML still retains a
  rendering-review gate.
- HealthLink BC: selected care/navigation branches.
- WorkBC: content acquisition held until the invalid robots policy or an approved
  feed is resolved.
- BC Laws: content acquisition held pending approved CiviX/export and licence
  verification; never impersonate a permitted search bot.

Acquisition uses an identified crawler, HTTPS GET only, no cookies or proxy
credentials, same-host redirects, path checks on every hop, public-only DNS
answers and a TLS connection pinned to the checked address. Credentials,
nonstandard ports, private/mixed DNS answers, caller-supplied query workflows,
ambiguous encoded paths, account/submission paths and external redirects are
rejected. The licensed Service BC adapter is the narrow exception: it uses two
code-owned, exact CKAN query URLs and validates dataset/resource/licence identity.

Robots policies must return 200 with valid plain text. HTML, missing/redirected
policies, malformed rules and denied paths fail closed. Standard wildcards,
specific user-agent groups, longest-match rules and a longer publisher
`Crawl-delay` are honored. A single worker is sequential: at least one second
between host requests. Host request deadlines are durable in an acquisition
ledger/manifest. Run one worker/manifest per publisher programme; separate
manifests do not share a rate limiter. Manual samples do not automatically retry.
The full programme has a finite, durable retry budget and honors `Retry-After`.

Default limits: 25-second HTTP timeout, 4 MB HTML, 512 KB robots, four followed
redirects. Responses are requested uncompressed and unexpected compression is
rejected. ETag/Last-Modified conditional requests are used when available; HTTP
304 requires a known version, and 404/410 withdraw prior versions. Failed
refreshes quarantine active content rather than asserting continued currency.

Extraction preserves headings, accordion exclusion labels, lists and complete
table rows. The 2,400-character grouping target is soft, but **every new upload
is at most 8,000 characters**. Long prose splits without removing words; long
simple tables split only between rows, repeating headers, captions, introductory
context and surrounding exclusions. Local table references resolve to their
complete definition/qualification sections; relevant definitions, `tfoot` notes
and `aria-describedby` qualifications accompany every affected part. Missing,
ambiguous or oversized referenced groups remain review-gated. Prose exceptions repeat in every affected
part. An oversized row, oversized required exception/context, unverified legacy
table structure or unsplittable merged-cell table quarantines the document with
an explicit reason; the complete extracted text and response remain available
for review. There is no truncated-table fallback. Footer-only, too-short, maintenance/access-denied,
missing-region, unresolved dynamic, publisher-freshness and prompt-like content
is quarantined. Ordinary complete-looking text is still **review-required**,
never automatically active.
Nested/merged-cell tables and exclusions outside the structured extractor's
supported elements also retain explicit structural-review gates; they are not
silently treated as complete ordinary prose.

## Full programme: durable candidates, not blanket publication

`data\source-programme.json` defines the twelve overlapping topic seeds and six
hosts. It is an inventory, **not permission**: its null `rightsReview` values,
historical sitemap counts and candidate aliases cannot authorize acquisition.
`programme_policy.py` is an explicit, broader **candidate** policy. It does not
widen `policy.py`'s manual/publication paths.

```powershell
# Offline by default: persist seeds, blocked reasons and coverage; no publisher/Azure calls.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion programme

# Only after an accountable owner supplies actual publisher/path/format rights evidence.
# These examples describe capabilities; this implementation did not run a bulk acquisition.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion programme --acquire --rights-review .\ingestion\.generated\candidate-rights.json --request-budget 20000 --byte-budget 1000000000 --max-candidates 100000 --max-retries 2 --batch-requests 25 --run-seconds 120

# Same manifest, same rights review and cumulative budget. Limits are not reset or enlarged.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion programme --acquire --resume --rights-review .\ingestion\.generated\candidate-rights.json

# A running local worker observes the durable signal before its next request.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion programme --pause
```

`--programme` defaults to `data\source-programme.json`.
`--programme-manifest` defaults to
`ingestion\.generated\programme\manifest.json`; this is **separate from**
`ingestion\.generated\state.json`, `approved-review.json` and `publish-plan.json`.
Packaged runtimes set the absolute `BC_INGESTION_PROJECT_ROOT` so those defaults
resolve to the copied catalogue, programme and writable output directories.
An explicit `--url SOURCE_ID=HTTPS_URL` list may select starting candidates;
otherwise all twelve seeds and declared sitemap URLs are inventoried. Original
seeds, registry/catalogue identities and cumulative limits cannot change on resume.
`--max-pages` remains the manual cap, not a full-programme override.

Programme defaults are 20,000 **total publisher HTTP requests** (robots, sitemaps,
redirects and retries included), 1,000,000,000 charged response bytes,
100,000 frontier URLs, two retries, 4-MB content responses, 512-KB robots,
25-second per-request timeout and at least one second between host request
starts. An invocation checkpoints after 25 requests or 120 seconds by default;
one in-flight request may finish within its own timeout. Publisher crawl delays
and `Retry-After` can require a later explicit resume. Requests/bytes are charged
**before dispatch**; a failed or interrupted read retains its conservative
byte reservation, including the transport's one-byte overflow probe.
The counters and retry attempts survive process interruption. This is bounded
at-least-once acquisition after an interrupted request, not an impossible
exactly-once network guarantee; canonical ledger versions remain idempotent.

The following is an **invalid, deliberately unapproved template**, not a rights
review. Replace placeholders only with real accountable evidence. `programmeHash`
is the SHA-256 of canonical JSON (`metadata.digest`) for the registry, not a
hash invented from the catalogue name. Times require explicit offsets.

```json
{
  "schemaVersion": 2,
  "programmeHash": "<exact-registry-hash>",
  "purpose": "candidate-acquisition",
  "approvalKind": "internal-blanket",
  "approvalConfirmed": false,
  "reviewer": null,
  "reviewId": null,
  "reviewedAt": null,
  "expiresAt": null,
  "approvalEvidence": {
    "kind": "internal-session-approval",
    "reference": "<private-record-reference>",
    "sha256": "<canonical-evidence-sha256>"
  },
  "revocation": {
    "status": "active",
    "reference": "<private-revocation-reference>",
    "revokedAt": null
  },
  "exclusions": [
    "authenticated-paths",
    "bookings",
    "forms",
    "payments",
    "pdf",
    "personal-records",
    "third-party-clinical-content",
    "transactions",
    "uploads",
    "workbc-job-board-data"
  ],
  "grants": [
    {
      "host": "www2.gov.bc.ca",
      "pathPrefixes": ["/gov/content"],
      "routes": [
        {
          "technicalRoute": "html",
          "format": "html",
          "pathPrefixes": ["/gov/content"],
          "clearsAccessHold": null
        },
        {
          "technicalRoute": "sitemap-xml",
          "format": "sitemap-xml",
          "pathPrefixes": ["/sitemap"],
          "clearsAccessHold": null
        }
      ],
      "publicReferences": [
        {
          "kind": "copyright",
          "url": "https://www2.gov.bc.ca/gov/content/home/copyright"
        }
      ]
    }
  ]
}
```

Grants are per host, source path, technical route and format, expire after at
most 30 days, carry a private exact-hash approval reference, and bind to the
exact programme and review hash. Public licence, terms, copyright, access and
robots references remain separate from private approval evidence and are
recorded only when a real first-party URL exists. Revoked reviews fail closed.
Legacy schema-v1 publisher-evidence reviews remain readable for existing runs,
but they cannot express or clear route-specific holds.
A grant does not bypass robots, authenticated/account/transaction exclusions,
source quality holds or human publication review. A route may clear only the
matching programme access hold named on a more-specific non-`/` prefix; a
blanket wildcard cannot clear a hold. Rights for HTML do not silently authorize
a sitemap, rendered page, publisher feed or legal XML route. A sitemap's
declaration of `icbc.com` is not verification of an alias: cross-host redirects
and canonicals are still rejected. Same-host canonical targets must pass both
scope and robots checks before their aliases are merged. Canonical identity
deduplicates overlapping seeds while retaining every matching source/topic tag.

Implemented capabilities: direct HTML/XHTML extraction, **discovery-only**
standard XML sitemaps without DTDs/entities, the bounded source contracts above,
and dedicated CiviX/legal XML parsing from an explicitly supplied approved
response. The programme crawler still acquires only ordinary permitted HTML and
discovery sitemaps; it does not manufacture rendered responses or feed access.
PDF/Office documents, compressed sitemaps, arbitrary XML, forms and live job
records remain unsupported. WorkBC's invalid robots response, BC Laws'
general-crawl denial, runtime robots decisions, ICBC terms/rendering
requirements and BC Housing freshness review remain independent gates. Adapter
availability is not permission.

### Checkpoint, review and coverage files

Under the programme manifest's directory:

| Path | Meaning |
|---|---|
| `manifest.json` | Revisioned frontier, canonical aliases, shared `Ledger` candidate state, exact rights identity, request reservations, host deadlines, retries, events and discovery cursors |
| `manifest.lock` | OS-released exclusive local worker lock; not a stale lock-file heuristic |
| `pause-request.json` | Durable stop signal, cleared only by explicit acquisition resume |
| `responses\<sha256>.body` | Immutable publisher response bytes; an existing object's digest is verified before reuse |
| `review-required.json` | Exact candidate hashes and quality flags, explicitly **not** an approval |
| `plans\<plan-hash>.json` | Content-addressed, exact-review publication plans; generating one is not executing it |
| `coverage.json` | Canonical/source/host counts, sitemap counts, aliases, states, withheld reasons, unexpanded links and cumulative budgets |

Frontier exhaustion is not a claim of complete coverage. Blocked sources,
unsupported formats, incomplete extraction and unexpanded links remain visible.
A frontier cap pauses at a persisted discovery cursor instead of silently
dropping the rest of a sitemap/table/page. A resume with a different programme,
rights identity or enlarged quota is rejected. Do not delete a manifest to make
an exhausted acquisition look like a new unreviewed sample.

To review candidates offline, use `programme --rights-review <file>
--review-manifest <exact-review.json>`. To separately publish an authorized
candidate plan, use `publish --programme-manifest <manifest.json>
--rights-review <file> --review-manifest <exact-review.json>`, with the existing
execution/environment gates below. The full-programme ledger cannot be sent
through the narrow manual publisher by omitting its explicit policy.

### Ephemeral Container Apps Jobs / private Blob checkpoints

`azure_blob.py` implements `ManifestStore` and `ResponseStore` using the existing
optional Azure SDK dependencies. Select it explicitly with
`--programme-store azure-blob`. Local mode remains the default; importing the
adapter or running local commands never authenticates to Azure. Selecting Blob
mode performs storage operations, but publisher acquisition still needs
`--acquire` plus a valid exact rights input. The implementation was tested with
offline SDK fakes/fault injection, not a live storage account or deployed job.

Provide **two separate, pre-existing private containers** in the specified
account. These example names are not provisioned by this package:

| Container / input | Job access and purpose |
|---|---|
| `bc-ingestion-candidates` | Storage Blob Data Contributor, scoped to this container: manifest lease/CAS, immutable candidate responses, scope inputs, review exports and plans |
| `bc-ingestion-rights` | Storage Blob Data Reader only: an accountable owner supplies the actual rights-review JSON; the candidate job has no create/update/delete path for this input |
| `AZURE_CLIENT_ID` | Optional user-assigned managed identity ID; otherwise ManagedIdentityCredential's default |
| `AZURE_STORAGE_ACCOUNT_URL` | Optional fallback for `--blob-account-url`, HTTPS account endpoint only |

No keys, SAS URLs, connection strings, interactive authentication or automatic
CLI-credential fallback are accepted. An authorized operator can explicitly
select `--credential azure-cli`; the job default remains `managed-identity`.
Keep the source registry and catalogue in the immutable job image/checkout.
They are hash-checked on resume and also archived as candidate scope artifacts.
Do not reuse the existing published-content container for candidate writes.

The separately privileged publisher identity can place one canonical rights file
with the create-only `rights-upload` command. It accepts only
`bc-ingestion-rights/reviews/<run-prefix>.json`, requires the exact raw SHA-256
to equal the canonical JSON digest, validates the current programme/catalogue
schema and performs an ETag-conditional read after upload. Existing different
bytes are never overwritten. The managed-identity execution must set the
publisher's exact `AZURE_CLIENT_ID`; the acquisition identity remains Reader:

```powershell
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion rights-upload `
  --blob-account-url "https://<account>.blob.core.windows.net" `
  --rights-container bc-ingestion-rights `
  --rights-blob reviews/bc-full-v2.json `
  --run-prefix bc-full-v2 `
  --rights-sha256 <exact-canonical-file-sha256> `
  --rights-file <private-canonical-rights.json> `
  --credential managed-identity
```

Omit `--execute` for local validation. A one-shot publisher job may instead
provide the same bytes through the fixed `BC_RIGHTS_UPLOAD_BASE64` environment
input, add `--execute`, and override that execution only; its persistent
validation template does not need to change.

Initialize a durable run **once**, after the parent separately reviews and
provides private endpoint/DNS/network reachability and container-scoped roles.
Initialization can inventory candidates without granting acquisition rights:

```powershell
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion programme --programme-store azure-blob --blob-account-url "https://<account>.blob.core.windows.net" --candidate-container bc-ingestion-candidates --run-prefix bc-full-v1 --initialize --request-budget 20000 --byte-budget 1000000000 --max-candidates 100000 --max-retries 2
```

The repeated Container Apps Job command is:

```text
python -m bc_ingestion programme
  --programme-store azure-blob
  --blob-account-url https://<account>.blob.core.windows.net
  --candidate-container bc-ingestion-candidates
  --run-prefix bc-full-v1
  --acquire --resume
  --rights-container bc-ingestion-rights
  --rights-blob reviews/bc-full-v1.json
  --rights-sha256 <SHA256-of-the-exact-rights-file-bytes>
  --batch-requests 25 --run-seconds 120
  --credential managed-identity
```

Supply arguments as an array or one shell command; the displayed lines are not
shell continuations. The raw-file `--rights-sha256` is distinct from the
canonical-JSON `rightsReviewHash` already used in the ingestion metadata.
Both must remain bound to the same reviewed input. Read/download uses the
observed rights ETag, and subsequent storage/request boundaries recheck that
ETag. Expiry, replacement, revocation or inability to read the input stops the
job. The writable candidate checkpoint stores only the rights reference/hash,
not an editable copy of the grant. Blob mode rejects local `--rights-review`
and `--programme-manifest` paths, so ephemeral files cannot become authority.

Always reuse the same account, containers and **stable** run prefix. A missing
resume fails; it does not initialize empty counters. `--initialize` uses
conditional create and refuses an existing run. It cannot be combined with
resume/pause/publication. An acquisition step cannot enlarge quotas or swap
the scope/rights identity. Use one programme worker per host; job parallelism
should be one. Overlapping executions of this same run are also excluded by
the lease. Different prefixes do not share rate limits, so do not generate a
prefix per execution to bypass budgets.

#### Remote object layout and commit semantics

All candidate objects are below `--run-prefix` in `--candidate-container`:

| Blob object | Meaning |
|---|---|
| `<prefix>/manifest.json` | Small storage-format-v2 pointer: logical revision, hot-control reference, compacted index root, journal head/sequence/anchor and bounded storage format settings; leased during the complete run |
| `<prefix>/objects/<sha256>` | Create-only hot control, journal segments, immutable B+ tree pages, lazy document/link payloads, raw responses, scope inputs and bounded exports |
| `<prefix>/pause-request.json` | Independent pause signal; creation does not require the running worker's lease, and resume acknowledges it conditionally |

1. A 60-second manifest lease is renewed every 15 seconds, including while
   waiting for host pacing or publisher responses. Failure to renew or prove
   ownership stops further operations. The implementation never breaks a lease.
2. Before **each publisher request**, the request/byte reservation and host
   deadline are uploaded in the small immutable **hot-control record**, and the
   leased `If-Match` pointer commits that record before the request can run.
   A budget-only checkpoint does not read, copy or upload any documents.
3. Response objects and derived artifacts upload with `If-None-Match: *`.
   Previously acknowledged immutable objects can be reused within an execution
   without a redundant HEAD. Cold reads use the committed ETag, exact byte
   length and SHA-256; an unexpected existing upload is verified, not overwritten.
4. Mutations are tracked per canonical candidate/document record. Large sections
   and link lists live in separately addressed payloads. Audit/seed/review lists
   use bounded append pages. Changed metadata/index operations enter immutable
   journal segments; untouched records and payloads are not serialized again.
   Once the journal reaches its threshold, bounded oldest segments compact into
   copy-on-write B+ tree pages. Only affected pages and ancestor paths are written,
   not an entire corpus index or document snapshot.
5. New payloads, journal segments, hot control and any compacted pages upload
   first. The small manifest pointer then advances using its **previous** ETag
   and active lease. A crash before
   the pointer commit can leave unreferenced objects, never a partially committed
   file set. A lost commit acknowledgement is fatal/ambiguous, not automatically
   retried or rolled back; the next owner reloads the remote committed revision.
6. Resume validates hot control and a **bounded** journal suffix: contiguous
   sequences, unique operations, byte counts and the compacted anchor must agree.
   Index pages, document sections, links and raw artifacts are validated lazily
   on actual use with conditional GET and exact SHA-256/length checks. There is
   no HEAD scan of all referenced artifacts. A cold missing/modified artifact
   fails when requested; successful resume is not a claim that every cold
   artifact was re-audited.
7. Pending/discovery/retry/in-flight queues, URL aliases, content duplicates,
   review summaries and coverage counts have transactional indexes/materialized
   counts. Resuming, selecting work and reporting do not walk all documents.
   Rights ETags are rechecked at load and commit/request boundaries, not on
   every cached reference lookup.

   In-flight reservations remain charged conservatively; interrupted acquisition
   is bounded at-least-once, not an exactly-once network promise.

There are no local files required to resume a Blob-backed run. Logical names
such as `review-required.json`, `coverage.json`, `inputs/programme.json`,
`inputs/catalog.json` and `plans/<plan-hash>.json` resolve through the manifest's
`artifacts` index. `artifactOrigins` records the producing state revision: derived
reports from a previous completed step can be older than an interrupted
acquisition's authoritative ledger, and are refreshed on resume. CLI output
contains private object URLs without SAS tokens. Review/publication remains a
separate exact-hash operation; acquisition never marks candidates active.
Blob-backed `review-required.json` is a bounded index page (100 documents by
default), not an unbounded per-job reconstruction of every chunk. Use
`--review-page-size <1..1000>` and `--review-after <document-id>` to follow its
`nextAfter` cursor. Cached review identities are discovery metadata only:
publication still recomputes content, extraction and exact review hashes.
Local/sample review exports retain their original complete-file behavior.

SDK storage retries are disabled for these operations to avoid hiding ambiguous
write outcomes. Connection/read timeouts are 5/10 seconds. Internal storage
limits are explicit in `checkpoint_tree.StorageLimits`:

| Limit | Default |
|---|---|
| Hot control / leased pointer / rights input | 128 KiB / 16 KB / 1 MB |
| Individual metadata record / immutable index page | 32 KiB / 64 KiB |
| B+ tree fanout / maximum depth | 32 / 8 |
| Large immutable payload | 16 MiB |
| Journal segment | 32 operations, at most 256 KiB |
| One commit's mutation set | 256 operations |
| Retained journal target / absolute replay cap | 8 / 16 segments, at most 4 MiB replay |
| One compaction | At most 8 segments, 512 written pages, 16 MiB |
| Audit/seed list page / index and record caches | 32 items / 256 pages and 256 records |
| One execution's internal storage work | 5,000 calls, 64 MiB read, 256 MiB written, 110 seconds |

Limits fail explicitly before additional work; they never discard a record,
reset acquisition counters or turn a storage failure into a publisher retry.
A bounded SDK request already in flight can finish within its own timeout.
Execution/cache ceilings are independent of the committed format settings and
publisher budgets; the latter still survive every execution. Source discovery
checkpoints in batches of 50, so an interrupted large sitemap resumes its saved
cursor. Bootstrap/rights-input reads and lease release are small, fixed overhead,
not per-document work.

Storage v2 does not rewrite local/sample state. Small old Blob-v1 checkpoints
(at most 8 MiB and 24 candidate/document records) can migrate atomically while
preserving revision, quotas, references and approvals. Larger legacy monoliths
fail with an explicit offline-migration requirement rather than silently
reinitializing or doing unbounded conversion in a job.

The offline scaling test uses the real ledger/extractor, **500 then 1,000
synthetic candidate/document records**, three checkpoints per record, and a fresh
Blob-store instance every 25 records:

| Measured storage work | 500 records | 1,000 records |
|---|---:|---:|
| Uploaded bytes, including immutable index versions | 92,594,703 | 215,895,695 |
| Accounted storage calls | 14,532 | 32,612 |

Doubling records increased uploaded bytes **2.33×** and calls **2.24×**, not 4×.
Manifest resume needed at most **15 calls / 116,671 bytes**, plus the separate
fixed rights-input read. The largest object was **65,521 bytes**. A hot
reservation-only save read **zero** cold-document bytes and uploaded under
16 KiB. Tests also cover replay corruption, lazy artifact corruption, lease
loss, unknown commit acknowledgement, compaction failure, nested mutations,
bounded review paging and local/legacy compatibility. These are measured
offline storage-protocol results, not live Azure throughput/SLA claims.

Publisher budgets do not count storage control-plane I/O. This implementation does not
perform garbage collection: retain all referenced objects, and only remove
orphans through a separately reviewed, lease-aware retention process. Changing
or deleting immutable objects outside this protocol invalidates their references.

To pause a remote worker, issue `programme --programme-store azure-blob` with
the same account/container/prefix and `--pause` (no `--acquire`/`--resume`).
The next request boundary observes the durable signal. Only explicit resume
clears it. Exit code 1 denotes a planned acquisition pause; exit code 2 denotes
a validation/storage failure. Use job replica retry limit 0 and let the
orchestrator inspect `status`/`pauseReason` before deliberately starting another
execution. `--resume` also acknowledges an operator pause: do not blindly
schedule that acknowledgement after someone has requested a stop.
Do not configure job retries to recreate manifests.
Private endpoint/DNS/roles and actual rights evidence remain external activation
requirements; no such resources, grants, crawling or publication were created here.

### Archived Service BC re-extraction, without crawling or publication

The saved Service BC response's SHA-256 is checked against its exact source
ledger version before re-extraction. The read-only operation below writes only
a separate candidate directory:

```powershell
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion reextract --from-ledger .\ingestion\.generated\state.json --document-id 41a0dff74c96234f8edb988e2acbb02b --response-file .\ingestion\.generated\service-bc.html
```

`--snapshot-version` can select an exact older version; otherwise the active
snapshot (or latest when none is active) is used. Output is under
`ingestion\.generated\reextractions\<compact-id-and-hash>\`, including
`identity.json` with the full identities, candidate `state.json`,
`responses\<full-sha256>.body`, `chunks.json`, `review-required.json` and
`extraction-report.json`. Compact directory names avoid deep Windows path limits
and are checked for identity collisions. Source ledger/approval/plan files are
not overwritten, and re-extraction does **not** advance source checked/fetched
dates or create permission/approval.

The captured 23,141-character legacy table grouping re-extracts into **11
document chunks, maximum 7,965 characters**: eight contain all **65 complete
office rows**, repeated column headers and the applicable definitions for
`#services`, `#icbc`, `#income`, `#verifyid`, `#pesticide` and `#waste`. No cell is
truncated. Qualifications and footnotes are repeated where needed; groups that
cannot fit, malformed references and unsupported merged/nested structures are
explicitly quarantined. The full source response remains available.

These are **new review-required candidates**, not an updated live publication.
Their review hash binds the archived source identity and old published chunk
keys. Only a separately approved exact replacement plan retires those old keys;
an unapproved re-extraction does not withdraw or overwrite the current snapshot.

## Azure publishing - explicit and review-gated

Official packages are `azure-identity`, `azure-search-documents` and
`azure-storage-blob`. `azure_publish.build_index()` is the single source of the
native Search index schema. It defines lexical search plus an optional semantic
configuration named `bc-public-guidance`; it does **not** invent an embedding
model or vector dimensions. `--vector-dimensions <reviewed-dimensions>` exports
the matching `contentVector`/HNSW schema without making Azure calls.

Index fields: `id`, `documentId`, `sourceId`, `title`, `publisher`, `url`,
`content`, `section`, `checkedAt`, `publisherUpdatedAt`, `status`, `topics`,
`journeyIds`, `documentVersion`, `contentHash`. Retrieval **must filter
`status eq 'active'`**. Dates use `Edm.DateTimeOffset`; unknown publisher dates
remain null. No payload logging or stored user inputs are part of this package.

The original fields and index name remain compatible. Additive optional fields:

| Type | Fields |
|---|---|
| String | `canonicalUrl`, `sourceUrl`, `language`, `documentType`, `mediaType`, `extractionMethod`, `extractionHash`, `responseHash`, `rightsStatus`, `rightsReviewId`, `rightsHash`, `licenceUrl`, `legalStatus`, `legalSectionId`, `reviewHash` |
| ISO calendar-date string | `effectiveFrom`, `effectiveTo`, `consolidationDate`, `repealedAt` |
| Collection(String) | `sourceIds`, `aliasUrls`, `amendmentIds`, `sectionLocators` |
| Int32 | `metadataVersion`, `chunkPart`, `chunkParts` |
| Boolean | `isHistorical`, `containsExceptions` |
| DateTimeOffset | `fetchedAt` |

### Rollback-safe metadata shadow

The supported pre-publication path is a separate, empty
`bc-pilot-public-v2` index. It retains Direct Search and the
`bc-public-guidance` semantic configuration, includes the complete metadata
contract above, and deliberately omits `contentVector` and vector-search
configuration. It never reads or changes `AZURE_SEARCH_INDEX`, never uploads
documents, and refuses to use the live `bc-pilot-public` name as the shadow.

The command emits JSON containing both index inventories, document counts,
ETags, normalized schema SHA-256 values and an exact field/semantic/vector diff:

```powershell
$env:AZURE_SEARCH_ENDPOINT = "https://srch-bcassist-xufhsendpx.search.windows.net"

# Read-only inventory, including a missing shadow.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion shadow-index --shadow-action get --credential azure-cli

# Create only when missing. A concurrent/existing index is read and validated,
# never upserted, replaced, deleted, or migrated.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion shadow-index --shadow-action create --execute --credential azure-cli

# Read back and require the exact vector-disabled schema.
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion shadow-index --shadow-action validate --credential azure-cli
```

Creation requires `Search Service Contributor` on the Search service for the
selected identity. The implementation uses create-only semantics, validates a
concurrent existing index, and compares the live index schema fingerprint and
ETag before and after the operation. An incompatible v2 schema fails without an
update. Candidate publication and switching the API to v2 are separate,
explicitly reviewed operations.

Unknown metadata stays null (collections may be empty); an HTML `lang` attribute
is not a guessed language. Metadata is carried in the local document's versioned
`metadata` object and flattened only for Search. `responseHash` identifies raw
publisher bytes; `contentHash` retains the existing normalized text definition;
`extractionHash` also binds structure, canonical provenance, language/type,
rights, publisher date and legal metadata. `reviewHash` binds that snapshot,
the chunk layout/8,000-character contract and its review generation. No user
conversation is stored. The existing English content analyzer is unchanged;
language metadata does not claim a multilingual index/analyzer migration.

Legal intervals use **inclusive start, exclusive end**, in explicit publisher
calendar dates. Repeal bounds the interval; consolidation, fetch/check time and
HTTP Last-Modified are never substituted for effective dates. Unknown effective
time returns unknown. Legal section identity, amendment references and historical
status travel with the exact snapshot. This metadata contract is not a working
CiviX extractor or a representation that legislative coverage exists.

`merge_index_schema` copies the live schema and only appends compatible fields
and missing configurations. It preserves existing vectors/dimensions, unknown
fields, scoring/semantic settings and data. Incompatible field types, analyzers
or vector dimensions require a separately reviewed new index; they are not
silently replaced. `--create-index` now conditionally creates a missing index or
updates an existing one with its live ETag (`IfNotModified`), with downtime
disabled. It never deletes/recreates an index. Offline migration preview:

```powershell
.\ingestion\.venv\Scripts\python.exe -m bc_ingestion index-schema --index-name bc-pilot-public --existing-schema .\ingestion\.generated\exported-index.json
```

**Activation is separate:** authorize/apply the additive schema before uploading
new metadata, then re-review/re-publish selected new snapshots. Old indexed
documents retain null new fields. The protected four-snapshot state and approvals
were not rewritten by this implementation. Its legacy Service BC snapshot has a
23,141-character table chunk: old keys remain available for exact withdrawals,
but new upload planning withholds that document with
`legacy-structure-review-required` until the separate archived re-extraction
above is reviewed and explicitly published as a replacement.
Neither its table nor the already-published snapshot is silently truncated,
re-chunked, republished or withdrawn by a schema preview.

For an authorized publishing operation, configure the existing resources:

| Variable | Meaning |
|---|---|
| `AZURE_SEARCH_ENDPOINT` | `https://<service>.search.windows.net` |
| `AZURE_SEARCH_INDEX` | Existing reviewed index name |
| `AZURE_CLIENT_ID` | Optional user-assigned managed identity client ID |
| `AZURE_STORAGE_ACCOUNT_URL` | Optional `https://<account>.blob.core.windows.net` |
| `AZURE_STORAGE_CONTAINER` | Existing private staging container |
| `INGESTION_PUBLISH_ENABLED` | Must be exactly `true` for execution |
| `AZURE_SEARCH_VECTOR_ENABLED` | Explicit opt-in to real reviewed-document embedding |
| `AZURE_OPENAI_ENDPOINT` | Reviewed Azure OpenAI v1 embedding endpoint |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Actual embedding deployment, never inferred |
| `AZURE_OPENAI_EMBEDDING_DIMENSIONS` | Must match the Search vector field and API query embedding |

Authentication defaults to **ManagedIdentityCredential**, optionally selected
with `AZURE_CLIENT_ID`. A reviewed operator/CI execution may explicitly choose
`--credential azure-cli`; this is not an automatic fallback and does not change
the production API's managed-identity-only inference policy. There is no key,
connection string or interactive login in this tool. Grant the chosen identity
Search Index Data Contributor for documents, Search Service Contributor only if
index-schema updates are explicitly authorized, and Storage Blob Data Contributor
only on the approved staging container. This package never provisions resources.

Human approval is a separate file identifying exact content, for example:

```json
{
  "publisherPermissionConfirmed": true,
  "reviewer": "Accountable content owner",
  "reviewedAt": "2026-10-24T20:00:00Z",
  "documents": [
    {"documentId": "<from-state>", "contentHash": "<reviewed-content-sha256>"}
  ]
}
```

This example is **not an approval**. The initial publication used a separate
actual review manifest for exactly the four unchanged approved snapshots.
New or refreshed content needs its own exact-hash review; the remaining sampled
full text is not approved by that release. Even an approval cannot clear quality
flags, change publisher provenance, or promote Web IQ/model output. Hashes are
recomputed before promotion.
For new v2 extractions, each approved document also needs the exact
`extractionHash` and `reviewHash` from `review-required.json`; content-only
approvals remain compatible solely with untouched legacy v1 snapshots.
Metadata-only changes require new review. A withdrawn/quarantined snapshot that
reappears with identical words gets a new review generation; an old approval or
HTTP 304 cannot resurrect it. Repeated unchanged acquisition does not create
duplicate versions, and creating a review plan does not mark anything active.
New versions supersede previous active versions; withdrawal/quarantine plans
remove their Search chunk keys. Reviewed source text and metadata can be staged
as private JSON blobs, not user information or downloaded account files.

`publish` defaults to dry-run even with an approval file. Actual operations need
all of `--execute`, `--approved`, `--review-manifest` and the environment gate.
Optional `--stage-blob` writes only reviewed chunks to the existing container;
`--create-index` explicitly enables schema creation/update. Do not run those
options until the user and source owner authorize a separate publishing step.
Per-document SDK results are checked; failed batches are reported, not marked
complete. Search publication was executed for the initial four-document release
and its 12 indexed chunks were verified against Azure.

Blob staging is a separate optional path, not a prerequisite for Search
publication or API retrieval. The initial publication recorded a non-public
`reviewed-content` container with public networking disabled, no bypass and
no observed private endpoint. Re-verify the current approved network path before
staging or activating an acquisition job; this offline implementation does not
verify any subsequent infrastructure rollout. Reachability and the container-scoped
data role are both required. Provisioning a container is not proof that Blob
staging was exercised or is reachable from an operator's machine.

Withdrawals are applied before optional embedding/staging, so a later enrichment
failure cannot leave known withdrawn content active. Every upload and delete
acknowledgment must match the requested document keys. Source/quality gates can
withdraw previously published content; they cannot be bypassed by an old review.

When hybrid retrieval is enabled, the approved documents are enriched using the
real Azure OpenAI embedding API and explicit dimensions. Missing/wrong counts,
non-finite/zero vectors, mismatched schema dimensions and upstream errors fail
closed. There are no fabricated vectors or silent lexical fallbacks. The publisher
needs embedding invocation permission in addition to its scoped Search/Blob
permissions. Lexical/semantic-only publication remains valid without embeddings.

The hosting template creates a separate publisher identity; it does not attach
that identity to a job or grant the operator its permissions. Use an explicitly
authorized runner for that identity or grant the reviewed CLI publishing identity
the required data roles. Never repurpose the anonymous API identity for content
or agent publication.

SDK references:

- [Python Search package](https://learn.microsoft.com/python/api/overview/azure/search-documents-readme)
- [Semantic field configuration](https://learn.microsoft.com/python/api/azure-search-documents/azure.search.documents.indexes.models.semanticprioritizedfields)
- [Blob uploads and identity/RBAC](https://learn.microsoft.com/azure/storage/blobs/storage-blob-upload-python)
