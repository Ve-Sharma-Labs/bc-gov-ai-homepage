import { HttpAgent } from "@ag-ui/client";
import { ApiError, getResearchPageToken } from "./api";
import { researchProgressSchema, researchResultSchema, type ResearchAction, type ResearchGeography, type ResearchOffer, type ResearchResult } from "./research-schema";

export function startResearchRun(options: {
  runId: string; offer: ResearchOffer; action: ResearchAction; geography: ResearchGeography;
  onProgress: (phase: "retrieving" | "summarizing") => void;
  onResult: (result: ResearchResult) => void;
  onError: (message: string) => void;
}) {
  let cancelled = false;
  let terminal = false;
  let pending: ResearchResult | null = null;
  const body = {
    version: 1, runId: options.runId, action: options.action, geography: options.geography,
    threadId: options.offer.threadId, parentRunId: options.offer.parentRunId,
    parentMessageId: options.offer.parentMessageId,
  };
  const agent = new HttpAgent({
    url: "/api/research", threadId: options.offer.threadId, debug: false,
    fetch: async (target, init) => {
      const headers = new Headers(init?.headers);
      headers.set("content-type", "application/json");
      headers.set("x-bc-research-page", getResearchPageToken());
      const response = await fetch(target, {
        ...init, headers, body: JSON.stringify(body), cache: "no-store", credentials: "same-origin",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new ApiError(response.status, "RESEARCH_UNAVAILABLE",
          typeof payload?.error?.message === "string" ? payload.error.message.slice(0, 600)
            : "Optional research is unavailable. Your original answer is unchanged.");
      }
      if (!response.headers.get("content-type")?.includes("text/event-stream")) {
        await response.body?.cancel();
        throw new Error("Unexpected research response.");
      }
      return response;
    },
  });
  const fail = (message: string) => {
    terminal = true;
    pending = null;
    if (!cancelled) options.onError(message);
  };
  const subscription = agent.run({
    runId: options.runId, threadId: options.offer.threadId, messages: [],
    tools: [], context: [], state: {},
  }).subscribe({
    next: (event) => {
      if (cancelled || terminal) return;
      if (event.type === "CUSTOM" && event.name === "bc.research.progress") {
        const progress = researchProgressSchema.safeParse(event.value);
        if (progress.success) options.onProgress(progress.data.phase);
      } else if (event.type === "CUSTOM" && event.name === "bc.research.result") {
        const result = researchResultSchema.safeParse(event.value);
        if (!result.success || result.data.runId !== options.runId
          || result.data.action !== options.action || result.data.parentRunId !== options.offer.parentRunId
          || result.data.parentMessageId !== options.offer.parentMessageId) {
          fail("The research result did not match this answer. Nothing was changed.");
        } else {
          pending = result.data;
        }
      } else if (event.type === "RUN_FINISHED") {
        if (event.runId !== options.runId || event.threadId !== options.offer.threadId || !pending) {
          fail("The research result was incomplete. Your original answer is unchanged.");
        } else {
          terminal = true;
          options.onResult(pending);
          pending = null;
        }
      } else if (event.type === "RUN_ERROR") {
        fail(typeof event.message === "string" ? event.message.slice(0, 600) : "Research failed.");
      }
    },
    error: (error: unknown) => fail(error instanceof ApiError ? error.message
      : "Optional research was interrupted. Your original answer is unchanged."),
    complete: () => { if (!terminal && !cancelled) fail("Research ended before a verified result arrived."); },
  });
  return {
    cancel: async () => {
      if (cancelled) return;
      cancelled = true;
      pending = null;
      agent.abortRun();
      subscription.unsubscribe();
      if (terminal) return;
      for (let attempt = 0; attempt < 12; attempt++) {
        const response = await fetch(`/api/runs/${encodeURIComponent(options.runId)}/cancel`, {
          method: "POST", cache: "no-store", credentials: "same-origin",
          signal: AbortSignal.timeout(3000),
        });
        if (response.status === 200 || response.status === 409 || response.status === 404) return;
        if (response.status !== 202) break;
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      throw new Error("Research cancellation could not be confirmed. Please retry your question.");
    },
  };
}
