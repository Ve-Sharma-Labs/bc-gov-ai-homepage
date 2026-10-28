import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const isAgentResponse = (response) => response.request().method() === "POST"
  && new URL(response.url()).pathname === "/api/agent";
const chatCookie = async (page) => (await page.context().cookies()).find((cookie) => cookie.name === "bc_pilot_session");

function streamEvents(text) {
  return text.split(/\r?\n\r?\n/).flatMap((frame) => {
    const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
    return data ? [JSON.parse(data)] : [];
  });
}

async function captureRealAgentResponses(page) {
  await page.addInitScript(() => {
    const original = window.fetch.bind(window);
    window.realAgentResponses = [];
    window.fetch = async (input, init) => {
      const response = await original(input, init);
      if (String(input) === "/api/agent") {
        const captured = { text: null, error: null };
        window.realAgentResponses.push(captured);
        // Tee the real response without delaying or replacing the stream consumed by the app.
        void response.clone().text().then(
          (text) => { captured.text = text; },
          (error) => { captured.error = error.message; },
        );
      }
      return response;
    };
  });
}

async function installFixtureStream(page) {
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: {
    mode: "foundry", aiConfigured: true, generalChatConfigured: true, retrievalReady: true,
    requestVersions: [1, 2], webIqEnabled: false, transactionsEnabled: false,
    message: "TEST FIXTURE: this browser stream does not invoke a model.",
  } }));
  // Only declared fixture cases replace transport; all other tests use the real local API.
  await page.addInitScript(() => {
    const original = window.fetch.bind(window);
    window.fixtureStreams = [];
    window.fetch = async (input, init) => {
      if (String(input) !== "/api/agent") return original(input, init);
      const request = JSON.parse(init.body);
      const encoder = new TextEncoder();
      return new Response(new ReadableStream({
        start(controller) {
          let closed = false;
          const stream = {
            request,
            aborted: false,
            send(events) {
              if (!closed) for (const event of events) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
            },
            finish() {
              if (closed) return;
              closed = true;
              controller.close();
            },
          };
          window.fixtureStreams.push(stream);
          init.signal.addEventListener("abort", () => {
            stream.aborted = true;
            if (closed) return;
            closed = true;
            controller.error(new DOMException("Fixture response stopped", "AbortError"));
          }, { once: true });
        },
      }), { headers: { "content-type": "text/event-stream" } });
    };
  });
}

async function fixtureReply(page, index, response, text) {
  await expect.poll(() => page.evaluate(() => window.fixtureStreams.length)).toBe(index + 1);
  await page.evaluate(({ index, response, text }) => {
    const stream = window.fixtureStreams[index];
    const { runId, threadId } = stream.request;
    const messageId = `fixture-answer-${index}`;
    stream.send([
      { type: "RUN_STARTED", runId, threadId },
      { type: "CUSTOM", name: "bc.response", value: { version: 1, ...response } },
      { type: "TEXT_MESSAGE_START", messageId, role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId, delta: text },
      { type: "TEXT_MESSAGE_END", messageId },
      { type: "RUN_FINISHED", runId, threadId },
    ]);
    stream.finish();
  }, { index, response, text });
  await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
}

async function home(page) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator(".journey-card")).toHaveCount(7);
  await expect(page.locator(".composer-float")).toHaveAttribute("data-ready", "true");
  await page.evaluate(() => document.fonts.ready);
}

