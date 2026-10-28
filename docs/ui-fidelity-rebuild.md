# BC UI fidelity rebuild: America.gov reference

**Status:** The UI rebuild is implemented locally. The latest user instruction
requested autonomous completion; technical visual checkpoints were performed
without claiming human/public-brand sign-off. See `DESIGN.md` for the finished
system and `apps/web/IMPLEMENTATION.md` for the actual integration.
**Reference:** America.gov homepage and How it works, inspected October 24, 2026.
**Decision:** The first BC interface is not an acceptable visual-fidelity baseline.
Keep the working service foundations, but replace the visual composition and
interaction system rather than incrementally retheming its cards.

**Method:** Independent design assessment A
`f1015b03-0c4c-4278-9e29-4800414ff1ae`, independent implementation/browser
assessment B `290acf58-a91b-4a4a-8488-b0109b0ef33b`, and direct inspection of
America.gov's delivered HTML, CSS and client modules. The assessments did not
share findings with one another.

Native canvas access failed inside the assessment workers, so they used fresh
isolated Edge contexts. The parent inspected the reference in native browser
canvases as well. No user-visible detector overlay is available. The local
preview remains running; no UI source was changed by this research pass.

## 1. What actually creates the reference's polish

The reference is **Astro + React + a bespoke design and motion system**.
Its chat transport is not a visual toolkit.

| System | Verified implementation | Implication |
|---|---|---|
| Editorial typography | Rhymes serif family and Helvetica Now Text/Display | Large regular-weight display type, distinct text/UI roles, deliberate line breaks |
| Photo-led homepage | Layered responsive photographs tied to example questions | The entry point demonstrates a human situation rather than a directory of services |
| Adaptive composer | Rounded form, approximately one-line initial input, shared layout identity | The input feels like a continuous object through focus, expansion and docking |
| Motion | Motion/Framer Motion family, shared-layout animation, custom card timelines and native View Transitions | Navigation and state changes are choreographed rather than merely faded |
| How-it-works scenes | Ten separately authored, visible-hydrated artwork islands | Each concept has a visual demonstration, not a repeated icon-card template |
| Dimensional artwork | Images, SVG, positioned HTML, and OGL/react-ogl for a specific orb effect | Most scenes do not require a 3D engine; specialized effects have static fallbacks |

The detailed source evidence, module URLs, typography declarations and animation
parameters are in [America.gov implementation research](america-ui-implementation-research.md).

## 2. The measurable differences

| Element | Reference | Current BC pilot |
|---|---|---|
| Desktop hero headline | 96px, regular-weight serif | 68px, bold BC Sans |
| Mobile headline at 390px | Approximately 46.8px | 32px |
| Desktop idle composer | Approximately 852 x 96px, 48px nominal radius | 780 x 220px, 14px radius |
| Mobile idle composer | Approximately 348 x 97px | 358 x 212px |
| Entry visuals | Photography behind/around the example composer | No photographs or illustrative scenes |
| Navigation | Wordmark plus one persistent Menu pill | Wordmark, two links and exposed theme controls; About disappears from the header at narrower widths |
| How it works | Large editorial introduction and paired animated/illustrated scenes | A long text-only About article |
| Closing experience | Repeated input/CTA and a designed brand signature | Utility footer |
| Small-text treatment | Distinct text roles within the reference system | Several BC privacy/status/identity labels measure about 9.4-11.2px |

The reference composer dimensions above were measured directly at 1440x900 and
390x844 after font loading with reduced motion enabled. BC control measurements
come from the independent 1440px-wide desktop and 390x844 mobile evidence.
Whole-page geometry comparisons must use identical viewport sizes.

The approximately **2.2-times-taller idle input** is an immediate reason our
entry point reads as a government form rather than the reference's conversational
capsule. Width changes alone will not fix that.

Do not adopt aggregate image, DOM-node, shadow or transition counts as quality
targets. Those counts include duplicated/decorative images and elements that
merely have transition styles. Likewise, different photos in independent page
loads do not prove that the breakpoint selects a different photograph.

