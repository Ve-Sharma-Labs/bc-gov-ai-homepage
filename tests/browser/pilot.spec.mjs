import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const catalogue = JSON.parse(readFileSync(new URL("../../data/pilot-catalog.json", import.meta.url), "utf8"));
const escapeRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

async function openHome(page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Hello, British Columbia");
  await expect(page.locator(".journey-card")).toHaveCount(7);
  await page.evaluate(() => document.fonts.ready);
  await expect(page.locator(".composer-float")).toHaveAttribute("data-ready", "true");
}

async function openJourney(page, journey) {
  await page.getByRole("button", { name: new RegExp(escapeRegex(journey.title)) }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: journey.title })).toBeVisible();
  await expect(page.getByText("Guided plan · Not AI-generated", { exact: true })).toBeVisible();
}

test("serves the real catalogue and honest native-AI capability status", async ({ page }) => {
  await openHome(page);
  const response = await page.request.get("/api/catalog");
  expect(response.ok()).toBeTruthy();
  const served = await response.json();
  expect(served).toEqual(catalogue);
  const capabilities = await (await page.request.get("/api/capabilities")).json();
  expect(capabilities.aiConfigured).toBe(false);
  expect(capabilities.generalChatConfigured).toBe(false);
  expect(capabilities.retrievalReady).toBe(false);
  expect(capabilities.requestVersions).toContain(2);
  expect(capabilities.transactionsEnabled).toBe(false);
  expect(capabilities.webIqEnabled).toBe(false);
  await expect(page.locator(".connection-status")).toContainText("AI answers not connected");
  expect((await page.context().cookies()).some((cookie) => cookie.name === "bc_pilot_session")).toBe(false);
});

for (const journey of catalogue.journeys) {
  test(`real preparation and handoffs: ${journey.id}`, async ({ page }) => {
    await openHome(page);
    await openJourney(page, journey);
    await expect(page.getByRole("heading", { name: "Your preparation plan" })).toBeVisible();
    await expect(page.getByRole("checkbox")).toHaveCount(journey.steps.length);
    await page.getByText(journey.steps[0].title, { exact: true }).click();
    await expect(page.getByRole("checkbox").first()).toBeChecked();
    await expect(page.getByText(`1 of ${journey.steps.length} steps reviewed`, { exact: true })).toBeVisible();
    for (const handoff of journey.handoffs) {
      const link = page.locator(".handoff-link").filter({ hasText: handoff.label });
      await expect(link).toHaveAttribute("href", handoff.url);
      await expect(link).toHaveAttribute("target", "_blank");
    }
    await expect(page.getByText("Nothing has been booked, renewed or submitted here.", { exact: false })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

test("dispatches a free-form v2 general question once and preserves it when the real API has no general binding", async ({ page }) => {
  await openHome(page);
  const prompt = "Help me understand the next step for renewing my licence.";
  const agentRequests = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/agent") agentRequests.push(request.postDataJSON());
  });
  const input = page.getByRole("textbox", { name: "What would you like help with?" });
  await input.fill(prompt);
  const responsePromise = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/agent");
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(503);
  const failure = await response.json();
  expect(failure.error.code).toBe("GENERAL_AGENT_NOT_CONFIGURED");
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.locator(".chat-recovery")).toContainText(failure.error.message);
  await expect(page.locator(".question-text")).toHaveText(prompt);
  await expect(input).toHaveValue(prompt);
  await expect(page.getByRole("heading", { name: "AI answer" })).toHaveCount(0);
  expect(agentRequests).toHaveLength(1);
  expect(agentRequests[0]).toMatchObject({ state: {}, tools: [], context: [], forwardedProps: { bc: { version: 2, mode: "general" } } });
  expect(agentRequests[0].forwardedProps.bc).not.toHaveProperty("journeyId");
  await expect(page.getByRole("button", { name: "Try again", exact: true })).toBeEnabled();
  await expect(page.locator(".composer-scope-label")).toHaveText("General B.C. chat");
});

test("reset requires confirmation and clears only transient page work", async ({ page }) => {
  await openHome(page);
  const journey = catalogue.journeys[0];
  await openJourney(page, journey);
  await page.getByText(journey.steps[0].title, { exact: true }).click();
  await page.getByRole("textbox").fill("A draft to be cleared only after confirmation.");
  await page.getByRole("button", { name: "Start over", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("This clears the conversation");
  await dialog.getByRole("button", { name: "Keep this conversation" }).click();
  await expect(page.getByRole("checkbox").first()).toBeChecked();
  await page.getByRole("button", { name: "Start over", exact: true }).click();
  await dialog.getByRole("button", { name: "Start over", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Hello, British Columbia");
  await expect(page.getByRole("textbox")).toHaveValue("");
  await openJourney(page, journey);
  await expect(page.getByRole("checkbox").first()).not.toBeChecked();
});

test("location filtering respects explicit service exclusions", async ({ page }) => {
  await openHome(page);
  const journey = catalogue.journeys.find((item) => item.id === "service-bc");
  await openJourney(page, journey);
  const excluded = catalogue.locations.find((location) => location.excludedServices.includes("icbc-licensing"));
  expect(excluded).toBeTruthy();
  const finder = page.locator(".location-finder");
  await finder.getByRole("combobox", { name: "Service", exact: true }).selectOption("icbc-licensing");
  await finder.getByRole("combobox", { name: "Municipality", exact: true }).selectOption(excluded.municipality);
  await finder.getByRole("button", { name: "Find locations" }).click();
  const expected = catalogue.locations.filter((location) =>
    location.municipality === excluded.municipality &&
    location.services.includes("icbc-licensing") &&
    !location.excludedServices.includes("icbc-licensing"),
  );
  await expect(finder.locator(".location-result-count")).toHaveText(`${expected.length} ${expected.length === 1 ? "location" : "locations"} in these results`);
  await expect(finder.locator(".location")).toHaveCount(expected.length);
});

test("source registry includes and distinguishes gated publishers", async ({ page }) => {
  await page.goto("/sources");
  await expect(page.getByText("12 sources in this curated catalogue")).toBeVisible();
  await expect(page.locator(".source-directory-list .source-card")).toHaveCount(12);
  const blocked = catalogue.sources.filter((source) => source.status === "blocked");
  await page.getByLabel("Source status").selectOption("blocked");
  await expect(page.locator(".source-directory-list .source-card")).toHaveCount(blocked.length);
  for (const source of blocked) {
    await expect(page.locator(`#source-${source.id}`)).toContainText("Access restricted");
  }
});

test("light and dark themes persist, reflow and pass automated accessibility", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openHome(page);
  for (const theme of ["light", "dark"]) {
    const label = `${theme[0].toUpperCase()}${theme.slice(1)} theme`;
    await page.getByRole("button", { name: "Menu", exact: true }).click();
    await page.locator(".theme-option").filter({ has: page.getByRole("radio", { name: label }) }).click();
    await expect(page.getByRole("radio", { name: label })).toBeChecked();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.getByRole("button", { name: "Close menu", exact: true }).click();
    await page.reload();
    await expect(page.locator(".journey-card")).toHaveCount(7);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.evaluate(() => document.fonts.ready);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`homepage-${theme}.png`), fullPage: true });
  }
});

test("service navigation remains useful without JavaScript", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.goto(`${baseURL}/services`);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("The official service");
    const officialLinks = page.locator("main a[href^='https://']");
    expect(await officialLinks.count()).toBeGreaterThanOrEqual(5);
  } finally {
    await context.close();
  }
});
