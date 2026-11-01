const phases = new Set([
  "configuration", "approval", "dataset", "capabilities", "evaluation", "request",
  "response", "parse-events", "validate-turn", "check-outcome", "cleanup", "write-report", "completion",
]);
const failureCodes = new Map([
  ["AssertionError", "assertion_failed"],
  ["SyntaxError", "invalid_json"],
  ["TimeoutError", "timed_out"],
  ["AbortError", "aborted"],
  ["TypeError", "type_error"],
]);

export function summarizeFailure(error, { phase = "evaluation", turn, status } = {}) {
  const summary = {
    phase: phases.has(phase) ? phase : "evaluation",
    code: failureCodes.get(error?.name) ?? "unexpected_error",
  };
  if (Number.isSafeInteger(turn) && turn > 0) summary.turn = turn;
  if (Number.isInteger(status) && status >= 100 && status <= 599) summary.status = status;
  return summary;
}

const count = (value) => Array.isArray(value) ? value.length : 0;

export function summarizeResult(result) {
  // Only case metadata comes from the checked-in dataset. Runtime payloads and
  // exception messages (including assertion actual/expected values) stay in memory.
  const summary = {
    case: result.case,
    expectedBehaviour: result.expectedBehaviour,
    passed: result.passed === true,
    turns: result.turns.map((turn) => ({
      hasText: typeof turn.text === "string" && turn.text.trim().length > 0,
      hasState: Boolean(turn.state),
      modelResponse: turn.response?.origin === "model",
      groundedResponse: turn.response?.kind === "grounded",
      citationCount: count(turn.citations),
      errorCount: count(turn.errors),
      warningCount: count(turn.warnings),
    })),
  };
  if (Object.hasOwn(result, "error")) {
    summary.error = summarizeFailure(result.error, result.failureContext);
  }
  if (Object.hasOwn(result, "cleanupError")) {
    summary.cleanupError = summarizeFailure(result.cleanupError, result.cleanupContext);
  }
  return summary;
}
