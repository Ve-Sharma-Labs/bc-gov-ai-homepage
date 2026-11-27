import { expect, test } from "@playwright/test";

const selected = process.env.JURISDICTION ?? "bc";

test.describe("selected government presentation", () => {
  test.skip(selected !== "sk", "Saskatchewan pack checks run on its separately selected build.");

  test("local pilot identity, themes and official handoffs stay jurisdiction-specific", async ({ page }) => {
    test.setTimeout(90_000);
    for (const theme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
      await page.goto("/");
      await expect(page.locator("html")).toHaveAttribute("data-jurisdiction", "sk");
      const identity = page.getByRole("link", { name: "Saskatchewan assistant pilot home" });
      const logo = identity.locator("img");
      await expect(logo).toHaveAttribute("src", "/brand/sk-wordmark.png");
      await expect(logo).toBeVisible();
      await expect.poll(() => logo.evaluate((image) => image.naturalWidth)).toBe(373);
      const bounds = await logo.boundingBox();
      expect(bounds.width / bounds.height).toBeCloseTo(373 / 79, 2);
      expect(await identity.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgb(255, 255, 255)");
      expect(await page.getByRole("button", { name: "Menu", exact: true }).evaluate((element) => getComputedStyle(element).backgroundColor))
        .toBe(theme === "dark" ? "rgb(251, 221, 64)" : "rgb(4, 106, 56)");
      await expect(page.locator(".pilot-notice")).toContainText("not an official Government of Saskatchewan service");
      await expect(page.locator(".hero-photograph img")).toHaveAttribute("src", "/images/sk/saskatchewan-fields-1600.webp");
      await expect(page.getByText(/Guided plans and fictional resident profiles are not available/u)).toBeVisible();
      await expect(page.locator("body")).not.toContainText(/British Columbia|Service BC|ICBC|BCID/u);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", "/pilot-icon.svg");
      expect((await page.request.get("/brand/bc-logo-horizontal-transparent.png")).status()).toBe(404);
      expect((await page.request.get("/favicon.ico")).status()).toBe(404);
    }
    for (const route of ["/services", "/about", "/how-it-works", "/sources", "/credits", "/chat"]) {
      await page.goto(route);
      await expect(page.locator(".pilot-notice")).toContainText("not an official");
      await expect(page.locator("body")).not.toContainText(/British Columbia|Service BC|ICBC|BCID/u);
    }
    await page.goto("/services");
    const handoffs = page.locator('.service-directory a[target="_blank"]');
    await expect(handoffs).toHaveCount(3);
    for (const handoff of await handoffs.all()) expect(await handoff.getAttribute("href")).toMatch(/^https:\/\/www\.saskatchewan\.ca\//u);
    await page.goto("/chat");
    await expect(page.getByRole("button", { name: /Choose a pathway|Contextual demo/u })).toHaveCount(0);
    await page.goto("/credits");
    const flag = page.getByRole("img", { name: "Flag of Saskatchewan" });
    await expect(flag).toHaveAttribute("src", "/brand/sk-flag.png");
    expect(await flag.evaluate((image) => image.naturalWidth / image.naturalHeight)).toBe(2);
    expect((await page.request.get("/brand/attribution.json")).ok()).toBeTruthy();
  });

  test("Saskatchewan carousel controls and photo credits are accessible", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
    await page.goto("/");
    const photo = page.locator(".hero-photograph img");
    const controls = page.getByRole("group", { name: "Explore Saskatchewan photographs" });
    await expect(photo).toHaveAttribute("alt", /Saskatchewan crop fields/u);
    await expect(page.locator(".hero-photograph source")).toHaveAttribute("srcset", "/images/sk/saskatchewan-fields-800.webp");
    await expect(controls).toBeVisible();
    await expect(page.getByRole("button", { name: "Play slideshow" })).toBeDisabled();
    const next = page.getByRole("button", { name: "Next photograph" });
    await next.focus();
    await page.keyboard.press("Enter");
    await expect(photo).toHaveAttribute("src", "/images/sk/saskatoon-river-1600.webp");
    await expect(page.locator(".example-count")).toHaveText("02 / 05");
    await page.getByRole("button", { name: "Previous photograph" }).click();
    await expect(photo).toHaveAttribute("src", "/images/sk/saskatchewan-fields-1600.webp");
    await page.goto("/credits");
    await expect(page.locator(".photo-credits figure")).toHaveCount(5);
    await expect(page.locator(".photo-credits a[href^='https://unsplash.com/photos/']")).toHaveCount(5);
    await expect(page.locator(".photo-credits a[href^='https://unsplash.com/@']")).toHaveCount(5);
    await expect(page.getByRole("link", { name: "Unsplash licence" })).toHaveAttribute("href", "https://unsplash.com/license");
  });
});
