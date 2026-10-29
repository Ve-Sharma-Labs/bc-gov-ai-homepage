import { describe, expect, it, vi } from "vitest";
import { startAgentRun } from "@/lib/agent";

const runId = "f05e8854-c039-4d6e-bf53-d35e9ec4e0be";
const threadId = "05a7643d-cbc2-4bda-9d3c-4e571b8d8112";

function eventsResponse(events: object[]) {
  const encoded = new TextEncoder().encode(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""));
  // Splitting inside fields and UTF-8 characters exercises the published SSE decoder.
  return new Response(new ReadableStream({
    start(controller) {
      for (let offset = 0; offset < encoded.length; offset += 7) controller.enqueue(encoded.slice(offset, offset + 7));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}

describe("published AG-UI HttpAgent integration", () => {
  it("sends the agreed input and decodes real SSE framing with native annotations", async () => {
    const events = [
      { type: "RUN_STARTED", runId, threadId },
      { type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "grounded", origin: "model" } },
      { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "B.C. guidance — check sources." },
      { type: "TEXT_MESSAGE_END", messageId: "answer-1" },
      { type: "CUSTOM", name: "annotations", value: { messageId: "answer-1", annotations: [{ type: "citation", title: "ICBC", url: "https://www.icbc.com/driver-licensing" }] } },
      { type: "RUN_FINISHED", runId, threadId },
    ];
    const fetcher = vi.fn().mockResolvedValue(eventsResponse(events));
    vi.stubGlobal("fetch", fetcher);
    const onEvent = vi.fn();
    const onFailure = vi.fn();
    const onClose = vi.fn();
    await startAgentRun({ runId, threadId, mode: "general", messages: [{ id: "user-1", role: "user", content: "A test question" }], onEvent, onFailure, onClose }).done;
    expect(fetcher.mock.calls[0][0]).toBe("/api/agent");
    const init = fetcher.mock.calls[0][1];
    expect(init.credentials).toBe("same-origin");
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({ runId, threadId, state: {}, tools: [], context: [], forwardedProps: { bc: { version: 2, mode: "general" } } });
    expect(body.forwardedProps.bc).not.toHaveProperty("journeyId");
    expect(body.messages).toEqual([{ id: "user-1", role: "user", content: "A test question" }]);
    expect(onEvent.mock.calls.map(([event]) => event.type)).toEqual(events.map((event) => event.type));
    expect(onEvent.mock.calls[3][0].delta).toBe("B.C. guidance — check sources.");
    expect(onFailure).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("handles a real safe 503 body without producing any model events", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ error: { code: "AI_NOT_CONFIGURED", message: "Native AI is not connected." } }, { status: 503 })));
    const onEvent = vi.fn();
    const onFailure = vi.fn();
    await startAgentRun({ runId, threadId, mode: "general", messages: [], onEvent, onFailure, onClose: vi.fn() }).done;
    expect(onFailure).toHaveBeenCalledWith("Native AI is not connected.", "AI_NOT_CONFIGURED");
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("preserves transient rate-limit details without automatically retrying", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(
      { error: { code: "RATE_LIMITED", message: "Wait before trying again." } },
      { status: 429, headers: { "Retry-After": "30" } },
    ));
    vi.stubGlobal("fetch", fetcher);
    const onFailure = vi.fn();
    await startAgentRun({ runId, threadId, mode: "general", messages: [], onEvent: vi.fn(), onFailure, onClose: vi.fn() }).done;
    expect(onFailure).toHaveBeenCalledWith(
      "Wait before trying again.",
      "RATE_LIMITED",
      expect.stringMatching(/Z$/u),
    );
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("maps the daily processing allowance to the next UTC reset", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-27T23:59:00Z"));
    try {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(
        {
          error: {
            code: "BUDGET_EXHAUSTED",
            message: "The pilot has reached its daily processing allowance. Guided plans remain available.",
          },
        },
        { status: 429, headers: { "Retry-After": "60" } },
      )));
      const onFailure = vi.fn();
      await startAgentRun({
        runId,
        threadId,
        mode: "general",
        messages: [],
        onEvent: vi.fn(),
        onFailure,
        onClose: vi.fn(),
      }).done;
      expect(onFailure).toHaveBeenCalledWith(
        "The pilot has reached its daily processing allowance. Guided plans remain available.",
        "BUDGET_EXHAUSTED",
        "2026-10-28T00:00:00.000Z",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects an unexpected non-stream success response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ text: "Not a protocol response" })));
    const onEvent = vi.fn();
    const onFailure = vi.fn();
    await startAgentRun({ runId, threadId, mode: "general", messages: [], onEvent, onFailure, onClose: vi.fn() }).done;
    expect(onFailure).toHaveBeenCalledWith(expect.stringContaining("unexpected response"), "INVALID_STREAM");
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("cancels the active request and sends only the originating run cancellation", async () => {
    let signal: AbortSignal | undefined;
    const fetcher = vi.fn((_url: string, init: RequestInit) => {
      if (_url.includes("/cancel")) return Promise.resolve(Response.json({ status: "cancelled" }));
      signal = init.signal as AbortSignal;
      return new Promise<Response>((_resolve, reject) => {
        signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      });
    });
    vi.stubGlobal("fetch", fetcher);
    const onFailure = vi.fn();
    const onClose = vi.fn();
    const run = startAgentRun({ runId, threadId, mode: "general", messages: [], onEvent: vi.fn(), onFailure, onClose });
    await vi.waitFor(() => expect(signal).toBeDefined());
    run.cancel();
    await run.done;
    expect(signal!.aborted).toBe(true);
    expect(fetcher.mock.calls[1][0]).toBe(`/api/runs/${runId}/cancel`);
    expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "POST", credentials: "same-origin", keepalive: true });
    expect(onFailure).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("sends only versioned journey data, never client-selected agent definitions", async () => {
    const fetcher = vi.fn().mockResolvedValue(eventsResponse([{ type: "RUN_STARTED", runId, threadId }, { type: "RUN_FINISHED", runId, threadId }]));
    vi.stubGlobal("fetch", fetcher);
    await startAgentRun({ runId, threadId, mode: "pathway", journeyId: "licence-renewal", messages: [], onEvent: vi.fn(), onFailure: vi.fn(), onClose: vi.fn() }).done;
    expect(JSON.parse(fetcher.mock.calls[0][1].body).forwardedProps).toEqual({ bc: { version: 2, mode: "pathway", journeyId: "licence-renewal" } });
  });

  it("uses explicit version 3 contextual mode without browser facts, state or tool payloads", async () => {
    const fetcher = vi.fn().mockResolvedValue(eventsResponse([
      { type: "RUN_STARTED", runId, threadId },
      { type: "RUN_FINISHED", runId, threadId },
    ]));
    vi.stubGlobal("fetch", fetcher);
    await startAgentRun({
      runId,
      threadId,
      mode: "contextual-demo",
      messages: [{ id: "user-1", role: "user", content: "What should I do next?" }],
      onEvent: vi.fn(),
      onFailure: vi.fn(),
      onClose: vi.fn(),
    }).done;
    const body = JSON.parse(fetcher.mock.calls[0][1].body);
    expect(body.forwardedProps).toEqual({ bc: { version: 3, mode: "contextual-demo" } });
    expect(body.context).toEqual([]);
    expect(body.state).toEqual({});
    expect(body.tools).toEqual([]);
    expect(JSON.stringify(body)).not.toMatch(/employment\.status|synthetic-government-record|contextSummary|personaId/iu);
    expect(new Headers(fetcher.mock.calls[0][1].headers).get("x-bc-context-page")).toMatch(
      /^[A-Za-z0-9-]{20,128}$/u,
    );
  });

  it("delivers genuine streamed text before the connection closes", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new ReadableStream({
      start(value) { controller = value; },
    }), { headers: { "Content-Type": "text/event-stream" } })));
    const send = (event: object) => controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
    const onEvent = vi.fn();
    const onClose = vi.fn();
    const run = startAgentRun({ runId, threadId, mode: "general", messages: [], onEvent, onFailure: vi.fn(), onClose });
    send({ type: "RUN_STARTED", runId, threadId });
    send({ type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "dialogue", origin: "model" } });
    send({ type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" });
    send({ type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "Which B.C. service" });
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ delta: "Which B.C. service" })));
    expect(onClose).not.toHaveBeenCalled();
    send({ type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: " do you mean?" });
    send({ type: "TEXT_MESSAGE_END", messageId: "answer-1" });
    send({ type: "RUN_FINISHED", runId, threadId });
    controller.close();
    await run.done;
    expect(onEvent.mock.calls.filter(([event]) => event.type === "TEXT_MESSAGE_CONTENT")).toHaveLength(2);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not downgrade an unavailable general request to a legacy or specialist request", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({
      error: { code: "GENERAL_AGENT_NOT_CONFIGURED", message: "General B.C. chat is not connected." },
    }, { status: 503 }));
    vi.stubGlobal("fetch", fetcher);
    const onFailure = vi.fn();
    await startAgentRun({ runId, threadId, mode: "general", messages: [], onEvent: vi.fn(), onFailure, onClose: vi.fn() }).done;
    expect(onFailure).toHaveBeenCalledWith("General B.C. chat is not connected.", "GENERAL_AGENT_NOT_CONFIGURED");
    expect(fetcher).toHaveBeenCalledOnce();
    expect(JSON.parse(fetcher.mock.calls[0][1].body).forwardedProps).toEqual({ bc: { version: 2, mode: "general" } });
  });

  it("can dispose a terminal stream without sending an unnecessary server cancellation", async () => {
    const bytes = new TextEncoder().encode([
      { type: "RUN_STARTED", runId, threadId },
      { type: "RUN_FINISHED", runId, threadId },
    ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""));
    const fetcher = vi.fn().mockResolvedValue(new Response(new ReadableStream({
      start(controller) { controller.enqueue(bytes); },
    }), { headers: { "Content-Type": "text/event-stream" } }));
    vi.stubGlobal("fetch", fetcher);
    const onEvent = vi.fn();
    const run = startAgentRun({ runId, threadId, mode: "general", messages: [], onEvent, onFailure: vi.fn(), onClose: vi.fn() });
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "RUN_FINISHED" })));
    run.cancel();
    run.cancel();
    await run.done;
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
