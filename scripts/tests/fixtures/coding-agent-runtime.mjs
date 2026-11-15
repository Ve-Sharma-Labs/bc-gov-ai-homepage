import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import { networkInterfaces } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const image = "ghcr.io/github/gh-aw-firewall/agent:0.28.23@sha256:2c78aaba1c108e130e2d6d01e4f2cca334ea04c53e6f258913ac34173fe7e3b2";
const model = "claude-sonnet-5";
const work = "test-results/coding-agent-evals/work";
const runtimeTarget = "/workspace/.gh-aw/coding-agent-runtime";

function compiledField(compiled, name) {
  const value = compiled.match(new RegExp(`^ +${name}: '?([^\\r\\n]+)`, "m"))?.[1];
  assert.ok(value, `Missing compiled ${name}`);
  return value.replace(/'$/, "").replace(/^"|"$/g, "");
}

async function execute(command, args, { timeoutMs = 120_000, ...options }) {
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  const collect = (chunk) => {
    output += chunk;
    if (output.length > 2 * 1024 * 1024) child.kill("SIGKILL");
  };
  child.stdout.on("data", collect);
  child.stderr.on("data", collect);
  const timer = setTimeout(() => child.kill("SIGKILL"), timeoutMs);
  try {
    const result = await new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("exit", (code, signal) => resolve({ code, signal }));
    });
    assert.equal(result.signal, null, "Runtime exceeded the probe's time or output bound");
    for (const match of output.matchAll(/::add-mask::([0-9a-f]{64})/g)) {
      output = output.replaceAll(match[1], "[redacted]");
    }
    return { ...result, output };
  } finally {
    clearTimeout(timer);
    child.stdout.destroy();
    child.stderr.destroy();
  }
}

function completion(response, body, message, finishReason) {
  const envelope = {
    id: "offline-permission-fixture", object: "chat.completion.chunk", created: 0, model: body.model,
    usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
  };
  if (!body.stream) {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({
      ...envelope, object: "chat.completion",
      choices: [{
        index: 0, finish_reason: finishReason,
        message: {
          ...message, tool_calls: message.tool_calls?.map(({ id, type, function: fn }) =>
            ({ id, type, function: fn })),
        },
      }],
    }));
    return;
  }
  response.writeHead(200, { "Content-Type": "text/event-stream" });
  response.write(`data: ${JSON.stringify({
    ...envelope, choices: [{ index: 0, delta: message, finish_reason: null }],
  })}\n\n`);
  response.write(`data: ${JSON.stringify({
    ...envelope, choices: [{ index: 0, delta: {}, finish_reason: finishReason }],
  })}\n\n`);
  response.end("data: [DONE]\n\n");
}

