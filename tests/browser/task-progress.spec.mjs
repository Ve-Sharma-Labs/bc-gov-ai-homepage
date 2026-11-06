import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("the configured conversation handles an immediate Send before capabilities arrive", async ({ page }) => {
  const requests = [];
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/capabilities", async (route) => {
    await pending;
    await route.fulfill({ json: {
      mode: "foundry", aiConfigured: true, generalChatConfigured: true, retrievalReady: false,
      conversationAvailable: true, conversationAgentReady: true, taskAssistanceAvailable: true,
      requestVersions: [1, 2, 3, 5], webIqEnabled: false, transactionsEnabled: false,
      syntheticContextAvailable: false, message: "Delayed capability fixture; no model is called.",
    } });
  });
  await page.route("**/api/agent", (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ status: 503, json: {
      error: { code: "CONVERSATION_AGENT_NOT_CONFIGURED", message: "Synthetic transport fixture." },
    } });
  });
  try {
    await page.goto("/chat");
    const composer = page.getByRole("textbox", { name: "What would you like help with?" });
    await composer.fill("please help me renew my drivers license");
    await page.getByRole("button", { name: "Send question", exact: true }).click();
    await expect.poll(() => requests.length).toBe(1);
    expect(requests[0].forwardedProps.bc.version).toBe(5);
    expect(requests[0].forwardedProps.bc.conversation).toMatchObject({
      revision: 0, noticeVersion: "ai-conversation-v1", shareContext: false,
    });
    await expect(composer).toHaveValue("please help me renew my drivers license");
  } finally {
    release();
  }
  await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
  expect(requests).toHaveLength(1);
});

test("processing and evaluation notices stay in optional Details", async ({ page }, testInfo) => {
  const processing = "Your messages are processed by AI in Azure. No ID numbers, credentials, documents, or medical histories.";
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: {
    mode: "foundry", aiConfigured: true, generalChatConfigured: true, retrievalReady: true,
    conversationAvailable: true, conversationAgentReady: true, taskAssistanceAvailable: true,
    requestVersions: [1, 2, 3, 5, 6], webIqEnabled: false, transactionsEnabled: false,
    syntheticContextAvailable: false, localEvidenceEvaluation: true, message: "Explicit UI fixture.",
  } }));
  for (const path of ["/", "/chat"]) {
    await page.goto(path);
    const details = path === "/" ? page.locator(".home-conversation-details > summary")
      : page.getByRole("button", { name: "Details", exact: true });
    await expect(details).toBeVisible();
    await expect(page.locator(".composer-ai-privacy")).toHaveCount(0);
    await expect(page.getByText(processing, { exact: true })).not.toBeVisible();
    await expect(page.getByText("Local evaluation only.", { exact: true })).not.toBeVisible();
    const composer = page.getByRole("textbox", { name: "What would you like help with?" });
    await composer.fill("Keep this draft");
    await details.click();
    await expect(page.locator(".conversation-details-content").getByText(processing, { exact: true })).toBeVisible();
    await expect(page.getByText("Local evaluation only.", { exact: true })).toBeVisible();
    if (path === "/") await details.click();
    else await page.getByRole("button", { name: "Close details", exact: true }).click();
    await expect(page.getByText("Local evaluation only.", { exact: true })).not.toBeVisible();
    await expect(composer).toHaveValue("Keep this draft");
    await expect(composer).toBeVisible();
  }
  await page.screenshot({ path: testInfo.outputPath("clean-composer.png"), fullPage: true });
});

