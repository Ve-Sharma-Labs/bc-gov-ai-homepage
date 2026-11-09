import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const sourceUrl = "https://www2.gov.bc.ca/gov/content/governments/organizational-structure/ministries-organizations/ministries/citizens-services/servicebc";
const wire = (events) => events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");

async function fixtures(page, fail = false) {
  const normal = [];
  const research = [];
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: {
    mode: "foundry", aiConfigured: true, generalChatConfigured: true, retrievalReady: true,
    requestVersions: [1, 2, 3], webIqEnabled: true, transactionsEnabled: false,
    syntheticContextAvailable: false, message: "Synthetic research UI fixture; no provider is called.",
    research: {
      version: 1,
      foundryIq: { available: true, preview: true, reason: "Synthetic preview fixture." },
      webIq: { available: true, preview: false, reason: "Synthetic public-web fixture." },
    },
  } }));
  await page.route("**/api/agent", async (route) => {
    const input = route.request().postDataJSON();
    normal.push(input);
    const messageId = `${input.runId}-answer`;
    await route.fulfill({ contentType: "text/event-stream", body: wire([
      { type: "RUN_STARTED", runId: input.runId, threadId: input.threadId },
      { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "grounded", origin: "model" } },
      { type: "TEXT_MESSAGE_START", messageId, role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId, delta: `Original indexed guidance. [Official page](${sourceUrl})` },
      { type: "TEXT_MESSAGE_END", messageId },
      { type: "CUSTOM", name: "annotations", value: { messageId, annotations: [{
        sourceId: "service-bc", title: "Synthetic indexed source", url: sourceUrl,
      }] } },
      { type: "CUSTOM", name: "bc.research.offer", value: {
        version: 1, parentRunId: input.runId, parentMessageId: messageId, threadId: input.threadId,
        topics: ["service-bc"], actions: ["web-check", "corpus-explore"],
        expiresAt: "2099-01-01T00:00:00Z",
      } },
      { type: "RUN_FINISHED", runId: input.runId, threadId: input.threadId },
    ]) });
  });
  await page.route("**/api/research", async (route) => {
    if (route.request().method() === "DELETE") return route.fulfill({ status: 204 });
    const input = route.request().postDataJSON();
    research.push(input);
    if (fail) return route.fulfill({ status: 503, json: {
      error: { code: "RESEARCH_UNAVAILABLE", message: "Synthetic provider outage. Your answer is unchanged." },
    } });
    const common = {
      sourceId: "service-bc", title: "Synthetic supplemental source",
      publisher: "Government of British Columbia", url: sourceUrl,
    };
    const citation = input.action === "web-check" ? {
      ...common, kind: "web", humanReviewed: false, method: "search",
      retrievedAt: "2026-01-01T00:00:00Z", crawledAt: null, publisherUpdatedAt: null, quoteLimit: 200,
    } : {
      kind: "indexed", retrievedAt: "2026-01-01T00:00:00Z", reference: {
        ...common, documentId: "fixture-document", documentVersion: "fixture-version",
        section: "Fixture", chunkId: "fixture-chunk", metadata: null,
        checkedAt: "2026-01-01T00:00:00Z", publisherUpdatedAt: null,
      },
    };
    await route.fulfill({ contentType: "text/event-stream", body: wire([
      { type: "RUN_STARTED", runId: input.runId, threadId: input.threadId },
      { type: "CUSTOM", name: "bc.research.progress", value: { version: 1, phase: "retrieving" } },
      { type: "CUSTOM", name: "bc.research.result", value: {
        version: 1, action: input.action, runId: input.runId, parentRunId: input.parentRunId,
        parentMessageId: input.parentMessageId,
        text: `Synthetic supplemental guidance. [Official page](${sourceUrl})`,
        citations: [citation], notice: "Synthetic supplement; not live verification.",
      } },
      { type: "RUN_FINISHED", runId: input.runId, threadId: input.threadId },
    ]) });
  });
  return { normal, research };
}

for (const action of ["web-check", "corpus-explore"]) {
  test(`explicit ${action} supplements keep the indexed answer and draft`, async ({ page }) => {
    const requests = await fixtures(page);
    await page.goto("/chat");
    const composer = page.getByRole("textbox", { name: "What would you like help with?" });
    await composer.fill("Service BC office information");
    await page.getByRole("button", { name: "Send question", exact: true }).click();
    await expect(page.getByText("Original indexed guidance.", { exact: false })).toBeVisible();
    expect(requests.normal).toHaveLength(1);
    expect(requests.research).toHaveLength(0);
    await composer.fill("Keep this draft");
    await page.locator(".research-supplement summary").click();
    await page.getByRole("button", { name: action === "web-check"
      ? "Check current official information" : "Explore across sources (Preview)", exact: true }).click();
    await expect(page.getByText("Synthetic supplemental guidance.", { exact: false })).toBeVisible();
    await expect(page.getByText("Original indexed guidance.", { exact: false })).toBeVisible();
    await expect(composer).toHaveValue("Keep this draft");
    expect(requests.research).toHaveLength(1);
    expect(Object.keys(requests.research[0]).sort()).toEqual([
      "version", "runId", "threadId", "parentRunId", "parentMessageId", "action", "geography",
    ].sort());
    const audit = await new AxeBuilder({ page }).include(".research-supplement").analyze();
    expect(audit.violations).toEqual([]);
    await composer.fill("Another ordinary question");
    await page.getByRole("button", { name: "Send question", exact: true }).click();
    await expect.poll(() => requests.normal.length).toBe(2);
    expect(requests.research).toHaveLength(1);
    expect(requests.normal[1].forwardedProps.bc.researchRequested).toBeUndefined();
    expect(JSON.stringify(requests.normal[1].messages)).not.toContain("Synthetic supplemental guidance");
  });
}

test("an optional outage leaves the original answer and ordinary Send available", async ({ page }) => {
  const requests = await fixtures(page, true);
  await page.goto("/chat");
  const composer = page.getByRole("textbox", { name: "What would you like help with?" });
  await composer.fill("Service BC office information");
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await page.locator(".research-supplement summary").click();
  await page.getByRole("button", { name: "Check current official information", exact: true }).click();
  await expect(page.getByText("Synthetic provider outage. Your answer is unchanged.")).toBeVisible();
  await expect(page.getByText("Original indexed guidance.", { exact: false })).toBeVisible();
  await composer.fill("Next ordinary question");
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect.poll(() => requests.normal.length).toBe(2);
  expect(requests.research).toHaveLength(1);
});
