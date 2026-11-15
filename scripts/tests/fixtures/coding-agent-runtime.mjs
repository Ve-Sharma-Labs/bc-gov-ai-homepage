import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import { networkInterfaces } from "node:os";
import path from "node:path";

const require = createRequire(import.meta.url);
const model = "claude-sonnet-5";
const work = "test-results/coding-agent-evals/work";
const smoke = `node --test ${work}/*.test.mjs`;
const single = `node --test ${work}/probe.test.mjs`;
const syntax = `node --check ${work}/probe.mjs`;

function compiledField(compiled, name) {
  const value = compiled.match(new RegExp(`^ +${name}: '?([^\\r\\n]+)`, "m"))?.[1];
  assert.ok(value, `Missing compiled ${name}`);
  return value.replace(/'$/, "").replace(/^"|"$/g, "");
}

async function execute(command, args, options) {
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  const collect = (chunk) => {
    output += chunk;
    if (output.length > 2 * 1024 * 1024) child.kill("SIGKILL");
  };
  child.stdout.on("data", collect);
  child.stderr.on("data", collect);
  const timer = setTimeout(() => child.kill("SIGKILL"), 120_000);
  try {
    const result = await new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("exit", (code, signal) => resolve({ code, signal }));
    });
    assert.equal(result.signal, null, "Runtime exceeded the probe's time or output bound");
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
          ...message, tool_calls: message.tool_calls?.map(({ index, ...call }) => call),
        },
      }],
    }));
    return;
  }
  response.writeHead(200, { "Content-Type": "text/event-stream" });
  response.write(`data: ${JSON.stringify({
    ...envelope,
    choices: [{ index: 0, delta: message, finish_reason: null }],
  })}\n\n`);
  response.write(`data: ${JSON.stringify({
    ...envelope, choices: [{ index: 0, delta: {}, finish_reason: finishReason }],
  })}\n\n`);
  response.end("data: [DONE]\n\n");
}

