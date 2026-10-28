import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const suppliedFavicon = readFileSync(new URL("../../apps/web/public/favicon.ico", import.meta.url));

test("transparent logo preserves proportions with a readable dark-mode fallback", async ({ page }, testInfo) => {
  for (const theme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    await page.goto("/");
    const home = page.getByRole("link", { name: "British Columbia service assistant home" });
    const logo = home.getByRole("img", { name: "Government of British Columbia" });
    await expect(logo).toBeVisible();
    await expect(logo).toHaveAttribute("src", "/brand/bc-logo-horizontal-transparent.png");
    await expect.poll(() => logo.evaluate((image) => image.naturalWidth)).toBe(361);
    const pixels = await logo.evaluate((image) => {
      const canvas = document.createElement("canvas");
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext("2d");
      context.drawImage(image, 0, 0);
      const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
      let opaqueWhite = 0;
      for (let y = 16; y < 104; y++) {
        for (let x = 16; x < 145; x++) {
          const index = (y * canvas.width + x) * 4;
          if (data[index] === 255 && data[index + 1] === 255 && data[index + 2] === 255 && data[index + 3] === 255) opaqueWhite++;
        }
      }
      return { cornerAlpha: data[3], opaqueWhite };
    });
    expect(pixels.cornerAlpha).toBe(0);
    expect(pixels.opaqueWhite).toBeGreaterThan(0);
    const bounds = await logo.boundingBox();
    expect(bounds.width / bounds.height).toBeCloseTo(361 / 120, 2);
    expect(await home.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(theme === "dark" ? "rgb(255, 255, 255)" : "rgba(0, 0, 0, 0)");
    expect(await logo.evaluate((element) => getComputedStyle(element).filter)).toBe("none");
    const menu = await page.getByRole("button", { name: "Menu", exact: true }).boundingBox();
    expect(bounds.x + bounds.width).toBeLessThan(menu.x);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.locator(".header-inner").screenshot({ path: testInfo.outputPath(`branding-${theme}.png`) });
  }
});

test("favicon and touch-icon metadata resolve to the supplied branding", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", "/favicon.ico");
  await expect(page.locator('link[rel="apple-touch-icon"]')).toHaveAttribute("href", "/apple-touch-icon.png");
  await expect(page.locator('link[href="/icon.svg"]')).toHaveCount(0);
  const favicon = await page.request.get("/favicon.ico");
  expect(favicon.ok()).toBeTruthy();
  expect(await favicon.body()).toEqual(suppliedFavicon);
  const icon = await page.request.get("/apple-touch-icon.png");
  expect(icon.ok()).toBeTruthy();
  expect(icon.headers()["content-type"]).toContain("image/png");
});