test("version-six negotiation and official EI link rendering are explicit fixtures", async ({ page }) => {
  const requests = [];
  await page.route("**/api/capabilities", (route) => {
    expect(route.request().headers()["x-bc-client-version"]).toBe("6");
    return route.fulfill({ json: {
      mode: "foundry", aiConfigured: true, generalChatConfigured: true, retrievalReady: true,
      conversationAvailable: true, conversationAgentReady: true, taskAssistanceAvailable: true,
      requestVersions: [1, 2, 3, 5, 6], webIqEnabled: false, transactionsEnabled: false,
      syntheticContextAvailable: false, message: "Version-six transport fixture; no real model or source publication.",
    } });
  });
  await page.route("**/api/agent", (route) => {
    const input = route.request().postDataJSON();
    requests.push(input);
    const events = [
      { type: "RUN_STARTED", runId: input.runId, threadId: input.threadId },
      { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "handoff", origin: "application", decisionOrigin: "application" } },
      { type: "TEXT_MESSAGE_START", messageId: "fixture-answer", role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "fixture-answer", delta: "Explicit rendering fixture: [Official EI guidance](https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit.html). No application was submitted." },
      { type: "TEXT_MESSAGE_END", messageId: "fixture-answer" },
      { type: "CUSTOM", name: "bc.conversation", value: {
        version: 1, noticeVersion: "ai-conversation-v1", threadId: input.threadId, revision: 1,
        expiresAt: "2099-01-01T00:00:00Z", goal: "job-loss", goalLabel: "Employment Insurance (EI)",
        subject: "you", phase: "handoff", questionCount: 0, question: null, facts: [],
        shareContext: false, journeyId: null, suggestedDemoId: null, limitation: "source-coverage", decisionOrigin: "application",
      } },
      { type: "CUSTOM", name: "bc.task", value: { version: 1, threadId: input.threadId, revision: 1, task: null, step: null, handoffs: [], sources: [], guidance: "" } },
      { type: "RUN_FINISHED", runId: input.runId, threadId: input.threadId },
    ];
    return route.fulfill({ contentType: "text/event-stream", body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("") });
  });
  await page.goto("/chat");
  await expect(page.getByRole("button", { name: "Details", exact: true })).toBeVisible();
  await page.getByRole("textbox").fill("I want to claim EI");
  await page.getByRole("button", { name: "Send question", exact: true }).click();
  await expect(page.getByRole("link", { name: /Official EI guidance/ })).toHaveAttribute(
    "href", "https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit.html",
  );
  expect(requests).toHaveLength(1);
  expect(requests[0].forwardedProps.bc.version).toBe(6);
  await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /finding work/i })).toHaveCount(0);
});

  test("starter questions fill the one composer without sending or replacing a draft silently", async ({ page }, testInfo) => {
    const prompts = [
      "I need to renew my drivers license",
      "I need to apply for guardianship",
      "I need to apply for disability",
      "I just lost my job, what do I do?",
    ];
    let sent = 0;
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.route("**/api/capabilities", (route) => route.fulfill({ json: {
      mode: "foundry", aiConfigured: true, generalChatConfigured: true, retrievalReady: true,
      conversationAvailable: true, conversationAgentReady: true, taskAssistanceAvailable: true,
      requestVersions: [1, 2, 3, 5], webIqEnabled: false, transactionsEnabled: false,
      syntheticContextAvailable: false, message: "Explicit UI fixture; no model is called.",
    } }));
    await page.route("**/api/agent", (route) => {
      sent++;
      return route.fulfill({ status: 500, body: "Starter selection must not submit." });
    });
    for (const path of ["/", "/chat"]) {
      await page.goto(path);
      await expect(path === "/" ? page.locator(".home-conversation-details > summary")
        : page.getByRole("button", { name: "Details", exact: true })).toBeVisible();
      if (path === "/") {
        await expect(page.locator(".photo-story .conversation-starters")).toHaveCount(0);
        await expect(page.locator(".hero-stage > .conversation-starters")).toBeVisible();
      }
      const input = page.getByRole("textbox", { name: "What would you like help with?" });
      const url = page.url();
      for (const prompt of prompts) {
        await input.fill("");
        await page.getByRole("button", { name: prompt, exact: true }).click();
        await expect(input).toHaveValue(prompt);
        await expect(input).toBeFocused();
        expect(page.url()).toBe(url);
        expect(sent).toBe(0);
      }
      await input.fill("My unfinished question");
      await page.getByRole("button", { name: prompts[0], exact: true }).click();
      await expect(input).toHaveValue("My unfinished question");
      await page.getByRole("button", { name: "Keep my draft" }).click();
      await expect(input).toHaveValue("My unfinished question");
      await page.getByRole("button", { name: prompts[1], exact: true }).click();
      await page.getByRole("button", { name: "Replace draft" }).click();
      await expect(input).toHaveValue(prompts[1]);
      await expect(input).toBeFocused();
      expect(sent).toBe(0);
    }
    for (const theme of ["light", "dark"]) {
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      expect(results.violations, JSON.stringify(results.violations)).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      await page.screenshot({ path: testInfo.outputPath(`chat-starters-${theme}.png`), fullPage: true });
    }
  });

  test("the reported outside-BC chat continues entirely through typed replies", async ({ page }) => {
    const requests = [];
    const texts = [
      "Of course. Is it a B.C.-issued licence?",
      "Thanks - it was issued elsewhere. Renew with the original issuer or get a B.C. licence?",
      "Use the original issuer's official renewal service. I won't substitute B.C.'s renewal rules.",
    ];
    await page.route("**/api/capabilities", (route) => route.fulfill({ json: {
      mode: "foundry", aiConfigured: true, generalChatConfigured: true, retrievalReady: true,
      conversationAvailable: true, conversationAgentReady: true, taskAssistanceAvailable: true,
      requestVersions: [1, 2, 3, 5], webIqEnabled: false, transactionsEnabled: false,
      syntheticContextAvailable: false, message: "Explicit UI fixture; no model is called.",
    } }));
    await page.route("**/api/agent", (route) => {
      const request = route.request().postDataJSON();
      requests.push(request);
      const turn = requests.length;
      expect(turn).toBeLessThanOrEqual(3);
      const summary = {
        version: 1, noticeVersion: "ai-conversation-v1", threadId: request.threadId, revision: turn,
        expiresAt: "2099-01-01T00:00:00Z", goal: "licence-renewal", goalLabel: "Renew with the original issuer",
        subject: "you", phase: turn < 3 ? "clarify" : "handoff", questionCount: Math.min(turn, 2),
        question: turn < 3 ? {
          id: turn === 1 ? "issuer-question" : "route-question",
          kind: turn === 1 ? "context" : "intent", factKey: turn === 1 ? "licence-jurisdiction" : null,
          text: texts[turn - 1], reason: "The original issuer and B.C. have different services.",
          choices: turn === 1 ? ["Yes, issued in B.C.", "Issued somewhere else"] : ["Renew with the original issuer", "Get a B.C. licence"],
          candidates: [], personal: false,
        } : null,
        facts: turn > 1 ? [{
          key: "licence-jurisdiction", label: "Licence issuer", value: "other", displayValue: "Issued somewhere else",
          status: "provided", provenance: "citizen-answer", subject: "you", personal: false,
        }] : [],
        shareContext: false, journeyId: null, suggestedDemoId: null,
        limitation: turn < 3 ? "missing-context" : "source-coverage", decisionOrigin: "application",
      };
      const id = `answer-${turn}`;
      const events = [
        { type: "RUN_STARTED", runId: request.runId, threadId: request.threadId },
        { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "dialogue", origin: "application", decisionOrigin: "application" } },
        { type: "TEXT_MESSAGE_START", messageId: id, role: "assistant" },
        { type: "TEXT_MESSAGE_CONTENT", messageId: id, delta: texts[turn - 1] },
        { type: "TEXT_MESSAGE_END", messageId: id },
        { type: "CUSTOM", name: "bc.conversation", value: summary },
        { type: "CUSTOM", name: "bc.task", value: { version: 1, threadId: request.threadId, revision: turn, task: null, step: null, sources: [], handoffs: [], guidance: "" } },
        { type: "RUN_FINISHED", runId: request.runId, threadId: request.threadId },
      ];
      return route.fulfill({ contentType: "text/event-stream", body: events.map((item) => `data: ${JSON.stringify(item)}\n\n`).join("") });
    });
    await page.goto("/chat");
    await expect(page.getByRole("button", { name: "Details", exact: true })).toBeVisible();
    for (const [index, text] of [
      "hi please help me renew my drivers license",
      "Issued somewhere else",
      "how do i renrew?",
    ].entries()) {
      await page.getByRole("textbox").fill(text);
      await page.getByRole("button", { name: "Send question", exact: true }).click();
      await expect(page.locator(".message-assistant")).toHaveCount(index + 1);
      await expect(page.locator(".message-assistant").last()).toContainText(texts[index]);
      await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
      await expect(page.locator(".conversation .discovery-question")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Issued somewhere else" })).toHaveCount(0);
    }
    expect(requests[1].forwardedProps.bc.conversation.questionId).toBe("issuer-question");
    expect(requests[2].forwardedProps.bc.conversation.questionId).toBe("route-question");
    await expect(page.locator(".message-assistant").filter({ hasText: "Is it a B.C.-issued licence?" })).toHaveCount(1);
    await page.getByRole("button", { name: "Details", exact: true }).click();
    await page.getByText("What I understand", { exact: true }).click();
    await expect(page.locator(".ai-context-summary")).toContainText("Issued somewhere else");
    await page.getByRole("button", { name: "Close details" }).focus();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "Details", exact: true })).toBeFocused();
    await expect(page.getByRole("region", { name: "Conversation details" })).toHaveCount(0);
  });

