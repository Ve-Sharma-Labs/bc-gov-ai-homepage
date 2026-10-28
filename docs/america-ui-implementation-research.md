# America.gov: implementation evidence for the BC UI rebuild

Research requested October 24, 2026, after the user rejected the first BC pilot
interface as insufficiently faithful to America.gov.

This document records observations from public HTML, CSS, JavaScript delivered to
the browser, and live DOM inspection. It is not access to the site's private
repository or backend. Hashed asset URLs and the implementation may change.
No America.gov fonts, artwork, or application code were copied into the BC app.

## Main finding

America.gov's appearance is not supplied by its chat transport. It is a bespoke
visual system built from editorial typography, photography, large illustrated
feature scenes, carefully shaped surfaces, and coordinated motion.

The first BC build reproduced service functionality and accessibility primitives,
but did not reproduce that visual system. Changing AG-UI to Vercel AI SDK, or
Next.js to Astro, would not by itself close the gap.

## Verified technologies and their actual roles

| Layer | Evidence | Role in the experience |
|---|---|---|
| Astro | `astro-island`, `/_astro/` assets, named component exports | Server-rendered page shell and selective interactive hydration |
| React | React renderer and component bundles; `HomePageIsland`, `SiteShell`, `HowItWorksArtwork` | Stateful composer, navigation, examples, and feature demonstrations |
| Base UI | Explicit `https://base-ui.com/production-error` and `Base UI` identifiers in shared primitives, with radio/checkbox composition in importing bundles | Unstyled interaction primitives beneath the custom presentation |
| Sonner | Toast implementation and `data-sonner-toaster` in the shared primitives bundle | Toast behavior; not the page composition or primary chat interface |
| Tailwind-generated utilities and custom CSS | Utility classes, CSS layers, custom `type-*`, `site-*`, radius, spacing, shadow and colour tokens | Bespoke design system, not a stock chat theme |
| Motion / Framer Motion family | `AnimatePresence`, `MotionConfigContext`, shared `layoutId`, `motionComponentSymbol`, `data-framer-portal-id`, spring and projection internals | Shared-layout movement, menu morphing, composer expansion, staged entrances |
| Native View Transitions | Explicit `@view-transition`, named navigation groups and `document.startViewTransition` | Navigation continuity and selected page/state handoffs |
| Custom card timelines | `card-timeline` and per-scene sequences | Choreographed product demonstrations with playback and reduced-motion control |
| OGL with `react-ogl` | Canvas bundle explicitly names `rendererPackageName: react-ogl`; orb imports Canvas/Plane/shaders | A specific WebGL privacy-orb effect, not the whole website |
| Raster/SVG/HTML artwork | Responsive WebP files, transparent decorative assets, phone frames, SVG details and positioned HTML | Most of the illustrated feature-card composition |
| AI SDK-compatible chat transport | Previously inspected SSE UI-message protocol | Transfers chat events; does not create the visual design |

No Three.js, Rive, or Lottie claim is made. A file named `Canvas` was traced
before identifying the renderer: the observed implementation is `react-ogl`.
The exact animation package version was not established.

## Component-library follow-up: shadcn/ui and Magic UI

The user requested this comparison after the reference trace, not as a substitute
for it. Public library documentation and the actual Magic UI component sources
were inspected on October 24, 2026. No dependencies were installed or UI components
replaced for this investigation.

### What the additional America.gov trace establishes

The shared `ui-primitives` bundle explicitly includes Base UI's production-error
formatter and Sonner's toast implementation. The shipped RadioGroup and Checkbox
bundles import the shared primitives and expose composition/state contracts such
as `render`, `onValueChange`, `onCheckedChange`, `data-checked` and `data-unchecked`.
This is stronger evidence than inferring a library from its file name or rounded
buttons.

It **does not establish that the site was generated with shadcn/ui**. Open-code
components can lose their original names during bundling, and `data-slot` is not
unique to shadcn. Likewise, no inspected evidence establishes Magic UI usage.
The single `data-react-aria-top-layer` marker occurs inside toast code; it is not
sufficient to attribute all application controls to React Aria.

