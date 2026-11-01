import { expect, test } from "@playwright/test";

test("live text-first EI conversation remains usable with dated sources", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  let pageId = "";
  let requests = 0;
  let lastSent = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/agent" && request.method() === "POST") {
      requests++;
      pageId = request.headers()["x-bc-conversation-page"] || pageId;
      expect(request.postDataJSON().forwardedProps.bc.version).toBe(6);
    }
  });
  const send = async (text) => {
    await page.waitForTimeout(Math.max(0, 8100 - (Date.now() - lastSent)));
    const previousAnswers = await page.locator(".message-assistant").count();
    await page.getByRole("textbox", { name: "What would you like help with?" }).fill(text);
    const response = page.waitForResponse((response) =>
      new URL(response.url()).pathname === "/api/agent" && response.request().method() === "POST");
    lastSent = Date.now();
    await page.getByRole("button", { name: "Send question", exact: true }).click();
    const result = await response;
    expect(result.status()).toBe(200);
    await expect.poll(() => page.locator(".message-assistant").count(), {
      timeout: 90_000,
    }).toBeGreaterThan(previousAnswers);
    await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0, { timeout: 90_000 });
    await expect(page.locator(
      ".chat-recovery, .conversation-control-error, .context-error",
    )).toHaveCount(0);
    await expect(page.locator(".answer-warning")).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "What would you like help with?" })).toBeEditable();
    return page.locator(".message-assistant").last();
  };
  await page.emulateMedia({ reducedMotion: "reduce" });
  try {
    const capabilities = page.waitForResponse("**/api/capabilities");
    await page.goto("/");
    const settings = await (await capabilities).json();
    expect(settings.localEvidenceEvaluation && settings.retrievalReady).toBe(true);
    await expect(page.locator(".home-conversation-details > summary")).toBeVisible();
    await expect(page.getByText("Local evaluation only.", { exact: true })).not.toBeVisible();
    const starter = "I just lost my job, what do I do?";
    await page.getByRole("button", { name: starter, exact: true }).click();
    await expect(page.getByRole("textbox")).toHaveValue(starter);
    expect(requests).toBe(0);
    await send(starter);
    const application = await send("finding work? i want to claim my EI please");
    await expect(application).toContainText(/EI|Employment Insurance/);
    await expect(application).not.toContainText("rent or finding work");
    const answer = await send("I don't have my ROE yet");
    await expect(answer).toContainText(/ROE|record of employment/i);
    await expect(answer.locator('a[href^="https://www.canada.ca/"]').first()).toBeVisible();
    await expect(page.getByRole("textbox")).toHaveCount(1);
    await expect(page.getByRole("textbox")).toBeInViewport();
    await answer.getByRole("button", { name: /sources?/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText("Dated copy of an official page").first()).toBeVisible();
    await page.getByRole("button", { name: "Close sources" }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath("live-ei-conversation.png"), fullPage: true });
  } finally {
    if (pageId) {
      const response = await page.request.delete("/api/conversation", {
        headers: {
          Origin: new URL(testInfo.project.use.baseURL).origin,
          "X-BC-Conversation-Page": pageId,
        },
      });
      expect(response.status()).toBe(204);
    }
  }
});
