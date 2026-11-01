import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("AI-led renewal clarification and privacy controls work without a persona picker", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const catalog = await (await page.request.get("/api/catalog")).json();
  const journey = catalog.journeys.find((item) => item.id === "licence-renewal");
  const requests = [];
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: {
    mode: "foundry", aiConfigured: true, generalChatConfigured: true, retrievalReady: true,
    conversationAvailable: true, conversationAgentReady: true, requestVersions: [1, 2, 3, 5],
    webIqEnabled: false, transactionsEnabled: false, syntheticContextAvailable: false,
    message: "Explicit browser fixture; no model is invoked by this presentation test.",
  } }));
  await page.route("**/api/agent", (route) => {
    const request = route.request().postDataJSON();
    requests.push(request);
    const revision = request.forwardedProps.bc.conversation.revision + 1;
    const first = revision === 1;
    const value = {
      version: 1, noticeVersion: "ai-conversation-v1", threadId: request.threadId, revision,
      expiresAt: "2099-01-01T00:00:00Z", goal: "licence-renewal",
      goalLabel: "Renew a driver's licence", subject: "you", phase: first ? "clarify" : "guide",
      questionCount: 1, question: first ? {
        id: "fixture-issuer-question", kind: "context", factKey: "licence-jurisdiction",
        text: "Is it a B.C.-issued licence?", reason: "Use the right preparation guide. No licence number is needed.",
        choices: ["Yes, issued in B.C.", "Issued somewhere else", "Not sure"], candidates: [], personal: false,
      } : null,
      facts: first ? [] : [{
        key: "licence-jurisdiction", label: "Licence issuer", value: "bc", displayValue: "Issued in B.C.",
        status: "provided", provenance: "citizen-answer", personal: false, subject: "you",
      }],
      shareContext: false, journeyId: first ? null : "licence-renewal", suggestedDemoId: null,
      limitation: first ? "missing-context" : "none", decisionOrigin: "model",
    };
    const events = [
      { type: "RUN_STARTED", runId: request.runId, threadId: request.threadId },
      { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: first ? "dialogue" : "handoff", origin: "application", decisionOrigin: "model" } },
      { type: "TEXT_MESSAGE_START", messageId: `answer-${revision}`, role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: `answer-${revision}`, delta: first
        ? "Of course - I can help you prepare to renew your driver's licence. Is it a B.C.-issued licence?"
        : "Let's prepare your ID. Use [ICBC's accepted ID guide](https://www.icbc.com/driver-licensing/visit-dl-office/Accepted-ID), and keep your documents private. Nothing has been renewed or booked." },
      { type: "TEXT_MESSAGE_END", messageId: `answer-${revision}` },
      { type: "CUSTOM", name: "bc.conversation", value },
      ...(!first ? [{ type: "CUSTOM", name: "bc.artifact", value: {
        version: 1, id: "fixture-renewal-guide", kind: "preparation", journey,
        sources: catalog.sources.filter((source) => journey.sourceIds.includes(source.id)), transactionsEnabled: false,
      } }] : []),
      { type: "RUN_FINISHED", runId: request.runId, threadId: request.threadId },
    ];
    return route.fulfill({ contentType: "text/event-stream", body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("") });
  });
  await page.goto("/");
  await expect(page.locator(".home-conversation-details > summary")).toBeVisible();
  await expect(page.locator(".composer-ai-privacy")).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: /Use personal details/ })).toHaveCount(0);
  await page.getByRole("textbox").fill("PLEASE HELP ME RENEW MY DRIVERS LICENESE PELASE");
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.locator(".message-assistant")).toContainText("B.C.-issued licence");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Yes, issued in B.C." })).toHaveCount(0);
  await page.getByRole("textbox").fill("Yes, issued in B.C.");
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect(page.locator(".message-assistant").last()).toContainText("Let's prepare your ID.");
  await expect(page.getByRole("region", { name: "Source-backed preparation" })).toHaveCount(0);
  await page.getByRole("button", { name: "Details", exact: true }).click();
  await expect(page.getByRole("region", { name: "Source-backed preparation" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /Use personal details/ })).not.toBeChecked();
  await expect(page.locator(".message-assistant").last()).not.toContainText("unsupported");
  await page.getByText("What I understand", { exact: true }).click();
  await expect(page.locator(".ai-context-summary")).toContainText("Issued in B.C.");
  expect(requests.map((request) => request.forwardedProps.bc.version)).toEqual([5, 5]);
  expect(requests[1].messages).toHaveLength(1);
  expect(requests[1].forwardedProps.bc.conversation.questionId).toBe("fixture-issuer-question");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((theme) => { document.documentElement.dataset.theme = theme; }, theme);
    await page.locator(".ai-conversation-context").scrollIntoViewIfNeeded();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations)).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath(`ai-conversation-${theme}.png`), fullPage: true });
  }
});
