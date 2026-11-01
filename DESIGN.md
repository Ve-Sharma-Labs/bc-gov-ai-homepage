# BC service assistant: reference-led interface

## Authority and scope

The user rejected the first form-and-card prototype and approved the
America.gov-referenced rebuild in the session plan. This describes the
implemented replacement, not a new stock component-library theme.

America.gov supplies the visual/interaction reference; its code, font files,
photographs and national marks are not used. The initial visual rebuild preserved
the backend contract. The subsequent approved chat increment adds a dedicated
conversation surface and versioned progress/results while preserving that visual
identity. Human brand/public-release approval is not claimed.

## Visual system

- **Display:** Libre Caslon Display regular, locally hosted under OFL.
- **Body and controls:** BC Sans with its original open-source font notices.
- **Photography:** five provenance-checked, free Unsplash BC photographs:
  Vancouver, Garibaldi Lake, Tofino, Peachland and Victoria's Parliament
  Buildings. Local WebP variants avoid runtime third-party image requests;
  Victoria has a dedicated portrait mobile crop. See `apps/web/ASSETS.md`
  and `/credits`.
- **Identity:** the user-supplied horizontal British Columbia logo replaces the
  placeholder mountain/sun symbol. Its surrounding white matte is removed for
  light mode, with internal white detail and original proportions retained.
  Dark mode keeps a white backing for the blue wordmark's legibility rather than
  recolouring it. The supplied ICO is the browser favicon; the stacked mark
  supplies a proportion-preserving touch icon.
- **Palette:** neutral light surfaces or near-black `#0b0d12`, provincial blue
  `#013366`, restrained BC gold and readable secondary text. The photos carry
  the visual warmth rather than artificial neon/glow effects.
- **Type roles:** large regular-serif greetings/editorial headings, readable
  sans-serif body/captions, and clearly distinct source/status metadata.
- **Geometry:** site measure up to 1392px; 880px photographic hero scene with
  a nominal 852px composer inside it; 96px desktop and 97px mobile idle composer
  heights; 48px/32px composer radii; generous editorial section separation.
- **Artwork:** paired 688:453 frames on wide screens, single-column scenes on
  mobile, rounded clipping and progressive squircle support.

## Composition

The homepage opens with a quiet pilot banner, wordmark and Menu, followed by
"Hello, British Columbia." and a compact composer integrated into a photograph.
One example invites an explicit guided-plan action. Previous/next and pause
controls do not submit or overwrite a person's draft.

An editorial explanation and two illustrated scenes precede the ordinary
service-plan list. The complete `/how-it-works` page contains four original
demonstrations: official sources, checklist preparation, service/location
matching and an official handoff. Captions sit outside the illustrated frames.
About remains the accessible place for detailed privacy and technical limits.

The footer provides a large BC closing signature and a clear return-to-task
action. Every route remains accessible through the same menu at phone, tablet
and desktop widths. The ordinary and compact chat footers carry
"Built with love in BC by @VeVarunSharma" with the requested profile link.

`/chat` is an operate surface: compact header, restrained right-aligned question,
centered readable answer and bottom-pinned composer. Valid homepage submissions
always open it, including unavailable/error cases. Genuine server-owned activity
gives way to progressively validated sections, not a replayed typing effect.
Exact-page sources open in a desktop panel or mobile sheet; canonical
preparation/location results stay alongside the conversation. The hero and large
marketing footer do not intrude on the active task.

## Component and motion foundations

shadcn CLI-generated Base UI primitives support the new controls; Motion handles
composer layout, menu transitions, photo crossfades and illustration movement.
The adapted Magic UI Blur Fade retains its MIT notice and adds a readable static
SSR/reduced-motion state. Existing tested React Aria checklist/reset/theme
controls remain; one control never nests competing primitive owners.

Scene playback pauses when offscreen, when the page is hidden, on explicit
pause and for reduced motion. Typing or focusing the input pauses example
rotation. Static explanatory text does not depend on animation.

## Shared state and composer

