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
  deleteDiscoverySession,
  deleteConversationSession,
  getCapabilities,
  getCatalog,
  getContextSummary,
  getDemoPersonas,
  getDiscoverySummary,
  getConversationSummary,
  getConversationTask,
  resetDiscoveryPageToken,
  resetConversationPageToken,
  updateConversationControl,
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
  type DiscoveryCommand,
  type DiscoveryFactKey,
  type ConversationCommand,
  type ConversationFactKey,
  type ConversationControl,
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
  conversationSharing: boolean;
  conversationControlError: string;
  conversationControlPending: boolean;
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
  submit: (submission?: {
    prompt: string;
    action?: DiscoveryCommand["action"];
    factKey?: DiscoveryFactKey;
    conversationAction?: ConversationCommand["action"];
    conversationFactKey?: ConversationFactKey;
    shareContext?: boolean;
  }) => Promise<boolean>;
  refreshDiscovery: () => Promise<boolean>;
  refreshConversation: () => Promise<boolean>;
  setConversationSharing: (value: boolean) => Promise<void>;
  taskControl: (action: "review" | "next" | "back" | "skip", stepId?: string, reviewed?: boolean) => Promise<boolean>;
  retryConversationControl: () => Promise<boolean>;
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
  const [conversationSharing, updateConversationSharing] = useState(false);
  const [controlBusy, setControlBusy] = useState(false);
  const [conversationControlError, setConversationControlError] = useState("");
  const controlController = useRef<AbortController | null>(null);
  const failedControl = useRef<ConversationControl | null>(null);
  const conversationSharingRef = useRef(false);

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
  const discoveryStarted = useRef(false);
  const conversationStarted = useRef(false);
  const conversationVersion = useRef<5 | 6 | null>(null);
  const lastConversationAttempt = useRef<{ prompt: string; command: ConversationCommand } | null>(null);
  const lastSubmission = useRef<Parameters<AssistantActions["submit"]>[0]>(undefined);
  const lastDiscoveryAttempt = useRef<{ prompt: string; command: DiscoveryCommand } | null>(null);

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
    if (lastSubmission.current && next.trim() !== lastSubmission.current.prompt.trim()) {
      lastSubmission.current = undefined;
    }
    if (lastDiscoveryAttempt.current && next.trim() !== lastDiscoveryAttempt.current.prompt.trim()) {
      lastDiscoveryAttempt.current = null;
    }
    if (lastConversationAttempt.current && next.trim() !== lastConversationAttempt.current.prompt.trim()) {
      lastConversationAttempt.current = null;
    }
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

  const forgetDiscovery = useCallback(() => {
    controlController.current?.abort();
    controlController.current = null;
    failedControl.current = null;
    setControlBusy(false);
    setConversationControlError("");
    lastSubmission.current = undefined;
    lastDiscoveryAttempt.current = null;
    lastConversationAttempt.current = null;
    conversationVersion.current = null;
    conversationSharingRef.current = false;
    updateConversationSharing(false);
    if (conversationStarted.current) {
      conversationStarted.current = false;
      void deleteConversationSession({ keepalive: true }).catch(() => {
        console.warn("AI context cleanup could not be confirmed; the page binding was rotated.");
        if (mounted.current) setNotice("Context was cleared on this page. Server cleanup will finish at expiry.");
      });
    }
    resetConversationPageToken();
    if (discoveryStarted.current) {
      discoveryStarted.current = false;
      void deleteDiscoverySession({ keepalive: true }).catch(() => {
        console.warn("Conversation context cleanup failed; the page binding was rotated.");
        if (mounted.current) setNotice("Context is cleared on this page. Server cleanup couldn't be confirmed; the old context will expire.");
      });
    }
    resetDiscoveryPageToken();
    dispatch({ type: "clear-discovery" });
  }, [dispatch]);

  const clearContextMemory = useCallback(() => {
    if (activeRun.current?.mode === "contextual-demo") cancelActiveRun();
    contextController.current?.abort();
    controlController.current?.abort();
    contextController.current = null;
    contextSessionCreated.current = false;
    threadId.current = null;
    setActivePersona(null);
    setConsentReceipt(null);
    setContextSummary(null);
    setContextLoading(false);
    dispatch({ type: "clear-context" });
    forgetDiscovery();
  }, [cancelActiveRun, dispatch, forgetDiscovery, setActivePersona, setConsentReceipt]);

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
      if (conversationStarted.current) {
        conversationStarted.current = false;
        void deleteConversationSession({ keepalive: true }).catch(() => {
          console.warn("AI conversation cleanup couldn't be confirmed; it will expire.");
        });
        resetConversationPageToken();
      }
      if (discoveryStarted.current) {
        discoveryStarted.current = false;
        void deleteDiscoverySession({ keepalive: true }).catch(() => {
          console.warn("Conversation context cleanup could not be confirmed; it will expire.");
        });
        resetDiscoveryPageToken();
      }
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
    forgetDiscovery();
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
  }, [cancelActiveRun, dispatch, forgetDiscovery, setActivePersona, setConsentReceipt]);

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

  const refreshDiscovery = useCallback(async () => {
    if (isStreaming(stateRef.current)) return false;
    const currentThread = threadId.current;
    try {
      const summary = await getDiscoverySummary();
      if (!mounted.current || threadId.current !== currentThread) return false;
      if (summary && summary.threadId !== currentThread) {
        setNotice("This context belongs to a different conversation. Please start over.");
        return false;
      }
      if (!summary) {
        forgetDiscovery();
        threadId.current = null;
      }
      dispatch({ type: "refresh-discovery", summary });
      setNotice("Context refreshed. Your question has not been resent.");
      return true;
    } catch (error) {
      if (mounted.current && threadId.current === currentThread) {
        setNotice(error instanceof ApiError ? error.message : "Context couldn't be refreshed. Please start over.");
      }
      return false;
    }
  }, [dispatch, forgetDiscovery]);

  const submit = useCallback<AssistantActions["submit"]>(async (submission) => {
    const retrying = submission === undefined;
    submission ??= lastSubmission.current;
    const prompt = (submission?.prompt ?? draftRef.current).trim();
    if (!mounted.current || !prompt || prompt.length > 4000 || isStreaming(stateRef.current) || controlController.current) return false;
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
    const useConversation = mode === "general" && capabilitiesRef.current.conversationAvailable
      && capabilitiesRef.current.requestVersions?.includes(5);
    const useDiscovery = !useConversation && mode === "general"
      && capabilitiesRef.current.discoveryAvailable
      && capabilitiesRef.current.requestVersions?.includes(4);
    if (submission?.action && !useDiscovery) {
      setNotice("Conversation context is not active here. Return to general conversation first.");
      return false;
    }
    if (submission?.conversationAction && !useConversation) {
      setNotice("Return to AI-led general conversation to change this context.");
      return false;
    }
    const conversationAction = submission?.conversationAction ?? "respond";
    const conversation: ConversationCommand | undefined = useConversation
      ? retrying && lastConversationAttempt.current?.prompt === prompt
        ? lastConversationAttempt.current.command
        : {
          action: conversationAction, revision: stateRef.current.conversation?.revision ?? 0,
          noticeVersion: "ai-conversation-v1",
          shareContext: submission?.shareContext ?? conversationSharingRef.current,
          ...(["respond", "skip"].includes(conversationAction) && stateRef.current.conversation?.question
            ? { questionId: stateRef.current.conversation.question.id } : {}),
          ...(submission?.conversationFactKey ? { factKey: submission.conversationFactKey } : {}),
        }
      : undefined;
    const action = submission?.action ?? "respond";
    const discovery: DiscoveryCommand | undefined = useDiscovery
      ? retrying && lastDiscoveryAttempt.current?.prompt === prompt
        ? lastDiscoveryAttempt.current.command
        : {
      action,
      revision: stateRef.current.discovery?.revision ?? 0,
      ...(["respond", "skip"].includes(action) && stateRef.current.discovery?.question
        ? { questionId: stateRef.current.discovery.question.id } : {}),
      ...(submission?.factKey ? { factKey: submission.factKey } : {}),
        } : undefined;
    const runId = crypto.randomUUID();
    const messageId = crypto.randomUUID();
    threadId.current ||= crypto.randomUUID();
    const currentThreadId = threadId.current;
    const history = discovery || conversation ? [] : historyForAgent(stateRef.current.messages, mode);
    if (conversation && conversationVersion.current === null) {
      conversationVersion.current = capabilitiesRef.current.requestVersions?.includes(6) ? 6 : 5;
    }
    const scope = mode === "contextual-demo"
      ? { mode }
      : mode === "pathway"
        ? { mode, journeyId: journeyId! }
        : { mode, ...(discovery ? { discovery } : {}), ...(conversation ? {
          conversation,
          conversationVersion: conversationVersion.current ?? 5,
        } : {}) };
    const run: ActiveRun = { runId, mode, cancelled: false, cancelTransport: null };
    activeRun.current = run;
    const previous = stateRef.current;
    dispatch({
      type: "start",
      runId,
      messageId,
      prompt,
      mode,
      ...(discovery ? { discovery: { revision: discovery.revision, threadId: currentThreadId } } : {}),
      ...(conversation ? { conversation: { revision: conversation.revision, threadId: currentThreadId } } : {}),
      taskAssistance: !!conversation && !!capabilitiesRef.current.taskAssistanceAvailable,
      ...(previous.error && previous.prompt === prompt ? { replaceRunId: previous.runId ?? undefined } : {}),
    });
    setNotice("");
    setDraft("");
    lastSubmission.current = submission;
    lastDiscoveryAttempt.current = discovery ? { prompt, command: discovery } : null;
    lastConversationAttempt.current = conversation ? { prompt, command: conversation } : null;
    if (conversation) conversationStarted.current = true;
    if (discovery) discoveryStarted.current = true;

    try {
      const { startAgentRun } = await import("@/lib/agent");
      if (!isCurrentRun(run)) return false;
      const handle = startAgentRun({
        runId,
        threadId: currentThreadId,
        ...scope,
        messages: [...history, { id: messageId, role: "user", content: prompt }],
        onEvent: (event) => {
          if (isCurrentRun(run)) {
            dispatch({ type: "event", runId, event });
            if (event.type === "RUN_FINISHED" && stateRef.current.status === "complete") {
              lastSubmission.current = undefined;
              lastDiscoveryAttempt.current = null;
              lastConversationAttempt.current = null;
            }
          }
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

  const runConversationControl = useCallback(async (control: ConversationControl) => {
    if (!mounted.current || controlController.current || isStreaming(stateRef.current)) return false;
    const controller = new AbortController();
    const expectedThread = threadId.current;
    controlController.current = controller;
    setControlBusy(true);
    setConversationControlError("");
    try {
      const response = await updateConversationControl(control, controller.signal);
      if (!mounted.current || controller.signal.aborted || threadId.current !== expectedThread) return false;
      const previous = stateRef.current.conversation;
      if (!previous || response.summary.threadId !== previous.threadId
        || response.summary.revision < previous.revision || response.summary.revision > previous.revision + 1) {
        throw new ApiError(409, "CONVERSATION_CHANGED", "Your context changed. Refresh it before trying again.");
      }
      dispatch({ type: "control", response });
      conversationSharingRef.current = response.summary.shareContext;
      updateConversationSharing(response.summary.shareContext);
      failedControl.current = null;
      setNotice(response.notice);
      return true;
    } catch (error) {
      if (mounted.current && !controller.signal.aborted) {
        failedControl.current = control;
        setConversationControlError(error instanceof ApiError ? error.message : "The setting couldn't be saved. Try again.");
      }
      return false;
    } finally {
      if (controlController.current === controller) {
        controlController.current = null;
        if (mounted.current) setControlBusy(false);
      }
    }
  }, [dispatch]);

  const taskControl = useCallback<AssistantActions["taskControl"]>(async (action, stepId, reviewed) => {
    const summary = stateRef.current.conversation;
    const task = stateRef.current.task?.task;
    if (!summary || !task) return false;
    return runConversationControl({
      id: crypto.randomUUID(), revision: summary.revision, noticeVersion: "ai-conversation-v1",
      action, taskId: task.id, stepId: stepId ?? task.activeStepId,
      ...(action === "review" ? { reviewed: reviewed ?? true } : {}),
    });
  }, [runConversationControl]);

  const retryConversationControl = useCallback(async () => (
    failedControl.current ? runConversationControl(failedControl.current) : false
  ), [runConversationControl]);

  const setConversationSharing = useCallback(async (value: boolean) => {
    if (isStreaming(stateRef.current) || controlController.current) return;
    const summary = stateRef.current.conversation;
    if (summary && capabilitiesRef.current.taskAssistanceAvailable) {
      if (!value) {
        conversationSharingRef.current = false;
        updateConversationSharing(false);
      }
      await runConversationControl({
        id: crypto.randomUUID(), revision: summary.revision, noticeVersion: "ai-conversation-v1",
        action: "sharing", shareContext: value,
      });
    } else {
      conversationSharingRef.current = value;
      updateConversationSharing(value);
    }
    if (summary && !capabilitiesRef.current.taskAssistanceAvailable) {
      await submit({
        prompt: value ? "Use the optional details I choose to share." : "Stop using my personal context.",
        conversationAction: "sharing", shareContext: value,
      });
    }
  }, [runConversationControl, submit]);

  const refreshConversation = useCallback(async () => {
    if (isStreaming(stateRef.current)) return false;
    const expectedThread = threadId.current;
    try {
      const withTask = !!capabilitiesRef.current.taskAssistanceAvailable;
      const controlSnapshot = withTask ? await getConversationTask() : undefined;
      const summary = withTask ? controlSnapshot?.summary ?? null : await getConversationSummary();
      if (!mounted.current || threadId.current !== expectedThread) return false;
      if (summary && summary.threadId !== expectedThread) {
        setNotice("This context belongs to another conversation. Start over.");
        return false;
      }
      if (!summary) {
        forgetDiscovery();
        threadId.current = null;
      }
      dispatch({ type: "refresh-conversation", summary,
        ...(withTask ? { task: controlSnapshot?.task ?? null } : {}),
      });
      failedControl.current = null;
      setConversationControlError("");
      if (summary) {
        conversationSharingRef.current = summary.shareContext;
        updateConversationSharing(summary.shareContext);
      }
      return true;
    } catch (error) {
      if (mounted.current) setNotice(error instanceof ApiError ? error.message : "Context couldn't be refreshed.");
      return false;
    }
  }, [dispatch, forgetDiscovery]);

  const stop = useCallback(() => {
    const runId = stateRef.current.runId;
    cancelActiveRun();
    if (runId) dispatch({ type: "stop", runId });
  }, [cancelActiveRun, dispatch]);

  const reset = useCallback(() => {
    cancelActiveRun();
    forgetDiscovery();
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
  }, [cancelActiveRun, dispatch, forgetDiscovery, setActivePersona, setConsentReceipt, setDraft]);

  const selected = catalog?.journeys.find((journey) => journey.id === selectedId) ?? null;
  const busy = isStreaming(state) || controlBusy;
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
    conversationSharing,
    setConversationSharing,
    taskControl,
    retryConversationControl,
    conversationControlError,
    conversationControlPending: controlBusy,
    refreshConversation,
    activatePersona,
    updateConsent,
    revokeConsentScope,
    refreshContextSummary,
    clearContext,
    refreshDiscovery,
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
    conversationSharing,
    setConversationSharing,
    taskControl,
    retryConversationControl,
    conversationControlError,
    controlBusy,
    refreshConversation,
    activatePersona,
    updateConsent,
    revokeConsentScope,
    refreshContextSummary,
    clearContext,
    refreshDiscovery,
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