async function theme(page, name) {
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await page.locator(".theme-option").filter({ has: page.getByRole("radio", { name: `${name} theme` }) }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", name.toLowerCase());
  await page.getByRole("button", { name: "Close menu", exact: true }).click();
}

test("homepage enters a full chat page even when AI is unavailable", async ({ page }, testInfo) => {
  await home(page);
  const prompt = "Help me prepare to renew my licence.";
  await page.getByRole("textbox").fill(prompt);
  const responsePromise = page.waitForResponse(isAgentResponse);
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(503);
  const failure = await response.json();
  expect(failure.error.code).toBe("GENERAL_AGENT_NOT_CONFIGURED");
  expect(response.request().postDataJSON().forwardedProps).toEqual({ bc: { version: 2, mode: "general" } });
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.locator(".question-text")).toHaveText(prompt);
  await expect(page.locator(".chat-recovery")).toContainText(failure.error.message);
  await expect.poll(async () => {
    const recovery = await page.locator(".chat-recovery-actions").boundingBox();
    const composer = await page.locator(".composer-float").boundingBox();
    return recovery.y + recovery.height - composer.y;
  }).toBeLessThanOrEqual(0);
  await expect(page.locator(".hero-photograph, .journeys-section, .site-footer")).toHaveCount(0);
  await expect(page.locator(".composer-float")).toHaveClass(/is-chat/);
  await expect(page.getByRole("textbox")).toHaveCount(1);
  await expect(page.getByRole("textbox")).toHaveValue(prompt);
  await expect(page.locator(".footer-credit")).toContainText("Built with love in BC by @VeVarunSharma");
  await expect(page.getByRole("link", { name: "@VeVarunSharma", exact: true })).toHaveAttribute("href", "https://github.com/VeVarunSharma");
  for (const name of ["Light", "Dark"]) {
    await theme(page, name);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath(`chat-unavailable-${name.toLowerCase()}.png`) });
  }
  await page.getByRole("link", { name: "Home", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Hello, British Columbia");
  await page.getByRole("link", { name: "Return to your conversation" }).click();
  await expect(page.locator(".question-text")).toHaveText(prompt);
  await page.reload();
  await expect(page.locator(".message")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "How can we help?" })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveValue("");
});

test("a real v2 greeting is application dialogue without Foundry, Search or a false citation warning", async ({ page, baseURL }) => {
  await captureRealAgentResponses(page);
  await home(page);
  expect(await chatCookie(page)).toBeUndefined();
  const capabilities = await (await page.request.get("/api/capabilities")).json();
  expect(capabilities.generalChatConfigured).toBe(false);
  expect(capabilities.retrievalReady).toBe(false);
  await page.getByRole("textbox").fill("Hello");
  const responsePromise = page.waitForResponse(isAgentResponse);
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("text/event-stream");
  const request = response.request().postDataJSON();
  expect(request.forwardedProps).toEqual({ bc: { version: 2, mode: "general" } });
  await expect.poll(() => page.evaluate(() => typeof window.realAgentResponses[0]?.text)).toBe("string");
  const events = streamEvents(await page.evaluate(() => window.realAgentResponses[0].text));
  const contextIndex = events.findIndex((event) => event.type === "CUSTOM" && event.name === "bc.response");
  expect(contextIndex).toBeGreaterThanOrEqual(0);
  expect(events[contextIndex].value).toEqual({ version: 1, kind: "dialogue", origin: "application" });
  expect(contextIndex).toBeLessThan(events.findIndex((event) => event.type === "TEXT_MESSAGE_START"));
  expect(events.some((event) => event.type === "RUN_FINISHED")).toBe(true);
  expect(events.some((event) => event.type === "RUN_ERROR" || event.name === "annotations")).toBe(false);
  const text = events.filter((event) => event.type === "TEXT_MESSAGE_CONTENT").map((event) => event.delta).join("");
  expect(text).toContain("B.C. government services");
  await expect(page.locator(".message-assistant .answer-content")).toHaveText(text);
  await expect(page.getByRole("heading", { name: "BC service assistant", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "AI answer", exact: true })).toHaveCount(0);
  await expect(page.locator(".answer-warning, .chat-recovery, .answer-sources")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
  await expect(page.getByRole("textbox")).toHaveValue("");
  expect(Boolean(await chatCookie(page))).toBe(true);

  const legacy = await page.request.post("/api/agent", {
    headers: { Origin: baseURL },
    data: {
      threadId: randomUUID(), runId: randomUUID(), state: {}, tools: [], context: [],
      messages: [{ id: randomUUID(), role: "user", content: "Hello" }],
      forwardedProps: { bc: { version: 1 } },
    },
  });
  expect(legacy.status()).toBe(503);
  expect(legacy.headers()["content-type"]).toContain("application/json");
});

test("a legacy clarification becomes application dialogue, not a mandatory pathway gate", async ({ page }) => {
  const requests = [];
  await page.route("**/api/agent", (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ status: 422, json: { error: {
      code: "JOURNEY_REQUIRED", message: "TEST FIXTURE: choose a service to continue.",
    } } });
  });
  await home(page);
  await page.getByRole("textbox").fill("Help me with a service.");
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect(page.getByRole("heading", { name: "BC service assistant", exact: true })).toBeVisible();
  await expect(page.locator(".chat-recovery, .chat-topic-options, .answer-warning")).toHaveCount(0);
  await expect(page.locator(".composer-scope-label")).toHaveText("General B.C. chat");
  await expect(page.getByRole("textbox")).toHaveValue("");
  expect(requests).toHaveLength(1);
  expect(requests[0].forwardedProps.bc).toEqual({ version: 2, mode: "general" });
  await page.getByRole("textbox").fill("Keep this unsent draft");
  await page.getByRole("button", { name: "Choose a guided pathway" }).click();
  await expect(page.locator(".scope-options button")).toHaveCount(8);
  const accessibility = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(accessibility.violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("textbox")).toHaveValue("Keep this unsent draft");
  expect(requests).toHaveLength(1);
  await expect(page.locator(".question-text")).toHaveCount(1);
});