// Only fixed fixture responses enter the actual runtime; there is no model or permission mock.
async function verifyInsideContainer() {
  assert.equal(process.platform, "linux");
  assert.match(process.version, /^v24\./);
  assert.ok(Object.values(networkInterfaces()).flat().every((address) => address.internal));
  const compiled = readFileSync("/profile.lock.yml", "utf8");
  const metadata = JSON.parse(compiled.match(/^# gh-aw-metadata: (.+)$/m)[1]);
  const configBefore = readFileSync(`${runtimeTarget}/config.json`);
  assert.throws(() => writeFileSync(`${runtimeTarget}/write-probe`, "unsafe"), { code: "EROFS" });
  const sdkPackage = JSON.parse(readFileSync(`${runtimeTarget}/node_modules/@github/copilot-sdk/package.json`, "utf8"));
  assert.equal(sdkPackage.version, metadata.engine_versions["copilot-sdk"]);
  const testPath = `/workspace/${work}/probe.test.mjs`;
  const publicTest = readFileSync(testPath, "utf8");
  const driverBefore = readFileSync(`${runtimeTarget}/driver.cjs`);
  mkdirSync("/workspace/home");
  mkdirSync("/tmp/gh-aw", { recursive: true });
  mkdirSync("/tmp/runner");
  writeFileSync("/tmp/runner/prompt.txt", "Execute the fixed synthetic tools from the offline fixture, then stop.");
  const env = {
    PATH: "/runtime/bin:/usr/local/bin:/usr/bin:/bin", HOME: "/workspace/home",
    COPILOT_HOME: "/workspace/home/.copilot", NODE_PATH: `${runtimeTarget}/node_modules`,
    CI: "true", COPILOT_OFFLINE: "true", COPILOT_AUTO_UPDATE: "false",
    COPILOT_API_KEY: "dummy-byok-key-for-offline-mode", CODING_EVAL_TEST_SECRET: "do-not-inherit-test-sentinel",
    COPILOT_MODEL: model, COPILOT_AGENT_RUNNER_TYPE: "STANDALONE",
    COPILOT_SDK_URI: "http://127.0.0.1:3002",
    GITHUB_WORKSPACE: "/workspace", RUNNER_TEMP: "/runtime-root",
    GITHUB_REPOSITORY: "fixture/permission-probe", GITHUB_EVENT_NAME: "pull_request",
    GITHUB_RUN_ID: "1", GITHUB_RUN_ATTEMPT: "1", GITHUB_OUTPUT: "/tmp/runner/output.txt",
    GH_AW_PHASE: "agent", GH_AW_PROMPT: "/tmp/runner/prompt.txt", AWF_REFLECT_ENABLED: "1",
    GH_AW_TIMEOUT_MINUTES: "20", GH_AW_MAX_TURNS: "60", GH_AW_MAX_AI_CREDITS: "300",
    GH_AW_COPILOT_SDK_SERVER_ARGS: compiledField(compiled, "GH_AW_COPILOT_SDK_SERVER_ARGS"),
    GH_AW_COPILOT_SDK_TOOL_CONFIG: compiledField(compiled, "GH_AW_COPILOT_SDK_TOOL_CONFIG"),
    GH_AW_HARNESS_MAX_RETRIES: compiledField(compiled, "GH_AW_HARNESS_MAX_RETRIES"),
    GH_AW_MAX_TOOL_DENIALS: compiledField(compiled, "GH_AW_MAX_TOOL_DENIALS"),
  };
  const version = spawnSync("/runtime/copilot", ["--no-auto-update", "--version"], {
    cwd: "/workspace", env, encoding: "utf8", timeout: 60_000, maxBuffer: 64 * 1024,
  });
  assert.equal(version.status, 0, "Pinned CLI could not start");
  assert.ok(version.stdout.includes(`CLI ${metadata.engine_versions.copilot}.`));

  let active;
  const server = http.createServer(async (request, response) => {
    try {
      if (request.method === "GET" && request.url === "/reflect") {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ endpoints: [{
          configured: true, provider: "copilot", port: 10000,
          models_url: "http://api-proxy:10000/models", models: [model],
        }] }));
        return;
      }
      if (request.method === "GET" && request.url === "/models") {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ data: [{ id: model }] }));
        return;
      }
      assert.equal(request.method, "POST");
      assert.equal(request.url, "/chat/completions");
      let raw = "";
      for await (const chunk of request) {
        raw += chunk;
        assert.ok(raw.length < 2 * 1024 * 1024);
      }
      const body = JSON.parse(raw);
      active.requests++;
      assert.ok(active.requests <= active.steps.length + 1, "Unexpected recovery/model request");
      for (const message of body.messages.filter((item) => item.role === "tool")) {
        active.results.set(message.tool_call_id, message.content);
      }
      const names = body.tools.map((tool) => tool.function?.name);
      for (const forbidden of ["bash", "read_bash", "write_bash", "task"]) {
        assert.ok(!names.includes(forbidden), `Unexpected free-form execution tool: ${forbidden}`);
      }
      for (const required of ["run_public_smoke_tests", "check_candidate_syntax"]) {
        assert.ok(names.includes(required), `Missing fixed tool ${required}`);
      }
      const index = active.results.size;
      const step = active.steps[index];
      if (!step) {
        completion(response, body, { role: "assistant", content: "Offline fixture complete." }, "stop");
        return;
      }
      assert.ok(names.includes(step.tool), `Missing ${step.tool} tool`);
      completion(response, body, {
        role: "assistant", content: null,
        tool_calls: [{
          index: 0, id: `probe_${active.name}_${index}`, type: "function",
          function: { name: step.tool, arguments: JSON.stringify(step.args) },
        }],
      }, "tool_calls");
    } catch (error) {
      active.error = error;
      response.writeHead(400, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ error: { message: error.message } }));
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(10000, "127.0.0.1", resolve);
  });
  async function run(name, steps) {
    active = { name, steps, requests: 0, results: new Map() };
    const result = await execute(process.execPath, [
      "/runtime-root/gh-aw/actions/copilot_harness.cjs", process.execPath,
      `${runtimeTarget}/driver.cjs`, "/runtime/copilot",
    ], { cwd: "/workspace", env });
    assert.ifError(active.error);
    assert.ok(active.requests > 0,
      `Runtime did not reach the offline provider; exit ${result.code}: ${result.output.slice(-1200)}`);
    assert.equal((result.output.match(/^\[copilot-harness\] attempt \d+: spawning:/gm) ?? []).length, 1);
    return { ...result, results: [...active.results.values()] };
  }
  try {
    const repaired = await run("repair", [
      { tool: "run_public_smoke_tests", args: {} },
      { tool: "edit", args: {
        path: `/workspace/${work}/probe.mjs`, old_str: "return 0;", new_str: "return 1;",
      } },
      { tool: "run_public_smoke_tests", args: {} },
      { tool: "check_candidate_syntax", args: {} },
    ]);
    assert.equal(repaired.code, 0);
    const before = JSON.parse(repaired.results[0]);
    const after = JSON.parse(repaired.results[2]);
    const syntax = JSON.parse(repaired.results[3]);
    assert.equal(before.status, "failed");
    assert.equal(before.exitCode, 1);
    assert.match(before.checks[0].stdout, /PROBE_CWD=\/workspace/);
    assert.match(before.checks[0].stdout, /PROBE_PRIVATE=false/);
    assert.doesNotMatch(before.checks[0].stdout, /do-not-inherit-test-sentinel|COPILOT_API_KEY|GITHUB_TOKEN/);
    assert.equal(after.exitCode, 0);
    assert.equal(syntax.exitCode, 0);
    assert.equal(readFileSync(testPath, "utf8"), publicTest);

    const invalid = await run("invalid", [
      { tool: "run_public_smoke_tests", args: { command: "node --eval 'process.exit(0)'", path: "/private" } },
    ]);
    assert.match(invalid.results[0], /takes no arguments|additional properties|not allowed|tool execution failed/i);
    assert.doesNotMatch(invalid.results[0], /PROBE_CWD/);
    const immutable = await run("immutable", [
      { tool: "edit", args: {
        path: `${runtimeTarget}/driver.cjs`, old_str: '"use strict";', new_str: 'throw new Error("modified");',
      } },
    ]);
    assert.match(immutable.results[0] ?? immutable.output, /read.only|EROFS|permission denied/i);
    assert.equal(readFileSync(`${runtimeTarget}/driver.cjs`, "utf8"), driverBefore.toString("utf8"));
    assert.equal(readFileSync(`${runtimeTarget}/config.json`, "utf8"), configBefore.toString("utf8"));
    return {
      cli: metadata.engine_versions.copilot, fixedTools: 2, shellTools: 0,
      smoke: "assertions-before/pass-after", syntax: "passed", publicTestPreserved: true,
      arbitraryArguments: "rejected", runtimeMutation: "rejected",
      referenceCheckoutVisible: false, credentialsForwarded: false, harnessAttemptsPerSession: 1,
    };
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}

