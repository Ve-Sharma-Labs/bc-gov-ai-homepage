"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { createTaskFileTools } = require("./tools.cjs");

function required(name) {
  assert.ok(process.env[name], `${name} is required`);
  return process.env[name];
}

function assertReadOnlyRuntime() {
  assert.equal(process.platform, "linux", "Evaluation driver requires the isolated Linux runtime");
  const directory = fs.realpathSync(__dirname);
  const mount = fs.readFileSync("/proc/self/mountinfo", "utf8").split("\n").find((line) => {
    const fields = line.split(" ");
    const target = fields[4]?.replace(/\\([0-7]{3})/g, (_, octal) => String.fromCharCode(parseInt(octal, 8)));
    return target === directory && fields[5].split(",").includes("ro");
  });
  assert.ok(mount, "Evaluation executable and configuration require their own read-only runtime mount");
}

async function main() {
  assertReadOnlyRuntime();
  const sdk = require("./node_modules/@github/copilot-sdk");
  const actions = path.join(required("RUNNER_TEMP"), "gh-aw", "actions");
  const { runWithCopilotSDK } = require(path.join(actions, "copilot_sdk_session.cjs"));
  const { parseCopilotSDKToolConfig } = require(path.join(actions, "copilot_sdk_tool_config.cjs"));
  const { parseMultiProviderJson } = require(path.join(actions, "copilot_sdk_multi_provider.cjs"));
  const { readRegular } = await import(pathToFileURL(path.join(__dirname, "inputs.mjs")).href);
  const config = JSON.parse(fs.readFileSync(path.join(__dirname, "config.json"), "utf8"));
  assert.equal(fs.realpathSync(required("GITHUB_WORKSPACE")), config.workspace);
  const tools = createTaskFileTools(sdk, config, readRegular);
  const toolConfig = parseCopilotSDKToolConfig(required("GH_AW_COPILOT_SDK_TOOL_CONFIG"));
  assert.equal(toolConfig.capabilities.bash, false, "Free-form shell execution must remain disabled");
  const providers = parseMultiProviderJson(required("GH_AW_COPILOT_SDK_MULTI_PROVIDER_JSON"));
  assert.ok(providers, "Invalid provider configuration");

  class EvaluationClient extends sdk.CopilotClient {
    createSession(sessionConfig) {
      for (const tool of tools) sessionConfig.availableTools.addCustom(tool.name);
      return super.createSession({
        ...sessionConfig,
        tools: [...sessionConfig.tools, ...tools],
        availableTools: new sdk.ToolSet().addCustom("read_task_file").addCustom("edit_candidate").addMcp("*"),
        excludedTools: new sdk.ToolSet().addBuiltIn("*"),
      });
    }
  }

  const result = await runWithCopilotSDK({
    sdkUri: required("COPILOT_SDK_URI"),
    connectionToken: required("COPILOT_CONNECTION_TOKEN"),
    prompt: fs.readFileSync(required("GH_AW_PROMPT"), "utf8"),
    model: required("COPILOT_MODEL"),
    providers: providers.providers,
    models: providers.models,
    permissionConfig: toolConfig.permissions,
    toolConfig,
    sdkModule: { ...sdk, CopilotClient: EvaluationClient },
    logger: (message) => process.stderr.write(`[coding-agent-eval-driver] ${message}\n`),
  });
  process.exit(result.exitCode);
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`[coding-agent-eval-driver] ${error.message}\n`);
    process.exit(1);
  });
}

module.exports = { assertReadOnlyRuntime };