## 3. Design critique

### Specificity and overall impression

The BC identity tokens are coherent, but the composition is interchangeable with
an enterprise service portal. America.gov is authored at the composition,
typography, image, interaction and storytelling levels. We matched functionality
and applied provincial colours; we did not match that reference.

Whitespace is not the problem by itself: the reference uses substantial,
intentional whitespace. The problem is the absence of visual material and
hierarchy that make the space feel composed.

### Usability score, not a fidelity score

| # | Heuristic | Score | Finding |
|---|---|---|---|
| 1 | Visibility of system status | 3/4 | Useful state feedback, but technical status has too much prominence |
| 2 | Match with the real world | 2/4 | Resident-facing copy exposes Azure/Foundry/Web IQ terminology |
| 3 | User control and freedom | 3/4 | Reset confirmation and cancellation are worth preserving |
| 4 | Consistency and standards | 3/4 | Coherent tokens; uneven navigation behavior across widths |
| 5 | Error prevention | 3/4 | Input limits and honest transaction boundaries are sound |
| 6 | Recognition rather than recall | 3/4 | Guided options and official links are discoverable |
| 7 | Flexibility and efficiency | 2/4 | The unconfigured primary AI path limits the intended interaction |
| 8 | Aesthetic and minimalist design | 3/4 | Legible and relatively uncluttered; this does not establish sophistication |
| 9 | Error recognition and recovery | 3/4 | Draft preservation and recovery wording are useful |
| 10 | Help and documentation | 2/4 | Text-heavy explanation; mobile header loses the About route |
| **Total** | **General usability** | **27/40** | **Acceptable on this scale; reference fidelity fails** |

The earlier mistake was treating functional/technical success as evidence of
visual success. This score must not become another substitute for reference
comparison and user acceptance.

### What is working

- Consistent local BC Sans assets and theme behavior.
- Real source-backed plans, visible source provenance and honest handoffs.
- Keyboard controls, draft preservation, reset and cancellation foundations.

### Priority issues

**[P1] Replace the homepage composition.** The current heading/form/service-grid
sequence has no equivalent of the reference's photographic example scene.
Build a photo-led hero with one active example and the composer integrated into
that scene. Keep a conventional service-browse path, but not as the visual
centre of the homepage. Target: `assistant-app.tsx`, `journeys.tsx`, `globals.css`.
Work type: shape and rebuild, not colour polish.

**[P1] Replace the composer interaction pattern.** A permanent field label,
three-row input, resize handle and rectangular button produce a form-like
experience. Use an accessible but visually compact label, automatic input
growth, a circular send control, and consistent shared-layout identity across
hero, focused and docked states. Target: `composer.tsx`, `assistant-app.tsx`.
Work type: component rebuild and animation.

**[P1] Rework typography and trust copy.** A large regular-weight serif is a
major part of the reference. Resolve the BC-approved display-face decision;
keep BC Sans for readable body/UI text. Increase undersized interface copy.
Consolidate repetitive caveats into concise, contextual disclosures without
hiding important source or capability limits. Target: layout/fonts, theme
tokens, composer and About copy. Work type: typography and content design.

**[P1] Build a real How-it-works experience.** The existing About article is not
an equivalent. Create an editorial opening followed by paired, individually
authored concept scenes: official sources, preparation plans, service-location
matching, and controlled handoffs. Each gets a short caption and meaningful
motion. Privacy/legal detail remains available separately. Target: a dedicated
How-it-works page, shared scene controller, original assets. Work type: page
rebuild and demonstration components.

**[P1] Rebuild navigation and the closing moment.** A persistent menu must retain
all routes at every breakpoint; do not merely hide links on tablets/phones.
Move secondary controls into the menu and create a consistent footer/return-to-
question pattern across pages. Target: `chrome.tsx`, navigation, dock and footer.
Work type: navigation/layout/animation.

