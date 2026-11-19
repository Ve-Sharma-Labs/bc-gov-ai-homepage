"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");
const { networkInterfaces } = require("node:os");
const { pathToFileURL } = require("node:url");
const { createEvaluationTools, validateJson } = require("./tools.cjs");

async function probe() {
  const write = fs.writeFileSync.bind(fs);
  const stringify = JSON.stringify;
  const request = JSON.parse(fs.readFileSync(0, "utf8"));
  const candidate = await import(`data:text/javascript;base64,${request.source}`);
  const fn = candidate[request.function];
  assert.equal(typeof fn, "function", "Missing required export");
  const results = [];
  for (const invocation of request.invocations) {
    let value;
    try {
      value = await fn(...invocation.args);
    } catch {
      results.push({ kind: "throw" });
      continue;
    }
    if (value === undefined) results.push({ kind: "return", undefined: true });
    else {
      validateJson(value);
      results.push({ kind: "return", value });
    }
  }
  write(3, stringify({ results }));
}

async function main() {
  assert.equal(process.platform, "linux");
  assert.equal(process.pid, 1, "The check worker requires its own PID namespace");
  assert.ok(Object.values(networkInterfaces()).flat().every((address) => address.internal),
    "The check worker requires a network-disabled container");
  assert.equal(process.env.GITHUB_TOKEN, undefined);
  assert.equal(process.env.COPILOT_CONNECTION_TOKEN, undefined);
  assert.equal(fs.existsSync("/var/run/docker.sock"), false);
  const mounts = fs.readFileSync("/proc/self/mountinfo", "utf8").split("\n").map((line) => line.split(" "));
  for (const target of ["/runtime", "/eval/test-results/coding-agent-evals/work"]) {
    assert.ok(mounts.some((fields) => fields[4] === target && fields[5].split(",").includes("ro")),
      "The check worker requires read-only runtime and candidate mounts");
  }
  const { readRegular } = await import(pathToFileURL(path.join(__dirname, "inputs.mjs")).href);
  const config = JSON.parse(fs.readFileSync(path.join(__dirname, "config.json"), "utf8"));
  const tools = createEvaluationTools({ defineTool: (name, definition) => ({ name, ...definition }) }, config, readRegular, {
    recordProbe: (record) => process.stderr.write(`${JSON.stringify({ type: "candidate.self_check", ...record })}\n`),
  });
  const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  const operations = new Map();
  const send = (id, value) => process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id, ...value })}\n`);
  input.on("line", (line) => {
    void (async () => {
      if (Buffer.byteLength(line) > 64 * 1024) throw new Error("Oversized worker request");
      const request = JSON.parse(line);
      if (request.method === "notifications/cancelled") {
        operations.get(request.params?.requestId)?.abort();
        return;
      }
      if (request.id === undefined) return;
      if (request.method === "initialize") {
        send(request.id, { result: {
          protocolVersion: "2024-11-05", capabilities: { tools: {} },
          serverInfo: { name: "coding-agent-checks", version: "1" },
        } });
      } else if (request.method === "ping") send(request.id, { result: {} });
      else if (request.method === "tools/list") {
        send(request.id, { result: { tools: tools.map((tool) => ({
          name: tool.name, description: tool.description, inputSchema: tool.parameters,
        })) } });
      } else if (request.method === "tools/call") {
        const tool = tools.find((item) => item.name === request.params?.name);
        if (!tool) send(request.id, { error: { code: -32602, message: "Unknown check operation" } });
        else {
          const controller = new AbortController();
          operations.set(request.id, controller);
          try {
            const result = await tool.handler(request.params.arguments, { signal: controller.signal });
            send(request.id, { result: {
              isError: result.resultType !== "success", content: [{ type: "text", text: result.textResultForLlm }],
            } });
          } finally {
            operations.delete(request.id);
          }
        }
      } else send(request.id, { error: { code: -32601, message: "Unsupported method" } });
    })().catch((error) => {
      process.stderr.write(`Check worker failed: ${error.message}\n`);
      process.exit(1);
    });
  });
  input.on("close", () => {
    for (const controller of operations.values()) controller.abort();
  });
}

(process.argv[2] === "--probe" ? probe() : main()).catch((error) => {
  process.stderr.write(`Check worker startup failed: ${error.message}\n`);
  process.exit(1);
});
