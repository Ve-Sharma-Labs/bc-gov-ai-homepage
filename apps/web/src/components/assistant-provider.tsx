"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { getCapabilities, getCatalog } from "@/lib/api";
import {
  unavailableCapabilities,
  type Capabilities,
  type Catalog,
  type Journey,
  type JourneyId,
} from "@/lib/contract";
import {
  historyForAgent,
  initialStreamState,
  isStreaming,
  streamReducer,
  type StreamAction,
  type StreamState,
} from "@/lib/stream";

export interface AssistantState {
  catalog: Catalog | null;
  capabilities: Capabilities;
  loading: boolean;
  catalogError: string;
  draft: string;
  notice: string;
  selectedId: JourneyId | null;
  selected: Journey | null;
  checked: Set<string>;
  state: StreamState;
  busy: boolean;
}

export interface AssistantActions {
  load: () => Promise<void>;
  setDraft: Dispatch<SetStateAction<string>>;
  setNotice: Dispatch<SetStateAction<string>>;
  setSelectedId: Dispatch<SetStateAction<JourneyId | null>>;
  setChecked: Dispatch<SetStateAction<Set<string>>>;
  selectJourney: (journey: Journey) => void;
  clearJourney: () => void;
  submit: () => Promise<boolean>;
  stop: () => void;
  reset: () => void;
}

export type AssistantContextValue = AssistantState & AssistantActions;

export interface AssistantProviderProps {
  children: ReactNode;
}

interface ActiveRun {
  runId: string;
  cancelled: boolean;
  cancelTransport: (() => void) | null;
}

const AssistantContext = createContext<AssistantContextValue | null>(null);
const connectionFailure = "The assistant connection couldn’t load. Your question has been kept. Please try again.";

function cancelRun(run: ActiveRun) {
  run.cancelled = true;
  const cancel = run.cancelTransport;
  run.cancelTransport = null;
  cancel?.();
}