for (const retrievalReady of [true, false]) {
test(`renewal advances without guide loops (${retrievalReady ? "current" : "expired"} sources)`, async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const catalog = await (await page.request.get("/api/catalog")).json();
  const journey = catalog.journeys.find((item) => item.id === "licence-renewal");
  const requests = [];
  const controls = [];
  let summary;
  let task;
  const snapshot = () => ({
    version: 1, threadId: summary.threadId, revision: summary.revision, task: task ?? null,
    step: task ? journey.steps.find((step) => step.id === task.activeStepId) : null,
    handoffs: task ? journey.handoffs : [], sources: task ? catalog.sources : [],
    guidance: task?.activeStepId === "find-licensing-office"
      ? "Let's find an office that offers licensing. Which city or town would you like to visit?"
      : "Check one primary and one secondary piece of accepted ID using ICBC's official list.",
  });
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: {
    mode: "foundry", aiConfigured: true, generalChatConfigured: true, retrievalReady,
    conversationAvailable: true, conversationAgentReady: true, taskAssistanceAvailable: true,
    requestVersions: [1, 2, 3, 5], webIqEnabled: false, transactionsEnabled: false,
    syntheticContextAvailable: false, message: "Explicit UI fixture; no model is called.",
  } }));
  await page.route("**/api/conversation/control", (route) => {
    const input = route.request().postDataJSON();
    controls.push(input);
    summary = { ...summary, revision: summary.revision + 1, shareContext: input.shareContext ?? summary.shareContext };
    return route.fulfill({ json: {
      summary, task: snapshot(), notice: input.shareContext ? "Optional context sharing is on." : "Optional context sharing is off.",
    } });
  });
  await page.route("**/api/agent", (route) => {
    const request = route.request().postDataJSON();
    requests.push(request);
    const text = request.messages.at(-1).content;
    const first = requests.length === 1;
    summary = {
      version: 1, noticeVersion: "ai-conversation-v1", threadId: request.threadId,
      revision: request.forwardedProps.bc.conversation.revision + 1, expiresAt: "2099-01-01T00:00:00Z",
      goal: "licence-renewal", goalLabel: "Licence renewal", subject: "you",
      phase: first ? "clarify" : "guide", questionCount: 1,
      question: first ? {
        id: "issuer-question", kind: "context", factKey: "licence-jurisdiction", text: "Is it a B.C.-issued licence?",
        reason: "Choose the right guide.", choices: ["Yes, issued in B.C.", "Issued somewhere else"],
        candidates: [], personal: false,
      } : null,
      facts: [], shareContext: request.forwardedProps.bc.conversation.shareContext,
      journeyId: first ? null : journey.id, suggestedDemoId: null,
      limitation: first ? "missing-context" : "none", decisionOrigin: "model",
    };
    if (!first && !task) task = {
      id: "task-renewal-fixture", journeyId: journey.id, catalogVersion: "a".repeat(64),
      stepVersions: Object.fromEntries(journey.steps.map((step) => [step.id, "a".repeat(64)])),
      stepIds: journey.steps.map((step) => step.id), activeStepId: "prepare-identification",
      reviewedStepIds: [], skippedStepIds: [], phase: "preparing", waitingFor: "readiness",
      lastAction: "continue", municipality: null, service: "icbc-licensing",
    };
    if (/I have my ID/i.test(text)) task = {
      ...task, activeStepId: "find-licensing-office", reviewedStepIds: ["prepare-identification"],
      waitingFor: "municipality", lastAction: "reviewed",
    };
    const taskData = snapshot();
    const message = first ? "Of course. Is it a B.C.-issued licence?"
      : (/helping/i.test(text) ? "Yes - let's move this forward. " : "") + taskData.guidance
        + "\n\n[ICBC accepted identification](https://www.icbc.com/driver-licensing/visit-dl-office/Accepted-ID)";
    const events = [
      { type: "RUN_STARTED", runId: request.runId, threadId: request.threadId },
      { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "handoff", origin: "application", decisionOrigin: "model" } },
      { type: "TEXT_MESSAGE_START", messageId: `answer-${requests.length}`, role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: `answer-${requests.length}`, delta: message },
      { type: "TEXT_MESSAGE_END", messageId: `answer-${requests.length}` },
      { type: "CUSTOM", name: "bc.task", value: taskData },
      { type: "CUSTOM", name: "bc.conversation", value: summary },
      ...(!first ? [{ type: "CUSTOM", name: "bc.artifact", value: {
        version: 1, id: "task-task-renewal-fixture", kind: "preparation", journey,
        sources: catalog.sources, transactionsEnabled: false,
      } }] : []),
      { type: "RUN_FINISHED", runId: request.runId, threadId: request.threadId },
    ];
    return route.fulfill({ contentType: "text/event-stream", body: events.map((item) => `data: ${JSON.stringify(item)}\n\n`).join("") });
  });
  const send = async (text) => {
    const count = requests.length;
    await page.getByRole("textbox", { name: "What would you like help with?" }).fill(text);
    await page.getByRole("button", { name: "Send question", exact: true }).click();
    await expect.poll(() => requests.length).toBe(count + 1);
    await expect(page.getByRole("button", { name: "Stop answer" })).toHaveCount(0);
  };
  await page.goto("/chat");
  await expect(page.getByRole("button", { name: "Details", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /Use personal details/ })).toHaveCount(0);
  await send("please help me renew my drivers license");
  expect(requests[0].forwardedProps.bc.version).toBe(5);
  await expect(page.getByRole("button", { name: "Yes, issued in B.C." })).toHaveCount(0);
  await send("Yes, issued in B.C.");
  await expect(page.locator(".message-assistant").last()).toContainText("primary and one secondary");
  await expect(page.getByText("Full preparation guide", { exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "Details", exact: true }).click();
  await expect(page.getByText("Full preparation guide", { exact: true })).toBeVisible();
  const before = await page.locator(".message").count();
  await page.getByRole("checkbox", { name: /Use personal details/ }).click();
  await expect(page.getByRole("checkbox", { name: /Use personal details/ })).toBeChecked();
  await expect(page.locator(".chat-context-notice")).toHaveText("Optional context sharing is on.");
  expect(controls).toHaveLength(1);
  expect(requests).toHaveLength(2);
  await expect(page.locator(".message")).toHaveCount(before);
  await page.getByRole("button", { name: "Close details" }).click();
  await send("so plesae help me renew my BC DL please");
  await send("halllllo are you helping");
  await expect(page.locator(".message-assistant").last()).toContainText("move this forward");
  await expect(page.locator(".message-assistant").last()).not.toContainText("What would you like help figuring out");
  await expect(page.getByText("Full preparation guide", { exact: true })).toHaveCount(1);
  await send("I have my ID");
  await expect(page.locator(".message-assistant").last()).toContainText("city or town");
  await expect(page.getByRole("region", { name: "Current preparation step" })).toHaveCount(0);
  await page.getByRole("button", { name: "Details", exact: true }).click();
  await expect(page.locator(".task-progress-label")).toContainText("1 of 4");
  await page.getByText("Full preparation guide", { exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Check your two pieces of accepted ID" })).toBeChecked();
  await page.getByText("Full preparation guide", { exact: true }).click();
  await page.getByRole("button", { name: "Close details" }).click();
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
    await page.locator(".message-assistant").last().scrollIntoViewIfNeeded();
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(result.violations, JSON.stringify(result.violations)).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath(`task-progress-${theme}.png`), fullPage: true });
  }
});
}