// The provider supplies fixed tool calls, never permission decisions or model inference.
export async function verifyRuntimeContract({ runtimeDirectory, compiled, workspace }) {
  assert.equal(process.platform, "linux", "Run the probe in the documented disposable Linux container");
  assert.match(process.version, /^v24\./);
  assert.equal(process.env.COPILOT_OFFLINE, "true");
  assert.ok(Object.values(networkInterfaces()).flat().every((address) => address.internal),
    "The runtime probe requires --network=none");
  const binary = path.join(runtimeDirectory, "copilot");
  const actions = path.join(runtimeDirectory, "gh-aw");
  const toolConfig = JSON.parse(compiledField(compiled, "GH_AW_COPILOT_SDK_TOOL_CONFIG"));
  const serverArgs = JSON.parse(compiledField(compiled, "GH_AW_COPILOT_SDK_SERVER_ARGS"));
  const retries = compiledField(compiled, "GH_AW_HARNESS_MAX_RETRIES");
  const denialLimit = compiledField(compiled, "GH_AW_MAX_TOOL_DENIALS");
  const { resolveRetryConfig } = require(path.join(actions, "harness_retry_config.cjs"));
  assert.equal(resolveRetryConfig({ GH_AW_HARNESS_MAX_RETRIES: retries }).maxRetries, 0);

  const { buildCopilotSDKPermissionHandler } = require(path.join(actions, "copilot_sdk_permissions.cjs"));
  const permission = buildCopilotSDKPermissionHandler(toolConfig.permissions,
    () => assert.fail("The workflow must not select blanket approval"));
  for (const command of [smoke, single, syntax]) {
    assert.equal(permission({ kind: "shell", fullCommandText: command }).kind, "approve-once", command);
  }
  const deniedCommands = [
    "node --eval 'process.exit(0)'", "node scripts/coding-agent-evals.mjs grade",
    "node --test-other file.mjs", "npm install", "curl https://example.com",
    "env node --test probe.test.mjs", `${single} && node --eval 'process.exit(0)'`,
  ];
  for (const command of deniedCommands) {
    assert.equal(permission({ kind: "shell", fullCommandText: command }).kind, "reject", command);
  }

  mkdirSync(path.join(workspace, work), { recursive: true });
  mkdirSync("/tmp/gh-aw", { recursive: true });
  writeFileSync(path.join(workspace, work, "probe.mjs"), "export const value = 0;\n");
  const testPath = path.join(workspace, work, "probe.test.mjs");
  const publicTest = 'import assert from "node:assert/strict"; import test from "node:test";\n' +
    'import { value } from "./probe.mjs"; test("synthetic smoke", () => assert.equal(value, 1));\n';
  writeFileSync(testPath, publicTest);
  const home = path.join(workspace, "home");
  const runner = path.join(workspace, "runner");
  mkdirSync(home);
  mkdirSync(runner);
  const prompt = path.join(runner, "prompt.txt");
  writeFileSync(prompt, "Execute the fixed synthetic tool calls from the offline fixture, then stop.");
  const env = {
    PATH: process.env.PATH, HOME: home, COPILOT_HOME: path.join(home, ".copilot"),
    NODE_PATH: path.join(runtimeDirectory, "node_modules"),
    CI: "true", COPILOT_OFFLINE: "true", COPILOT_AUTO_UPDATE: "false",
    COPILOT_API_KEY: "dummy-byok-key-for-offline-mode",
    COPILOT_PROVIDER_BASE_URL: "http://127.0.0.1:10000",
    COPILOT_PROVIDER_TYPE: "openai", COPILOT_PROVIDER_WIRE_API: "completions",
    COPILOT_MODEL: model, COPILOT_AGENT_RUNNER_TYPE: "STANDALONE",
    GITHUB_WORKSPACE: workspace, RUNNER_TEMP: runner,
    GITHUB_REPOSITORY: "fixture/permission-probe", GITHUB_EVENT_NAME: "pull_request",
    GITHUB_RUN_ID: "1", GITHUB_RUN_ATTEMPT: "1", GITHUB_OUTPUT: path.join(runner, "output.txt"),
    GH_AW_PHASE: "agent", GH_AW_PROMPT: prompt, AWF_REFLECT_ENABLED: "1",
    GH_AW_TIMEOUT_MINUTES: "20", GH_AW_MAX_TURNS: "60", GH_AW_MAX_AI_CREDITS: "300",
    GH_AW_COPILOT_SDK_SERVER_ARGS: JSON.stringify(serverArgs),
    GH_AW_COPILOT_SDK_TOOL_CONFIG: JSON.stringify(toolConfig),
    GH_AW_HARNESS_MAX_RETRIES: retries, GH_AW_MAX_TOOL_DENIALS: denialLimit,
  };
  const metadata = JSON.parse(compiled.match(/^# gh-aw-metadata: (.+)$/m)[1]);
  const sdkPackage = JSON.parse(readFileSync(path.join(runtimeDirectory,
    "node_modules", "@github", "copilot-sdk", "package.json"), "utf8"));
  assert.equal(sdkPackage.version, metadata.engine_versions["copilot-sdk"]);
  const version = spawnSync(binary, ["--no-auto-update", "--version"], {
    cwd: workspace, env, encoding: "utf8", timeout: 60_000, maxBuffer: 64 * 1024,
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
        assert.ok(raw.length < 2 * 1024 * 1024, "Oversized synthetic request");
      }
      const body = JSON.parse(raw);
      active.requests++;
      assert.ok(active.requests <= active.steps.length + 1, "Unexpected recovery/model request");
      for (const message of body.messages.filter((item) => item.role === "tool")) {
        active.results.set(message.tool_call_id, message.content);
      }
      const index = active.results.size;
      const step = active.steps[index];
      if (!step) {
        completion(response, body, { role: "assistant", content: "Offline fixture complete." }, "stop");
        return;
      }
      const definition = body.tools?.find((tool) => tool.function?.name === step.tool)?.function;
      assert.ok(definition, `Missing native ${step.tool} tool`);
      for (const key of Object.keys(step.args)) {
        assert.ok(definition.parameters.properties[key], `Unknown ${step.tool} argument ${key}`);
      }
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
  const bash = (command) => ({ tool: "bash", args: { command, description: "Synthetic offline probe" } });
  async function run(name, steps, native = false) {
    active = { name, steps, requests: 0, results: new Map() };
    const nativeArgs = serverArgs.filter((arg, index) =>
      arg !== "--headless" && arg !== "--port" && serverArgs[index - 1] !== "--port");
    const result = await execute(native ? binary : process.execPath, native
      ? [...nativeArgs, "--add-dir", workspace, "--prompt", "Execute the offline fixture, then stop."]
      : [path.join(actions, "copilot_harness.cjs"), process.execPath,
        path.join(actions, "copilot_sdk_driver.cjs"), binary], {
      cwd: workspace, env: native ? env : { ...env, COPILOT_SDK_URI: "http://127.0.0.1:3002" },
    });
    assert.ifError(active.error);
    assert.ok(active.requests > 0,
      `Runtime stopped before the offline provider was reached; exit ${result.code}: ${result.output.slice(-600)}`);
    const attempts = result.output.match(/^\[copilot-harness\] attempt \d+: spawning:/gm) ?? [];
    if (!native) assert.equal(attempts.length, 1, "A failed SDK session must not start another attempt");
    return { ...result, requests: active.requests, results: [...active.results.values()] };
  }
  try {
    const native = await run("native", [bash(smoke)], true);
    assert.match(native.results[0], /Permission denied/);
    const repaired = await run("repair", [
      bash(smoke),
      { tool: "edit", args: {
        path: path.join(workspace, work, "probe.mjs"),
        old_str: "export const value = 0;", new_str: "export const value = 1;",
      } },
      bash(smoke), bash(single), bash(syntax),
    ]);
    assert.equal(repaired.code, 0, "Full harness did not complete the positive probe");
    assert.match(repaired.results[0], /ERR_ASSERTION/);
    for (const index of [2, 3, 4]) {
      assert.match(repaired.results[index], /completed with exit code 0/);
    }
    assert.equal(readFileSync(testPath, "utf8"), publicTest);
    const denied = await run("denied", [bash(deniedCommands[0])]);
    assert.equal(denied.code, 1);
    assert.equal(denied.requests, 1, "Permission refusal must stop further model requests");
    const guards = denied.output.split(/\r?\n/).filter((line) =>
      line.startsWith('{"type":"guard.tool_denials_exceeded"')).map((line) => JSON.parse(line));
    assert.equal(guards.length, 1);
    assert.equal(guards[0].data.denialCount, 1);
    assert.equal(guards[0].data.threshold, 1);
    return {
      cli: metadata.engine_versions.copilot, nativeSmoke: "denied",
      sdkSmoke: "assertions-before/pass-after", sdkEdit: "candidate-only", sdkSyntax: "passed",
      negativeRules: deniedCommands.length, harnessAttempts: 1, denialRequests: denied.requests,
      deniedExit: denied.code,
    };
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}