The useful architectural similarity is:

**headless primitives -> application-owned styled components -> bespoke scenes
and choreography.**

That is exactly where shadcn can help us: ownership and composition, not automatic
visual parity.

### shadcn/ui: recommended foundation, not a site template

[shadcn's documentation](https://ui.shadcn.com/docs) describes an open-code
distribution system: component source becomes part of the application.
The [current CLI](https://ui.shadcn.com/docs/cli) supports `base`, `radix`, and
`aria` foundations. The inspected Button, Dialog and Popover documentation
resolved to the Base UI variants; do not assume older Radix-only descriptions
apply to every current variant.

For newly rebuilt primitives, **shadcn/ui with the Base UI option** is a good
candidate. It gives us editable Button, Dialog, Popover, Tooltip, Radio Group and
other control compositions while staying close to the headless approach found
in the reference. Keep these invisible as a library choice: their default
spacing, radius and typography are not our final design.

Use semantic theme tokens with separate component geometry. One global
`--radius` multiplier cannot express the reference's compact controls, 48px
desktop composer, and large squircle artwork frames adequately.

The current React Aria implementation is not the reason the prototype looks
wrong. Retain tested behavior until its replacement passes the same keyboard,
focus, dismissal, reset and cancellation tests. Do not introduce multiple
overlapping focus managers for one dialog or replace every control just to
claim a library migration.

The shadcn Carousel uses Embla, which is a suitable candidate for accessible
example navigation and snapping. The reference homepage contains an
Embla-style carousel engine, but its exact dependency/version was not proven
from names alone. Either way, the image staging and composer choreography remain
custom work.

### Motion: the primary animation layer

Use Motion directly for shared layout, menu morphing, composer expansion and the
scene timeline. Base UI documents its integration with Motion, including
controlled open state, portal lifetime and exit-animation completion. These
details matter when someone closes a menu halfway through its opening animation:
the surface must reverse smoothly and focus must return correctly.

`MotionConfig reducedMotion="user"` suppresses transform/layout motion, but does
not automatically stop CSS keyframes, timers, video playback or every
opacity/filter animation. Those require explicit scene-level behavior and a
readable static state. [Motion accessibility](https://motion.dev/docs/react-accessibility)

### Magic UI: inspect individual pieces, not the whole aesthetic

Magic UI describes itself as copyable landing-page/marketing components.
Its open-source repository is MIT licensed; preserve notices for adopted code.
That licence does not automatically cover Magic UI Pro, example media, fonts or
third-party logos.

| Candidate | Possible BC use | Source-level caveat and verdict |
|---|---|---|
| Blur Fade | A restrained in-view entrance for an illustration or caption | The inspected component starts hidden and animates opacity/blur/translation. It has no component-level reduced-motion or no-JavaScript final-state policy. Adapt selectively; do not hide the primary heading/input behind it. |
| Animated List | An explanatory checklist-building scene | It reveals items on a timer and reverses their display order. No built-in scene pause or visibility gate is present in the inspected component. Suitable only after adaptation for a labelled demonstration, not live answers or required task steps. |
| Animated Beam | An optional illustration of evidence flowing into an answer | Defaults include an infinite animated gradient. Bound it to the scene, use the BC palette, provide pause/static behavior, and avoid suggesting nonexistent live integrations. Not a required reference feature. |
| Orbiting Circles | An optional overview of approved source categories | A simple CSS orbit, not the reference's complete dimensional agency composition. Needs responsive geometry, visibility/pause/reduced-motion controls and permitted artwork. |
| iPhone / Safari frame | A reusable shell for a mobile/browser product demonstration | Source content, crop, aspect ratio and animation remain ours. Prefer generic device framing when appropriate; never use example media or imply a separate mobile app exists. |
| Bento Grid / Bento Card | At most a starting point for layout experiments | Defaults use three columns, 22rem automatic rows and icon/title/hover-CTA treatment. The reference has paired 688:453 visual scenes with captions outside them. Use a custom editorial grid instead of adopting this preset wholesale. |
| Animated Theme Toggler | Optional transition technique | Its implementation mutates `.dark` and can own a `theme` storage key. Our app owns `data-theme`, its own preference key and a System option. Do not add a competing theme controller. A star/polygon wipe is not required for reference fidelity. |

A concrete compatibility issue: the inspected Magic UI `BentoCard` calls
`Button asChild`, while the inspected shadcn Base UI Button uses a different
composition contract. The current Base UI Button documentation recommends a
plain anchor with `buttonVariants` for links so the element retains link
semantics. Copying that Magic UI example into a Base UI setup unchanged would
need correction; a shared component registry is not proof of API compatibility.

Do not use border beams, rainbow/shimmer buttons, neon cards, generic particles,
scrambling text, or stock SaaS bento arrangements merely because they are
available. They can be appropriate elsewhere but do not reproduce the observed
America.gov design.

### Recommended candidate stack

**Next.js + React + application-owned shadcn/Base UI primitives + semantic
Tailwind/CSS tokens + Motion**, with selected adapted Magic UI components only
where they reduce work on a specific reference-aligned scene.

Keep AG-UI/Foundry independent of that presentation layer. No Vercel hosting,
external AI gateway or Magic UI hosted service is needed.

The largest remaining work is still original imagery, the selected approved
display-serif treatment, hero composition, a continuous composer, and bespoke
How-it-works scenes. The libraries make that work easier; they do not supply
those design decisions.

## Typography: a major difference from the first BC build

The stylesheet declares **Rhymes Text** and **Rhymes Display**, alongside
**Helvetica Now Text** and **Helvetica Now Display**. The live inspected
headlines used Rhymes Text; text and feature captions used Helvetica Now roles.

Observed CSS:

- Major site/page headings use regular weight, line height `1`, and tight
  tracking, rather than heavy sans-serif display type.
- The site hero uses a 96px desktop base and scales toward 144px on wider screens.
- The mobile home hero has a separate `clamp(36px, 12vw, 48px)` rule.
- Page headings use a fluid 48-96px range before the wide-screen rule.
- Feature captions use an emphasized short lead followed by ordinary-weight
  explanatory text, not a large title inside every bordered card.
- Body, interface, and display roles are distinct, with font-specific fallback
  metrics to reduce layout movement during font loading.

The BC prototype uses BC Sans throughout and a bold, long two-line hero. That
is a fundamentally different typographic voice, not a small font-size mismatch.

**Constraint:** BC Sans is required by the current BC guidance reviewed for the
project. Rhymes and Helvetica Now files must not be downloaded from America.gov
and reused. A contrasting display face requires an appropriately licensed,
BC-approved choice or explicit brand-direction review. With BC Sans everywhere,
we can match composition and motion, but must not promise typographic identity.

## Layout and surface evidence

The reference stylesheet defines:

| Property | Observed value / behavior |
|---|---|
| Maximum site container | `87rem` (1392px at a 16px root size) |
| Site gutter | 16px |
| Major section gaps | 9rem and 18rem (144px / 288px), applied responsively |
| Main responsive breakpoints | 768px and 1145px, with additional wide-screen type scaling at 1440px |
| How-it-works artwork stage | Aspect ratio `688 / 453` |
| Feature layout | One column on small screens, two from the `mobile` breakpoint |
| Feature row gaps | 56px in the sampled smaller layout; larger desktop-specific spacing |
| Bento radius | Nominal 32px, 48px from 1145px |
| Enhanced corners | Progressive `corner-shape: superellipse(1.3)` support and a 1.194 corner scale |
| Dark page background | `#0b0d12` |
| Light page background | `#fff` |
| Theme startup | Resolved scheme painted before the main stylesheet arrives |

The nominal corner tokens are scaled inside the squircle treatment. For example,
a live 723px-wide panel measured a feature radius of approximately 38.208px,
not simply 32px. Numbers from this panel must not be presented as desktop
measurements.

The homepage contains layered photographic example scenes, with separate
backdrop and primary-image assets, responsive image candidates, descriptive
alternative text on meaningful images, and different fetch priorities. The
current BC prototype has no comparable imagery.

## The composer is a designed interaction, not a large textarea

The shared chat-input component includes:

- A compact initial text area inside a heavily rounded surface.
- Layout-driven expansion and resize observation.
- Inline attachment/voice/send controls when those capabilities exist.
- Context-dependent hero and docked appearances.
- Animated notices, suggestions and attachment states.
- Shared layout identity `home-ask` between hero and docked contexts.
- Mobile visual-viewport and focus handling.
- Reduced-motion alternatives.

A live 723px-wide homepage inspection measured the main form at approximately
655px wide by 96px high, with a 40px textarea and 32px nominal corner radius.
This is materially different from our always-expanded, labelled multiline form.

Matched-width follow-up measurements after font loading, with reduced motion
enabled, found **852 x 96px / 48px radius at 1440x900**, and
**348 x 97px / 32px radius at 390x844**. This corrects a generic capsule-element
measurement in the visual assessment: 9999px should not be attributed to the
actual hero form. Its observed nominal radius is 48px desktop / 32px mobile.

Do not use the reference's hidden alternate styles as the design baseline.
Some shipped branches, including an alternate `hotdog` treatment, are present
in source but are not proof of the ordinary current experience.

## Motion is coordinated across components

Concrete parameters observed in the served code:

| Interaction | Evidence |
|---|---|
| Composer subcomponent expansion | Spring with 0.16 bounce, approximately 420ms open / 280ms close |
| Suggestion/layout motion | Spring parameters including stiffness 420 and damping 38 |
| Menu morph | Shared layout identity; approximately 520ms open and 260ms close, with staggered content |
| Standard easing | Out-quint `cubic-bezier(.22,1,.36,1)` and drawer `cubic-bezier(.32,.72,0,1)` |
| Named navigation transitions | 300ms groups preserving logo/menu continuity |
| Reduced motion | Zero-duration alternatives and disabled movement paths |

These are observations, not instructions to paste minified code into our app.
Reproduce the behavior using maintained library APIs and original components.

The reference contains a real choreography layer: the menu surface grows from
its trigger, the input changes location and shape without losing identity,
and content enters at purposeful moments. A hover colour plus a fade-in is not
equivalent.

## What the How it works page actually contains

The page renders ten `HowItWorksArtwork` islands using **`client:visible`**:

1. Sources
2. Ad-free
3. Government
4. Account/privacy
5. Guidance
6. Documents
7. Languages
8. Voice
9. Personalized questions
10. Feedback

These are individually authored scenes, not ten instances of the same icon card.
Examples visible in delivered assets/code include moving cloud layers behind a
source panel, a dimensional government seal, a privacy orb, phone/UI frames,
an animated document drop and anonymization sequence, changing language/input
states, and microphone waveforms.

The card timeline code coordinates waits, labels, simultaneous transitions,
state changes, staggered text, and loops. It imports in-view and reduced-motion
hooks and has explicit play/pause control. The DOM exposes animation pause
buttons. Some GPU scenes have static raster fallbacks.

Much of the perceived polish comes from these **illustrated demonstrations**.
They are explanatory scenes, not evidence that every pictured transaction
executes live. The BC version must illustrate only implemented capabilities,
or label future concepts clearly.

## Implications for the Azure-native BC implementation

Keep:

- Azure/Foundry, the API, source policy and structured data contracts.
- React, the AG-UI transport, and accessible headless controls.
- BC identity and truthful capability/source disclosures.

Replace or substantially rework:

- The current homepage composition and heavy visual chrome.
- The large form-style composer.
- The static service-card grid as the dominant visual feature.
- The text-document treatment of `/about` as our How-it-works equivalent.
- The typography hierarchy and blue-on-blue surface system.
- The absence of photographic scenes, illustrated product demonstrations,
  and shared-layout interaction.

Recommended implementation tools are Next.js/React with Motion and a custom
token system. Astro remains technically suitable, but a migration is not
necessary for visual parity. Add OGL/react-ogl only for a justified matching
effect; ordinary SVG, CSS, images and Motion are sufficient for many scenes.

The next build must begin with measured reference frames and an asset/interaction
inventory. Passing an accessibility detector is a baseline, not a visual
similarity test. Exact BC-specific imagery, font approval, and a functioning
approved AI connection remain distinct inputs.

## Evidence links

- [Reference homepage](https://america.gov/)
- [Reference How it works](https://america.gov/how-it-works)
- [Delivered stylesheet](https://america.gov/_astro/base-html.CwS-h-Cz.css)
- [Homepage island](https://america.gov/_astro/home-page.MXnP0Bow.js)
- [How-it-works artwork](https://america.gov/_astro/how-it-works-artwork.DRaBdi02.js)
- [Card timeline controller](https://america.gov/_astro/card-timeline.Cj_A76oc.js)
- [Shared chat input](https://america.gov/_astro/chat-input.mxSvj7Y9.js)
- [Home/docked chrome](https://america.gov/_astro/home-chrome.CVoy302n.js)
- [Navigation component](https://america.gov/_astro/nav.Bq8-NAcL.js)
- [Motion runtime symbols](https://america.gov/_astro/react.DyZwBLgS.js)
- [Canvas / react-ogl renderer](https://america.gov/_astro/Canvas.yDS5SOjR.js)
- [Privacy orb](https://america.gov/_astro/privacy-orb-artwork.B8ZB9BQK.js)
- [Shared primitives with Base UI/Sonner evidence](https://america.gov/_astro/ui-primitives.DsZRvVe1.js)
- [Reference radio-group composition](https://america.gov/_astro/RadioGroup.B6xqtkCH.js)
- [Reference checkbox composition](https://america.gov/_astro/checkbox.qW-zJ6E5.js)
- [BC typography requirements](https://www2.gov.bc.ca/gov/content/digital/design-system/foundations/typography)
- [shadcn/ui open-code model](https://ui.shadcn.com/docs)
- [shadcn CLI foundation choices](https://ui.shadcn.com/docs/cli)
- [shadcn semantic theming](https://ui.shadcn.com/docs/theming)
- [shadcn Base UI Button and link semantics](https://ui.shadcn.com/docs/components/base/button)
- [shadcn input-group composition](https://ui.shadcn.com/docs/components/base/input-group)
- [shadcn Carousel / Embla](https://ui.shadcn.com/docs/components/base/carousel)
- [Base UI animation lifecycle](https://base-ui.com/react/handbook/animation)
- [Magic UI introduction](https://magicui.design/docs)
- [Magic UI component index](https://magicui.design/llms.txt)
- [Magic UI Bento source](https://github.com/magicuidesign/magicui/blob/main/apps/www/registry/magicui/bento-grid.tsx)
- [Magic UI Blur Fade source](https://github.com/magicuidesign/magicui/blob/main/apps/www/registry/magicui/blur-fade.tsx)
- [Magic UI Animated List source](https://github.com/magicuidesign/magicui/blob/main/apps/www/registry/magicui/animated-list.tsx)
- [Magic UI Animated Beam source](https://github.com/magicuidesign/magicui/blob/main/apps/www/registry/magicui/animated-beam.tsx)
- [Magic UI Orbiting Circles source](https://github.com/magicuidesign/magicui/blob/main/apps/www/registry/magicui/orbiting-circles.tsx)
- [Magic UI theme-toggler source](https://github.com/magicuidesign/magicui/blob/main/apps/www/registry/magicui/animated-theme-toggler.tsx)
- [Magic UI iPhone frame](https://magicui.design/docs/components/iphone)
- [Magic UI open-source licence](https://github.com/magicuidesign/magicui/blob/main/LICENSE.md)