### Cognitive load and emotional journey

The current homepage is relatively easy to understand, but it offers five
undifferentiated options once the user reaches the grid. About mixes
explanation, implementation detail and privacy material at similar visual
weight. The experience opens and closes at the same emotional level.

The reference uses a human opening, visual explanations, and a deliberate
closing signature. Reproduce that sequence without borrowing unsupported
product claims or reducing appropriate government safeguards.

### Persona risks

- A reference-familiar visitor immediately reads the large input as a form,
  rather than the product they expected.
- A resident seeking reassurance encounters infrastructure terminology and
  repeated caveats instead of a clear illustrated explanation.
- A mobile visitor loses the About link from the header, even though help is
  still reachable through less-obvious footer/inline routes.

### Detector evidence and limits

The static CLI detector returned **zero findings**. The runtime browser detector
reported **122 repeated rule observations**, not 122 distinct defects, across
six page/state samples. Most concerned small text and estimated line lengths.
Some findings were context-dependent or false positives: the intentional gold
masthead border and a single approved font family are not inherently defects.

The runtime evidence supports a text-size review. It does not measure design
fidelity. Chrome rendered-font inspection also confirmed actual BC Sans Regular
and Bold, rather than a broken-font fallback.

## 4. Rebuild architecture

Keep Next.js, React, the existing APIs, AG-UI, Foundry integration and the source
policy. None prevents the reference look.

Create reusable presentation components:

- `ReferenceHero`: restrained header, short greeting and photographic examples.
- `AdaptiveComposer`: shared hero/focus/dock identity, automatic sizing, clear
  pending/streaming/error states and accessible labels.
- `ExampleSceneCarousel`: real BC context, deliberate crops, a pause control,
  keyboard navigation and an equivalent static reduced-motion state.
- `MorphingMenu`: one cross-breakpoint entry point, theme and service/help routes.
- `FeatureScene` and `SceneTimeline`: source, checklist, location and handoff
  demonstrations with shared playback, visibility and reduced-motion behavior.
- `EditorialSection` and `SiteSignature`: readable narrative and consistent
  ending without a repeated grid of utility cards.

Use Motion for layout projection, controlled entrances and timeline sequences.
Use CSS/SVG/raster layers for most artwork. Add OGL/react-ogl only if a selected
scene genuinely needs a shader effect. Do not add several animation engines
or migrate frameworks as a substitute for design work.

The existing legal/technical About content should remain reachable, but should
not be asked to serve as the entire product explanation page.

### Library decision after the reference-first investigation

Recommended candidate foundation: **shadcn/ui with Base UI**, with **Motion**
for choreography and **selectively adapted Magic UI** pieces for illustrated
scenes. This is a researched recommendation, not an installed dependency or a
new visual style selected in place of the America.gov reference.

The additional reference trace confirms Base UI and Sonner in America.gov's
shared bundle. It does not prove shadcn/ui or Magic UI generated the website.
Matching the same primitive family makes composition easier; it does not make
default shadcn controls visually equivalent to the reference.

| Rebuild surface | Reuse | Work that remains custom |
|---|---|---|
| Header/menu | Base UI or shadcn Dialog/Popover primitives | Trigger-to-panel morph, navigation layout, exit timing and focus restoration |
| Composer | Accessible input/button primitives; input-group patterns where useful | 96-97px idle geometry, input growth, shared hero/dock identity, mobile viewport handling |
| Example scene | Embla/shadcn Carousel if its snapping behavior fits | Photography, crops, backdrop treatment, pause behavior and coordinated example text |
| How-it-works | Selected Blur Fade, list or device-frame techniques | Paired visual-scene grid, original BC artwork, captions and timelines |
| Sources and task controls | Existing verified React Aria or deliberately replaced primitives | Reference-aligned styling without regressing source truth, keyboard use or task state |
| Theme | Existing single preference owner and semantic tokens | Both full visual themes, System mode and any restrained transition |

