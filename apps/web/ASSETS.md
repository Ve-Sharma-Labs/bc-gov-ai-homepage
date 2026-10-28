# BC editorial assets

Curated on **24 October 2026 (Pacific time)** for the approved, local-preview
America.gov-reference UI rebuild. This is an asset/provenance handoff, not
public BC brand approval or a change to the service catalogue.

## User-supplied identity

The user supplied a horizontal British Columbia logo, a favicon ICO and a
stacked British Columbia mark for this project.

- `public/brand/bc-logo-horizontal-original.png`: original 500 x 300 PNG.
- `public/brand/bc-logo-horizontal.png`: 361 x 120 header asset. Only surplus
  white canvas was trimmed and 16px clear space added; artwork colours and
  proportions are unchanged. Retained as the original white-matte version.
- `public/brand/bc-logo-horizontal-transparent.png`: same dimensions, with the
  surrounding white matte removed and antialiased edges de-matted. Interior
  emblem whites are protected, including mountain and sun-ray details. Composing
  it back onto white differs from the supplied artwork by at most one RGB level.
  The header is transparent in light mode; a CSS white backing remains in dark
  mode so the original blue lettering stays readable without recolouring it.
- `public/favicon.ico`: supplied bytes unchanged, containing 16px, 32px and
  48px frames. Replaces the old placeholder `icon.svg`.
- `public/brand/bc-logo-stacked.jpg`: original stacked image retained. The
  attachment had a `.png` filename but its actual format is JPEG.
- `public/apple-touch-icon.png`: stacked mark fitted, without cropping or
  stretching, into a padded 180px square for touch-icon metadata.

The stacked mark is not stretched into a landscape hero banner; the existing
BC photographs remain. User-supplied brand assets are separate from the
Unsplash/font licences below and do not imply public-release approval.

## Integration contract

- `src/lib/hero-images.ts` exports `HeroImage` and `heroImages`. It contains
  public display metadata only, with no dependencies, JSX, journey mapping,
  API access, or generated claims.
- Each `src` and `mobileSrc` is a local public-root URL. `width` and `height`
  describe the **desktop file**, not an invented common aspect ratio.
- The first four photographs have 1600px-wide desktop and 800px-wide mobile
  WebP variants under `public/images/bc/`, retaining the full composition.
  Victoria has a 2400 x 1600 desktop variant and a dedicated 1200 x 1800
  portrait mobile crop, avoiding the previous shallow panorama's upscaling.
  Only cropping, resizing, JPEG-to-WebP conversion and metadata stripping
  were applied. One-pixel height differences are resize rounding.
- `position` is an art-directed CSS `object-position` recommendation for
  `object-fit: cover`, not a geographic coordinate. Keep it with the image
  when changing examples. Layout, rounded clipping, shadows, overlays and
  readable text surfaces belong to the UI, not the raster.
- Use responsive selection so mobile does not download the desktop image.
  Prioritize only the initially visible image; lazy-load later scenes.
  Do not eagerly preload all ten files.
- Pair photographs with real journey prompts in the consuming UI. A photograph
  is an editorial sense of place, not a picture of a service office, an
  applicant, a patient, a supported property, or an official endorsement.
- Credit the photographer and link the original Unsplash page where practical.
  Both links are in the data module even though this copyright license does
  not require attribution.

## Location and copyright evidence

Each original photo page was inspected, including its server-delivered
`window.__DEHYDRATED_DATA__` photo record. The quoted `location.name` below is
the **photo's location**, not the photographer's profile location or a search
keyword. For all five selected records, `premium` and `plus` were `false`,
`sponsorship` was `null`, and `public_domain` was `false`.