test("optional pathway changes preserve the draft and send explicit v2 scope and model clarification history", async ({ page }) => {
  await installFixtureStream(page);
  await home(page);
  const clarification = "Which B.C. government service or programme would you like help with?";
  await page.getByRole("textbox").fill("Help me with a service.");
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await fixtureReply(page, 0, { kind: "dialogue", origin: "model" }, clarification);
  await expect(page.locator(".answer-warning, .chat-recovery, .chat-topic-options")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "AI assistant", exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.fixtureStreams[0].request.forwardedProps.bc)).toEqual({ version: 2, mode: "general" });

  const draft = "Which identification should I prepare?";
  await page.getByRole("textbox").fill(draft);
  await page.getByRole("button", { name: "Choose a guided pathway" }).click();
  const options = page.locator(".scope-options button");
  await expect(options).toHaveCount(8);
  await options.nth(2).click();
  await expect(page.getByRole("textbox")).toHaveValue(draft);
  await page.getByRole("button", { name: "Change pathway" }).click();
  await options.nth(1).click();
  await expect(page.getByRole("textbox")).toHaveValue(draft);
  await expect(page.getByRole("button", { name: "Clear pathway and use general B.C. chat" })).toBeVisible();
  expect(await page.evaluate(() => window.fixtureStreams.length)).toBe(1);
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.fixtureStreams.length)).toBe(2);
  const pathway = await page.evaluate(() => window.fixtureStreams[1].request);
  expect(pathway.forwardedProps.bc).toEqual({ version: 2, mode: "pathway", journeyId: "licence-renewal" });
  expect(pathway.messages.map(({ role, content }) => ({ role, content }))).toEqual([
    { role: "user", content: "Help me with a service." },
    { role: "assistant", content: clarification },
    { role: "user", content: draft },
  ]);
  await fixtureReply(page, 1, { kind: "handoff", origin: "application" }, "TEST FIXTURE: check [official ICBC guidance](https://www.icbc.com/driver-licensing).");
  await expect(page.locator(".answer-warning")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "BC service assistant", exact: true })).toBeVisible();
  await page.getByRole("textbox").fill("What about provincial taxes?");
  await page.getByRole("button", { name: "Clear pathway and use general B.C. chat" }).click();
  await expect(page.getByRole("textbox")).toHaveValue("What about provincial taxes?");
  await expect(page.getByRole("button", { name: "Choose a guided pathway" })).toBeFocused();
  await expect(page.locator(".composer-scope-label")).toHaveText("General B.C. chat");
  expect(await page.evaluate(() => window.fixtureStreams.length)).toBe(2);
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.fixtureStreams.length)).toBe(3);
  const general = await page.evaluate(() => window.fixtureStreams[2].request);
  expect(general.forwardedProps.bc).toEqual({ version: 2, mode: "general" });
  expect(general.threadId).toBe(pathway.threadId);
  expect(general.messages.filter(({ role }) => role === "assistant").map(({ content }) => content)).toEqual([clarification]);
  await fixtureReply(page, 2, { kind: "dialogue", origin: "model" }, "What would you like to know about that service?");
});

