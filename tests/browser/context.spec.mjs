import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {
  completeContextFixture,
  contextEvaluationCases,
  installContextFixtureStream,
} from "./fixtures/context-demo.mjs";

const personaName = {
  "maya-caregiver": "Maya",
  "alex-disability-support": "Alex",
  "sam-job-loss": "Sam",
};
const scopeLabel = {
  "identity.read": "Identity and B.C. residency",
  "household.read": "Household and dependants",
  "employment.read": "Employment and income status",
  "disability-caregiving.read": "Disability or caregiving circumstances",
  "existing-programs.read": "Existing programs and applications",
  "region-preferences.read": "Region and service preferences",
};

async function openHome(page) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator(".journey-card")).toHaveCount(7);
  await expect(page.locator(".composer-float")).toHaveAttribute("data-ready", "true");
}

async function activatePersona(page, evaluationCase) {
  const name = personaName[evaluationCase.personaId];
  const selector = page.getByRole("button", {
    name: "Choose a synthetic demo persona",
  });
  await selector.click();
  const chooser = page.getByRole("dialog", { name: "Choose conversation context" });
  await chooser.getByRole("button", { name: new RegExp(`${name} synthetic`, "i") }).click();
  const consent = page.getByRole("dialog", { name: `Choose what ${name} may share` });
  for (const scope of evaluationCase.requiredScopes) {
    const checkbox = consent.getByRole("checkbox", { name: new RegExp(scopeLabel[scope]) });
    await expect(checkbox).toBeChecked();
    await expect(checkbox).toBeDisabled();
  }
  for (const scope of evaluationCase.optionalScopes) {
    const checkbox = consent.getByRole("checkbox", { name: new RegExp(scopeLabel[scope]) });
    await expect(checkbox).toBeChecked();
    await expect(checkbox).toBeEnabled();
  }
  await expect(consent.getByRole("textbox")).toHaveCount(0);
  await expect(consent.getByRole("button", { name: /^Submit$/i })).toHaveCount(0);
  await consent.getByRole("button", { name: "Use selected context" }).click();
  await expect(page.locator(".synthetic-context-banner")).toContainText(
    "Synthetic citizen context",
  );
  await expect(page.locator(".synthetic-context-banner")).toContainText(
    "no real government records are accessed",
  );
}

async function sendQuestion(page, question) {
  await page.getByRole("textbox", { name: "What would you like help with?" }).fill(question);
  await page.getByRole("button", { name: "Send question" }).click();
}

async function startOver(page) {
  await page.getByRole("button", { name: "Start over" }).click();
  const dialog = page.getByRole("dialog", { name: "Start fresh?" });
  await dialog.getByRole("button", { name: "Start over" }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function chooseTheme(page, theme) {
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  const label = `${theme[0].toUpperCase()}${theme.slice(1)} theme`;
  await page.locator(".theme-option").filter({
    has: page.getByRole("radio", { name: label }),
  }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await page.getByRole("button", { name: "Close menu", exact: true }).click();
}

for (const evaluationCase of contextEvaluationCases) {
  test(`anonymous versus contextual fixture comparison: ${evaluationCase.id}`, async ({
    page,
  }) => {
    await installContextFixtureStream(page);
    await openHome(page);

    await sendQuestion(page, evaluationCase.sampleQuestion);
    await completeContextFixture(
      page,
      0,
      `TEST FIXTURE: anonymous mode leaves ${evaluationCase.expected.anonymousRuleClarifyingQuestions} deterministic fact questions explicit.`,
    );
    const anonymousRequest = await page.evaluate(
      () => window.contextFixtureRequests[0],
    );
    expect(anonymousRequest.request.forwardedProps).toEqual({
      bc: { version: 2, mode: "general" },
    });
    await expect(page.locator(".context-artifact")).toHaveCount(0);
    await expect(page.locator(".program-match")).toHaveCount(
      evaluationCase.expected.anonymousProgramArtifacts,
    );
    await expect(page.getByText("Application or intake preview")).toHaveCount(0);

    await startOver(page);
    await activatePersona(page, evaluationCase);
    await sendQuestion(page, evaluationCase.sampleQuestion);
    await completeContextFixture(
      page,
      1,
      `TEST FIXTURE: contextual mode used ${evaluationCase.expected.contextualContextFactsUsed} reviewed synthetic facts without scoring model quality.`,
    );
    const contextualRequest = await page.evaluate(
      () => window.contextFixtureRequests[1],
    );
    expect(contextualRequest.request.forwardedProps).toEqual({
      bc: { version: 3, mode: "contextual-demo" },
    });
    expect(contextualRequest.headers["x-bc-context-page"]).toMatch(
      /^[A-Za-z0-9-]{20,128}$/u,
    );
    expect(contextualRequest.request.context).toEqual([]);
    expect(contextualRequest.request.state).toEqual({});
    expect(contextualRequest.request.tools).toEqual([]);
    expect(JSON.stringify(contextualRequest.request)).not.toMatch(
      /employment\.status|synthetic-government-record|personaId|contextSummary/iu,
    );

    for (const name of [
      "Synthetic context summary",
      "Synthetic program screening",
      "Synthetic application or intake preview",
      "Synthetic consent checkpoint",
      "Synthetic audit receipt",
    ]) {
      await expect(page.getByRole("region", { name })).toBeVisible();
    }
    await expect(page.locator(".program-match")).toHaveCount(
      evaluationCase.expected.contextualProgramArtifacts,
    );
    await expect(page.getByText("Application or intake preview")).toBeVisible();
    await expect(page.getByText("Transfer in this demo")).toBeVisible();
    await expect(page.getByText("None", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Submit$/i })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /^Submit$/i })).toHaveCount(0);
    await expect(page.getByText(/confirmation number/i)).toHaveCount(0);
  });
}

