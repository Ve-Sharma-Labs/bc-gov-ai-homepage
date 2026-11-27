import { copyFileSync, cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

export const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(webRoot, "..", "..");

const pick = (value, keys) => Object.fromEntries(keys.map((key) => [key, value[key]]));
const presentationKeys = [
  "title", "siteUrl", "socialAlt", "banner", "homeLabel", "greeting", "serviceIntro",
  "chatLabel", "conversationLabel", "assistantName", "scopeDescription", "clearScopeLabel",
  "helpLabel", "helpInline", "credit", "creditsTitle", "creditsIntro", "creditsNotice",
  "aboutLead", "aboutIdentity", "howIntro", "sourceScene", "sourceNotice", "pilotNotice",
  "emptyJourneys", "flag", "flagAlt", "starters", "identityLabel", "identityReason",
  "licenceNotice", "officeEmpty", "locationIntro", "locationEmpty", "serviceLabels",
  "handoffIllustration", "regionValue", "socialBackground", "socialAccent", "assets", "tokens",
];

export function publicProjection(pack) {
  return {
    ...pick(pack, ["schemaVersion", "id", "name", "shortName", "inlineName", "siteTitle", "description", "locale", "timeZone"]),
    officialDomains: [...pack.officialDomains],
    helpChannel: pick(pack.helpChannel, ["name", "url"]),
    brand: pick(pack.brand, ["logo", "logoWidth", "logoHeight", "fontFamily", "assetStatus"]),
    features: pick(pack.features, ["guidedJourneys", "syntheticContext"]),
    presentation: {
      ...pick(pack.presentation, presentationKeys),
      stream: pick(pack.presentation.stream, ["hello", "clarify", "checking", "searching", "unavailable"]),
      services: pack.presentation.services.map((service) => pick(service, ["name", "publisher", "description", "url"])),
    },
  };
}

export function loadPresentation(id = process.env.JURISDICTION ?? "bc", packsRoot = path.join(repositoryRoot, "jurisdictions")) {
  if (!/^[a-z][a-z0-9-]{1,31}$/u.test(id)) throw new Error("Invalid JURISDICTION.");
  const pack = JSON.parse(readFileSync(path.join(packsRoot, id, "jurisdiction.json"), "utf8"));
  if (pack.id !== id || pack.schemaVersion !== 1 || !pack.presentation
    || typeof pack.features?.guidedJourneys !== "boolean"
    || typeof pack.features?.syntheticContext !== "boolean"
    || !Array.isArray(pack.officialDomains) || !pack.brand?.logo) {
    throw new Error("Invalid jurisdiction presentation pack.");
  }
  return pack;
}

export function assertRuntimeJurisdiction(selected, requested = process.env.JURISDICTION ?? "bc") {
  if (selected !== requested) {
    throw new Error(`Web build jurisdiction ${selected} does not match runtime JURISDICTION ${requested}. Rebuild the selected pack.`);
  }
}

export function prepareJurisdiction({ production = process.env.NODE_ENV === "production" } = {}) {
  const packsRoot = process.env.JURISDICTION_PACKS_ROOT || path.join(repositoryRoot, "jurisdictions");
  const stamp = path.join(webRoot, process.env.NEXT_DIST_DIR || ".next", "jurisdiction.json");
  const starting = process.argv.includes("start") || process.env.JURISDICTION_RUNTIME === "true";
  if (starting) {
    if (!existsSync(stamp)) throw new Error("The web build has no jurisdiction stamp. Run a selected-pack build first.");
    const selected = JSON.parse(readFileSync(stamp, "utf8")).id;
    assertRuntimeJurisdiction(selected);
    return selected;
  }
  const pack = loadPresentation(process.env.JURISDICTION ?? "bc", packsRoot);
  const generated = path.join(webRoot, "src", "generated");
  const assets = path.join(webRoot, "public");
  const serialized = JSON.stringify(publicProjection(pack));
  const brandRoot = path.join(webRoot, "brand-assets", pack.id);
  const identityRoot = path.join(packsRoot, pack.id, "brand");
  const heroSource = readFileSync(path.join(brandRoot, "hero-images.ts"), "utf8");
  const themeSource = readFileSync(path.join(webRoot, "brand-assets", "bc", "theme.css"), "utf8");
  const bcPublic = path.join(webRoot, "brand-assets", "bc", "public");
  const brandPublic = path.join(brandRoot, "public");
  const licenceNames = ["AG-UI.txt", "Lucide.txt", "Magic-UI-MIT.txt", "React-Aria.txt", "shadcn-ui-MIT.txt"];
  if (pack.id !== "bc" && pack.presentation.assets.some((name) => !/^[a-z0-9-]+\.(?:png|json|svg)$/u.test(name))) {
    throw new Error("Invalid presentation asset path.");
  }
  const heroPaths = [...heroSource.matchAll(/^\s*(?:src|mobileSrc):\s*"\/([^"]+)",?\s*$/gmu)]
    .map((match) => path.join(brandPublic, match[1]));
  const requiredSources = [
    ...heroPaths,
    ...licenceNames.map((name) => path.join(bcPublic, "licenses", name)),
    ...(pack.id === "bc"
      ? [path.join(bcPublic, "fonts", "libre-caslon-display.woff2"),
        path.join(bcPublic, pack.brand.logo.slice(1)),
        path.join(bcPublic, "favicon.ico"),
        path.join(bcPublic, "apple-touch-icon.png")]
      : [path.join(brandPublic, "licenses", "Unsplash-Photo-License.txt"),
        path.join(identityRoot, "pilot-icon.svg"),
        ...(pack.id === "sk" ? [path.join(brandPublic, "favicon-saskatchewan.ico")] : []),
        ...pack.presentation.assets.map((name) => path.join(identityRoot, name))]),
  ];
  const missing = requiredSources.filter((source) => !existsSync(source));
  if (missing.length) {
    throw new Error(`Missing jurisdiction source assets: ${missing.map((source) => path.relative(webRoot, source)).join(", ")}. Restore the selected brand assets before preparing the web build.`);
  }
  const assetHash = pack.id === "sk" ? createHash("sha256")
    .update(readFileSync(path.join(brandPublic, "favicon-saskatchewan.ico"))).digest("hex") : "";
  const fingerprint = `${pack.id}:${createHash("sha256").update(serialized + heroSource + themeSource
    + readFileSync(fileURLToPath(import.meta.url), "utf8") + assetHash).digest("hex")}`;
  const manifestOutput = path.join(generated, "jurisdiction.json");
  if (existsSync(manifestOutput) && existsSync(path.join(assets, ".jurisdiction"))
    && (pack.id !== "sk" || existsSync(path.join(assets, "favicon-saskatchewan.ico")))
    && readFileSync(manifestOutput, "utf8") === serialized
    && readFileSync(path.join(assets, ".jurisdiction"), "utf8") === fingerprint) return pack.id;
  mkdirSync(generated, { recursive: true });
  writeFileSync(manifestOutput, serialized);
  writeFileSync(path.join(generated, "hero-images.ts"), heroSource);
  rmSync(assets, { recursive: true, force: true });
  mkdirSync(assets, { recursive: true });
  if (pack.id === "bc") {
    cpSync(path.join(webRoot, "brand-assets", "bc", "public"), assets, { recursive: true });
    writeFileSync(path.join(generated, "fonts.ts"), `import localFont from "next/font/local";
const sans = localFont({ src: [
{path:"../../node_modules/@bcgov/bc-sans/fonts/BCSans-Regular.woff2",weight:"400",style:"normal"},
{path:"../../node_modules/@bcgov/bc-sans/fonts/BCSans-Bold.woff2",weight:"700",style:"normal"},
{path:"../../node_modules/@bcgov/bc-sans/fonts/BCSans-Italic.woff2",weight:"400",style:"italic"}],
variable:"--font-body",display:"swap",fallback:["Arial","sans-serif"]});
const serif = localFont({src:"../../public/fonts/libre-caslon-display.woff2",variable:"--font-editorial",display:"swap",weight:"400",fallback:["Georgia","serif"]});
export const fontClasses = sans.variable + " " + serif.variable;\n`);
    writeFileSync(path.join(generated, "brand.css"), '@import "@bcgov/design-tokens/css-prefixed/variables.css";\n' + themeSource);
  } else {
    mkdirSync(path.join(assets, "brand"), { recursive: true });
    mkdirSync(path.join(assets, "licenses"), { recursive: true });
    for (const name of licenceNames) {
      copyFileSync(path.join(bcPublic, "licenses", name), path.join(assets, "licenses", name));
    }
    for (const name of pack.presentation.assets) {
      copyFileSync(path.join(identityRoot, name), path.join(assets, "brand", name));
    }
    copyFileSync(path.join(identityRoot, "pilot-icon.svg"), path.join(assets, "pilot-icon.svg"));
    cpSync(path.join(brandRoot, "public"), assets, { recursive: true });
    writeFileSync(path.join(generated, "fonts.ts"), 'export const fontClasses = "";\n');
    const tokens = pack.presentation.tokens;
    if (!tokens || Object.values(tokens).some((pair) => !Array.isArray(pair)
      || pair.length !== 2 || pair.some((color) => !/^#[0-9a-f]{6}$/iu.test(color)))) {
      throw new Error("Invalid pilot colour tokens.");
    }
    const variables = Object.entries(tokens).map(([name, pair]) => {
      if (!/^[a-z-]+$/u.test(name)) throw new Error("Invalid token name.");
      return `--${name}:light-dark(${pair[0]},${pair[1]});`;
    }).join("\n");
    writeFileSync(path.join(generated, "brand.css"), `:root{${variables}
--font-body:system-ui,-apple-system,"Segoe UI",Arial,sans-serif;
--font-editorial:system-ui,-apple-system,"Segoe UI",Arial,sans-serif;}
html[data-jurisdiction="${pack.id}"] h1,html[data-jurisdiction="${pack.id}"] h2{font-weight:700;letter-spacing:-.025em;line-height:1.2;}
html[data-jurisdiction="${pack.id}"] .identity{background:#fff;padding:12px 16px;}
html[data-jurisdiction="${pack.id}"] .identity-logo{width:240px;max-width:100%;height:auto;}
html[data-jurisdiction="${pack.id}"] .government-banner{height:auto;min-height:40px;text-align:center;}
html[data-jurisdiction="${pack.id}"] .site-header{position:relative;top:auto;padding:16px 0;}
html[data-jurisdiction="${pack.id}"] .chat-header{padding-bottom:16px;}
html[data-jurisdiction="${pack.id}"] .welcome-hero{padding-top:32px;}
.pilot-notice{padding:16px 24px;background:var(--surface-soft);color:var(--text);border-bottom:1px solid var(--line-strong);font-size:14px;}
.pilot-hero{background:var(--hero);padding:48px 24px;border-radius:8px;}
.pilot-hero h1{font-size:32px;}.pilot-hero p{margin-block:16px;}
.pilot-hero .composer-anchor{margin-block:24px;min-height:150px;}
@media(max-width:767px){html[data-jurisdiction="${pack.id}"] .identity{padding:12px;}
html[data-jurisdiction="${pack.id}"] .identity-logo{width:180px;}.pilot-hero h1{font-size:24px;}
html[data-jurisdiction="${pack.id}"] .header-inner{width:calc(100% - 32px);}}
`);
  }
  writeFileSync(path.join(assets, ".jurisdiction"), fingerprint);
  return pack.id;
}

export function stampJurisdiction(id) {
  const dist = path.join(webRoot, process.env.NEXT_DIST_DIR || ".next");
  mkdirSync(dist, { recursive: true });
  writeFileSync(path.join(dist, "jurisdiction.json"), JSON.stringify({ id }));
}