test("a pending real capability response does not block dispatch or replace the first run's owner cookie", async ({ page }) => {
  let release;
  let heldCapabilities;
  const hold = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/capabilities", async (route) => {
    heldCapabilities = await route.fetch();
    await hold;
    await route.fulfill({ response: heldCapabilities });
  });
  try {
    await home(page);
    await expect.poll(() => Boolean(heldCapabilities)).toBe(true);
    expect(heldCapabilities.status()).toBe(200);
    expect(heldCapabilities.headers()["set-cookie"]).toBeUndefined();
    expect(await chatCookie(page)).toBeUndefined();
    const responsePromise = page.waitForResponse(isAgentResponse);
    await page.getByRole("textbox").fill("Hello");
    await page.getByRole("button", { name: "Send question", exact: true }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.locator(".question-text")).toHaveText("Hello");
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const request = response.request().postDataJSON();
    expect(request.forwardedProps.bc).toEqual({ version: 2, mode: "general" });
    await expect(page.locator(".message-assistant")).toContainText("B.C. government services");
    const owner = await chatCookie(page);
    expect(Boolean(owner)).toBe(true);
    const capabilityResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/capabilities");
    release();
    await capabilityResponse;
    expect((await chatCookie(page))?.value === owner.value, "A late metadata response must not replace the run owner").toBe(true);
    await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
    const cancellation = await page.evaluate(async (runId) => {
      const result = await fetch(`/api/runs/${runId}/cancel`, { method: "POST" });
      return { status: result.status, body: await result.json() };
    }, request.runId);
    expect(cancellation.status).toBe(409);
    expect(cancellation.body.error.code).toBe("RUN_FINISHED");
    await expect(page.locator(".chat-recovery, .answer-warning")).toHaveCount(0);
  } finally {
    release();
  }
});