Use one owner for focus/open state per overlay and one owner for the theme.
Do not nest competing headless components or install Base UI, Radix and Aria
versions of every control. The current React Aria foundation is not a visual
defect by itself.

Do not adopt Magic UI's stock BentoCard as the How-it-works layout: its
three-column/22rem/icon/hover-CTA defaults differ from the measured reference.
The inspected version also uses Radix-style `Button asChild`; it is not
drop-in compatible with shadcn's Base UI Button. Adapt composition and retain
plain-anchor semantics for links.

Require all adopted animation components to support a readable static initial
render, reduced motion, offscreen/hidden-page pause, explicit pause where needed,
and cancellation. Magic UI's inspected Blur Fade, list, beam and orbit sources
do not supply the complete scene policy themselves. Never animate fabricated
live agent activity, progress, sources, or transactions.

Start with one short reference-aligned slice: compact hero composer, one
photographic example, the morphing menu, and one original source/checklist
demonstration. Approve that slice side by side before adding the remaining
scenes. Do not import a whole template or effect catalogue.

The detailed candidate matrix, code-level caveats, links and licences are in
[the component-library follow-up](america-ui-implementation-research.md#component-library-follow-up-shadcnui-and-magic-ui).

## 5. Asset and typography decisions

The required asset work is part of the implementation, not optional decoration:

- A small approved BC photographic set representing the actual five journeys.
- Original visual scenes for source evidence, checklist preparation, office
  matching and agency handoff.
- Appropriate crops/posters for light, dark and mobile presentations.
- A BC-approved, licensed display-font decision.

Do not copy America.gov's font files, seal artwork, photographs, code or national
identity. Do not substitute fake licence documents, fake approvals, or fictional
transaction receipts. Explanatory demonstrations must illustrate capabilities we
have, or be clearly labelled as future concepts.

**Typography direction selected by the user:** plan for an approved display
serif for headlines, with BC Sans retained for body and interface text. The
specific face, brand approval and licensing remain implementation gates.
This selects the design direction; it does not authorize copying America.gov's
font files or establish that a particular font licence has been acquired.

## 6. Reference-conformance workflow and acceptance

1. Capture paired reference/BC frames at **1440x900** and **390x844**, in light
   and dark modes. Fix the named example and animation state for comparisons.
2. Implement only the homepage and How-it-works compositions first. Obtain
   visual acceptance before expanding to all service states.
3. Match the empty composer to approximately **96px desktop / 97px mobile**
   with a proposed +/-8px tolerance; expand only when content or controls require it.
4. Review header/hero/composer relationships, image crop, type scale, line breaks,
   corner treatment, section rhythm, and footer as a whole. Brand/content
   differences are expected; arbitrary spacing differences are not.
5. Validate menu opening/closing, example selection, focus/expansion, docking,
   cancellation, source opening and return-to-question with motion recordings,
   not just still screenshots. Reference timings are in the implementation report.
6. Pause scenes offscreen and on explicit user request; respect reduced motion
   and provide static/unsupported-GPU fallbacks.
7. Preserve keyboard, screen-reader, zoom, contrast, draft and source controls.
   Body/UI text should not fall into the current 9-11px microcopy pattern.
8. Connect the final UI to the approved Foundry/Search path before claiming a
   complete America.gov-like chat experience. An unavailable primary input is
   a functional fidelity gap, not something to disguise with animation.
9. Require explicit visual acceptance of the paired frames and interaction
   recordings. A passing detector, build, or generic usability score is not
   permission to call the result reference-faithful.

No font licensing, source permission, Azure deployment or live-AI approval is
implied by this rebuild specification.

## References

- [America.gov](https://america.gov/)
- [How it works](https://america.gov/how-it-works)
- [Detailed delivered-code evidence](america-ui-implementation-research.md)
- [BC typography policy](https://www2.gov.bc.ca/gov/content/digital/design-system/foundations/typography)
