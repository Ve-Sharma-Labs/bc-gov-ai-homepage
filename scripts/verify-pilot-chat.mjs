import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";

const journeyIds = [
  "licence-renewal", "road-test-booking", "rental-assistance", "health-coverage",
  "pharmacare-registration", "primary-care", "service-bc",
];
const releaseCases = {
  renewal: "reported renewal and continuation",
  guardianship: "guardianship starter",
  disability: "disability starter",
  "job-loss": "job-loss starter",
  "non-bc": "non-B.C. issuer",
  health: "previously covered health answer",
};
const plannerFailureStages = new Map([
  ["The assistant couldn't finish choosing the next step. Please retry.", "planner-response"],
  ["Unapproved decision withheld.", "planner-call"],
  ["The assistant's next step couldn't be verified. Please retry.", "planner-schema"],
  ["The assistant's next step couldn't be verified. Please try again.", "conversation-policy"],
]);
const genericRefusal = /I don't have current, reviewed source information|gov\/content\/home/;
const officialHandoffs = {
  acceptedId: "https://www.icbc.com/driver-licensing/visit-dl-office/Accepted-ID",
  locator: "https://www.icbc.com/locators/Pages/default.aspx?type=1&subtype=0",
  renewal: "https://www.icbc.com/driver-licensing/getting-licensed/Renew-your-licence-or-ID",
  guardianship: "https://www2.gov.bc.ca/gov/content/family-social-supports/seniors/"
    + "financial-legal-matters/substitute-decision-making",
  disability: "https://www2.gov.bc.ca/gov/content/family-social-supports/"
    + "services-for-people-with-disabilities/disability-assistance",
  workbc: "https://www.workbc.ca/",
};

export function releaseTarget(value) {
  const url = new URL(value);
  assert.ok(!url.username && !url.password && !url.search && !url.hash && url.pathname === "/",
    "Select an exact app origin without credentials, path, query, or fragment.");
  assert.ok(url.protocol === "https:" || (
    url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
  ), "Release checks require HTTPS, or an explicitly selected loopback candidate.");
  return url;
}

export function hasOfficialHandoff(text, expectedUrl) {
  const expected = new URL(expectedUrl);
  const links = text.matchAll(/(?<!!)\[[^[\]\r\n]+\]\((https:\/\/[^()\s]+)\)/gi);
  return [...links].some(([, target]) => {
    try {
      const url = new URL(target);
      return url.protocol === "https:" && !url.username && !url.password
        && url.href === expected.href;
    } catch {
      return false;
    }
  });
}

export function assertReleaseCapabilities(capabilities, { researchApproved = false } = {}) {
  assert.ok(capabilities.mode === "foundry" && capabilities.aiConfigured
    && capabilities.generalChatConfigured
    && capabilities.conversationAvailable && capabilities.conversationAgentReady
    && capabilities.taskAssistanceAvailable && capabilities.requestVersions?.includes(5),
  "The intended version-5 conversation and task assistance are not ready.");
  assert.ok(journeyIds.every((id) => capabilities.journeys?.[id] === true),
    "The seven existing pathway agent bindings are not all ready.");
  assert.ok(!capabilities.requestVersions.includes(6) && !capabilities.localEvidenceEvaluation,
    "This public release must not enable the experimental/local-only evidence profile.");
  assert.equal(capabilities.transactionsEnabled, false, "Transactions must remain disabled.");
  if (researchApproved) {
    assert.ok(capabilities.webIqEnabled === true && capabilities.research?.version === 1
      && capabilities.research.foundryIq?.available === true
      && capabilities.research.foundryIq.preview === true
      && capabilities.research.webIq?.available === true,
    "Both separately approved research paths must report the expected capabilities.");
  } else {
    assert.equal(capabilities.webIqEnabled, false, "Unreviewed live research must remain disabled.");
    assert.ok(!capabilities.research?.foundryIq?.available && !capabilities.research?.webIq?.available,
      "Research needs an explicit release-approval selection.");
  }
  const health = capabilities.sourceHealth;
  assert.ok(capabilities.retrievalReady && health?.status === "ready"
    && health.usableDocuments >= 4
    && ["health", "healthlink-bc", "service-bc"].every((id) => health.coveredSourceIds?.includes(id)),
  "The existing four-document factual baseline does not have current, verified source coverage.");
}

export function assertSuccessfulRun(events) {
  assert.equal(events[0]?.type, "RUN_STARTED", "The response did not start an agent run.");
  const failure = events.find((event) => event.type === "RUN_ERROR");
  const code = typeof failure?.code === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(failure.code)
    ? failure.code : "UNKNOWN";
  if (failure) {
    const error = new assert.AssertionError({
      message: `The conversation returned a run error (${code}).`,
    });
    if (code === "CONVERSATION_DECISION_INVALID") {
      error.releaseStage = plannerFailureStages.get(failure.message);
    }
    throw error;
  }
  assert.equal(events.at(-1)?.type, "RUN_FINISHED", "The run did not finish normally.");
}

