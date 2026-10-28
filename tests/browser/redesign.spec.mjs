import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function ready(page) {
  await page.goto("/");
  await expect(page.locator(".journey-card")).toHaveCount(7);
  await expect(page.locator(".composer-float")).toHaveAttribute("data-ready", "true");
  await page.evaluate(() => document.fonts.ready);
}

async function navigate(page, name) {
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await page.getByRole("dialog").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

test("reference-sized composer, local BC photo and hydration work together", async ({ page }, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await ready(page);
  const target = testInfo.project.name === "mobile" ? 97 : 96;
  await expect.poll(async () => Math.abs((await page.locator(".composer").boundingBox()).height - target)).toBeLessThanOrEqual(8);
  await expect(page.locator(".hero-photograph img")).toHaveAttribute("src", /\/images\/bc\//);
  await expect.poll(() => page.locator(".hero-photograph img").evaluate((image) => image.naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByRole("textbox")).toHaveCount(1);
  await expect(page.locator(".composer-float")).toHaveClass(/is-anchored/);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("reference-fold.png") });
});

test("one composer retains its draft through docking and internal navigation", async ({ page }) => {
  await ready(page);
  await page.getByRole("textbox").fill("Help me prepare for my next step.");
  await page.locator("footer").scrollIntoViewIfNeeded();
  await expect(page.locator(".composer-float")).toHaveClass(/is-docked/);
  await expect(page.getByRole("textbox")).toHaveCount(1);
  await expect(page.getByRole("textbox")).toHaveValue("Help me prepare for my next step.");
  await navigate(page, "How it works");
  await expect(page).toHaveURL(/\/how-it-works$/);
  await expect(page.getByRole("textbox")).toHaveValue("Help me prepare for my next step.");
  await navigate(page, "Home");
  await expect(page.getByRole("textbox")).toHaveValue("Help me prepare for my next step.");
  const storage = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage }, url: location.href }));
  expect(JSON.stringify(storage)).not.toContain("Help me prepare");
});

test("fifth example uses a sharp Victoria photograph with responsive crops and credits", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  await ready(page);
  await page.getByRole("button", { name: "Previous example", exact: true }).click();
  await expect(page.locator(".photo-story")).toHaveAttribute("data-example", "4");
  await expect(page.locator(".photo-place")).toHaveText("Victoria, British Columbia");
  const photo = page.getByRole("img", { name: "British Columbia's Parliament Buildings in Victoria, with a Canadian flag and fountain in daylight.", exact: true });
  await expect(photo).toBeVisible();
  const mobile = testInfo.project.name === "mobile";
  await expect.poll(() => photo.evaluate((image) => image.naturalWidth)).toBe(mobile ? 1200 : 2400);
  const image = await photo.evaluate((element) => ({
    src: new URL(element.currentSrc).pathname,
    height: element.naturalHeight,
    pixelCoverage: Math.min(element.naturalWidth / element.clientWidth, element.naturalHeight / element.clientHeight),
  }));
  expect(image.src).toBe(`/images/bc/victoria-parliament-${mobile ? 1200 : 2400}.webp`);
  expect(image.height).toBe(mobile ? 1800 : 1600);
  expect(image.pixelCoverage).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".photo-fallback")).toHaveCount(0);
  for (const colorScheme of ["light", "dark"]) {
    const label = `${colorScheme[0].toUpperCase()}${colorScheme.slice(1)} theme`;
    await page.getByRole("button", { name: "Menu", exact: true }).click();
    await page.locator(".theme-option").filter({ has: page.getByRole("radio", { name: label }) }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", colorScheme);
    await page.getByRole("button", { name: "Close menu", exact: true }).click();
    await page.locator(".photo-story").scrollIntoViewIfNeeded();
    await expect(page.locator(".composer-float")).toHaveClass(/is-anchored/);
    await expect(page.locator(".photo-question")).toBeVisible();
    await page.locator(".photo-story").screenshot({ path: testInfo.outputPath(`victoria-${colorScheme}.png`) });
  }
  await page.locator(".photo-question").click();
  await expect(page.getByRole("heading", { name: "Your preparation plan" })).toBeVisible();
  await page.goto("/credits");
  await expect(page.getByRole("link", { name: "Brian Zhu", exact: true })).toHaveAttribute("href", "https://unsplash.com/@dogrod");
  await expect(page.locator('a[href="https://unsplash.com/photos/the-british-columbia-parliament-buildings-are-showcased-0IM71KfH3mo"]')).toHaveText("Unsplash");
});