export async function verifyRuntimeContract({
  runtimeDirectory, compiled, workspace, repositoryRoot, prepareWorkspace, stageRuntime,
}) {
  const assets = `${workspace}-runtime`;
  const name = `bc-eval-runtime-${randomUUID()}`;
  mkdirSync(path.join(workspace, ".gh-aw", "coding-agent-runtime"), { recursive: true });
  mkdirSync(path.join(workspace, ".github", "aw", "coding-agent-runtime"), { recursive: true });
  mkdirSync(path.join(workspace, "scripts"));
  const data = path.join(workspace, "data", "evaluations", "coding-agent");
  mkdirSync(path.join(data, "fixtures"), { recursive: true });
  for (const file of ["driver.cjs", "tools.cjs"]) {
    cpSync(path.join(repositoryRoot, ".github/aw/coding-agent-runtime", file),
      path.join(workspace, ".github/aw/coding-agent-runtime", file));
  }
  cpSync(path.join(repositoryRoot, "scripts/coding-agent-evals.mjs"),
    path.join(workspace, "scripts/coding-agent-evals.mjs"));
  cpSync(path.join(runtimeDirectory, "node_modules"), path.join(workspace, "node_modules"),
    { recursive: true, dereference: true });
  const candidate = 'import fs from "node:fs";\n' +
    'console.log("PROBE_CWD=" + process.cwd()); console.log("PROBE_ENV=" + JSON.stringify(process.env));\n' +
    'console.log("PROBE_PRIVATE=" + fs.existsSync("/repo/tests/agent-evals/checks.mjs"));\n' +
    "export function probe() { return 0; }\n";
  writeFileSync(path.join(data, "fixtures", "probe.mjs"), candidate);
  const suite = JSON.parse(readFileSync(path.join(repositoryRoot, "data/evaluations/coding-agent/suite.json"), "utf8"));
  writeFileSync(path.join(data, "suite.json"), JSON.stringify({
    schemaVersion: 1, id: "offline-runtime-probe", minimumPassRate: 1, image: suite.image,
    cases: [{
      id: "probe", function: "probe", source: "reference-solution.mjs",
      prompt: "Return 1.", smoke: [{ args: [], value: 1 }],
    }],
  }));
  const manifest = prepareWorkspace(workspace, { revision: "a".repeat(40), model: "auto" });
  stageRuntime(workspace, assets, manifest);
  const config = JSON.parse(readFileSync(path.join(assets, "config.json"), "utf8"));
  config.workspace = "/workspace";
  writeFileSync(path.join(assets, "config.json"), JSON.stringify(config));
  writeFileSync(path.join(assets, "profile.lock.yml"), compiled);
  const mounts = [
    [workspace, "/workspace", false],
    [assets, runtimeTarget, true],
    [path.join(runtimeDirectory, "gh-aw"), "/runtime-root/gh-aw/actions", true],
    [path.join(runtimeDirectory, "copilot"), "/runtime/copilot", true],
    [path.join(runtimeDirectory, "bin"), "/runtime/bin", true],
    [path.join(assets, "profile.lock.yml"), "/profile.lock.yml", true],
    [fileURLToPath(import.meta.url), "/verify.mjs", true],
  ];
  for (const [source] of mounts) assert.doesNotMatch(source, /[,\r\n]/, "Unsafe Docker mount source");
  const args = [
    "run", "--rm", "--name", name, "--pull=never", "--platform", "linux/amd64",
    "--network=none", "--add-host", "api-proxy:127.0.0.1", "--read-only", "--cap-drop=ALL",
    "--security-opt=no-new-privileges", "--user", "1001:1001", "--pids-limit=128",
    "--memory=2g", "--cpus=2", "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
    ...mounts.flatMap(([source, target, readonly]) =>
      ["--mount", `type=bind,source=${source},target=${target}${readonly ? ",readonly" : ""}`]),
    "--workdir", "/workspace", "--entrypoint", "/runtime/bin/node", image, "/verify.mjs", "--child",
  ];
  try {
    const result = await execute("docker", args, { timeoutMs: 600_000 });
    assert.equal(result.code, 0, result.output.slice(-5000));
    const summary = result.output.split(/\r?\n/).find((line) => line.startsWith('{"cli":'));
    assert.ok(summary, "Missing runtime regression evidence");
    return JSON.parse(summary);
  } finally {
    const cleanup = spawnSync("docker", ["rm", "--force", name], { encoding: "utf8", timeout: 30_000 });
    assert.ok(cleanup.status === 0 || /No such container/.test(cleanup.stderr),
      `Runtime cleanup failed: ${cleanup.stderr}`);
    rmSync(assets, { recursive: true, force: true });
  }
}

if (process.argv[2] === "--child") {
  console.log(JSON.stringify(await verifyInsideContainer()));
}