export function decodeReleaseTurn(raw, threadId, previousRevision) {
  const events = raw.split(/\r?\n/).filter((line) => line.startsWith("data: "))
    .map((line) => JSON.parse(line.slice(6)));
  return decodeReleaseEvents(events, threadId, previousRevision);
}

export function decodeReleaseEvents(events, threadId, previousRevision) {
  assertSuccessfulRun(events);
  const text = events.filter((event) => event.type === "TEXT_MESSAGE_CONTENT")
    .map((event) => event.delta).join("");
  assert.ok(text.trim() && !genericRefusal.test(text),
    "A supported task returned the generic source-unavailable dead end.");
  const summary = events.find((event) => event.name === "bc.conversation")?.value;
  const task = events.find((event) => event.name === "bc.task")?.value;
  assert.ok(summary && task, "The conversation/task state was not returned.");
  assert.equal(summary.threadId, threadId, "The reply belongs to a different conversation.");
  assert.equal(summary.revision, previousRevision + 1, "The conversation revision did not advance.");
  assert.equal(task.revision, summary.revision, "Task and conversation revisions diverged.");
  assert.equal(task.threadId, threadId, "The task belongs to a different conversation.");
  assert.equal(summary.shareContext, false, "The check must not enable personal-context sharing.");
  return { text, summary, task, events };
}

