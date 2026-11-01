import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function home(page) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator(".journey-card")).toHaveCount(7);
  await expect(page.locator(".composer-float")).toHaveAttribute("data-ready", "true");
  await expect(page.getByRole("button", { name: "Choose a synthetic demo persona" })).toBeVisible();
}

async function send(page, prompt) {
  await page.getByRole("textbox", { name: "What would you like help with?" }).fill(prompt);
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
}

async function theme(page, name) {
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await page.locator(".theme-option").filter({
    has: page.getByRole("radio", { name: `${name} theme` }),
  }).click();
  await page.getByRole("button", { name: "Close menu", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", name.toLowerCase());
}

test("real discovery is warm, bounded, editable, and page-scoped", async ({ page }, testInfo) => {
  const requests = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/agent" && request.method() === "POST") {
      requests.push(request.postDataJSON());
    }
  });
  await home(page);
  await send(page, "I'm thinking of buying a motorcycle next year - what should I think of?");
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByRole("heading", { name: "What I understand" })).toBeVisible();
  await expect(page.locator(".message-assistant").last()).toContainText("That sounds exciting");
  await expect(page.locator(".discovery-context")).toContainText("Next year");
  await expect(page.locator(".discovery-count")).toHaveText(/Question 1 of at most 3/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "19 or older", exact: true }).click();
  await expect(page.locator(".message-assistant").last()).toContainText("motorcycle licence");
  await expect(page.locator(".discovery-count")).toHaveText(/Question 2 of at most 3/);
  await page.getByRole("button", { name: "My first one", exact: true }).click();
  await expect(page.locator(".discovery-recommendations")).toBeVisible();
  await expect(page.locator(".message-assistant").last()).toContainText("won't guess");
  await expect(page.locator(".discovery-context")).not.toContainText(/renew|PHN|immigration/);
  expect(requests).toHaveLength(3);
  for (const request of requests) {
    expect(request.forwardedProps.bc.version).toBe(4);
    expect(request.forwardedProps.bc.mode).toBe("general");
    expect(request.forwardedProps.bc).not.toHaveProperty("journeyId");
    expect(request.state).toEqual({});
    expect(request.context).toEqual([]);
    expect(request.messages).toHaveLength(1);
  }
  await page.getByRole("button", { name: "Change age when you plan to start" }).click();
  const age = page.getByRole("textbox", { name: "Change age when you plan to start" });
  await age.fill("30");
  await page.getByRole("button", { name: "Save change" }).click();
  await expect(page.locator(".discovery-fact").filter({ hasText: "Age when you plan to start" })).toContainText("30");
  await page.getByRole("button", { name: "Remove age when you plan to start" }).click();
  await expect(page.locator(".discovery-fact").filter({ hasText: "Age when you plan to start" })).toContainText("Not shared");
  await expect(page.locator(".chat-recovery")).toHaveCount(0);
  for (const name of ["Light", "Dark"]) {
    await theme(page, name);
    await page.locator(".discovery-context").scrollIntoViewIfNeeded();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath(`discovery-${name.toLowerCase()}.png`), fullPage: true });
  }
  await page.getByRole("link", { name: "Home", exact: true }).click();
  await page.getByRole("link", { name: "Return to your conversation" }).click();
  await expect(page.getByRole("heading", { name: "What I understand" })).toBeVisible();
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual(["bc-service-theme"]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "What I understand" })).toHaveCount(0);
  await expect(page.locator(".message")).toHaveCount(0);
});

test("a recommended fictional scenario still needs an explicit choice and consent", async ({ page }) => {
  const sessions = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/demo/session" && request.method() === "POST") {
      sessions.push(request.postDataJSON());
    }
  });
  await home(page);
  await send(page, "I lost my job and need help.");
  await expect(page.locator(".message-assistant").last()).toContainText("one step at a time");
  await page.getByRole("button", { name: "Both", exact: true }).click();
  await expect(page.getByRole("button", { name: "Try the recommended fictional scenario" })).toBeVisible();
  await expect(page.locator(".synthetic-context-banner")).toHaveCount(0);
  expect(sessions).toEqual([]);
  await page.getByRole("button", { name: "Try the recommended fictional scenario" }).click();
  const consent = page.getByRole("dialog", { name: "Choose what Sam may share" });
  await expect(consent).toContainText("All values are fictional");
  expect(sessions).toEqual([]);
  await consent.getByRole("button", { name: "Use selected context" }).click();
  await expect(page.locator(".synthetic-context-banner")).toContainText("Sam");
  expect(sessions).toEqual([{ personaId: "sam-job-loss" }]);
  await expect(page.getByRole("heading", { name: "What I understand" })).toHaveCount(0);
  await expect(page.locator(".synthetic-context-banner")).toContainText("no real government records");
  await send(page, "I want to buy a motorcycle next year.");
  await expect(page.locator(".chat-recovery")).toContainText("outside this fictional scenario");
  await page.getByRole("button", { name: "Continue anonymously" }).click();
  await expect(page.locator(".synthetic-context-banner")).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "What would you like help with?" })).toHaveValue("I want to buy a motorcycle next year.");
});
