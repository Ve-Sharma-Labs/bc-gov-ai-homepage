import { EventType, type BaseEvent } from "@ag-ui/core";
import { describe, expect, it } from "vitest";
import { capabilitiesSchema, discoverySummarySchema, runOptionsSchema } from "@/lib/contract";
import { historyForAgent, initialStreamState, streamReducer, type StreamState } from "@/lib/stream";
import { discoveryFixture } from "./discovery-fixtures";
import { guidedCapabilities } from "./fixtures";

const start = () => streamReducer(initialStreamState, {
  type: "start", runId: "fixture-run", messageId: "fixture-user",
  prompt: "TEST FIXTURE motorcycle goal", mode: "general",
  discovery: { revision: 0, threadId: "fixture-thread" },
});
const event = (state: StreamState, value: BaseEvent) => streamReducer(state, {
  type: "event", runId: "fixture-run", event: value,
});
const contextEvent = (value: unknown = discoveryFixture()): BaseEvent => ({
  type: EventType.CUSTOM, name: "bc.discovery", value,
});
const text = () => {
  let state = event(start(), {
    type: EventType.CUSTOM, name: "bc.response",
    value: { version: 1, kind: "dialogue", origin: "application" },
  });
  state = event(state, { type: EventType.TEXT_MESSAGE_START, messageId: "fixture-answer", role: "assistant" });
  return event(state, { type: EventType.TEXT_MESSAGE_CONTENT, messageId: "fixture-answer", delta: "TEST FIXTURE question" });
};
const finish = (state: StreamState) => event(state, {
  type: EventType.RUN_FINISHED, runId: "fixture-run", threadId: "fixture-thread",
});

describe("versioned discovery contract", () => {
  it("accepts only narrow general-mode commands and an advertised version", () => {
    const options = { version: 4, mode: "general", discovery: { action: "respond", revision: 0 } };
    expect(runOptionsSchema.safeParse(options).success).toBe(true);
    for (const extra of [
      { journeyId: "licence-renewal" }, { researchRequested: true }, { mode: "pathway" },
      { mode: "contextual-demo" }, { profile: { age: 30 } }, { version: 2 },
    ]) expect(runOptionsSchema.safeParse({ ...options, ...extra }).success).toBe(false);
    expect(runOptionsSchema.safeParse({ ...options, discovery: { action: "skip", revision: 0 } }).success).toBe(false);
    expect(capabilitiesSchema.safeParse({
      ...guidedCapabilities, discoveryAvailable: true, requestVersions: [1, 2, 3, 4],
    }).success).toBe(true);
    expect(capabilitiesSchema.safeParse({
      ...guidedCapabilities, discoveryAvailable: true, requestVersions: [1, 2, 3],
    }).success).toBe(false);
  });

  it("rejects invented records, contradictory facts, duplicates, and excessive questions", () => {
    const fixture = discoveryFixture();
    expect(discoverySummarySchema.safeParse(fixture).success).toBe(true);
    for (const invalid of [
      { ...fixture, questionCount: 4 },
      { ...fixture, facts: [fixture.facts[0], fixture.facts[0]] },
      { ...fixture, facts: [{ ...fixture.facts[0], provenance: "government-record" }] },
      { ...fixture, facts: [{ ...fixture.facts[0], status: "unknown" }] },
      { ...fixture, suggestions: [{ journeyId: "licence-renewal", reason: "not yet" }] },
      { ...fixture, phase: "plan" },
    ]) expect(discoverySummarySchema.safeParse(invalid).success).toBe(false);
  });
});

describe("discovery stream lifecycle", () => {
  it("commits context only after terminal success and never replays personal turns", () => {
    let state = event(text(), contextEvent());
    expect(state.discovery).toBeNull();
    expect(state.pendingDiscovery?.goalId).toBe("motorcycle");
    state = finish(state);
    expect(state.discovery?.revision).toBe(1);
    expect(state.pendingDiscovery).toBeNull();
    expect(state.messages.every((message) => message.discovery)).toBe(true);
    expect(historyForAgent(state.messages)).toEqual([]);
    expect(historyForAgent(state.messages, "pathway")).toEqual([]);
    expect(historyForAgent(state.messages, "contextual-demo")).toEqual([]);
  });

  it("discards interrupted context and ignores late events after Stop", () => {
    const pending = event(text(), contextEvent());
    const stopped = streamReducer(pending, { type: "stop", runId: "fixture-run" });
    expect(stopped.pendingDiscovery).toBeNull();
    expect(stopped.discovery).toBeNull();
    expect(event(stopped, contextEvent())).toBe(stopped);
    expect(finish(stopped)).toBe(stopped);
  });

  it("rejects mismatched revisions, threads, and duplicate updates", () => {
    for (const summary of [
      discoveryFixture({ revision: 3 }), discoveryFixture({ threadId: "someone-else" }),
    ]) {
      expect(event(text(), contextEvent(summary)).errorCode).toBe("DISCOVERY_CHANGED");
    }
    expect(event(event(text(), contextEvent()), contextEvent()).status).toBe("error");
    expect(finish(text()).errorCode).toBe("DISCOVERY_CHANGED");
    const legacy = streamReducer(initialStreamState, {
      type: "start", runId: "fixture-run", messageId: "fixture-user", prompt: "Public question",
    });
    expect(event(legacy, contextEvent()).status).toBe("error");
  });

  it("clears context on reset and mode changes, and refreshes without resending", () => {
    const complete = finish(event(text(), contextEvent()));
    expect(streamReducer(complete, { type: "reset" })).toEqual(initialStreamState);
    expect(streamReducer(complete, { type: "clear-context" }).discovery).toBeNull();
    expect(streamReducer(complete, { type: "clear-discovery" }).discovery).toBeNull();
    const refreshed = streamReducer(complete, { type: "refresh-discovery", summary: discoveryFixture({ revision: 2 }) });
    expect(refreshed.discovery?.revision).toBe(2);
    expect(refreshed.status).toBe("idle");
    expect(refreshed.messages).toEqual(complete.messages);
  });
});