test("selector, consent, drawer and active-run consent change are keyboard safe", async ({
  page,
}) => {
  await installContextFixtureStream(page);
  await openHome(page);
  const alex = contextEvaluationCases.find(
    (item) => item.personaId === "alex-disability-support",
  );
  const selector = page.getByRole("button", {
    name: "Choose a synthetic demo persona",
  });
  await selector.focus();
  await page.keyboard.press("Enter");
  const chooser = page.getByRole("dialog", { name: "Choose conversation context" });
  await expect(chooser).toBeVisible();
  const chooserA11y = await new AxeBuilder({ page })
    .include(".context-consent-sheet")
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(chooserA11y.violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(selector).toBeFocused();

  await activatePersona(page, alex);
  const usedTrigger = page.getByRole("button", { name: "What the assistant used" });
  await usedTrigger.click();
  const drawer = page.getByRole("dialog", { name: "What the assistant used" });
  await expect(drawer).toContainText("Required for this flow");
  await expect(drawer.getByRole("button", {
    name: "Remove consent for Employment and income status",
  })).toHaveCount(0);
  const drawerA11y = await new AxeBuilder({ page })
    .include(".context-drawer")
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(drawerA11y.violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(usedTrigger).toBeFocused();

  await sendQuestion(page, "Keep this contextual run active.");
  await page.waitForFunction(() => window.contextFixtureStreams?.length === 1);
  await page.evaluate(() => {
    const stream = window.contextFixtureStreams[0];
    const { runId, threadId } = stream.request;
    stream.send([
      { type: "RUN_STARTED", runId, threadId },
      {
        type: "TEXT_MESSAGE_START",
        messageId: "active-context-answer",
        role: "assistant",
      },
      {
        type: "TEXT_MESSAGE_CONTENT",
        messageId: "active-context-answer",
        delta: "TEST FIXTURE: partial contextual text.",
      },
    ]);
  });
  await expect(page.getByRole("button", { name: "Stop answer" })).toBeVisible();
  await usedTrigger.click();
  const revoke = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/context/consents"
    && response.request().postDataJSON().action === "revoke"
  ));
  await drawer.getByRole("button", {
    name: "Remove consent for Region and service preferences",
  }).click();
  expect((await revoke).status()).toBe(200);
  await expect.poll(() => page.evaluate(
    () => window.contextFixtureStreams[0].aborted,
  )).toBe(true);
  await expect(page.getByText("TEST FIXTURE: partial contextual text.")).toHaveCount(0);
  await expect(drawer).not.toContainText("Region and service preferences");

  const storage = await page.evaluate(async () => ({
    url: location.href,
    local: Object.fromEntries(Object.entries(localStorage)),
    session: Object.fromEntries(Object.entries(sessionStorage)),
    databases: typeof indexedDB.databases === "function"
      ? await indexedDB.databases()
      : [],
  }));
  expect(JSON.stringify(storage)).not.toMatch(
    /employment recently ended|part-time|synthetic-government-record|context-summary/iu,
  );
  expect(new URL(storage.url).search).toBe("");
  expect(new URL(storage.url).hash).toBe("");

  const oldPageToken = await page.evaluate(
    () => window.contextFixtureRequests[0].headers["x-bc-context-page"],
  );
  await page.reload();
  await expect(page.getByRole("button", {
    name: "Choose a synthetic demo persona",
  })).toContainText("Anonymous");
  await expect(page.locator(".synthetic-context-banner")).toHaveCount(0);
  const staleGrantStatus = await page.evaluate(async (pageToken) => {
    const response = await fetch("/api/context/summary", {
      headers: { "x-bc-context-page": pageToken },
      cache: "no-store",
    });
    return response.status;
  }, oldPageToken);
  expect(staleGrantStatus).toBe(401);
});

test("visible contextual artifacts pass light/dark, reduced-motion and accessibility checks", async ({
  page,
}, testInfo) => {
  await installContextFixtureStream(page);
  await openHome(page);
  const sam = contextEvaluationCases.find((item) => item.personaId === "sam-job-loss");
  await activatePersona(page, sam);
  await sendQuestion(page, sam.sampleQuestion);
  await completeContextFixture(
    page,
    0,
    "TEST FIXTURE: review the deterministic screening package and official handoff.",
  );

  await expect(page.locator(".context-artifact")).toHaveCount(5);
  await expect(page.getByText("Reviewed source accessed")).toBeVisible();
  await expect(page.getByText("Contextual run completed")).toBeVisible();
  const checkbox = page.getByRole("checkbox", {
    name: /I reviewed what would be shared/,
  });
  await checkbox.focus();
  await page.keyboard.press("Space");
  await expect(page.getByRole("link", {
    name: "Continue to official service",
  })).toBeVisible();

  for (const theme of ["light", "dark"]) {
    await chooseTheme(page, theme);
    const accessibility = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(
      accessibility.violations,
      JSON.stringify(accessibility.violations, null, 2),
    ).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
    ).toBeLessThanOrEqual(1);
    await page.screenshot({
      path: testInfo.outputPath(`context-artifacts-${theme}.png`),
      fullPage: true,
    });
  }
});