test("the real client consumes incremental fixture events before terminal completion", async ({ page }, testInfo) => {
  await installFixtureStream(page);
  await home(page);
  await page.getByRole("textbox").fill("A synthetic streaming test question.");
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect.poll(() => page.evaluate(() => window.fixtureStreams.length)).toBe(1);
  expect(await page.evaluate(() => window.fixtureStreams[0].request.forwardedProps.bc)).toEqual({ version: 2, mode: "general" });
  await page.evaluate(() => window.fixtureStreams[0].send([
    { type: "RUN_STARTED", runId: window.fixtureStreams[0].request.runId, threadId: window.fixtureStreams[0].request.threadId },
    { type: "CUSTOM", name: "status", value: { version: 1, phase: "thinking" } },
  ]));
  await expect(page.locator(".run-progress")).toHaveText("Thinking...");
  await expect(page.locator(".run-progress")).toHaveCount(1);
  await expect(page.locator(".message-assistant")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("fixture-chat-thinking.png") });
  await page.evaluate(() => window.fixtureStreams[0].send([
    { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "grounded", origin: "model" } },
    { type: "TEXT_MESSAGE_START", messageId: "test-answer", role: "assistant" },
    { type: "CUSTOM", name: "annotations", value: { messageId: "test-answer", annotations: [
      { url: "https://www.icbc.com/driver-licensing/visit-a-dl-office", title: "TEST FIXTURE official reference", publisher: "ICBC", documentId: "fixture", documentVersion: "v1" },
    ] } },
    { type: "TEXT_MESSAGE_CONTENT", messageId: "test-answer", delta: "TEST FIXTURE: this first section arrived before the answer was complete.\n\n" },
  ]));
  await expect(page.locator(".answer-content")).toContainText("first section arrived");
  await expect(page.getByRole("button", { name: "Stop answer" })).toBeVisible();
  await expect(page.locator(".message-state, .run-progress")).toHaveCount(0);
  const sourceButton = page.getByRole("button", { name: "1 source", exact: true });
  if (testInfo.project.name === "mobile") await sourceButton.tap();
  else await sourceButton.click();
  await expect(page.locator(".answer-sources-trigger")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("dialog", { name: "Sources for this answer" })).toContainText("TEST FIXTURE official reference");
  await page.getByRole("button", { name: "Close sources" }).click();
  await expect(sourceButton).toBeFocused();
  await sourceButton.press("Enter");
  await expect(page.getByRole("dialog", { name: "Sources for this answer" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sourceButton).toBeFocused();
  await page.evaluate(() => window.fixtureStreams[0].send([
    { type: "TEXT_MESSAGE_CONTENT", messageId: "test-answer", delta: "TEST FIXTURE: this second section arrived later." },
    { type: "TEXT_MESSAGE_END", messageId: "test-answer" },
  ]));
  await expect(page.locator(".answer-content")).toContainText("second section arrived later");
  await expect(page.getByRole("button", { name: "Stop answer" })).toBeVisible();
  await page.evaluate(() => window.fixtureStreams[0].send([
    { type: "RUN_FINISHED", runId: window.fixtureStreams[0].request.runId, threadId: window.fixtureStreams[0].request.threadId },
  ]));
  await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
  await expect(page.locator(".composer-float [role='status']")).toHaveText("Answer complete. Review the sources before acting.");
  await page.evaluate(() => {
    window.fixtureStreams[0].send([
      { type: "CUSTOM", name: "annotations", value: { messageId: "test-answer", annotations: [
        { url: "https://www.icbc.com/driver-licensing", title: "TEST FIXTURE late reference", publisher: "ICBC" },
      ] } },
    ]);
    window.fixtureStreams[0].finish();
  });
  await expect(page.getByRole("button", { name: "2 sources", exact: true })).toBeVisible();
  await expect(page.locator(".answer-warning")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("fixture-chat-complete.png") });
});

test.describe("document provenance in a B.C. timezone", () => {
  test.use({ timezoneId: "America/Vancouver" });

  test("declared legal metadata keeps effective bounds and consolidation separate without day shifts or whole-site claims", async ({ page }, testInfo) => {
    await installFixtureStream(page);
    await home(page);
    await page.getByRole("textbox").fill("TEST FIXTURE: show legal document provenance.");
    await page.getByRole("button", { name: "Send question", exact: true }).click();
    await expect.poll(() => page.evaluate(() => window.fixtureStreams.length)).toBe(1);
    const metadata = {
      version: 1, sourceIds: ["bc-laws"], documentType: "legal", language: "en-CA",
      contentHash: "a".repeat(64), extractionHash: "b".repeat(64), reviewHash: "c".repeat(64),
      rightsReviewId: "TEST-FIXTURE-rights-review", rightsHash: "d".repeat(64),
      legalStatus: "in-force", effectiveFrom: "2026-10-24", effectiveTo: "2027-01-01",
      consolidationDate: "2026-10-25", repealedAt: null, legalSectionId: "section-12", isHistorical: false,
    };
    await page.evaluate((metadata) => {
      const stream = window.fixtureStreams[0];
      const { runId, threadId } = stream.request;
      stream.send([
        { type: "RUN_STARTED", runId, threadId },
        { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "grounded", origin: "model" } },
        { type: "TEXT_MESSAGE_START", messageId: "legal-fixture", role: "assistant" },
        { type: "CUSTOM", name: "annotations", value: { messageId: "legal-fixture", annotations: [{
          sourceId: "bc-laws", url: "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/03075_01",
          title: "TEST FIXTURE legal reference", publisher: "BC Laws", checkedAt: "2026-10-24",
          publisherUpdatedAt: null, metadata,
        }] } },
        { type: "TEXT_MESSAGE_CONTENT", messageId: "legal-fixture", delta: "TEST FIXTURE: this answer carries document-level provenance." },
        { type: "TEXT_MESSAGE_END", messageId: "legal-fixture" },
        { type: "RUN_FINISHED", runId, threadId },
      ]);
      stream.finish();
    }, metadata);
    await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
    const sourceButton = page.getByRole("button", { name: "1 source", exact: true });
    if (testInfo.project.name === "mobile") await sourceButton.tap();
    else await sourceButton.click();
    const dialog = page.getByRole("dialog", { name: "Sources for this answer" });
    await dialog.locator(".source-card > summary").click();
    for (const [label, value] of [
      ["Effective from (inclusive)", "2026-10-24"],
      ["Effective to (exclusive)", "2027-01-01"],
      ["Consolidation date", "2026-10-25"],
    ]) {
      await expect(dialog.getByText(label, { exact: true }).locator("..").locator("time")).toHaveText(value);
    }
    await expect(dialog.getByText("Checked", { exact: true }).locator("..").locator("dd")).toHaveText("Oct 24, 2026");
    await expect(dialog.getByText("Historical snapshot", { exact: true }).locator("..").locator("dd")).toHaveText("No");
    await dialog.getByText("Review provenance", { exact: true }).click();
    await expect(dialog.getByText(/not whole-site coverage/)).toBeVisible();
    await expect(dialog.getByText("TEST-FIXTURE-rights-review", { exact: true })).toBeVisible();
    await expect(dialog.locator(".source-provenance code")).toHaveCount(4);
    expect(await dialog.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
    const accessibility = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(accessibility.violations, JSON.stringify(accessibility.violations, null, 2)).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("fixture-source-provenance.png") });
  });
});

