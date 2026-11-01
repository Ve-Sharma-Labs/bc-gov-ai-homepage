import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { summarizeFailure, summarizeResult } from "./grounded-evaluation-report.mjs";

const normalize = (value) => value.replace(/\s+/gu, " ").trim().toLowerCase();
let evaluationPhase = "configuration";

function assertGrounded(turn, publisher) {
  assert.equal(turn.response?.origin, "model", turn.text);
  assert.equal(turn.response?.kind, "grounded", turn.text);
  assert.ok(turn.citations.some((item) => new URL(item.url).hostname.endsWith(publisher)), turn.text);
  assert.ok(turn.citations.every((item) => item.metadata?.version === 2
    && item.metadata.useScope === "local-noncommercial-evaluation"
    && item.metadata.humanReviewed === false), "Local provenance was lost or overstated.");
  assert.ok(!/couldn't verify|could not verify|don't have.*sources|do not have.*sources/iu.test(turn.text), turn.text);
}

function checkOutcome(id, turns) {
  if (id === "renewal-compound-followup") {
    assertGrounded(turns[2], "bclaws.gov.bc.ca");
    const qualifiedFeeQuote = /For a driver['’]s licence[^.\n]*\$\d/iu.test(turns[2].text)
      && turns[2].citations.some((source) => source.url.endsWith("/334_91"));
    assert.ok(/fee|payment|cost/iu.test(turns[2].text) || qualifiedFeeQuote,
      "Additional preparation beyond ID was not answered.");
    assert.ok(!/Do you have your ID ready/iu.test(turns[2].text), turns[2].text);
    assert.equal(turns[4].task?.task?.municipality, "Vancouver");
    assert.ok(/icbc\.com\/locators/iu.test(turns[4].text), turns[4].text);
    assert.ok(!/try another city|no (?:matching )?office in Vancouver/iu.test(turns[4].text), turns[4].text);
  } else if (id === "job-loss-to-ei") {
    assertGrounded(turns[1], "canada.ca");
    assert.ok(/appl(?:y|ication)/iu.test(turns[1].text), turns[1].text);
    assertGrounded(turns[2], "canada.ca");
    assert.ok(/can apply[\s\S]{0,160}(?:haven't|not yet|without)|(?:don't|do not|no need to)[\s\S]{0,30}wait/iu.test(turns[2].text), turns[2].text);
    assert.ok(!/rent or finding work/iu.test(turns[1].text), turns[1].text);
  } else if (id === "adult-guardianship-next-step") {
    for (const turn of turns.slice(2)) assertGrounded(turn, "bclaws.gov.bc.ca");
    assert.ok(/court|committee/iu.test(turns[2].text), turns[2].text);
    assert.ok(/legal|lawyer|advis/iu.test(turns[3].text), turns[3].text);
    assert.ok(!/is this for an adult or a child/iu.test(turns[2].text), turns[2].text);
  } else if (id === "child-guardianship-correction") {
    assertGrounded(turns[2], "bclaws.gov.bc.ca");
    assert.ok(/child|family/iu.test(turns[2].text), turns[2].text);
    assert.ok(!/committeeship|Patients Property Act/iu.test(turns[2].text), turns[2].text);
    assert.ok(!/\byou(?:'re|\u2019re| are) (?:not an adult|a child|under)/iu.test(turns[2].text),
      "The child's service topic was mistaken for the speaker's age.");
  } else if (id === "disability-application-help") {
    assertGrounded(turns[2], "bclaws.gov.bc.ca");
    assert.ok(/form|application/iu.test(turns[2].text), turns[2].text);
    assert.ok(/www2\.gov\.bc\.ca\/gov\/content\/family-social-supports/iu.test(turns[2].text), turns[2].text);
    assertGrounded(turns[3], "bclaws.gov.bc.ca");
    assert.ok(/nurse practitioner/iu.test(turns[3].text), turns[3].text);
  } else if (id === "explicit-goal-switch") {
    assertGrounded(turns[2], "canada.ca");
    assert.ok(/report|claim status|Service Canada Account/iu.test(turns[2].text), turns[2].text);
    assert.ok(turns[2].citations.some((source) => source.url.endsWith("/after-applying.html")),
      "The after-applying question did not use the relevant after-applying guidance.");
    assert.ok(!/driver|licence|licensing/iu.test(turns[2].text), turns[2].text);
  } else {
    throw new Error("Add explicit outcome assertions before adding a live case.");
  }
}

async function main() {
  const base = new URL(process.env.PILOT_BASE_URL || "http://127.0.0.1:3000");
  evaluationPhase = "approval";
  assert.ok(process.argv.includes("--live-approved") && ["127.0.0.1", "localhost"].includes(base.hostname),
    "This billable synthetic evaluation requires --live-approved and a loopback app.");
  evaluationPhase = "dataset";
  const dataset = JSON.parse(await readFile(new URL("../data/evaluations/grounded-conversation-cases.json", import.meta.url), "utf8"));
  const selectedId = process.argv.find((value) => value.startsWith("--case="))?.slice(7);
  const cases = dataset.cases.filter((item) => !selectedId || item.id === selectedId);
  assert.ok(cases.length, "Unknown evaluation case");
  const output = resolve(process.argv.find((value) => value.startsWith("--output="))?.slice(9)
    || "test-results\\grounded-live-results.json");
  evaluationPhase = "capabilities";
  const capabilities = await fetch(new URL("/api/capabilities", base), {
    headers: { "X-BC-Client-Version": "6" }, signal: AbortSignal.timeout(60_000),
  }).then(async (response) => {
    assert.equal(response.status, 200);
    return response.json();
  });
  assert.ok(capabilities.requestVersions.includes(6) && capabilities.conversationAgentReady
    && capabilities.retrievalReady && capabilities.localEvidenceEvaluation,
  "The complete isolated local source/agent profile must be ready before model evaluation.");

  let lastRequestAt = 0;
  const results = [];
  for (const item of cases) {
    evaluationPhase = "evaluation";
    let cookie = "";
    let state = null;
    let phase = "request";
    let turnNumber = 0;
    let responseStatus;
    const page = randomUUID();
    const threadId = randomUUID();
    const turns = [];
    const headers = () => ({
      "Content-Type": "application/json", Origin: base.origin,
      "X-BC-Conversation-Page": page, ...(cookie ? { Cookie: cookie } : {}),
    });
    const result = { case: item.id, expectedBehaviour: item.expectedBehaviour, passed: false, turns };
    try {
      for (const prompt of item.messages) {
        phase = "request";
        turnNumber += 1;
        responseStatus = undefined;
        await new Promise((done) => setTimeout(done, Math.max(0, 8100 - (Date.now() - lastRequestAt))));
        lastRequestAt = Date.now();
        const response = await fetch(new URL("/api/agent", base), {
          method: "POST", headers: headers(), signal: AbortSignal.timeout(120_000),
          body: JSON.stringify({
            threadId, runId: randomUUID(), state: {}, context: [], tools: [],
            messages: [{ id: randomUUID(), role: "user", content: prompt }],
            forwardedProps: { bc: { version: 6, mode: "general", conversation: {
              action: "respond", revision: state?.revision ?? 0,
              noticeVersion: "ai-conversation-v1", shareContext: false,
              ...(state?.question ? { questionId: state.question.id } : {}),
            } } },
          }),
        });
        phase = "response";
        responseStatus = response.status;
        for (const value of response.headers.getSetCookie()) {
          if (value.startsWith("bc_pilot_session=")) cookie = value.split(";")[0];
        }
        const raw = await response.text();
        assert.equal(response.status, 200, raw.slice(0, 700));
        phase = "parse-events";
        const events = raw.split(/\r?\n/u).filter((line) => line.startsWith("data: "))
          .map((line) => JSON.parse(line.slice(6)));
        const turn = {
          prompt,
          text: events.filter((event) => event.type === "TEXT_MESSAGE_CONTENT").map((event) => event.delta).join(""),
          response: events.find((event) => event.name === "bc.response")?.value,
          state: events.find((event) => event.name === "bc.conversation")?.value,
          task: events.find((event) => event.name === "bc.task")?.value,
          citations: events.filter((event) => event.name === "annotations").flatMap((event) => event.value.annotations),
          errors: events.filter((event) => event.type === "RUN_ERROR"),
          warnings: events.filter((event) => event.name === "bc.warning").map((event) => event.value),
        };
        turns.push(turn);
        phase = "validate-turn";
        assert.deepEqual(turn.errors, [], JSON.stringify(turn.errors));
        assert.deepEqual(turn.warnings, [], JSON.stringify(turn.warnings));
        assert.equal(events.at(-1)?.type, "RUN_FINISHED");
        assert.ok(turn.state && turn.text.trim(), JSON.stringify(turn));
        assert.ok(turn.state.questionCount <= 3);
        assert.ok(!/\b(?:I|we) (?:have )?(?:renewed|submitted|booked|paid)|\byou are (?:eligible|approved)/iu.test(turn.text), turn.text);
        assert.ok(!/(?:please (?:provide|enter|send)|what is your)[\s\S]{0,25}(?:SIN|PHN|licence number|bank account)/iu.test(turn.text), turn.text);
        if (turns.length > 1) {
          const prior = turns[turns.length - 2];
          assert.notEqual(normalize(turn.text), normalize(prior.text), "The previous reply was repeated.");
          if (prior.state?.question && turn.state.question) {
            assert.notEqual(normalize(turn.state.question.text), normalize(prior.state.question.text), "The answered intake question was repeated.");
          }
        }
        state = turn.state;
      }
      phase = "check-outcome";
      checkOutcome(item.id, turns);
      result.passed = true;
    } catch (error) {
      result.error = error;
      result.failureContext = {
        phase, ...(phase !== "check-outcome" ? { turn: turnNumber, status: responseStatus } : {}),
      };
    } finally {
      if (cookie) {
        let cleanupStatus;
        try {
          const response = await fetch(new URL("/api/conversation", base), { method: "DELETE", headers: headers() });
          cleanupStatus = response.status;
          assert.equal(response.status, 204, "Synthetic page cleanup failed.");
        } catch (error) {
          result.passed = false;
          result.cleanupError = error;
          result.cleanupContext = { phase: "cleanup", status: cleanupStatus };
        }
      }
      results.push(result);
      const summaries = results.map(summarizeResult);
      evaluationPhase = "write-report";
      await mkdir(dirname(output), { recursive: true });
      await writeFile(output, JSON.stringify({
        scope: "local-noncommercial-evaluation", version: 6,
        evaluatedAt: new Date().toISOString(), results: summaries,
      }, null, 2));
      const summary = summaries.at(-1);
      console[summary.passed ? "log" : "error"](JSON.stringify({
        case: summary.case, passed: summary.passed, turns: summary.turns.length,
        error: summary.error, cleanupError: summary.cleanupError,
      }));
    }
    if (!result.passed) break;
  }
  evaluationPhase = "completion";
  assert.equal(results.length, cases.length, "Evaluation stopped after a failing case.");
  assert.ok(results.every((result) => result.passed), `A grounded outcome failed; inspect ${output}.`);
}

main().catch((error) => {
  console.error(JSON.stringify({ passed: false, error: summarizeFailure(error, { phase: evaluationPhase }) }));
  process.exitCode = 1;
});
