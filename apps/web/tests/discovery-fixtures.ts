import type { DiscoverySummary } from "@/lib/contract";

export function discoveryFixture(overrides: Partial<DiscoverySummary> = {}): DiscoverySummary {
  return {
    version: 1,
    threadId: "fixture-thread",
    revision: 1,
    phase: "understand",
    goalId: "motorcycle",
    goalLabel: "Planning for a motorcycle",
    about: "you",
    questionCount: 1,
    facts: [{ key: "timeframe", label: "When you are planning", value: "Next year", status: "provided", provenance: "citizen-answer" }],
    question: {
      id: "fixture-age-question",
      factKey: "age",
      text: "How old will you be when you expect to start riding? An age range is fine.",
      reason: "TEST FIXTURE: optional planning context, not an eligibility decision.",
      choices: ["Under 19", "19 or older", "Not sure"],
    },
    suggestions: [],
    suggestedDemoId: null,
    expiresAt: "2099-01-01T00:00:00Z",
    ...overrides,
  };
}