test("Stop keeps the restored prompt without implicitly submitting another run", async ({ page }) => {
  const cancellations = [];
  await installFixtureStream(page);
  await page.route("**/api/runs/*/cancel", (route) => {
    const runId = new URL(route.request().url()).pathname.split("/").at(-2);
    cancellations.push(runId);
    return route.fulfill({ status: 202, json: { runId, status: "cancelling" } });
  });
  await home(page);
  const prompt = "TEST FIXTURE: Stop this answer.";
  await page.getByRole("textbox").fill(prompt);
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.fixtureStreams.length)).toBe(1);
  await page.evaluate(() => window.fixtureStreams[0].send([
    { type: "RUN_STARTED", runId: window.fixtureStreams[0].request.runId, threadId: window.fixtureStreams[0].request.threadId },
    { type: "CUSTOM", name: "status", value: { version: 1, phase: "thinking" } },
  ]));
  await expect(page.locator(".run-progress")).toHaveText("Thinking...");
  await page.getByRole("button", { name: "Stop answer" }).click();
  await expect(page.locator(".chat-recovery")).toContainText("Response stopped");
  await expect(page.getByRole("textbox")).toHaveValue(prompt);
  expect(await page.evaluate(() => window.fixtureStreams.length)).toBe(1);
  expect(await page.evaluate(() => window.fixtureStreams[0].aborted)).toBe(true);
  await expect.poll(() => cancellations.length).toBe(1);
  expect(cancellations[0]).toBe(await page.evaluate(() => window.fixtureStreams[0].request.runId));
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.fixtureStreams.length)).toBe(2);
  await page.getByRole("button", { name: "Stop answer" }).click();
  await expect(page.locator(".chat-recovery")).toContainText("Response stopped");
  expect(await page.evaluate(() => window.fixtureStreams.length)).toBe(2);
  await expect.poll(() => cancellations.length).toBe(2);
  const requests = await page.evaluate(() => window.fixtureStreams.map((stream) => stream.request));
  expect(requests.every((request) => request.forwardedProps.bc.version === 2 && request.forwardedProps.bc.mode === "general" && !request.forwardedProps.bc.journeyId)).toBe(true);
  expect(cancellations[1]).toBe(requests[1].runId);
  expect(cancellations[1]).not.toBe(cancellations[0]);
  await expect(page.locator(".question-text")).toHaveCount(1);
});