`AssistantProvider` lives inside the shared Next layout. Draft, selected journey,
checklist, conversation and run ownership stay in memory across internal
navigation. They are not serialized to local storage, session storage or URLs.
Reload and confirmed Start over clear them; Start over also stops active work.

`ComposerDock` owns one accessible textarea. It anchors to the hero/plan position
or docks above the viewport/keyboard without mounting a second interactive copy.
Sizing observes the actual input width so a zero-width initial render cannot
inflate the idle input. The single run announcer remains available across routes.
Focus is retained within the form when moving from the textarea to Send or Stop,
so a button activation cannot trigger blur-driven dock movement mid-interaction.

Theme state remains owned by `bc-service-theme` and `data-theme`, including
System mode and before-paint bootstrap. Tailwind dark variants read that same
state; no independent Magic UI theme controller is installed.

## Trust and accessibility

AI-led conversation keeps the same composer and visual identity. The initial
message is understood by the model; a relevant follow-up is asked in ordinary
chat. The main thread contains messages, actionable official links, and one
composer, not answer widgets or checklists. People can type "not sure" or "skip"
without finding a special control. **Details** is closed by default and holds
the full guide, progress, sharing settings, and editable **What I understand**.
It is a non-modal disclosure, never a prerequisite for continuing the chat.

Four sentence-length starter questions appear in empty chat and beside the
homepage's chat entry. They fill/focus the composer without sending. A
non-empty draft requires explicit replacement. Active chats expose these through
the compact **Examples** control; they do not compete with the latest answer.

A compact notice by the composer discloses Azure processing. Personal-context
sharing is an unchecked, optional control; its change applies to subsequent
model inputs and never claims to erase earlier processing. AI-decided turns
with application-reviewed wording are labeled separately from factual model
answers and deterministic no-model commands. In this mode, no exact-keyword
match or persona picker is a prerequisite to receiving help.

Task assistance brings the current practical action into the main conversation.
The full preparation guide in Details is expandable and persists through follow-ups;
routine turns do not replace it with another introduction. User-reported
readiness, step navigation, and checklist controls share the same task state.
Progress controls may update the current action without adding chat bubbles.

The sharing checkbox waits for the server's confirmation when turning on and
shows a short status, not an invented user/assistant exchange. It does not show
a fake model Stop state while saving. Task-level AI disclosure avoids repeated
per-message boilerplate. Guide/context summaries retain composer focus on
pointer activation so the fixed dock cannot move their target mid-click;
native keyboard behavior remains available.

The retained version-4 context-first increment preserves this visual world. Its warm,
goal-specific follow-up questions use inline choices and skip/general-guidance
actions, not an intake modal. **What I understand** is a compact, editable
summary with clear self-report and unknown/not-shared labels. A visible current
context panel counts as the latest conversation content, so a floating
new-content notification does not cover its controls. Pointer actions retain
composer focus until activation; keyboard focus remains native.

The fictional-context entry is labeled **Try fictional context** rather than
suggesting that anonymous users have no useful conversational context.
Conversation-led fictional-scenario suggestions still open the existing
granular consent sheet; they do not activate a persona automatically.

Guided plans are explicitly not AI-generated. Unconfigured AI keeps the question
and draft in chat and explains that guided plans/direct service links remain available. There are
no fake answers, simulated bookings, uploads, voice buttons or transaction claims.

Source timestamps, limitations and office exclusions remain attached to the
real catalogue. Illustrated cards are explanatory, not live agent progress,
current availability or receipts.

Keyboard navigation, Escape/focus return, semantic links, meaningful stream
announcements, reduced motion, source disclosure, no-JavaScript service links,
image failure and narrow reflow are preserved. Automated accessibility results
are evidence, not a certification or public-release approval.

## Verification

The production browser suite covers matched desktop/mobile viewports, both
themes, exact idle-composer tolerance, hydration, all five plans, source/office
rules, shared state across navigation, menu keyboard behavior, scene pause,
broken images and additional 320px/tablet reflow.

The frontend unit suite also covers the real AG-UI decoder, error/terminal state,
reset and cancelled/late events. The full application build remains Next
standalone. No cloud service or resident transaction is exercised for UI tests.