test("reviewed checklist state survives source-page navigation and clears on reload", async ({ page }) => {
  await ready(page);
  await page.locator(".journey-card").first().click();
  const checkbox = page.getByRole("checkbox").first();
  await checkbox.focus();
  await page.keyboard.press("Space");
  await expect(checkbox).toBeChecked();
  await navigate(page, "Our sources");
  await expect(page.locator(".source-card")).toHaveCount(12);
  await navigate(page, "Home");
  await expect(page.getByRole("checkbox").first()).toBeChecked();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Hello, British Columbia");
  await page.locator(".journey-card").first().click();
  await expect(page.getByRole("checkbox").first()).not.toBeChecked();
});

test("menu retains every route, keyboard dismissal and proper link semantics", async ({ page }) => {
  await ready(page);
  const trigger = page.getByRole("button", { name: "Menu", exact: true });
  await trigger.click();
  for (const name of ["Home", "How it works", "Browse services", "Our sources", "About this pilot"]) {
    await expect(page.getByRole("dialog").getByRole("link", { name, exact: true })).toBeVisible();
  }
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(result.violations, JSON.stringify(result.violations, null, 2)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("How it works has four original scenes and a readable reduced-motion state", async ({ page }, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/how-it-works");
  await expect(page.locator(".feature-scene")).toHaveCount(4);
  await expect(page.locator(".scene-frame[data-playing='true']")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Straight from the source.", exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(result.violations, JSON.stringify(result.violations, null, 2)).toEqual([]);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath("how-it-works.png"), fullPage: true });
});

test("example browsing never submits or overwrites the person's question", async ({ page }) => {
  await ready(page);
  let requests = 0;
  page.on("request", (request) => { if (new URL(request.url()).pathname === "/api/agent") requests++; });
  await page.getByRole("textbox").fill("My own question, not an example.");
  const first = await page.locator(".photo-place").textContent();
  await page.getByRole("button", { name: "Next example", exact: true }).click();
  await expect(page.locator(".photo-place")).not.toHaveText(first);
  await expect(page.getByRole("textbox")).toHaveValue("My own question, not an example.");
  expect(requests).toBe(0);
});

test("a failed photograph does not block the guided journey", async ({ page }) => {
  await page.route("**/images/bc/*.webp", (route) => route.abort());
  await ready(page);
  await expect(page.locator(".photo-fallback")).toBeVisible();
  await page.locator(".journey-card").first().click();
  await expect(page.getByRole("heading", { name: "Your preparation plan" })).toBeVisible();
});

test("illustrations can pause without concealing their explanation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await ready(page);
  const scene = page.locator(".scene-sources");
  await scene.scrollIntoViewIfNeeded();
  await expect(scene.locator(".scene-frame")).toHaveAttribute("data-playing", "true");
  await scene.getByRole("button", { name: "Pause sources illustration" }).click();
  await expect(scene.locator(".scene-frame")).toHaveAttribute("data-playing", "false");
  await expect(scene.getByRole("heading", { name: "Straight from the source." })).toBeVisible();
  await scene.getByRole("button", { name: "Play sources illustration" }).click();
  await expect(scene.locator(".scene-frame")).toHaveAttribute("data-playing", "true");
});

test("narrow reflow and tablet navigation remain complete", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const width of [320, 820]) {
    await page.setViewportSize({ width, height: 900 });
    await ready(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.getByRole("button", { name: "Menu", exact: true }).click();
    await expect(page.getByRole("dialog").getByRole("link", { name: "About this pilot" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
});

test("informational pages keep inline links distinguishable in dark mode", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  for (const route of ["/about", "/sources", "/services", "/credits"]) {
    await page.goto(route);
    await expect(page.locator(".composer-float")).toHaveAttribute("data-ready", "true");
    await page.evaluate(() => document.fonts.ready);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(result.violations, `${route}: ${JSON.stringify(result.violations, null, 2)}`).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  }
});
