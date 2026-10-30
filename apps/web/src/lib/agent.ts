import { HttpAgent } from "@ag-ui/client";
import type { BaseEvent, Message } from "@ag-ui/core";
import { ApiError, getContextPageToken } from "./api";
import type { JourneyId } from "./contract";

type AgentRunOptions = {
  threadId: string;
  runId: string;
  messages: Message[];
  onEvent: (event: BaseEvent) => void;
  onFailure: (message: string, code?: string, retryAt?: string) => void;
  onClose: () => void;
  researchRequested?: boolean;
} & (
  | { mode: "general"; journeyId?: never }
  | { mode: "pathway"; journeyId: JourneyId }
  | { mode: "contextual-demo"; journeyId?: never; researchRequested?: false }
);

function retryAt(response: Response, code: string): string | null {
  if (code === "BUDGET_EXHAUSTED") {
    const now = new Date();
    return new Date(Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate() + 1,
    )).toISOString();
  }
  const value = response.headers.get("retry-after");
  if (!value) return null;
  if (/^\d{1,9}$/u.test(value)) {
    return new Date(Date.now() + Number(value) * 1000).toISOString();
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) && parsed > Date.now() ? new Date(parsed).toISOString() : null;
}

export function startAgentRun(options: AgentRunOptions) {
  let cancelled = false;
  let terminal = false;
  const agent = new HttpAgent({
    url: "/api/agent",
    threadId: options.threadId,
    initialMessages: options.messages,
    initialState: {},
    debug: false,
    fetch: async (url, init) => {
      const headers = new Headers(init?.headers);
      if (options.mode === "contextual-demo") {
        headers.set("x-bc-context-page", getContextPageToken());
      }
      const response = await fetch(url, {
        ...init,
        headers,
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        const code = payload?.error?.code || "AGENT_UNAVAILABLE";
        const message = typeof payload?.error?.message === "string" ? payload.error.message.slice(0, 600) : "The assistant is unavailable. Your question has been kept.";
        throw new ApiError(response.status, code, message, retryAt(response, code));
      }
      if (!response.headers.get("content-type")?.includes("text/event-stream")) {
        await response.body?.cancel();
        throw new ApiError(502, "INVALID_STREAM", "The assistant returned an unexpected response. Your question has been kept.");
      }
      return response;
    },
  });
  let resolveDone: () => void;
  const done = new Promise<void>((resolve) => { resolveDone = resolve; });
  let closed = false;
  const finish = () => {
    if (closed) return;
    closed = true;
    if (!cancelled) options.onClose();
    resolveDone();
  };
  // The SDK owns wire decoding; our reducer owns presentation. No second state/tool runtime.
  const subscription = agent.run({
    threadId: options.threadId,
    runId: options.runId,
    messages: options.messages,
    state: {},
    tools: [],
    context: [],
    forwardedProps: { bc: options.mode === "contextual-demo"
      ? { version: 3, mode: "contextual-demo" }
      : {
        version: 2,
        mode: options.mode,
        ...(options.mode === "pathway" ? { journeyId: options.journeyId } : {}),
        ...(options.researchRequested ? { researchRequested: true } : {}),
      } },
  }).subscribe({
    next: (event) => {
      if (cancelled) return;
      if ((event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") && (!("runId" in event) || event.runId === options.runId)) terminal = true;
      options.onEvent(event);
    },
    error: (error: unknown) => {
      if (!cancelled) {
        if (error instanceof ApiError) {
          if (error.retryAt) options.onFailure(error.message, error.code, error.retryAt);
          else options.onFailure(error.message, error.code);
        } else {
          options.onFailure("The connection to the assistant was interrupted. Your question has been kept. Please try again.");
        }
      }
      finish();
    },
    complete: finish,
  });

  return {
    done,
    cancel: () => {
      if (cancelled) return;
      cancelled = true;
      agent.abortRun();
      subscription.unsubscribe();
      finish();
      if (terminal) return;
      // Aborting the stream is immediate; the authenticated endpoint also cancels server work.
      void fetch(`/api/runs/${encodeURIComponent(options.runId)}/cancel`, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        keepalive: true,
      }).catch(() => undefined);
    },
  };
}
