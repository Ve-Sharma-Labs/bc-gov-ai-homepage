import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const limit = Number.parseInt(process.env.AGENTIC_QA_TURN_LIMIT || "12", 10);
assert.ok(Number.isSafeInteger(limit) && limit > 0, "AGENTIC_QA_TURN_LIMIT must be a positive integer.");

const statePath = resolve(process.env.AGENTIC_QA_BUDGET_PATH || "/tmp/gh-aw/agentic-qa-turns.json");

async function readState() {
  try {
    const value = JSON.parse(await readFile(statePath, "utf8"));
    assert.equal(value.limit, limit, "The existing QA budget uses a different limit.");
    assert.ok(Number.isSafeInteger(value.used) && value.used >= 0 && value.used <= value.limit);
    return value;
  } catch (error) {
    if (error?.code === "ENOENT") return { version: 1, limit, used: 0 };
    throw error;
  }
}

async function save(state) {
  await mkdir(dirname(statePath), { recursive: true });
  await writeFile(statePath, `${JSON.stringify(state, null, 2)}\n`, { flag: "w" });
}

const [command = "status", rawAmount = "1"] = process.argv.slice(2);
const state = await readState();

if (command === "reset") {
  const reset = { version: 1, limit, used: 0 };
  await save(reset);
  console.log(JSON.stringify({ ...reset, remaining: limit }));
} else if (command === "consume") {
  const amount = Number.parseInt(rawAmount, 10);
  assert.ok(Number.isSafeInteger(amount) && amount > 0, "The consumed turn count must be a positive integer.");
  assert.ok(state.used + amount <= state.limit,
    `Agentic QA turn budget exceeded: ${state.used + amount}/${state.limit}.`);
  state.used += amount;
  await save(state);
  console.log(JSON.stringify({ ...state, remaining: state.limit - state.used }));
} else if (command === "status") {
  console.log(JSON.stringify({ ...state, remaining: state.limit - state.used }));
} else {
  throw new Error(`Unknown command: ${command}`);
}
