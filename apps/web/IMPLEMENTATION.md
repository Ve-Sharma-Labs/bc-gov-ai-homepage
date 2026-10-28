# Web implementation

## Runtime and local commands

Next.js 16.4.2 and React 19.3.1 remain unchanged. Node 24 is required.
From the repository root, use `scripts/setup.ps1`, `npm run dev`, or
`npm run build` followed by `npm start` for the standalone production preview.
Root tooling starts the unchanged Python API and waits for the catalogue.

`API_BASE_URL` is server-only, defaults to local loopback, and is not present in
the browser bundle. Do not put credentials in `NEXT_PUBLIC_*` settings.
The API's origin/host policy and error contracts remain authoritative.

## Presentation

- shadcn CLI 4.22.0 generated the reviewed Base UI Button/Dialog source in
  `components/ui`. Base UI 1.9.0 and Motion 14.3.0 support the new menu/composer.
- Tailwind 4.3.3 and semantic CSS map to the same `data-theme` preference.
  The generated defaults are not the finished layout; `globals.css` owns the
  measured reference treatment.
- `HeroExperience` stages local BC photos and existing catalogue journey
  examples. `FeatureScenes` contains four original illustrative compositions.
- `BlurFade` is adapted from Magic UI, with static SSR and reduced-motion
  safeguards; it is not a whole Magic UI template.
- The existing accessible React Aria checklist, theme and reset controls remain.
  Do not nest an additional focus/overlay manager inside a control.
- `ASSETS.md`, `/credits` and `public/licenses` record asset and component
  provenance. Header branding and the favicon now use the user-supplied BC
  assets; their use does not itself establish public-release approval.

## State and navigation

`AssistantProvider` owns the catalogue/capabilities and tab-memory draft,
checklist, selected journey and stream state. Internal Next navigation retains
them; reload and confirmed reset clear them. No conversation state is persisted
in browser storage or URLs. A single theme preference is the exception.

`ComposerDock` renders exactly one interactive input. Its width-aware sizing
handles first layout, resizing and typed content; its layout shifts between
the page anchor and viewport dock. Visual-viewport changes keep the dock above
a mobile keyboard. Position-only layout motion avoids stretching the text as
the dock moves. Navigation does not repeat or start model requests.

Submitting echoes the question, clears the sent draft and opens `/chat`
immediately. Catalogue/capability discovery never gates the agent request;
the agent endpoint is authoritative if configuration has changed. Errors and
Stop restore the question unless the person has already written another draft.
Retry is one explicit request, not an automatic resend or a preliminary
capability check.

The composer defaults to **General B.C. chat**. `ComposerScope` exposes all five
guided pathways as optional scope, with visible Change and Clear controls.
Changing or clearing a pathway preserves the draft, checklist and conversation.
Scope is fixed for an active run and captured before transport loading; clearing
it sends the next request as general chat, never a hidden previous pathway.
The non-modal picker supports Escape and returns focus without adding an input.

`useScenePlayback` initializes a hydration-consistent static frame, then enables
motion when visible and permitted. Timers stop for offscreen/hidden-page,
explicit pause and reduced motion. Example rotation also pauses on focus/typing.
Images that fail before hydration are detected after mount, not only by onError.

## AG-UI and API boundaries

The published `@ag-ui/client` 1.0.3 remains the transport. The existing application
reducer owns visible message/error/citation state. There is no Vercel AI SDK,
CopilotKit Cloud, external model gateway or duplicated chat runtime.

Requests contain user/assistant text history with empty client tool/context/state
fields. Browser requests always send `forwardedProps.bc` version 2 with explicit
`mode: "general"` (no journey ID) or `mode: "pathway"` and its selected journey ID.
An unavailable general binding never triggers a legacy/specialist fallback.

The API-owned `CUSTOM/bc.response` event declares version 1, response kind
(`dialogue`, `grounded`, `handoff`) and origin (`application`, `model`) before
answer text. Missing metadata retains the legacy factual/source-warning policy.
Late or repeated classifications cannot downgrade an answer's source checks.
Dialogue and application handoffs do not display missing-citation warnings;
model factual answers and model handoffs still do. Application replies are
labelled as the BC service assistant, not generated AI answers, and are excluded
from model history. Completed user prompts and genuine model clarifications
remain in history.

Only `RUN_FINISHED` completes a normal answer; cancelled/partial messages remain
unfinished and are excluded from later model history. Legacy `GREETING` and
`JOURNEY_REQUIRED` errors before any answer text recover as clearly
application-owned dialogue, not connection failures or a mandatory five-service
gate. Citations can arrive after text and run completion while that stream
remains current. A new prompt can start immediately after completion; disposing
the old terminal stream does not send a server cancellation.

The conversation renders one truthful activity row before text instead of an
empty answer plus duplicate loading labels. Text arrives only from real stream
events: there is no simulated typewriter replay. Memoized message/Markdown
rendering avoids reparsing unchanged answers on progress, source and status
updates, and stable Markdown components preserve focused official links.
Source buttons leave pointer focus to the source dialog, preventing a mobile
tap from missing when blur scrolls the page away from the fixed composer.
Keyboard activation and focus return to the source button remain supported.

Optional `metadata` on a citation/reference carries versioned document
provenance. The browser validates the document/source identifiers, hashes,
rights-review identifier, legal status, calendar dates and historical flag.
Absent/null metadata keeps the legacy source presentation; malformed annotation
metadata is omitted without replacing its otherwise safe official reference.
Catalogue provenance is never silently transferred to an answer's citation.

Source details show document type and supplied legal dates/status. Effective
start (inclusive), effective end (exclusive), consolidation and repeal dates
remain distinct and render as ISO calendar dates, with no browser-timezone
conversion. The existing Checked/Publisher calendar dates use UTC formatting.
Hash and rights-review details are available in a small native disclosure,
explicitly scoped to the cited snapshot rather than whole-site coverage.
These fields do not bypass API evidence review or enable the feature-gated
programme index migration.

The same-origin proxy accepts only the established health/catalogue/journey/
location/capability routes and agent/cancel POST routes. It bounds bodies,
rejects arbitrary upstream URLs and redirects, preserves session cookies,
errors and incremental SSE, and propagates cancellation.

Unconfigured AI does not generate a fixture answer. It preserves the draft and
points to real guided plans or official services. Ordinary application greetings
are not presented as model-generated or source-grounded. Web IQ, backend changes,
Azure provisioning and resident transactions remain outside this UI increment.

## Validation

From the repository root:

```powershell
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm run build
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm run test:e2e
```

Browser tests create their own isolated local API/web runtime. Set
`PILOT_BASE_URL` only when intentionally testing an already-running local
instance. Tests never invoke a real model or submit an agency transaction.

The Dockerfile still uses the repository root as build context, produces a
non-root Next standalone runtime, and bundles local photos/fonts. Docker/Azure
execution and independent accessibility/public-brand certification remain
separate verification gates.