export async function verifyPilotChat({
  baseUrl, liveApproved = false, researchApproved = false, fetchImpl = fetch,
  caseIds = [],
  pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
}) {
  assert.ok(Array.isArray(caseIds) && caseIds.every((id) => Object.hasOwn(releaseCases, id))
    && new Set(caseIds).size === caseIds.length, "Select unique, supported release case IDs.");
  assert.ok(!caseIds.length || liveApproved, "Focused cases require explicit live approval.");
  const selected = new Set(caseIds.map((id) => releaseCases[id]));
  const base = releaseTarget(baseUrl);
  const get = async (path) => {
    const response = await fetchImpl(new URL(path, base), {
      redirect: "error", signal: AbortSignal.timeout(30_000),
      ...(path === "/api/capabilities" ? { headers: { "X-BC-Client-Version": "6" } } : {}),
    });
    assert.equal(response.status, 200, `The ${path} release check failed (HTTP ${response.status}).`);
    return response.json();
  };
  const capabilities = await get("/api/capabilities");
  assertReleaseCapabilities(capabilities, { researchApproved });
  const catalog = await get("/api/catalog");
  for (const id of journeyIds) {
    const journey = catalog.journeys?.find((item) => item.id === id);
    assert.ok(journey?.steps?.length && journey?.handoffs?.length,
      `The reviewed ${id} preparation guide is missing.`);
  }
  const report = {
    target: base.origin, mode: liveApproved ? "live-synthetic" : "read-only",
    coverage: liveApproved ? (selected.size ? "focused" : "full") : "read-only",
    sourceHealth: {
      status: capabilities.sourceHealth.status,
      usableDocuments: capabilities.sourceHealth.usableDocuments,
      baselineSources: ["health", "healthlink-bc", "service-bc"],
    },
    cases: [], turns: 0,
  };
  if (!liveApproved) return report;
  let lastSent = 0;
  const runCase = async (name, check) => {
    if (selected.size && !selected.has(name)) return;
    const page = randomUUID();
    const threadId = randomUUID();
    let cookie = "";
    let summary;
    const before = report.turns;
    const headers = () => ({
      "Content-Type": "application/json", Origin: base.origin,
      "x-bc-conversation-page": page, ...(cookie ? { Cookie: cookie } : {}),
    });
    const send = async (text) => {
      assert.ok(report.turns < 18, "The bounded release check exceeded its 18-turn limit.");
      await pause(Math.max(0, 8000 - (Date.now() - lastSent)));
      lastSent = Date.now();
      report.turns++;
      const response = await fetchImpl(new URL("/api/agent", base), {
        method: "POST", redirect: "error", headers: headers(),
        signal: AbortSignal.timeout(90_000),
        body: JSON.stringify({
          threadId, runId: randomUUID(), tools: [], context: [], state: {},
          messages: [{ id: randomUUID(), role: "user", content: text }],
          forwardedProps: { bc: { version: 5, mode: "general", conversation: {
            action: "respond", revision: summary?.revision ?? 0,
            noticeVersion: "ai-conversation-v1", shareContext: false,
            ...(summary?.question ? { questionId: summary.question.id } : {}),
          } } },
        }),
      });
      for (const value of response.headers.getSetCookie()) {
        if (value.startsWith("bc_pilot_session=")) cookie = value.split(";")[0];
      }
      assert.equal(response.status, 200, `The ${name} request failed; no limits will be reset or bypassed.`);
      const result = decodeReleaseTurn(await response.text(), threadId, summary?.revision ?? 0);
      summary = result.summary;
      return result;
    };
    try {
      await check(send);
      report.cases.push({ name, passed: true, turns: report.turns - before });
    } catch (error) {
      if (error instanceof Error) {
        error.releaseCase = name;
        error.releaseTurn = report.turns - before;
      }
      throw error;
    } finally {
      if (cookie) {
        const response = await fetchImpl(new URL("/api/conversation", base), {
          method: "DELETE", redirect: "error", headers: headers(),
          signal: AbortSignal.timeout(30_000),
        });
        assert.equal(response.status, 204, "The check could not clear its own synthetic conversation.");
      }
    }
  };
  await runCase("reported renewal and continuation", async (send) => {
    let result = await send("please help me renew my drivers license");
    assert.equal(result.summary.question?.factKey, "licence-jurisdiction");
    result = await send("Yes");
    assert.equal(result.summary.journeyId, "licence-renewal");
    assert.equal(result.summary.question, null);
    assert.equal(result.task.task?.activeStepId, "prepare-identification");
    assert.ok(hasOfficialHandoff(result.text, officialHandoffs.acceptedId),
      "Renewal preparation needs the specific ID guidance.");
    const taskId = result.task.task.id;
    result = await send("are you helping?");
    assert.equal(result.task.task?.id, taskId);
    assert.equal(result.task.task.activeStepId, "prepare-identification");
    assert.equal(result.summary.question, null, "A check-in must not restart issuer intake.");
    result = await send("I have my ID");
    assert.equal(result.task.task?.waitingFor, "municipality");
    assert.ok(result.task.task.reviewedStepIds.includes("prepare-identification"));
    result = await send("Vancouver");
    assert.equal(result.task.task?.municipality, "Vancouver");
    assert.ok(hasOfficialHandoff(result.text, officialHandoffs.locator),
      "Unavailable snapshot coverage needs ICBC's locator.");
    result = await send("What else should I bring?");
    assert.equal(result.task.task?.id, taskId, "A source gap must not discard task progress.");
    assert.ok(hasOfficialHandoff(result.text, officialHandoffs.renewal),
      "Missing detail needs a specific official next action.");
  });
  for (const item of [
    { name: "guardianship starter", prompt: "I need to apply for guardianship", goal: "caregiving", answer: "An adult", link: officialHandoffs.guardianship },
    { name: "disability starter", prompt: "I need to apply for disability", goal: "disability", answer: "Provincial disability assistance", link: officialHandoffs.disability },
    { name: "job-loss starter", prompt: "I just lost my job, what do I do?", goal: "job-loss", answer: "Finding work", link: officialHandoffs.workbc },
  ]) {
    await runCase(item.name, async (send) => {
      let result = await send(item.prompt);
      assert.equal(result.summary.goal, item.goal);
      if (!result.summary.question) {
        assert.equal(item.goal, "job-loss", "The starter needs its essential service-topic question.");
        assert.ok(hasOfficialHandoff(result.text, item.link),
          "A direct job-loss response needs its reviewed WorkBC next action.");
      }
      result = await send(item.answer);
      assert.equal(result.summary.question, null);
      assert.ok(hasOfficialHandoff(result.text, item.link),
        "The starter did not provide its reviewed official next action.");
    });
  }
  await runCase("non-B.C. issuer", async (send) => {
    let result = await send("help me renew my drivers license");
    assert.equal(result.summary.question?.factKey, "licence-jurisdiction");
    result = await send("Issued somewhere else");
    assert.equal(result.summary.journeyId, null);
    assert.notEqual(result.summary.question?.factKey, "licence-jurisdiction");
    result = await send("Renew with the original issuer");
    assert.equal(result.summary.journeyId, null);
    assert.equal(result.summary.question, null);
    assert.ok(result.text.includes("original issuer"));
  });
  await runCase("previously covered health answer", async (send) => {
    const result = await send("What is the Health Connect Registry?");
    assert.ok(result.events.some((event) => event.name === "bc.response"
      && event.value.kind === "grounded" && event.value.origin === "model"),
    "The refreshed health control did not return a grounded answer.");
    assert.ok(result.events.some((event) => event.name === "annotations"
      && event.value.annotations?.length), "The health answer needs verified citations.");
  });
  return report;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const target = process.argv.find((argument) => argument.startsWith("--url="))?.slice(6);
  try {
    assert.ok(target, "Select the exact app with --url=https://your-reviewed-app/.");
    const report = await verifyPilotChat({
      baseUrl: target, liveApproved: process.argv.includes("--live-approved"),
      researchApproved: process.argv.includes("--research-approved"),
      caseIds: process.argv.filter((argument) => argument.startsWith("--case="))
        .map((argument) => argument.slice(7)),
    });
    console.log(JSON.stringify({ passed: true, ...report }, null, 2));
  } catch (error) {
    console.error(JSON.stringify({
      passed: false,
      case: error instanceof Error ? error.releaseCase : undefined,
      turn: error instanceof Error ? error.releaseTurn : undefined,
      stage: error instanceof Error ? error.releaseStage : undefined,
      error: error instanceof assert.AssertionError
        ? error.message.split("\n")[0]
        : "Release verification failed; inspect the selected target, transport, and response contract.",
    }));
    process.exitCode = 1;
  }
}
