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
import {
  ApiError,
  changeContextConsent,
  createDemoSession,
  deleteDemoSession,
  getCapabilities,
  getCatalog,
  getContextSummary,
  getDemoPersonas,
} from "@/lib/api";
import { contextCategoryByScope, contextCategoryDetails } from "@/lib/citizen-context";
import {
  unavailableCapabilities,
  type Capabilities,
  type Catalog,
  type ConsentReceipt,
  type ConsentScope,
  type ContextSummary,
  type DemoPersonaId,
  type DemoPersonaSummary,
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
  personas: DemoPersonaSummary[];
  personasLoading: boolean;
  personaError: string;
  activePersona: DemoPersonaSummary | null;
  consent: ConsentReceipt | null;
  contextSummary: ContextSummary | null;
  contextLoading: boolean;
  contextError: string;
  contextActive: boolean;
}

export interface AssistantActions {
  load: () => Promise<void>;
  loadPersonas: () => Promise<void>;
  setDraft: Dispatch<SetStateAction<string>>;
  setNotice: Dispatch<SetStateAction<string>>;
  setSelectedId: Dispatch<SetStateAction<JourneyId | null>>;
  setChecked: Dispatch<SetStateAction<Set<string>>>;
  selectJourney: (journey: Journey) => void;
  clearJourney: () => void;
  activatePersona: (personaId: DemoPersonaId, scopes: ConsentScope[]) => Promise<boolean>;
  updateConsent: (scopes: ConsentScope[]) => Promise<boolean>;
  revokeConsentScope: (scope: ConsentScope) => Promise<boolean>;
  refreshContextSummary: () => Promise<boolean>;
  clearContext: () => Promise<void>;
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
  mode: "general" | "pathway" | "contextual-demo";
  cancelled: boolean;
  cancelTransport: (() => void) | null;
}

const AssistantContext = createContext<AssistantContextValue | null>(null);
const connectionFailure = "The assistant connection couldn’t load. Your question has been kept. Please try again.";
const contextFailure = "Synthetic context could not be updated. No new context was shared.";

function cancelRun(run: ActiveRun) {
  run.cancelled = true;
  const cancel = run.cancelTransport;
  run.cancelTransport = null;
  cancel?.();
}

function activeConsent(receipt: ConsentReceipt | null): receipt is ConsentReceipt {
  return !!receipt
    && !receipt.revokedAt
    && receipt.scopes.length > 0
    && Date.parse(receipt.expiresAt) > Date.now();
}