These are ordinary **Unsplash License** photographs, not Unsplash+ media:
[license](https://unsplash.com/license), with a retained copy at
`public/licenses/Unsplash-Photo-License.txt`. The license permits local download,
adaptation and website use, including commercial use. It does not permit an
unmodified-image resale or building a competing image library. No Unsplash API
integration, random-photo endpoint, or runtime third-party image request is used.

### Vancouver waterfront

- **ID:** `vancouver-waterfront`
- **Photographer:** [Aditya Chinchure](https://unsplash.com/@adityachinchure)
- **Original photo:** [A city skyline with boats](https://unsplash.com/photos/a-city-skyline-with-boats-f2HurUPuVyA)
- **Photo ID / CDN key:** `f2HurUPuVyA` /
  `photo-1659221483787-66b4e6c00c78`
- **Location evidence:** `location.name = "Vancouver, BC, Canada"`;
  the page description also explicitly says the photograph is in Vancouver,
  Canada. No more specific neighbourhood is asserted.
- **Published / original dimensions:** 30 July 2022 / 6000 × 4000.
- **Crop / use:** full composition; `50% 48%` keeps the skyline, moored boats
  and reflected water together. A community/waterfront example, including a
  darker editorial scene; not evidence of housing availability.
- **Alt:** “Boats and towers along Vancouver's waterfront reflected in the water
  at dusk.”
- **Caution:** privately owned buildings and boats are incidental to the wider
  scene. No property release has been independently obtained.

### Garibaldi Lake

- **ID:** `garibaldi-lake`
- **Photographer:** [Vlad Namashko](https://unsplash.com/@nvv)
- **Original photo:** [A lake surrounded by mountains and trees](https://unsplash.com/photos/a-lake-surrounded-by-mountains-and-trees-yXIfv6rQDuQ)
- **Photo ID / CDN key:** `yXIfv6rQDuQ` /
  `photo-1658730335794-c5edd544ccbb`
- **Location evidence:** `location.name = "Garibaldi Lake, British Columbia, Canada"`.
- **Published / original dimensions:** 25 July 2022 / 6000 × 4000.
- **Crop / use:** full composition; `50% 42%` favours the lake opening and
  snowy ridge over the foreground rocks. The vivid landscape offers a
  distinctly BC opening or example scene. It is not current trail,
  accessibility, weather or park-access information.
- **Alt:** “Turquoise Garibaldi Lake below forested slopes and snow-covered
  mountains in British Columbia.”
- **Caution:** detailed foliage has a larger byte budget than the other scenes.
  Do not preload this alongside every other example.

### Tofino coast

- **ID:** `tofino-coast`
- **Photographer:** [Frederic Leblanc](https://unsplash.com/@_thewhiteguy)
- **Original photo:** [Photography of shore line](https://unsplash.com/photos/photography-of-shore-line-xUd_HMODlDg)
- **Photo ID / CDN key:** `xUd_HMODlDg` /
  `photo-1501653687363-adb671c87db7`
- **Location evidence:** `location.name = "Tofino, Canada"`, with the photo
  location at approximately 49.1530, -125.9066 on Vancouver Island, BC.
  The photographer's short caption is “Feelings”; that caption alone is
  **not** the location evidence. No specific beach name is claimed.
- **Published / original dimensions:** 2 August 2017 / 5652 × 3768.
- **Crop / use:** full composition; `50% 56%` holds the shoreline and horizon.
  A quiet coastal alternative with natural negative space; do not assume the
  light sky supplies contrast for white text.
- **Alt:** “Ocean waves and a pink evening sky reflected on a beach in Tofino.”
- **Caution:** an intentionally soft, atmospheric photograph, not a
  lower-resolution placeholder.

### Okanagan Lake / Peachland

- **ID:** `okanagan-lake`
- **Photographer:** [Robbie Down](https://unsplash.com/@robbiedown)
- **Original photo:** [Green trees near body of water during daytime](https://unsplash.com/photos/green-trees-near-body-of-water-during-daytime-zppGPIF-aqo)
- **Photo ID / CDN key:** `zppGPIF-aqo` /
  `photo-1618776574386-1003feb9e86f`
- **Location evidence:** `location.name = "Peachland, BC, Canada"`; the photo's
  own tags additionally identify “okanagan” and “okanagan lake”. The BC
  verification rests on the location field, not those tags alone.
- **Published / original dimensions:** 18 April 2021 / 5982 × 3365.
- **Crop / use:** full, approximately 16:9 composition; `50% 46%` retains the
  open lake and hills while keeping some foreground pines. Interior-BC
  geographic variety without inventing a service-specific setting.
- **Alt:** “Okanagan Lake and surrounding hills seen past pine trees near
  Peachland.”
- **Caution:** a scenic overview, not evidence of available housing, an office,
  a recommended accessible route, or current environmental conditions.

### Victoria Parliament Buildings

- **ID:** `victoria-parliament`
- **Photographer:** [Brian Zhu](https://unsplash.com/@dogrod)
- **Original photo:** [The British Columbia Parliament Buildings are showcased](https://unsplash.com/photos/the-british-columbia-parliament-buildings-are-showcased-0IM71KfH3mo)
- **Photo ID / CDN key:** `0IM71KfH3mo` /
  `photo-1751496631531-1f3fb4ab0a28`
- **Location evidence:** `location.name = "Legislative Assembly of British Columbia, Belleville Street, Victoria, BC, Canada"`.
  The public photo page and its photo record were inspected in the browser;
  the caption also identifies the BC Parliament Buildings in Victoria.
- **Published / original dimensions:** 2 July 2025 / 7008 x 4672.
- **Crop / use:** daylight architecture replaces the blurry fifth-slide night
  panorama. The desktop variant retains the full composition. The mobile
  variant is a centre portrait crop retaining the main dome, flag and fountain;
  `50% 50%` keeps these landmarks centred in both responsive frames.
- **Alt:** "British Columbia's Parliament Buildings in Victoria, with a Canadian
  flag and fountain in daylight."
- **Caution:** distant visitors and building signage are incidental to the
  architectural scene. This is a sense of place, not a Service BC office
  photograph, a government endorsement or a model/property release.

## Files and production recipe

Paths below are relative to `public/images/bc/`. All files are opaque WebP.

| File | Dimensions | Bytes | Encoding quality |
|---|---:|---:|---:|
| `vancouver-waterfront-1600.webp` | 1600 × 1067 | 217,136 | 82 |
| `vancouver-waterfront-800.webp` | 800 × 534 | 55,852 | 78 |
| `garibaldi-lake-1600.webp` | 1600 × 1067 | 374,810 | 76 |
| `garibaldi-lake-800.webp` | 800 × 534 | 102,006 | 74 |
| `tofino-coast-1600.webp` | 1600 × 1067 | 30,908 | 82 |
| `tofino-coast-800.webp` | 800 × 534 | 7,942 | 78 |
| `okanagan-lake-1600.webp` | 1600 × 900 | 156,872 | 82 |
| `okanagan-lake-800.webp` | 800 × 450 | 43,644 | 78 |
| `victoria-parliament-2400.webp` | 2400 x 1600 | 654,414 | 86 |
| `victoria-parliament-1200.webp` | 1200 x 1800 | 356,588 | 86 |

The first four sources were downloaded directly from their CDN keys using:

```text
https://images.unsplash.com/{CDN key}?w=1600&fit=max&fm=jpg&q=90&cs=srgb
```

Each 1600px source was decoded with the repository's existing `sharp`, oriented,
and encoded to WebP at `effort: 6`. The mobile file was resized from that same
download buffer to 800px, **not** recompressed from the desktop WebP.
`withoutEnlargement: true` was used. The Garibaldi variants received the
explicitly lower qualities in the table for their unusually dense foliage.

Victoria was downloaded at 4000 x 2667 from:

```text
https://images.unsplash.com/photo-1751496631531-1f3fb4ab0a28?ixid=NHwxMjA3fDA&ixlib=rb-4.1.0&w=4000&fit=max&fm=jpg&q=92&cs=srgb
```

Both Victoria variants were generated independently from that JPEG buffer with
`sharp`, auto-orientation, `withoutEnlargement: true`, WebP quality 86 and
`effort: 6`. Desktop uses `resize({ width: 2400 })`; mobile uses
`resize({ width: 1200, height: 1800, fit: "cover", position: "centre" })`.
The old fifth-slide night-panorama files are retired.

No exposure, colour, scene content, watermark removal, generated objects or
AI editing was applied. Source download buffers were not kept as duplicate
production files.

### Source download SHA-256

These hashes identify the exact downloaded JPEG buffers used for conversion,
not a claim that an upstream original will never change.

```text
a159dba2f7a994e8791dbe634a7ba1df5cea28275a274fe8ba3bb4ef6d6071bc  vancouver-waterfront
8c4df340d0e193616b4c817a01a0aa13da9f806a1f66d5a87a1348cf974efa84  garibaldi-lake
53cff35451e2efd85295975e6f11f9eeb4cfef99d706950664d358b9f261ca6d  tofino-coast
5e7515cb0b4e6886aaf26f594690b4832ec00042d8764838cf86a0786df99b5f  okanagan-lake
bb3b927e9b1d1ef7ae85528fa38360ed315d4a9deadc68ba61738908bc8e629a  victoria-parliament
```

### Production SHA-256

```text
4e695db99aaa8ee8240b817bb4598bcbb8bf0f1ebf389e99f5d0772b169f9c50  vancouver-waterfront-1600.webp
203f0c368198ae009a914933527adff5add155a08a6bcfad019014fe391f0f7e  vancouver-waterfront-800.webp
bfee0a232042c74ac2f160c893ccb80f6d86e028b33b7da8c1aa468f8d82a7b3  garibaldi-lake-1600.webp
781ad1fee2a36f5edd71f90318ed5a719b04799e023128e8f0faebca5b89bbca  garibaldi-lake-800.webp
0fa0353ccffb94c445feee63cd6cc88f85e0c6caf75d3af0608d81c830ea75d5  tofino-coast-1600.webp
4c2341d1c77d8a9efb68ac3d2f2d0aaf0f04b0ff92ffb6bd6d1c13fafbbd3e03  tofino-coast-800.webp
618079dc7dd16d3400d547a165ad113fe68f69057877acfd705cd206e28e6e2c  okanagan-lake-1600.webp
851bc4c4e58c4fbabf3385449ed804858260018082e4dc26e2b2f788af1687b4  okanagan-lake-800.webp
f7dee2e8b7db8b9688ef0527c06de1c223f06814421155f5c49104708b8bfefc  victoria-parliament-2400.webp
aaf06c4861f8dfe3dd313ea1f38ddd1a1e347064e91b1ce1ee71deb2c0563f71  victoria-parliament-1200.webp
```

## Open-license display serif

**Libre Caslon Display Regular**, normal style, weight **400**, by
**Impallari Type / The Libre Caslon Display Authors**.

- **Public file / URL:** `public/fonts/libre-caslon-display.woff2` /
  `/fonts/libre-caslon-display.woff2`
- **Official WOFF2 source:** [Google Fonts CDN, v18, Latin subset](https://fonts.gstatic.com/s/librecaslondisplay/v18/TuGOUUFxWphYQ6YI6q9Xp61FQzxDRKmzr1lWfxk.woff2)
- **Source stylesheet:** [Google Fonts CSS2](https://fonts.googleapis.com/css2?family=Libre+Caslon+Display&display=swap).
  The modern-browser response identifies this WOFF2 as the Latin subset.
- **Original project:** [impallari/Libre-Caslon-Display](https://github.com/impallari/Libre-Caslon-Display).
  [Google Fonts metadata](https://github.com/google/fonts/blob/main/ofl/librecaslondisplay/METADATA.pb)
  identifies upstream source commit `3491f6a9cfde2bc15e736463b0bc7d93054d5da1`.
- **License:** SIL Open Font License 1.1. The complete, unchanged copyright and
  OFL notice is retained in `public/licenses/Libre-Caslon-Display-OFL.txt`,
  downloaded from [Google Fonts' OFL file](https://raw.githubusercontent.com/google/fonts/main/ofl/librecaslondisplay/OFL.txt).
- **Bytes / SHA-256:** 24,236 /
  `84267e937417f10dff37df818c5ef7f1e9f2e6a703e03c2dd286d3320af53269`.
- **Intended role:** large regular-weight editorial headings. Its high-contrast
  strokes and serif detail offer a defensible open-license interpretation of
  the pinned elegant display-serif direction. It is **not Rhymes**, and exact
  glyph shapes and line wraps will differ.
- **Integration:** declare as a local normal/400 display face with font-display
  swap and a suitable fallback. Keep BC Sans for body, UI, small labels and
  unsupported glyphs. Do not synthesize a bold or italic display face that was
  not supplied.
- **Coverage limitation:** this compact file is Google's Latin subset, not the
  full Latin Extended font or a replacement for BC Sans's language coverage.
  Text outside it must fall back to BC Sans; validate any Indigenous-language
  and multilingual headings with that fallback before release.

No America.gov font file, Rhymes licence, Helvetica Now file, government crest,
stock-library preview watermark, or generated image is included.

## Pinned reference / consuming-UI handoff

The source of visual authority remains
[`docs/america-ui-implementation-research.md`](../../docs/america-ui-implementation-research.md)
and the approved session plan. No alternate concept tournament was run.
Keep the following integration matrix when using these assets:

| State / surface | Fixed reference role | Asset / semantic implementation responsibility |
|---|---|---|
| Home, 1440 × 900, Light and Dark | A visible photographic opening, regular display heading, one compact approximately 852 × 96px composer | Stage the selected local photo with semantic text and controls above or beside it; do not bake UI into the photo |
| Home, 390 × 844, Light and Dark | Readable photograph and approximately 348 × 97px idle composer, allowed to grow | Select `mobileSrc` and retain its focal point; Victoria uses a dedicated high-resolution portrait crop |
| Example changes, focus, hidden page, reduced motion | One active example; changing the image must not submit a question or overwrite a draft | Parent owns previous/next/pause and visibility/motion policy; these files are static |
| How it works: evidence | Source evidence becomes a source card, with a caption outside the artwork | Render real source title, publisher, date/limitation and link as HTML; SVG/CSS owns connecting marks |
| How it works: preparation | Preparation checklist assembles, not a transaction receipt | Render actual task labels and review-only checkbox state as HTML; parent owns the bounded timeline |
| How it works: office matching | Exclusions visibly narrow office choices | Use real catalogue office/exclusion data and semantic list/filter states, not invented map data |
| How it works: official handoff | Explain an external official destination without implying submission | Render the destination, preparation copy and native external link in an original frame |

The four explanatory scenes use the reference's paired 688:453 artwork stages
on wide screens, single-column reflow on narrow screens, and static readable
reduced-motion states. They are **semantic UI work**, not missing raster assets.
The parent implements all scene code, crop-in-layout tests, typography wraps,
contrast, keyboard behavior, and final visual acceptance.

## Validation and remaining limitations

- All ten WebP files were fully decoded to raw pixels with `sharp`, with
  warnings treated as failures; dimensions, format, byte counts and hashes were
  checked. They are real editorial photographs, not thumbnails: 1600px / 800px
  variants for the first four, and 2400px / 1200px variants for Victoria.
  All ten also decoded successfully in the installed Edge browser. Combined
  photo storage is 2,000,172 bytes; responsive loading selects individual files,
  not that entire total.
- The selected scenes were visually inspected for composition, visible people,
  baked UI, borders, letterboxing, prominent advertising and watermarks.
  There are no identifiable people in sensitive contexts, and no prominent
  readable brand or watermark is used as the subject. Distant boats, buildings
  and small urban signage are **not** a third-party-rights clearance.
- All ten data-module URLs were resolved to their actual local files and their
  dimensions verified; all ten production hashes matched this report. The
  standalone TypeScript module passed strict `tsc --noEmit` validation.
  Final integration must not replace the files with Unsplash thumbnail or
  Open Graph URLs (the latter add a logo overlay).
- The font passed WOFF2 signature/length checks and an actual browser
  `FontFace.load()` test; the browser reported it loaded and available and
  successfully measured “British Columbia” with it.
  Its authentic OFL notice is bundled separately rather than replaced with a
  generic “free font” claim.
- Location evidence is creator/platform-provided public metadata, not
  independently surveyed geography. These five southern/coastal/interior
  scenes are not comprehensive representation of all BC regions or communities.
- **Copyright is separate from releases and brand approval.** Unsplash does
  not guarantee all model/property permissions; see
  [Releases and Trademarks](https://help.unsplash.com/en/articles/2612329-releases-and-trademarks).
  No releases were independently obtained, and no photographer was contacted.
  Reassess any commercial endorsement, sensitive juxtaposition, private
  property focus or new crop before public use.
- The display-serif choice and public BC identity remain a release gate.
  This local candidate does not authorize deployment or assert government
  endorsement. Legal/public-brand review and the user's actual visual
  acceptance remain separate from asset readiness.
