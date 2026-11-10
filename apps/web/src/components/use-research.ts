"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getResearchPageToken, resetResearchPageToken } from "@/lib/api";
import type { ResearchAction, ResearchGeography, ResearchOffer, ResearchResult } from "@/lib/research-schema";

export interface ResearchView {
  runId: string;
  action: ResearchAction;
  phase: "retrieving" | "summarizing" | "complete" | "error" | "stopped";
  result?: ResearchResult;
  error?: string;
}

export function useResearch() {
  const [items, setItems] = useState<Record<string, ResearchView>>({});
  const active = useRef<{ key: string; runId: string; cancel: (() => Promise<void>) | null } | null>(null);
  const mounted = useRef(true);
  const update = useCallback((key: string, value: ResearchView) => {
    if (mounted.current) setItems((previous) => ({ ...previous, [key]: value }));
  }, []);
  const stop = useCallback(() => {
    const run = active.current;
    if (!run) return;
    active.current = null;
    setItems((previous) => ({ ...previous, [run.key]: { ...previous[run.key], phase: "stopped" } }));
    return run.cancel?.();
  }, []);
  const start = useCallback(async (offer: ResearchOffer, action: ResearchAction, geography: ResearchGeography) => {
    if (active.current || !offer.actions.includes(action)) return;
    const key = `${offer.parentMessageId}:${action}`;
    const runId = crypto.randomUUID();
    if (Date.parse(offer.expiresAt) <= Date.now()) {
      update(key, { runId, action, phase: "error", error: "This action expired. Ask the question again." });
      return;
    }
    const run: { key: string; runId: string; cancel: (() => Promise<void>) | null } = {
      key, runId, cancel: null,
    };
    active.current = run;
    update(key, { runId, action, phase: "retrieving" });
    try {
      const { startResearchRun } = await import("@/lib/research-transport");
      if (!mounted.current || active.current !== run) return;
      const handle = startResearchRun({
        runId, offer, action, geography,
        onProgress: (phase) => {
          if (active.current === run) update(key, { runId, action, phase });
        },
        onResult: (result) => {
          if (active.current !== run) return;
          active.current = null;
          update(key, { runId, action, phase: "complete", result });
        },
        onError: (error) => {
          if (active.current !== run) return;
          active.current = null;
          update(key, { runId, action, phase: "error", error });
        },
      });
      run.cancel = handle.cancel;
    } catch {
      if (active.current === run) {
        active.current = null;
        update(key, { runId, action, phase: "error", error: "Optional research could not start." });
      }
    }
  }, [update]);
  const reset = useCallback(async (hasOffers: boolean) => {
    const page = getResearchPageToken();
    const stopped = stop();
    resetResearchPageToken();
    setItems({});
    const revoke = async () => {
      if (!hasOffers) return;
      const response = await fetch("/api/research", {
        method: "DELETE", headers: { "x-bc-research-page": page },
        cache: "no-store", credentials: "same-origin", keepalive: true,
      });
      if (!response.ok) throw new Error("Server research cleanup could not be confirmed.");
    };
    await Promise.all([stopped, revoke()]);
  }, [stop]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const run = active.current;
      active.current = null;
      void run?.cancel?.().catch(() => console.warn("Research cancellation could not be confirmed."));
    };
  }, []);
  return useMemo(() => ({ items, start, stop, reset }), [items, start, stop, reset]);
}
