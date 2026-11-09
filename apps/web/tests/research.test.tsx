import { act, renderHook } from "@testing-library/react";
import { EventType } from "@ag-ui/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useResearch } from "@/components/use-research";
import { researchOfferSchema, researchResultSchema, type ResearchOffer, type ResearchResult } from "@/lib/research-schema";
import { historyForAgent, initialStreamState, streamReducer } from "@/lib/stream";
import { allowedApiRequest } from "@/lib/proxy";

type Start = typeof import("@/lib/research-transport").startResearchRun;
const { start } = vi.hoisted(() => ({ start: vi.fn<Start>() }));
vi.mock("@/lib/research-transport", () => ({ startResearchRun: start }));
const offer: ResearchOffer = {
  version: 1, parentRunId: "parent", parentMessageId: "answer", threadId: "thread",
  topics: ["service-bc"], actions: ["web-check", "corpus-explore"], expiresAt: "2099-01-01T00:00:00Z",
};
const result: ResearchResult = {
  version: 1, action: "web-check", runId: "research", parentRunId: "parent",
  parentMessageId: "answer", text: "Synthetic web supplement.", notice: "Not live verification.",
  citations: [{
    kind: "web", sourceId: "service-bc", title: "Synthetic official source",
    publisher: "Government of British Columbia", url: "https://www2.gov.bc.ca/gov/content/test",
    retrievedAt: "2026-01-01T00:00:00Z", crawledAt: null, publisherUpdatedAt: null,
    humanReviewed: false, method: "search", quoteLimit: 200,
  }],
};

beforeEach(() => {
  start.mockReset().mockImplementation(() => ({ cancel: vi.fn(async () => undefined) }));
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
});

describe("optional research", () => {
  it("does not fetch or load the provider transport on mount or an idle stop", () => {
    const hook = renderHook(useResearch);
    expect(hook.result.current.stop()).toBeUndefined();
    expect(start).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    hook.unmount();
  });

  it("requires a per-answer action and keeps results separate from chat", async () => {
    const hook = renderHook(useResearch);
    await act(() => hook.result.current.start(offer, "web-check", "victoria"));
    expect(start).toHaveBeenCalledOnce();
    const options = start.mock.calls[0][0];
    expect(Object.keys(options)).not.toContain("messages");
    expect(options.geography).toBe("victoria");
    act(() => options.onResult({ ...result, runId: options.runId }));
    expect(hook.result.current.items["answer:web-check"].result?.text).toBe(result.text);
    expect(hook.result.current.items["answer:corpus-explore"]).toBeUndefined();
    expect(historyForAgent(initialStreamState.messages)).toEqual([]);
  });

  it("preserves the original answer when research fails", async () => {
    const hook = renderHook(useResearch);
    await act(() => hook.result.current.start(offer, "web-check", "british-columbia"));
    act(() => start.mock.calls[0][0].onError("Provider unavailable."));
    expect(hook.result.current.items["answer:web-check"]).toMatchObject({
      phase: "error", error: "Provider unavailable.",
    });
    expect(hook.result.current.stop()).toBeUndefined();
  });

  it("does not start a transport after stop during its dynamic import", async () => {
    const hook = renderHook(useResearch);
    await act(async () => {
      const pending = hook.result.current.start(offer, "web-check", "british-columbia");
      hook.result.current.stop();
      await pending;
    });
    expect(start).not.toHaveBeenCalled();
  });

  it("clears research and ignores late events after Start over", async () => {
    const hook = renderHook(useResearch);
    await act(() => hook.result.current.start(offer, "web-check", "british-columbia"));
    const callbacks = start.mock.calls[0][0];
    await act(() => hook.result.current.reset(true));
    act(() => callbacks.onResult(result));
    expect(hook.result.current.items).toEqual({});
    expect(fetch).toHaveBeenCalledWith("/api/research", expect.objectContaining({ method: "DELETE" }));
  });

  it("does not send expired actions", async () => {
    const hook = renderHook(useResearch);
    await act(() => hook.result.current.start({
      ...offer, expiresAt: "2001-01-01T00:00:00Z",
    }, "web-check", "victoria"));
    expect(start).not.toHaveBeenCalled();
    expect(hook.result.current.items["answer:web-check"].phase).toBe("error");
  });

  it("attaches offers only to the matching answer without adding chat turns", () => {
    let state = streamReducer(initialStreamState, {
      type: "start", runId: "parent", messageId: "question", prompt: "Office information", mode: "general",
    });
    state = streamReducer(state, { type: "event", runId: "parent", event: {
      type: EventType.TEXT_MESSAGE_START, messageId: "answer", role: "assistant",
    } });
    state = streamReducer(state, { type: "event", runId: "parent", event: {
      type: EventType.TEXT_MESSAGE_CONTENT, messageId: "answer", delta: "Original answer.",
    } });
    const before = state;
    state = streamReducer(state, { type: "event", runId: "parent", event: {
      type: EventType.CUSTOM, name: "bc.research.offer", value: { ...offer, parentRunId: "other" },
    } });
    expect(state).toBe(before);
    state = streamReducer(state, { type: "event", runId: "parent", event: {
      type: EventType.CUSTOM, name: "bc.research.offer", value: offer,
    } });
    expect(state.messages).toHaveLength(2);
    expect(state.messages[1]).toMatchObject({ content: "Original answer.", researchOffer: offer });
  });

  it("rejects provenance laundering and unapproved links", () => {
    expect(researchResultSchema.safeParse(result).success).toBe(true);
    expect(researchResultSchema.safeParse({ ...result, action: "corpus-explore" }).success).toBe(false);
    expect(researchResultSchema.safeParse({ ...result, citations: [{
      ...result.citations[0], url: "https://evil.example/", humanReviewed: true,
    }] }).success).toBe(false);
    expect(researchOfferSchema.safeParse({ ...offer, query: "private" }).success).toBe(false);
  });

  it("allows only scoped POST/DELETE research routes through the BFF", () => {
    expect(allowedApiRequest("POST", "/api/research", new URLSearchParams())).toBe(true);
    expect(allowedApiRequest("DELETE", "/api/research", new URLSearchParams())).toBe(true);
    expect(allowedApiRequest("GET", "/api/research", new URLSearchParams())).toBe(false);
    expect(allowedApiRequest("POST", "/api/research", new URLSearchParams("url=https://evil.example"))).toBe(false);
    expect(allowedApiRequest("POST", "/api/research/anything", new URLSearchParams())).toBe(false);
  });
});
