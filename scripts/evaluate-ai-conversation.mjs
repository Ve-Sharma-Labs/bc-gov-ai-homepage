import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

const base = new URL(process.env.PILOT_BASE_URL || "http://127.0.0.1:3000");
if (!process.argv.includes("--live-approved") || !["127.0.0.1", "localhost"].includes(base.hostname)) {
  throw new Error("Use --live-approved against the local app. This invokes the configured model with synthetic cases.");
}

const cases = [
  { name: "reported renewal typo", text: "PLEASE HELP ME RENEW MY DRIVERS LICENESE PELASE", goal: "licence-renewal", question: "licence-jurisdiction", reply: "Yes", journey: "licence-renewal" },
  { name: "already supplied issuer", text: "please help me renew my BC driver's licence", goal: "licence-renewal", journey: "licence-renewal", noQuestion: true },
  { name: "road test paraphrase", text: "Can you help me book a drivers test?", goal: "road-test-booking", question: "road-test-kind", reply: "A car", journey: "road-test-booking" },
  { name: "rent help", text: "I need help paying my rent", goal: "rental-assistance", journey: "rental-assistance", reply: "Help paying rent" },
  { name: "medical coverage", text: "Help me sign up for MSP", goal: "health-coverage", journey: "health-coverage" },
  { name: "medication costs", text: "I need help with medication costs", goal: "pharmacare-registration", journey: "pharmacare-registration" },
  { name: "finding a doctor", text: "I need a family docter", goal: "primary-care", journey: "primary-care" },
  { name: "service office", text: "help me find the right service bc office", goal: "service-bc", question: "service-need", reply: "Driver licensing", journey: "service-bc" },
  { name: "business licence negative", text: "I need to renew my business licence", goal: "business", notJourney: "licence-renewal" },
  { name: "BCeID negative", text: "Help me with my BCeID account", goal: "bceid", notJourney: "licence-renewal" },
  { name: "motorcycle negative", text: "I'm thinking of buying a motorcycle next year", goal: "motorcycle", notJourney: "licence-renewal" },
  { name: "tenancy negative", text: "My landlord won't fix the apartment, what are my tenant rights?", goal: "tenancy", notJourney: "rental-assistance" },
  { name: "fishing licence negative", text: "I need to renew my fishing licence", notJourney: "licence-renewal" },
  { name: "sourced information", text: "What is the Health Connect Registry?", goal: "primary-care", grounded: true },
  { name: "reported non-BC renewal loop", text: "hi please help me renew my drivers license", goal: "licence-renewal", question: "licence-jurisdiction", reply: "Issued somewhere else", routeReply: "how do i renrew?", finalIncludes: "original issuer", emptyJourney: true },
  { name: "non-BC exchange route", text: "I need to renew my drivers license", goal: "licence-renewal", question: "licence-jurisdiction", reply: "Issued somewhere else", routeReply: "Get a B.C. licence", finalIncludes: "moving-to-B.C.", emptyJourney: true },
  { name: "guardianship starter", text: "I need to apply for guardianship", goal: "caregiving", questionText: "adult", reply: "An adult", finalIncludes: "Adult Guardianship/Committeeship", emptyJourney: true },
  { name: "disability starter", text: "I need to apply for disability", goal: "disability", questionText: "PWD", reply: "Provincial disability assistance", finalIncludes: "Apply for disability assistance", emptyJourney: true },
  { name: "job-loss starter", text: "I just lost my job, what do I do?", goal: "job-loss", question: "priority", reply: "Finding work", finalIncludes: "WorkBC", emptyJourney: true },
  { name: "mixed renewal compatibility", text: "help me renew my drivers license", goal: "licence-renewal", question: "licence-jurisdiction", reply: "yes", compoundOffice: true },
  { name: "explicit EI compatibility", text: "I just lost my job, what do I do?", goal: "job-loss", question: "priority", reply: "finding work? i want to claim my EI please", finalIncludes: "canada.ca", emptyJourney: true },
];
const failures = [];
let lastRequestAt = 0;
const requestedCase = process.argv.find((arg) => arg.startsWith("--case="))?.slice(7);
const fromCase = process.argv.find((arg) => arg.startsWith("--from="))?.slice(7);
const startIndex = fromCase ? cases.findIndex((item) => item.name === fromCase) : 0;
assert.ok(startIndex >= 0, "Unknown starting case");
const selected = requestedCase ? cases.filter((item) => item.name === requestedCase) : cases.slice(startIndex);
assert.ok(selected.length, "No matching evaluation case");
for (const item of selected) {
  let cookie = "";
  const page = randomUUID();
  const threadId = randomUUID();
  const headers = () => ({ "Content-Type": "application/json", Origin: base.origin, "x-bc-conversation-page": page, ...(cookie ? { Cookie: cookie } : {}) });
  const send = async (text, state = null) => {
    // Respect the ordinary local per-client limit; this runner never disables admission controls.
    await new Promise((resolve) => setTimeout(resolve, Math.max(0, 8000 - (Date.now() - lastRequestAt))));
    lastRequestAt = Date.now();
    const response = await fetch(new URL("/api/agent", base), {
      method: "POST", headers: headers(), signal: AbortSignal.timeout(120_000),
      body: JSON.stringify({
        threadId, runId: randomUUID(), state: {}, context: [], tools: [],
        messages: [{ id: randomUUID(), role: "user", content: text }],
        forwardedProps: { bc: { version: 5, mode: "general", conversation: {
          action: "respond", revision: state?.revision || 0, noticeVersion: "ai-conversation-v1", shareContext: state?.shareContext ?? false,
          ...(state?.question ? { questionId: state.question.id } : {}),
        } } },
      }),
    });
    for (const value of response.headers.getSetCookie()) {
      if (value.startsWith("bc_pilot_session=")) cookie = value.split(";")[0];
    }
    const raw = await response.text();
    assert.equal(response.status, 200, raw.slice(0, 700));
    const events = raw.split(/\r?\n/).filter((line) => line.startsWith("data: ")).map((line) => JSON.parse(line.slice(6)));
    assert.equal(events.some((event) => event.type === "RUN_ERROR"), false, JSON.stringify({
      input: text, errors: events.filter((event) => event.type === "RUN_ERROR"),
    }));
    assert.equal(events.at(-1)?.type, "RUN_FINISHED");
    const stateEvent = events.find((event) => event.name === "bc.conversation");
    assert.ok(stateEvent);
    return {
      state: stateEvent.value, events,
      task: events.find((event) => event.name === "bc.task")?.value,
      text: events.filter((event) => event.type === "TEXT_MESSAGE_CONTENT").map((event) => event.delta).join(""),
    };
  };
  const control = async (result, action, fields = {}) => {
    const task = result.task?.task;
    const response = await fetch(new URL("/api/conversation/control", base), {
      method: "POST", headers: headers(),
      body: JSON.stringify({
        id: randomUUID(), revision: result.state.revision, noticeVersion: "ai-conversation-v1",
        action, ...(action === "sharing" ? {} : { taskId: task.id, stepId: task.activeStepId }), ...fields,
      }),
    });
    const value = await response.json();
    assert.equal(response.status, 200, JSON.stringify(value));
    assert.equal(value.summary.goal, result.state.goal);
    return { ...result, state: value.summary, task: value.task, notice: value.notice };
  };
  try {
    let result = await send(item.text);
    const firstQuestion = result.state.question;
    if (item.goal) assert.equal(result.state.goal, item.goal);
    if (item.question) assert.equal(result.state.question?.factKey, item.question, JSON.stringify(result.state));
    if (item.questionText) assert.ok(result.state.question?.text.includes(item.questionText), JSON.stringify(result.state));
    if (item.noQuestion) assert.equal(result.state.question, null);
    if (result.state.question && item.reply) result = await send(item.reply, result.state);
    if (item.compoundOffice) {
      const prior = result.text;
      result = await send("yes, what else to bring?", result.state);
      assert.notEqual(result.text, prior);
      assert.ok(!result.text.includes("Do you have your ID ready?"), result.text);
      assert.equal(result.state.facts.find((fact) => fact.key === "licence-jurisdiction")?.value, "bc");
      result = await send("thank you, now where do i go to renew my drivers license?", result.state);
      assert.ok(result.text.includes("city or town"), result.text);
      result = await send("vancoucver", result.state);
      assert.equal(result.task?.task?.municipality, "Vancouver");
      assert.ok(result.text.includes("icbc.com/locators"), result.text);
      assert.ok(!result.text.includes("try another city"), result.text);
    }
    if (item.routeReply) {
      assert.equal(result.state.facts.find((fact) => fact.key === "licence-jurisdiction")?.value, "other");
      assert.notEqual(result.state.question?.id, firstQuestion.id);
      assert.ok(result.state.question?.text.includes("place that issued it"));
      assert.equal(result.state.journeyId, null);
      result = await send(item.routeReply, result.state);
      assert.equal(result.state.facts.find((fact) => fact.key === "licence-jurisdiction")?.value, "other");
    }
    if (item.emptyJourney) {
      assert.equal(result.state.journeyId, null);
      assert.equal(result.state.question, null);
      assert.equal(result.state.shareContext, false);
      assert.equal(result.task?.task ?? null, null);
    }
    if (item.finalIncludes) assert.ok(result.text.includes(item.finalIncludes), result.text);
    if (item.journey) {
      assert.equal(result.state.journeyId, item.journey, JSON.stringify(result.state));
      assert.ok(result.events.some((event) => event.name === "bc.artifact" && event.value.kind === "preparation"));
      if (result.task?.task && !item.noQuestion) {
        const taskId = result.task.task.id;
        const stepId = result.task.task.activeStepId;
        result = await control(result, "sharing", { shareContext: true });
        assert.equal(result.task.task.activeStepId, stepId);
        assert.equal(result.notice, "Optional context sharing is on.");
        result = await send(
          item.name === "reported renewal typo" ? "so plesae help me renew my BC DL please" : "Please keep helping with this.",
          result.state,
        );
        assert.equal(result.task.task.id, taskId);
        assert.equal(result.task.task.activeStepId, stepId);
        assert.ok(!result.text.includes("Work through the checklist below"));
        assert.ok(!result.text.includes("Here's a reviewed preparation guide"));
        if (item.name === "reported renewal typo") {
          result = await send("halllllo are you helping", result.state);
          assert.equal(result.task.task.id, taskId);
          assert.equal(result.task.task.activeStepId, stepId);
          assert.ok(!result.text.includes("What would you like help figuring out"));
          assert.ok(result.text.includes("Accepted-ID"));
        }
        if (result.task.task.waitingFor === "municipality") {
          result = await send("Nanaimo", result.state);
          assert.equal(result.task.task.municipality, "Nanaimo");
        }
        result = await send(item.name === "reported renewal typo" ? "I have my ID" : "I have reviewed this step", result.state);
        assert.ok(result.task.task.reviewedStepIds.includes(stepId), JSON.stringify(result.task.task));
        assert.notEqual(result.task.task.activeStepId, stepId);
        if (item.name === "reported renewal typo") {
          assert.equal(result.task.task.waitingFor, "municipality");
          assert.ok(result.text.includes("city or town"));
          result = await send("Nanaimo", result.state);
          assert.ok(result.text.includes("Nanaimo"));
        }
        result = await control(result, "sharing", { shareContext: false });
        assert.ok(result.task.task.reviewedStepIds.includes(stepId));
        for (let step = 0; step < 40 && result.task.task.phase !== "ready-for-official-handoff"; step++) {
          result = await control(result, "review", { reviewed: true });
        }
        assert.equal(result.task.task.phase, "ready-for-official-handoff");
        assert.ok(result.task.guidance.includes("official service"));
      }
    }
    if (item.notJourney) assert.notEqual(result.state.journeyId, item.notJourney);
    if (item.grounded) {
      assert.ok(result.events.some((event) => event.name === "bc.response" && event.value.origin === "model" && event.value.kind === "grounded"));
      assert.ok(result.events.some((event) => event.name === "annotations" && event.value.annotations.length > 0));
    }
    assert.ok(result.state.questionCount <= 3);
    console.log(JSON.stringify({
      case: item.name, passed: true, goal: result.state.goal, phase: result.state.phase,
      ...(item.name.endsWith("compatibility") ? { scope: "routing-and-safe-source-gaps-not-full-grounding" } : {}),
    }));
  } catch (error) {
    failures.push(item.name);
    console.error(JSON.stringify({ case: item.name, passed: false, error: error.message }));
  } finally {
    if (cookie) {
      const response = await fetch(new URL("/api/conversation", base), { method: "DELETE", headers: headers() });
      if (response.status !== 204) throw new Error(`Cleanup failed (${response.status}).`);
    }
    if (failures.length) break;
  }
}
assert.deepEqual(failures, [], "Live conversation cases failed");