export function AssistantProvider({ children }: AssistantProviderProps) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities>(unavailableCapabilities);
  const [loading, setLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [draft, updateDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, updateSelectedId] = useState<JourneyId | null>(null);
  const [checked, setChecked] = useState(new Set<string>());
  const [state, setState] = useState<StreamState>(initialStreamState);
  const [personas, setPersonas] = useState<DemoPersonaSummary[]>([]);
  const [personasLoading, setPersonasLoading] = useState(false);
  const [personaError, setPersonaError] = useState("");
  const [activePersona, updateActivePersona] = useState<DemoPersonaSummary | null>(null);
  const [consent, updateConsentReceipt] = useState<ConsentReceipt | null>(null);
  const [contextSummary, setContextSummary] = useState<ContextSummary | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState("");

  const mounted = useRef(false);
  const draftRef = useRef("");
  const stateRef = useRef(state);
  const selectedIdRef = useRef<JourneyId | null>(null);
  const capabilitiesRef = useRef(capabilities);
  const personasRef = useRef<DemoPersonaSummary[]>([]);
  const activePersonaRef = useRef<DemoPersonaSummary | null>(null);
  const consentRef = useRef<ConsentReceipt | null>(null);
  const threadId = useRef<string | null>(null);
  const activeRun = useRef<ActiveRun | null>(null);
  const loadController = useRef<AbortController | null>(null);
  const personaController = useRef<AbortController | null>(null);
  const contextController = useRef<AbortController | null>(null);
  const contextSessionCreated = useRef(false);

  const setActivePersona = useCallback((value: DemoPersonaSummary | null) => {
    activePersonaRef.current = value;
    updateActivePersona(value);
  }, []);

  const setConsentReceipt = useCallback((value: ConsentReceipt | null) => {
    consentRef.current = value;
    updateConsentReceipt(value);
  }, []);

  const setSelectedId = useCallback<AssistantActions["setSelectedId"]>((value) => {
    if (isStreaming(stateRef.current) || activeConsent(consentRef.current)) return;
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

  const clearContextMemory = useCallback(() => {
    if (activeRun.current?.mode === "contextual-demo") cancelActiveRun();
    contextController.current?.abort();
    contextController.current = null;
    contextSessionCreated.current = false;
    threadId.current = null;
    setActivePersona(null);
    setConsentReceipt(null);
    setContextSummary(null);
    setContextLoading(false);
    dispatch({ type: "clear-context" });
  }, [cancelActiveRun, dispatch, setActivePersona, setConsentReceipt]);

  const loadPersonas = useCallback(async () => {
    if (!mounted.current || !capabilitiesRef.current.syntheticContextAvailable) return;
    personaController.current?.abort();
    const controller = new AbortController();
    personaController.current = controller;
    setPersonasLoading(true);
    setPersonaError("");
    try {
      const result = await getDemoPersonas(controller.signal);
      if (!mounted.current || controller.signal.aborted || personaController.current !== controller) return;
      personasRef.current = result;
      setPersonas(result);
    } catch (error) {
      if (!mounted.current || controller.signal.aborted || personaController.current !== controller) return;
      personasRef.current = [];
      setPersonas([]);
      setPersonaError(error instanceof ApiError
        ? error.message
        : "The fixed synthetic personas are temporarily unavailable.");
    } finally {
      if (mounted.current && personaController.current === controller) {
        personaController.current = null;
        setPersonasLoading(false);
      }
    }
  }, []);

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
      if (isCurrent()) {
        capabilitiesRef.current = connection;
        setCapabilities(connection);
      }
      return connection;
    });
    const [content, connection] = await Promise.allSettled([contentRequest, connectionRequest]);
    if (!isCurrent()) return;
    loadController.current = null;
    if (content.status === "fulfilled") {
      setCatalog(content.value);
      setCatalogError("");
    } else {
      setCatalogError("The guided-plan catalogue is temporarily unavailable. Official service links below still work.");
    }
    const nextCapabilities = connection.status === "fulfilled" ? connection.value : unavailableCapabilities;
    capabilitiesRef.current = nextCapabilities;
    setCapabilities(nextCapabilities);
    if (nextCapabilities.aiConfigured) setNotice("");
    if (nextCapabilities.syntheticContextAvailable) {
      void loadPersonas();
    } else {
      personaController.current?.abort();
      personasRef.current = [];
      setPersonas([]);
      setPersonasLoading(false);
      setPersonaError("");
      if (activePersonaRef.current) {
        clearContextMemory();
        void deleteDemoSession({ keepalive: true }).catch(() => undefined);
      }
    }
    setLoading(false);
  }, [clearContextMemory, loadPersonas]);

  useEffect(() => {
    mounted.current = true;
    void load();
    void import("@/lib/agent").catch(() => {
      console.warn("The assistant transport could not be preloaded. Sending a question will retry loading it.");
    });
    const clearBeforePageLeaves = () => {
      if (!contextSessionCreated.current) return;
      contextSessionCreated.current = false;
      void deleteDemoSession({ keepalive: true }).catch(() => undefined);
    };
    window.addEventListener("pagehide", clearBeforePageLeaves);
    return () => {
      mounted.current = false;
      window.removeEventListener("pagehide", clearBeforePageLeaves);
      loadController.current?.abort();
      personaController.current?.abort();
      contextController.current?.abort();
      loadController.current = null;
      personaController.current = null;
      contextController.current = null;
      cancelActiveRun();
      clearBeforePageLeaves();
    };
  }, [cancelActiveRun, load]);

  const selectJourney = useCallback((journey: Journey) => {
    if (isStreaming(stateRef.current) || activeConsent(consentRef.current)) return;
    setSelectedId(journey.id);
    setNotice("");
  }, [setSelectedId]);

  const clearJourney = useCallback(() => {
    if (isStreaming(stateRef.current) || activeConsent(consentRef.current)) return;
    setSelectedId(null);
    setNotice("");
  }, [setSelectedId]);

  const refreshContextSummary = useCallback(async () => {
    if (!activePersonaRef.current || !activeConsent(consentRef.current)) return false;
    const persona = activePersonaRef.current;
    const consentId = consentRef.current.consentId;
    setContextLoading(true);
    setContextError("");
    try {
      const summary = await getContextSummary();
      if (
        !mounted.current
        || activePersonaRef.current?.id !== persona.id
        || consentRef.current?.consentId !== consentId
      ) return false;
      setContextSummary(summary);
      return true;
    } catch (error) {
      if (!mounted.current) return false;
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        clearContextMemory();
      } else {
        setContextError(error instanceof ApiError ? error.message : contextFailure);
      }
      return false;
    } finally {
      if (mounted.current) setContextLoading(false);
    }
  }, [clearContextMemory]);

  const activatePersona = useCallback<AssistantActions["activatePersona"]>(async (personaId, scopes) => {
    if (!mounted.current || isStreaming(stateRef.current)) return false;
    const persona = personasRef.current.find((item) => item.id === personaId);
    const uniqueScopes = [...new Set(scopes)];
    const availableScopes = new Set(
      persona?.availableCategories.map((category) => contextCategoryDetails[category].scope),
    );
    if (!persona || uniqueScopes.length === 0 || uniqueScopes.some((scope) => !availableScopes.has(scope))) {
      setContextError("Choose at least one approved category for this fixed synthetic persona.");
      return false;
    }

    contextController.current?.abort();
    const controller = new AbortController();
    contextController.current = controller;
    if (activeRun.current?.mode === "contextual-demo") cancelActiveRun();
    dispatch({ type: "clear-context" });
    threadId.current = null;
    selectedIdRef.current = null;
    updateSelectedId(null);
    setContextLoading(true);
    setContextError("");
    try {
      const session = await createDemoSession(personaId, controller.signal);
      contextSessionCreated.current = true;
      const receipt = await changeContextConsent("grant", uniqueScopes, controller.signal);
      const summary = await getContextSummary(controller.signal);
      if (!mounted.current || controller.signal.aborted || contextController.current !== controller) return false;
      setActivePersona(session.persona);
      setConsentReceipt(receipt);
      setContextSummary(summary);
      return true;
    } catch (error) {
      if (controller.signal.aborted || !mounted.current) return false;
      contextSessionCreated.current = false;
      setActivePersona(null);
      setConsentReceipt(null);
      setContextSummary(null);
      void deleteDemoSession({ keepalive: true }).catch(() => undefined);
      setContextError(error instanceof ApiError ? error.message : contextFailure);
      return false;
    } finally {
      if (mounted.current && contextController.current === controller) {
        contextController.current = null;
        setContextLoading(false);
      }
    }
  }, [cancelActiveRun, dispatch, setActivePersona, setConsentReceipt]);

  const updateConsent = useCallback<AssistantActions["updateConsent"]>(async (scopes) => {
    const persona = activePersonaRef.current;
    const current = consentRef.current;
    if (!mounted.current || !persona || !activeConsent(current)) return false;
    const next = [...new Set(scopes)];
    const available = new Set(
      persona.availableCategories.map((category) => contextCategoryDetails[category].scope),
    );
    if (next.some((scope) => !available.has(scope))) {
      setContextError("Only approved categories for this fixed synthetic persona can be used.");
      return false;
    }
    const before = current.scopes;
    const removed = before.filter((scope) => !next.includes(scope));
    const added = next.filter((scope) => !before.includes(scope));
    if (!removed.length && !added.length) return true;

    if (activeRun.current?.mode === "contextual-demo") cancelActiveRun();
    dispatch({ type: "clear-context" });
    threadId.current = null;
    setContextError("");
    setContextSummary((summary) => {
      if (!summary) return null;
      const categories = new Set(next.map((scope) => contextCategoryByScope[scope]));
      return {
        ...summary,
        categories: summary.categories.filter((category) => categories.has(category)),
        facts: summary.facts.filter((fact) => categories.has(fact.category)),
        missingFacts: [],
      };
    });

    if (!next.length) {
      setActivePersona(null);
      setConsentReceipt(null);
      contextSessionCreated.current = false;
      setContextLoading(false);
      try {
        await changeContextConsent("revoke", before);
      } catch {
        // Local access is already closed; the idempotent DELETE below removes any remaining grant.
      }
      await deleteDemoSession({ keepalive: true }).catch(() => undefined);
      return true;
    }

    setConsentReceipt({ ...current, scopes: next });
    setContextLoading(true);
    try {
      let receipt = current;
      if (removed.length) receipt = await changeContextConsent("revoke", removed);
      if (added.length) receipt = await changeContextConsent("grant", added);
      if (!mounted.current || activePersonaRef.current?.id !== persona.id) return false;
      setConsentReceipt(receipt);
      const summary = await getContextSummary();
      if (!mounted.current || activePersonaRef.current?.id !== persona.id) return false;
      setContextSummary(summary);
      return true;
    } catch (error) {
      if (!mounted.current) return false;
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        clearContextMemory();
      } else {
        setContextError(error instanceof ApiError ? error.message : contextFailure);
      }
      return false;
    } finally {
      if (mounted.current) setContextLoading(false);
    }
  }, [cancelActiveRun, clearContextMemory, dispatch, setActivePersona, setConsentReceipt]);

  const revokeConsentScope = useCallback<AssistantActions["revokeConsentScope"]>(async (scope) => {
    const current = consentRef.current;
    if (!activeConsent(current) || !current.scopes.includes(scope)) return false;
    return updateConsent(current.scopes.filter((item) => item !== scope));
  }, [updateConsent]);

  const clearContext = useCallback(async () => {
    clearContextMemory();
    setContextError("");
    await deleteDemoSession({ keepalive: true }).catch(() => {
      if (mounted.current) setContextError("This page is anonymous now. Server cleanup will be retried when the page closes.");
    });
  }, [clearContextMemory]);

  const submit = useCallback(async () => {
    const prompt = draftRef.current.trim();
    if (!mounted.current || !prompt || prompt.length > 4000 || isStreaming(stateRef.current)) return false;
    if (activeRun.current) {
      if (stateRef.current.status !== "complete") return false;
      cancelActiveRun();
    }

    const contextual = activePersonaRef.current && activeConsent(consentRef.current);
    if (activePersonaRef.current && !contextual) {
      clearContextMemory();
      setContextError("Synthetic consent expired. Choose the persona again before using contextual mode.");
      return false;
    }
    const journeyId = selectedIdRef.current;
    const mode = contextual ? "contextual-demo" as const : journeyId ? "pathway" as const : "general" as const;
    const runId = crypto.randomUUID();
    const messageId = crypto.randomUUID();
    threadId.current ||= crypto.randomUUID();
    const currentThreadId = threadId.current;
    const history = historyForAgent(stateRef.current.messages, mode);
    const scope = mode === "contextual-demo"
      ? { mode }
      : mode === "pathway"
        ? { mode, journeyId: journeyId! }
        : { mode };
    const run: ActiveRun = { runId, mode, cancelled: false, cancelTransport: null };
    activeRun.current = run;
    const previous = stateRef.current;
    dispatch({
      type: "start",
      runId,
      messageId,
      prompt,
      mode,
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
  }, [cancelActiveRun, clearContextMemory, dispatch, isCurrentRun, setDraft]);

  const stop = useCallback(() => {
    const runId = stateRef.current.runId;
    cancelActiveRun();
    if (runId) dispatch({ type: "stop", runId });
  }, [cancelActiveRun, dispatch]);

  const reset = useCallback(() => {
    cancelActiveRun();
    contextController.current?.abort();
    contextController.current = null;
    contextSessionCreated.current = false;
    void deleteDemoSession({ keepalive: true }).catch(() => undefined);
    threadId.current = null;
    setActivePersona(null);
    setConsentReceipt(null);
    setContextSummary(null);
    setContextLoading(false);
    setContextError("");
    dispatch({ type: "reset" });
    setDraft("");
    selectedIdRef.current = null;
    updateSelectedId(null);
    setChecked(new Set());
    setNotice("");
  }, [cancelActiveRun, dispatch, setActivePersona, setConsentReceipt, setDraft]);

  const selected = catalog?.journeys.find((journey) => journey.id === selectedId) ?? null;
  const busy = isStreaming(state);
  const contextActive = !!activePersona && activeConsent(consent);
  const value = useMemo<AssistantContextValue>(() => ({
    catalog,
    capabilities,
    loading,
    catalogError,
    load,
    draft,
    setDraft,
    notice,
    setNotice,
    selectedId,
    setSelectedId,
    selected,
    checked,
    setChecked,
    state,
    busy,
    selectJourney,
    clearJourney,
    personas,
    personasLoading,
    personaError,
    loadPersonas,
    activePersona,
    consent,
    contextSummary,
    contextLoading,
    contextError,
    contextActive,
    activatePersona,
    updateConsent,
    revokeConsentScope,
    refreshContextSummary,
    clearContext,
    submit,
    stop,
    reset,
  }), [
    catalog,
    capabilities,
    loading,
    catalogError,
    load,
    draft,
    setDraft,
    notice,
    selectedId,
    setSelectedId,
    selected,
    checked,
    state,
    busy,
    selectJourney,
    clearJourney,
    personas,
    personasLoading,
    personaError,
    loadPersonas,
    activePersona,
    consent,
    contextSummary,
    contextLoading,
    contextError,
    contextActive,
    activatePersona,
    updateConsent,
    revokeConsentScope,
    refreshContextSummary,
    clearContext,
    submit,
    stop,
    reset,
  ]);

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>;
}

export function useAssistant(): AssistantContextValue {
  const context = useContext(AssistantContext);
  if (!context) throw new Error("useAssistant must be used within an AssistantProvider.");
  return context;
}
