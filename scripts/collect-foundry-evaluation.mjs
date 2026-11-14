import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";
import policy from "../data/evaluations/foundry-release-policy.json" with { type: "json" };
import { releaseCases, releaseTarget, verifyPilotChat } from "./verify-pilot-chat.mjs";

export async function collectFoundryEvaluation({
  baseUrl, approved = false, verify = verifyPilotChat,
}) {
  const target = releaseTarget(baseUrl);
  assert.ok(approved && ["127.0.0.1", "localhost", "[::1]"].includes(target.hostname),
    "Collection requires approval and an isolated loopback candidate.");
  assert.deepEqual(policy.cases.map((item) => item.id).sort(), Object.keys(releaseCases).sort(),
    "Every release scenario must have a reviewed Foundry rubric.");
  const histories = new Map(policy.cases.map((item) => [item.id, []]));
  const rows = [];
  const report = await verify({
    baseUrl: target.origin, liveApproved: true,
    observeTurn({ caseId, turn, query, response }) {
      const scenario = policy.cases.find((item) => item.id === caseId);
      const history = histories.get(caseId);
      assert.ok(scenario && history, "Unknown synthetic scenario.");
      assert.equal(turn, history.length / 2 + 1, "Synthetic turns must be ordered and unique.");
      const expected = scenario.turns[turn - 1];
      assert.ok(expected && query === expected.query, "Only checked-in synthetic queries are allowed.");
      assert.ok(typeof response === "string" && response.trim() && response.length <= 16000,
        "Missing or oversized synthetic response.");
      history.push({ role: "user", content: query });
      const contextualQuery = JSON.stringify(history);
      assert.ok(contextualQuery.length <= 64000, "Synthetic conversation exceeds the judge budget.");
      rows.push({
        id: `${caseId}:${turn}`, query: contextualQuery, response,
        expected_behavior: expected.expectedBehavior,
      });
      history.push({ role: "assistant", content: response });
    },
  });
  assert.equal(report.mode, "live-synthetic");
  assert.equal(report.coverage, "full", "Foundry Evals requires the complete synthetic suite.");
  assert.equal(report.cases.length, policy.cases.length);
  const expectedTurns = policy.cases.reduce((count, item) => count + item.turns.length, 0);
  assert.ok(expectedTurns > 0 && expectedTurns <= 18);
  assert.equal(report.turns, expectedTurns);
  assert.equal(rows.length, expectedTurns);
  for (const scenario of policy.cases) {
    const result = report.cases.find((item) => item.name === releaseCases[scenario.id]);
    assert.ok(result?.passed && result.turns === scenario.turns.length,
      "Every deterministic outcome and conversation cleanup must succeed.");
    assert.equal(histories.get(scenario.id).length, scenario.turns.length * 2);
  }
  const result = {
    schemaVersion: 1, origin: policy.origin, deterministicPassed: true, rows,
  };
  assert.ok(Buffer.byteLength(JSON.stringify(result)) <= 1024 * 1024,
    "Synthetic evaluation exceeds the upload budget.");
  return result;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const { values } = parseArgs({ options: {
      url: { type: "string" }, output: { type: "string" }, approved: { type: "boolean" },
    } });
    assert.ok(values.url && values.output, "Select a candidate origin and temporary output file.");
    const result = await collectFoundryEvaluation({
      baseUrl: values.url, approved: values.approved,
    });
    await writeFile(values.output, JSON.stringify(result), { flag: "wx", mode: 0o600 });
    console.log(JSON.stringify({ passed: true, syntheticTurns: result.rows.length }));
  } catch (error) {
    console.error(JSON.stringify({
      passed: false, code: "synthetic_collection_failed",
      case: Object.values(releaseCases).includes(error?.releaseCase) ? error.releaseCase : undefined,
      turn: Number.isSafeInteger(error?.releaseTurn) ? error.releaseTurn : undefined,
    }));
    process.exitCode = 1;
  }
}
