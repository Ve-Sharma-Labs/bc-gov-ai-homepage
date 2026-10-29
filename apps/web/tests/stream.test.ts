import { describe, expect, it } from "vitest";
import type { BaseEvent } from "@ag-ui/core";
import { historyForAgent, initialStreamState, needsSources, streamReducer, type StreamState } from "@/lib/stream";
import { contextArtifactsFixture } from "./fixtures";

const start = () => streamReducer(initialStreamState, { type: "start", runId: "run-1", messageId: "user-1", prompt: "My question" });
const event = (state: StreamState, data: Record<string, unknown>) => streamReducer(state, { type: "event", runId: "run-1", event: data as unknown as BaseEvent });
const text = () => event(event(start(), { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" }), { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "A sourced answer." });

describe("AG-UI presentation reducer", () => {
  it.each([
    { kind: "dialogue", origin: "application", sources: false, history: 1 },
    { kind: "dialogue", origin: "model", sources: false, history: 2 },
    { kind: "grounded", origin: "model", sources: true, history: 1 },
    { kind: "handoff", origin: "application", sources: false, history: 1 },
    { kind: "handoff", origin: "model", sources: true, history: 1 },
  ])("separates $origin $kind source requirements and history", ({ kind, origin, sources, history }) => {
    let state = event(start(), { type: "CUSTOM", name: "bc.response", value: { version: 1, kind, origin } });
    state = event(state, { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" });
    state = event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "TEST FIXTURE response" });
    state = event(state, { type: "TEXT_MESSAGE_END", messageId: "answer-1" });
    if (!sources) expect(state.announcement).not.toContain("source checks");
    state = event(state, { type: "RUN_FINISHED" });
    expect(state.messages[1].response).toEqual({ version: 1, kind, origin });
    expect(needsSources(state.messages[1])).toBe(sources);
    expect(historyForAgent(state.messages)).toHaveLength(history);
    if (!sources) expect(state.announcement).not.toContain("sources");
  });

  it("defaults legacy responses to factual guidance rather than inferring dialogue from their text", () => {
    const state = event(text(), { type: "RUN_FINISHED" });
    expect(needsSources(state.messages[1])).toBe(true);
    expect(state.messages[1].response).toBeUndefined();
  });

  it("reports a missing general binding after SSE startup without changing the mode or manufacturing a response", () => {
    let state = event(start(), { type: "RUN_STARTED" });
    state = event(state, { type: "CUSTOM", name: "status", value: { version: 1, phase: "connecting" } });
    state = event(state, { type: "RUN_ERROR", code: "GENERAL_AGENT_NOT_CONFIGURED", message: "Do not display raw server details" });
    expect(state.status).toBe("error");
    expect(state.error).toContain("General B.C. chat is not connected");
    expect(state.messages).toHaveLength(1);
    expect(state.errorCode).toBe("GENERAL_AGENT_NOT_CONFIGURED");
  });

  it("accepts response context after an empty start but never lets late metadata downgrade factual text", () => {
    const empty = event(start(), { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" });
    const context = { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "dialogue", origin: "application" } };
    expect(event(empty, context).messages[1].response?.kind).toBe("dialogue");
    const factual = text();
    expect(event(factual, context)).toBe(factual);
    const complete = event(factual, { type: "RUN_FINISHED" });
    expect(event(complete, context)).toBe(complete);
  });

  it("rejects unsupported response context and ignores a second response classification", () => {
    const invalid = event(start(), { type: "CUSTOM", name: "bc.response", value: { version: 2, kind: "dialogue", origin: "model" } });
    expect(invalid.status).toBe("error");
    const grounded = event(start(), { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "grounded", origin: "model" } });
    expect(event(grounded, { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "dialogue", origin: "model" } })).toBe(grounded);
  });

  it.each(["GREETING", "JOURNEY_REQUIRED"])("normalizes legacy %s without an error, fabricated model turn or mandatory selector", (code) => {
    const state = event(start(), { type: "RUN_ERROR", code, message: "Unsafe provider detail" });
    expect(state.status).toBe("complete");
    expect(state.error).toBeNull();
    expect(state.messages[1]).toMatchObject({ response: { kind: "dialogue", origin: "application" }, status: "complete" });
    expect(historyForAgent(state.messages)).toEqual([{ id: "user-1", role: "user", content: "My question" }]);
    expect(JSON.stringify(state)).not.toContain("Unsafe provider detail");
    expect(event(text(), { type: "RUN_ERROR", code }).status).toBe("error");
  });

  it("resets response context between runs and freezes metadata and citations after Stop", () => {
    const stopped = streamReducer(text(), { type: "stop", runId: "run-1" });
    expect(event(stopped, { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "dialogue", origin: "application" } })).toBe(stopped);
    expect(event(stopped, { type: "CUSTOM", name: "annotations", value: { messageId: "answer-1", annotations: [{ sourceId: "icbc" }] } })).toBe(stopped);
    const dialogue = event(start(), { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "dialogue", origin: "model" } });
    expect(streamReducer(dialogue, { type: "start", runId: "run-2", messageId: "user-2", prompt: "Next" }).response).toBeNull();
  });

  it("requires a terminal run event, not just text end, for completion", () => {
    const pending = event(text(), { type: "TEXT_MESSAGE_END", messageId: "answer-1" });
    expect(pending.messages[1].status).toBe("pending");
    const complete = event(pending, { type: "RUN_FINISHED" });
    expect(complete.status).toBe("complete");
    expect(complete.messages.every((message) => message.status === "complete")).toBe(true);
    expect(historyForAgent(complete.messages)).toHaveLength(1);
  });

  it("completes validated text with a fixed warning when later details are withheld", () => {
    let state = text();
    state = event(state, {
      type: "CUSTOM",
      name: "bc.warning",
      value: { version: 1, code: "DETAILS_WITHHELD" },
    });
    expect(state.warning).toContain("could not be verified");
    state = event(state, { type: "TEXT_MESSAGE_END", messageId: "answer-1" });
    state = event(state, { type: "RUN_FINISHED" });
    expect(state.status).toBe("complete");
    expect(state.messages[1].status).toBe("complete");
    expect(state.error).toBeNull();
  });

  it("preserves partial content and draft when a stream ends early", () => {
    const state = streamReducer(text(), { type: "closed", runId: "run-1" });
    expect(state.status).toBe("interrupted");
    expect(state.messages[1]).toMatchObject({ content: "A sourced answer.", status: "partial" });
    expect(state.prompt).toBe("My question");
    expect(historyForAgent(state.messages)).toEqual([]);
  });

  it("keeps cancellation terminal, ignoring late text and finish events", () => {
    const stopped = streamReducer(text(), { type: "stop", runId: "run-1" });
    const late = event(stopped, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "Not wanted" });
    expect(event(late, { type: "RUN_FINISHED" }).status).toBe("stopped");
    expect(late.messages[1].content).toBe("A sourced answer.");
  });

  it("retains citations delivered after text, a snapshot, and RUN_FINISHED", () => {
    let state = event(text(), { type: "CUSTOM", name: "annotations", value: { messageId: "answer-1", annotations: [{ type: "citation", sourceId: "icbc", url: "https://www.icbc.com/driver-licensing" }] } });
    state = event(state, { type: "MESSAGES_SNAPSHOT", messages: [{ id: "answer-1", role: "assistant", content: "Updated answer." }] });
    state = event(state, { type: "RUN_FINISHED" });
    state = event(state, { type: "CUSTOM", name: "annotations", value: { messageId: "answer-1", annotations: [{ type: "citation", sourceId: "service", url: "https://www2.gov.bc.ca/gov/content/home" }] } });
    expect(state.messages[1].citations).toHaveLength(2);
    expect(state.messages[1].content).toBe("Updated answer.");
    expect(state.status).toBe("complete");
  });

  it("supports native URL annotations before their message and rejects unsafe destinations", () => {
    let state = event(start(), { type: "CUSTOM", name: "annotations", value: {
      messageId: "answer-1",
      annotations: [
        { type: "citation", title: "Official guidance", url: "https://www.icbc.com/driver-licensing", annotated_regions: [{ type: "text_span", start_index: 0, end_index: 10 }] },
        { url: "javascript:alert(1)" },
        { url: "https://www.icbc.com.evil.test/" },
      ],
    } });
    state = event(state, { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" });
    expect(state.messages[1].citations).toEqual([{ url: "https://www.icbc.com/driver-licensing", title: "Official guidance", publisher: "" }]);
  });

  it("does not expose server error details, reasoning, state or tool arguments", () => {
    let state = text();
    for (const type of ["REASONING_MESSAGE_CONTENT", "TOOL_CALL_ARGS", "STATE_SNAPSHOT"]) {
      state = event(state, { type, delta: "secret", snapshot: { html: "<script>alert(1)</script>" } });
    }
    expect(state.messages[1].content).toBe("A sourced answer.");
    state = event(state, { type: "RUN_ERROR", message: "provider-secret" });
    expect(state.status).toBe("error");
    expect(JSON.stringify(state)).not.toContain("provider-secret");
  });

  it("does not fabricate an answer when a successful run has no text", () => {
    const state = event(start(), { type: "RUN_FINISHED" });
    expect(state.status).toBe("error");
    expect(state.messages).toHaveLength(1);
  });

  it("ignores previous-run callbacks and resets all transient data", () => {
    const state = streamReducer(text(), { type: "failure", runId: "old-run", message: "old" });
    expect(state.status).toBe("streaming");
    expect(streamReducer(state, { type: "reset" })).toEqual(initialStreamState);
  });

  it("bounds streamed content and treats an excessive answer as incomplete", () => {
    let state = event(start(), { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" });
    state = event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "x".repeat(60_000) });
    state = event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "x" });
    expect(state.status).toBe("interrupted");
  });

  it("safely handles message IDs that collide with object prototype properties", () => {
    let state = event(start(), { type: "CUSTOM", name: "annotations", value: { messageId: "__proto__", annotations: [{ sourceId: "icbc" }] } });
    state = event(state, { type: "TEXT_MESSAGE_START", messageId: "__proto__", role: "assistant" });
    expect(state.messages[1].citations).toEqual([{ sourceId: "icbc", title: "", publisher: "" }]);
  });

  it("does not let a new run rewrite prior text or attach evidence to it", () => {
    const previous = event(text(), { type: "RUN_FINISHED" });
    let state = streamReducer(previous, { type: "start", runId: "run-2", messageId: "user-2", prompt: "Next question" });
    state = streamReducer(state, { type: "event", runId: "run-2", event: { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "wrong" } as unknown as BaseEvent });
    state = streamReducer(state, { type: "event", runId: "run-2", event: { type: "CUSTOM", name: "annotations", value: { messageId: "answer-1", annotations: [{ sourceId: "wrong" }] } } as unknown as BaseEvent });
    expect(state.messages[1].content).toBe("A sourced answer.");
    expect(state.messages[1].citations).toEqual([]);
  });

  it("rejects a mismatched native run terminal event", () => {
    const state = event(text(), { type: "RUN_FINISHED", runId: "foreign-run" });
    expect(state.status).toBe("streaming");
  });

  it("renders only known server progress labels, not supplied claims", () => {
    let state = event(start(), { type: "CUSTOM", name: "status", value: { version: 1, phase: "thinking", message: "An untrusted claim" } });
    expect(state.progress).toBe("Thinking...");
    expect(JSON.stringify(state)).not.toContain("An untrusted claim");
    state = event(state, { type: "CUSTOM", name: "status", value: { phase: "retrieving" } });
    expect(state.progress).toBe("Checking official BC sources...");
    expect(event(state, { type: "CUSTOM", name: "status", value: { phase: "booking-completed" } }).status).toBe("error");
  });

  it("keeps citations to different pages and chunks from the same publisher", () => {
    const state = event(text(), { type: "CUSTOM", name: "annotations", value: { messageId: "answer-1", annotations: [
      { sourceId: "icbc", url: "https://www.icbc.com/driver-licensing", documentId: "licensing", documentVersion: "v1", chunkId: "id" },
      { sourceId: "icbc", url: "https://www.icbc.com/driver-licensing", documentId: "licensing", documentVersion: "v1", chunkId: "renewal" },
      { sourceId: "icbc", url: "https://www.icbc.com/driver-licensing/visit-a-dl-office", documentId: "offices", documentVersion: "v1" },
    ] } });
    expect(state.messages[1].citations).toHaveLength(3);
  });

  it("rejects arbitrary generated components instead of rendering an invalid artifact", () => {
    const state = event(text(), { type: "CUSTOM", name: "bc.artifact", value: { version: 1, id: "unsafe", kind: "html", html: "<script>bad</script>" } });
    expect(state.status).toBe("error");
    expect(JSON.stringify(state)).not.toContain("<script>");
  });

  it("accepts only validated context artifacts during an explicit contextual run", () => {
    let state = streamReducer(initialStreamState, {
      type: "start",
      runId: "run-context",
      messageId: "user-context",
      prompt: "Contextual question",
      mode: "contextual-demo",
    });
    for (const artifact of contextArtifactsFixture) {
      state = streamReducer(state, {
        type: "event",
        runId: "run-context",
        event: { type: "CUSTOM", name: "bc.artifact", value: artifact } as unknown as BaseEvent,
      });
    }
    expect(state.artifacts["run-context"]).toEqual(contextArtifactsFixture);

    let reordered = streamReducer(initialStreamState, {
      type: "start",
      runId: "run-context",
      messageId: "user-context",
      prompt: "Contextual question",
      mode: "contextual-demo",
    });
    reordered = streamReducer(reordered, {
      type: "event",
      runId: "run-context",
      event: {
        type: "CUSTOM",
        name: "bc.artifact",
        value: contextArtifactsFixture[1],
      } as unknown as BaseEvent,
    });
    expect(reordered.status).toBe("error");
    expect(reordered.artifacts).toEqual({});

    let duplicate = streamReducer(initialStreamState, {
      type: "start",
      runId: "run-context",
      messageId: "user-context",
      prompt: "Contextual question",
      mode: "contextual-demo",
    });
    for (const artifact of [
      contextArtifactsFixture[0],
      contextArtifactsFixture[0],
    ]) {
      duplicate = streamReducer(duplicate, {
        type: "event",
        runId: "run-context",
        event: {
          type: "CUSTOM",
          name: "bc.artifact",
          value: artifact,
        } as unknown as BaseEvent,
      });
    }
    expect(duplicate.status).toBe("error");

    const anonymous = event(start(), {
      type: "CUSTOM",
      name: "bc.artifact",
      value: contextArtifactsFixture[0],
    });
    expect(anonymous.status).toBe("error");
    expect(anonymous.artifacts).toEqual({});
  });

  it("clears contextual conversation and artifacts without removing anonymous turns", () => {
    let state = event(text(), { type: "RUN_FINISHED" });
    state = streamReducer(state, {
      type: "start",
      runId: "run-context",
      messageId: "user-context",
      prompt: "Contextual question",
      mode: "contextual-demo",
    });
    state = streamReducer(state, {
      type: "event",
      runId: "run-context",
      event: { type: "CUSTOM", name: "bc.artifact", value: contextArtifactsFixture[0] } as unknown as BaseEvent,
    });
    const cleared = streamReducer(state, { type: "clear-context" });
    expect(cleared.messages.map((message) => message.content)).toEqual(["My question", "A sourced answer."]);
    expect(cleared.messages.every((message) => message.mode === "general")).toBe(true);
    expect(cleared.artifacts["run-context"]).toBeUndefined();
    expect(historyForAgent(cleared.messages, "contextual-demo")).toEqual([]);
    expect(historyForAgent(cleared.messages, "general")).toHaveLength(1);
  });
});