export function AssistantProvider({ children }: AssistantProviderProps) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities>(unavailableCapabilities);
  const [loading, setLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [draft, updateDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, updateSelectedId] = useState<JourneyId | null>(null);
  const selectedIdRef = useRef<JourneyId | null>(null);
  const [checked, setChecked] = useState(new Set<string>());
  const [state, setState] = useState<StreamState>(initialStreamState);
  const mounted = useRef(false);
  const draftRef = useRef("");
  const stateRef = useRef(state);
  const threadId = useRef<string | null>(null);
  const activeRun = useRef<ActiveRun | null>(null);
  const loadController = useRef<AbortController | null>(null);

  const setSelectedId = useCallback<AssistantActions["setSelectedId"]>((value) => {
    if (isStreaming(stateRef.current)) return;
    const next = typeof value === "function" ? value(selectedIdRef.current) : value;
    selectedIdRef.current = next;
    updateSelectedId(next);
  }, []);

  const setDraft = useCallback<AssistantActions["setDraft"]>((value) => {
    const next = typeof value === "function" ? value(draftRef.current) : value;
    draftRef.current = next;
    updateDraft(next);
  }, []);

  const cancelActiveRun = useCallback(() => {
    const run = activeRun.current;
    activeRun.current = null;
    if (run) cancelRun(run);
  }, []);

  const dispatch = useCallback((action: StreamAction) => {
    // Refs advance with the reducer, not a later render, so batched actions use current history.
    const next = streamReducer(stateRef.current, action);
    stateRef.current = next;
    setState(next);
    if (next.status === "error" || next.status === "interrupted" || next.status === "stopped") {
      setDraft((current) => current || next.prompt);
      if (activeRun.current?.runId === next.runId) cancelActiveRun();
    }
  }, [cancelActiveRun, setDraft]);

  const isCurrentRun = useCallback((run: ActiveRun) => (
    mounted.current && activeRun.current === run && !run.cancelled
  ), []);

  const load = useCallback(async () => {
    if (!mounted.current) return;
    loadController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    setLoading(true);
    setCatalogError("");
    const isCurrent = () => mounted.current && !controller.signal.aborted && loadController.current === controller;
    const contentRequest = getCatalog(controller.signal).then((content) => {
      if (isCurrent()) setCatalog(content);
      return content;
    });
    const connectionRequest = getCapabilities(controller.signal).then((connection) => {
      if (isCurrent()) setCapabilities(connection);
      return connection;
    });
    const [content, connection] = await Promise.allSettled([contentRequest, connectionRequest]);
    if (!mounted.current || controller.signal.aborted || loadController.current !== controller) return;
    loadController.current = null;
    if (content.status === "fulfilled") {
      setCatalog(content.value);
      setCatalogError("");
    } else {
      setCatalogError("The guided-plan catalogue is temporarily unavailable. Official service links below still work.");
    }
    const nextCapabilities = connection.status === "fulfilled" ? connection.value : unavailableCapabilities;
    setCapabilities(nextCapabilities);
    if (nextCapabilities.aiConfigured) setNotice("");
    setLoading(false);
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    void import("@/lib/agent").catch(() => {
      console.warn("The assistant transport could not be preloaded. Sending a question will retry loading it.");
    });
    return () => {
      mounted.current = false;
      loadController.current?.abort();
      loadController.current = null;
      cancelActiveRun();
    };
  }, [cancelActiveRun, load]);

  const selectJourney = useCallback((journey: Journey) => {
    if (isStreaming(stateRef.current)) return;
    setSelectedId(journey.id);
    setNotice("");
  }, [setSelectedId]);

  const clearJourney = useCallback(() => {
    if (isStreaming(stateRef.current)) return;
    setSelectedId(null);
    setNotice("");
  }, [setSelectedId]);

  const submit = useCallback(async () => {
    const prompt = draftRef.current.trim();
    if (!mounted.current || !prompt || prompt.length > 4000 || isStreaming(stateRef.current)) return false;
    if (activeRun.current) {
      if (stateRef.current.status !== "complete") return false;
      cancelActiveRun();
    }

    const runId = crypto.randomUUID();
    const messageId = crypto.randomUUID();
    threadId.current ||= crypto.randomUUID();
    const currentThreadId = threadId.current;
    const history = historyForAgent(stateRef.current.messages);
    const journeyId = selectedIdRef.current;
    const scope = journeyId
      ? { mode: "pathway" as const, journeyId }
      : { mode: "general" as const };
    const run: ActiveRun = { runId, cancelled: false, cancelTransport: null };
    activeRun.current = run;
    const previous = stateRef.current;
    dispatch({
      type: "start", runId, messageId, prompt,
      ...(previous.error && previous.prompt === prompt ? { replaceRunId: previous.runId ?? undefined } : {}),
    });
    setNotice("");
    setDraft("");

    try {
      const { startAgentRun } = await import("@/lib/agent");
      if (!isCurrentRun(run)) return false;
      const handle = startAgentRun({
        runId,
        threadId: currentThreadId,
        ...scope,
        messages: [...history, { id: messageId, role: "user", content: prompt }],
        onEvent: (event) => {
          if (isCurrentRun(run)) dispatch({ type: "event", runId, event });
        },
        onFailure: (message, code, retryAt) => {
          if (isCurrentRun(run)) dispatch({ type: "failure", runId, message, code, retryAt });
        },
        onClose: () => {
          if (isCurrentRun(run)) dispatch({ type: "closed", runId });
        },
      });
      run.cancelTransport = handle.cancel;
      // A synchronous subscription callback may stop/reset before the handle is available.
      if (!isCurrentRun(run)) cancelRun(run);
      void handle.done.then(() => {
        if (!isCurrentRun(run)) return;
        dispatch({ type: "closed", runId });
        if (activeRun.current === run) activeRun.current = null;
      }, () => {
        if (!isCurrentRun(run)) return;
        dispatch({ type: "failure", runId, message: connectionFailure });
        if (activeRun.current === run) activeRun.current = null;
      });
      return true;
    } catch {
      if (isCurrentRun(run)) dispatch({ type: "failure", runId, message: connectionFailure });
      return false;
    }
  }, [cancelActiveRun, dispatch, isCurrentRun, setDraft]);

  const stop = useCallback(() => {
    const runId = stateRef.current.runId;
    cancelActiveRun();
    if (runId) dispatch({ type: "stop", runId });
  }, [cancelActiveRun, dispatch]);

  const reset = useCallback(() => {
    cancelActiveRun();
    threadId.current = null;
    dispatch({ type: "reset" });
    setDraft("");
    setSelectedId(null);
    setChecked(new Set());
    setNotice("");
  }, [cancelActiveRun, dispatch, setDraft, setSelectedId]);

  const selected = catalog?.journeys.find((journey) => journey.id === selectedId) ?? null;
  const busy = isStreaming(state);
  const value = useMemo<AssistantContextValue>(() => ({
    catalog, capabilities, loading, catalogError, load,
    draft, setDraft, notice, setNotice, selectedId, setSelectedId, selected,
    checked, setChecked, state, busy, selectJourney, clearJourney, submit, stop, reset,
  }), [
    catalog, capabilities, loading, catalogError, load, draft, setDraft, notice,
    selectedId, setSelectedId, selected, checked, state, busy, selectJourney, clearJourney, submit, stop, reset,
  ]);

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>;
}

export function useAssistant(): AssistantContextValue {
  const context = useContext(AssistantContext);
  if (!context) throw new Error("useAssistant must be used within an AssistantProvider.");
  return context;
}
