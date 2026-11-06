import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const script = fileURLToPath(new URL("../agentic-qa-budget.mjs", import.meta.url));

function run(statePath, ...args) {
  return spawnSync(process.execPath, [script, ...args], {
    encoding: "utf8",
    env: {
      ...process.env,
      AGENTIC_QA_BUDGET_PATH: statePath,
      AGENTIC_QA_TURN_LIMIT: "3"
    }
  });
}

test("agentic QA budget persists consumption and fails closed at the limit", async () => {
  const directory = await mkdtemp(join(tmpdir(), "agentic-qa-budget-"));
  const statePath = join(directory, "budget.json");

  const reset = run(statePath, "reset");
  assert.equal(reset.status, 0, reset.stderr);
  assert.deepEqual(JSON.parse(reset.stdout), { version: 1, limit: 3, used: 0, remaining: 3 });

  const consumed = run(statePath, "consume", "2");
  assert.equal(consumed.status, 0, consumed.stderr);
  assert.deepEqual(JSON.parse(consumed.stdout), { version: 1, limit: 3, used: 2, remaining: 1 });

  const refused = run(statePath, "consume", "2");
  assert.notEqual(refused.status, 0);
  assert.match(refused.stderr, /turn budget exceeded/iu);

  assert.deepEqual(JSON.parse(await readFile(statePath, "utf8")), {
    version: 1,
    limit: 3,
    used: 2
  });
});
