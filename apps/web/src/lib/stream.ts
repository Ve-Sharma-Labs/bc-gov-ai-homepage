import type { BaseEvent, Message } from "@ag-ui/core";
import { z } from "zod";
import { safeOfficialUrl } from "./links";
import {
  anonymousArtifactSchema,
  contextArtifactSchema,
  conversationSummarySchema,
  taskSnapshotSchema,
  conversationControlResponseSchema,
  discoverySummarySchema,
  evidenceMetadataSchema,
  progressSchema,
  responseContextSchema,
  type Artifact,
  type ChatMode,
  type ConversationSummary,
  type TaskSnapshot,
  type ConversationControlResponse,
  type DiscoverySummary,
  type EvidenceMetadata,
  type ResponseContext,
} from "./contract";

export interface Citation {
  sourceId?: string;
  url?: string;
  title?: string;
  publisher?: string;
  checkedAt?: string | null;
  publisherUpdatedAt?: string | null;
  documentId?: string;
  documentVersion?: string;
  chunkId?: string;
  section?: string;
  metadata?: EvidenceMetadata | null;
}

export interface ChatMessage {
  id: string;
  runId: string;
  mode: ChatMode;
  role: "user" | "assistant";
  content: string;
  status: "pending" | "complete" | "partial";
  citations: Citation[];
  response?: ResponseContext;
  discovery?: true;
  conversation?: true;
}

export interface StreamState {
  runId: string | null;
  status: "idle" | "connecting" | "streaming" | "complete" | "stopped" | "interrupted" | "error";
  messages: ChatMessage[];
  prompt: string;
  progress: string;
  error: string | null;
  errorCode: string | null;
  retryAt: string | null;
  warning: string | null;
  pendingCitations: Record<string, Citation[]>;
  announcement: string;
  artifacts: Record<string, Artifact[]>;
  response: ResponseContext | null;
  activeMode: ChatMode | null;
  discovery: DiscoverySummary | null;
  pendingDiscovery: DiscoverySummary | null;
  discoveryRevision: number | null;
  discoveryThreadId: string | null;
  conversation: ConversationSummary | null;
  pendingConversation: ConversationSummary | null;
  conversationRevision: number | null;
  conversationThreadId: string | null;
  task: TaskSnapshot | null;
  pendingTask: TaskSnapshot | null;
  taskFromControl: boolean;
  expectsTask: boolean;
}

export const initialStreamState: StreamState = {
  runId: null,
  status: "idle",
  messages: [],
  prompt: "",
  progress: "",
  error: null,
  errorCode: null,
  retryAt: null,
  warning: null,
  pendingCitations: {},
  announcement: "",
  artifacts: {},
  response: null,
  activeMode: null,
  discovery: null,
  pendingDiscovery: null,
  discoveryRevision: null,
  discoveryThreadId: null,
  conversation: null,
  pendingConversation: null,
  conversationRevision: null,
  conversationThreadId: null,
  task: null,
  pendingTask: null,
  taskFromControl: false,
  expectsTask: false,
};

export type StreamAction =
  | { type: "start"; runId: string; messageId: string; prompt: string; mode?: ChatMode; replaceRunId?: string; discovery?: { revision: number; threadId: string }; conversation?: { revision: number; threadId: string }; taskAssistance?: boolean }
  | { type: "event"; runId: string; event: BaseEvent }
  | { type: "failure"; runId: string; message: string; code?: string; retryAt?: string }
  | { type: "closed"; runId: string }
  | { type: "stop"; runId: string }
  | { type: "clear-context" }
  | { type: "clear-discovery" }
  | { type: "refresh-discovery"; summary: DiscoverySummary | null }
  | { type: "refresh-conversation"; summary: ConversationSummary | null; task?: TaskSnapshot | null }
  | { type: "control"; response: ConversationControlResponse }
  | { type: "reset" };

export const isStreaming = (state: StreamState) => state.status === "connecting" || state.status === "streaming";

const contextArtifactOrder = [
  "context-summary",
  "program-matches",
  "application-preview",
  "consent-request",
  "audit-receipt",
] as const;

const object = z.record(z.unknown());
const eventSchema = z.object({ type: z.string() }).passthrough();
const stringField = (value: unknown, maximum = 160) => typeof value === "string" ? value.slice(0, maximum) : "";
const dateField = (value: unknown) => value === null ? null : typeof value === "string" && value.length < 40 && Number.isFinite(Date.parse(value)) ? value : undefined;

function parseCitations(value: unknown): { messageId: string; citations: Citation[] } | null {
  const data = object.safeParse(value);
  if (!data.success) return null;
  const messageId = stringField(data.data.messageId || data.data.message_id);
  if (!messageId || !Array.isArray(data.data.annotations)) return null;
  const citations: Citation[] = [];
  for (const raw of data.data.annotations.slice(0, 30)) {
    const item = object.safeParse(raw);
    if (!item.success) continue;
    const nested = object.safeParse(item.data.url_citation);
    const annotation = nested.success ? { ...item.data, ...nested.data } : item.data;
    const sourceId = stringField(annotation.sourceId);
    const url = safeOfficialUrl(annotation.url);
    if (sourceId || url) {
      const checkedAt = dateField(annotation.checkedAt);
      const publisherUpdatedAt = dateField(annotation.publisherUpdatedAt);
      const metadata = evidenceMetadataSchema.nullable().safeParse(annotation.metadata);
      citations.push({
        ...(sourceId ? { sourceId } : {}),
        ...(url ? { url } : {}),
        title: stringField(annotation.title, 300),
        publisher: stringField(annotation.publisher, 200),
        ...(checkedAt !== undefined ? { checkedAt } : {}),
        ...(publisherUpdatedAt !== undefined ? { publisherUpdatedAt } : {}),
        ...(typeof annotation.documentId === "string" ? { documentId: stringField(annotation.documentId) } : {}),
        ...(typeof annotation.documentVersion === "string" ? { documentVersion: stringField(annotation.documentVersion, 300) } : {}),
        ...(typeof annotation.chunkId === "string" ? { chunkId: stringField(annotation.chunkId) } : {}),
        ...(typeof annotation.section === "string" ? { section: stringField(annotation.section, 1000) } : {}),
        ...(metadata.success ? { metadata: metadata.data } : {}),
      });
    }
  }
  return { messageId, citations };
}

function mergeCitations(previous: Citation[], next: Citation[]): Citation[] {
  const key = (citation: Citation) => JSON.stringify([citation.url || citation.sourceId, citation.documentId, citation.documentVersion, citation.chunkId]);
  const result = new Map(previous.map((citation) => [key(citation), citation]));
  for (const citation of next) result.set(key(citation), citation);
  return [...result.values()].slice(0, 30);
}

function citationsFor(state: StreamState, id: string): Citation[] {
  return Object.hasOwn(state.pendingCitations, id) ? state.pendingCitations[id] : [];
}

function terminate(
  state: StreamState,
  status: "stopped" | "interrupted" | "error",
  message: string,
  code?: string,
  retryAt?: string,
): StreamState {
  const parsedRetry = typeof retryAt === "string" && Number.isFinite(Date.parse(retryAt))
    ? new Date(retryAt).toISOString()
    : null;
  return {
    ...state,
    status,
    progress: "",
    pendingDiscovery: null,
    pendingConversation: null,
    pendingTask: null,
    error: message,
    errorCode: code && /^[A-Z_0-9]{1,64}$/.test(code) ? code : null,
    retryAt: parsedRetry,
    announcement: message,
    messages: state.messages.map((item) => item.runId === state.runId ? { ...item, status: "partial" } : item),
  };
}

function recoverDialogue(state: StreamState, code?: string): StreamState | null {
  const content = code === "GREETING"
    ? "Hello! What would you like to know about B.C. government services?"
    : code === "JOURNEY_REQUIRED"
      ? "Tell me a little more about the B.C. service or topic you need help with. You can also choose a guided pathway."
      : null;
  if (!content || state.messages.some((message) => message.runId === state.runId && message.role === "assistant" && message.content.trim())) return null;
  const response: ResponseContext = { version: 1, kind: "dialogue", origin: "application" };
  return {
    ...state,
    status: "complete",
    progress: "",
    error: null,
    errorCode: null,
    retryAt: null,
    warning: null,
    response,
    announcement: content,
    messages: [
      ...state.messages.filter((message) => message.runId !== state.runId || message.role === "user")
        .map((message) => message.runId === state.runId ? { ...message, status: "complete" as const } : message),
      {
        id: `dialogue-${state.runId}`,
        runId: state.runId!,
        mode: state.activeMode ?? "general",
        role: "assistant",
        content,
        status: "complete",
        citations: [],
        response,
      },
    ],
  };
}

export function needsSources(message: ChatMessage): boolean {
  return message.response?.kind !== "dialogue"
    && !(message.response?.kind === "handoff" && message.response.origin === "application");
}

export function streamReducer(state: StreamState, action: StreamAction): StreamState {
  if (action.type === "reset") return { ...initialStreamState };
  if (action.type === "control") {
    if (isStreaming(state)) return state;
    const parsed = conversationControlResponseSchema.safeParse(action.response);
    if (!parsed.success || !state.conversation || parsed.data.summary.threadId !== state.conversation.threadId
      || parsed.data.summary.revision < state.conversation.revision
      || parsed.data.summary.revision > state.conversation.revision + 1) return state;
    const changedStep = parsed.data.task.task?.activeStepId !== state.task?.task?.activeStepId
      || parsed.data.task.task?.phase !== state.task?.task?.phase;
    return { ...state, conversation: parsed.data.summary, task: parsed.data.task,
      taskFromControl: changedStep || state.taskFromControl, announcement: parsed.data.notice };
  }
  if (action.type === "refresh-conversation") {
    if (isStreaming(state)) return state;
    return {
      ...state, status: "idle", runId: null, error: null, errorCode: null, retryAt: null,
      conversation: action.summary, pendingConversation: null,
      task: action.task !== undefined ? action.task : state.task,
      taskFromControl: action.task !== undefined,
      announcement: "Context refreshed. Your message has not been resent.",
    };
  }
  if (action.type === "refresh-discovery") {
    if (isStreaming(state)) return state;
    return {
      ...state, status: "idle", runId: null, error: null, errorCode: null, retryAt: null,
      discovery: action.summary, pendingDiscovery: null,
      announcement: "Conversation context refreshed. Your question has not been resent.",
    };
  }
  if (action.type === "clear-discovery") {
    const privateRuns = new Set(state.messages.filter((message) => message.discovery || message.conversation).map((message) => message.runId));
    return {
      ...state, discovery: null, pendingDiscovery: null, discoveryRevision: null, discoveryThreadId: null,
      conversation: null, pendingConversation: null, conversationRevision: null, conversationThreadId: null,
      task: null, pendingTask: null, taskFromControl: false, expectsTask: false,
      artifacts: Object.fromEntries(Object.entries(state.artifacts).filter(([runId]) => !privateRuns.has(runId))),
    };
  }
  if (action.type === "clear-context") {
    const contextualRunIds = new Set(
      state.messages
        .filter((message) => message.mode === "contextual-demo")
        .map((message) => message.runId),
    );
    return {
      ...initialStreamState,
      messages: state.messages.filter((message) => message.mode !== "contextual-demo"),
      artifacts: Object.fromEntries(
        Object.entries(state.artifacts).filter(([runId]) => !contextualRunIds.has(runId)),
      ),
      announcement: "Synthetic citizen context cleared.",
    };
  }
  if (action.type === "start") {
    const mode = action.mode ?? "general";
    return {
      ...state,
      runId: action.runId,
      activeMode: mode,
      status: "connecting",
      prompt: action.prompt,
      progress: "Sending your question…",
      error: null,
      errorCode: null,
      retryAt: null,
      announcement: "Question sent.",
      pendingCitations: {},
      response: null,
      pendingDiscovery: null,
      pendingConversation: null,
      pendingTask: null,
      expectsTask: action.taskAssistance ?? false,
      conversationRevision: action.conversation?.revision ?? null,
      conversationThreadId: action.conversation?.threadId ?? null,
      discoveryRevision: action.discovery?.revision ?? null,
      discoveryThreadId: action.discovery?.threadId ?? null,
      messages: [...state.messages.filter((message) => message.runId !== action.replaceRunId), {
        id: action.messageId,
        runId: action.runId,
        mode,
        role: "user",
        content: action.prompt,
        status: "pending",
        citations: [],
        ...(action.discovery ? { discovery: true as const } : {}),
        ...(action.conversation ? { conversation: true as const } : {}),
      }],
      artifacts: Object.fromEntries(Object.entries(state.artifacts).filter(([runId]) => (
        runId !== action.replaceRunId
        && (!action.discovery || !state.messages.some((message) => message.runId === runId && message.discovery))
        && (!action.conversation || action.taskAssistance || !state.messages.some((message) => message.runId === runId && message.conversation))
      ))),
    };
  }
  if (action.runId !== state.runId) return state;
  if (action.type === "stop") {
    return isStreaming(state) ? terminate(state, "stopped", "Response stopped. Any partial answer below is unfinished; your question has been kept.") : state;
  }
  if (action.type === "failure") {
    return isStreaming(state)
      ? recoverDialogue(state, action.code) ?? terminate(
        state,
        "error",
        action.message,
        action.code,
        action.retryAt,
      )
      : state;
  }
  if (action.type === "closed") {
    return isStreaming(state) ? terminate(state, "interrupted", "The connection ended before the answer was complete. Treat partial text as unfinished. Your question has been kept.") : state;
  }

  const parsed = eventSchema.safeParse(action.event);
  if (!parsed.success) return state;
  const event = parsed.data;
  if (typeof event.runId === "string" && event.runId !== state.runId) return state;
  // Native citation events can follow text, snapshots, and even the terminal run event.
  if (event.type === "CUSTOM" && event.name === "annotations") {
    if (!isStreaming(state) && state.status !== "complete") return state;
    const annotations = parseCitations(event.value);
    if (!annotations) return state;
    const previous = citationsFor(state, annotations.messageId);
    const citations = mergeCitations(previous, annotations.citations);
    return {
      ...state,
      pendingCitations: { ...state.pendingCitations, [annotations.messageId]: citations },
      messages: state.messages.map((item) => item.id === annotations.messageId && item.runId === state.runId
        ? { ...item, citations: mergeCitations(item.citations, citations) }
        : item),
    };
  }
  if (event.type === "CUSTOM" && event.name === "bc.warning") {
    const warning = z.object({
      version: z.literal(1),
      code: z.literal("DETAILS_WITHHELD"),
    }).strict().safeParse(event.value);
    if (!isStreaming(state) || !warning.success) return state;
    return {
      ...state,
      warning: "Some generated details were withheld because they could not be verified. Use the cited official sources for current details.",
      announcement: "Some unverified details were withheld.",
    };
  }
  if (!isStreaming(state)) return state;
  if (event.type === "CUSTOM" && event.name === "bc.task") {
    if (!state.expectsTask) return state;
    const task = taskSnapshotSchema.safeParse(event.value);
    if (!task.success || state.pendingTask || task.data.threadId !== state.conversationThreadId
      || task.data.revision !== (state.conversationRevision ?? -1) + 1) {
      return terminate(state, "error", "The preparation update could not be verified. Refresh your context.", "TASK_CHANGED");
    }
    return { ...state, pendingTask: task.data };
  }
  if (event.type === "CUSTOM" && event.name === "bc.conversation") {
    const summary = conversationSummarySchema.safeParse(event.value);
    if (
      state.activeMode !== "general" || state.conversationRevision === null
      || state.pendingConversation || !summary.success
      || summary.data.threadId !== state.conversationThreadId
      || summary.data.revision !== state.conversationRevision + 1
    ) return terminate(state, "error", "The conversation update couldn't be verified. Refresh your context.", "CONVERSATION_CHANGED");
    return { ...state, pendingConversation: summary.data };
  }
  if (event.type === "CUSTOM" && event.name === "bc.discovery") {
    const summary = discoverySummarySchema.safeParse(event.value);
    if (
      state.activeMode !== "general" || state.discoveryRevision === null
      || state.pendingDiscovery || !summary.success
      || summary.data.threadId !== state.discoveryThreadId
      || summary.data.revision !== state.discoveryRevision + 1
    ) return terminate(state, "error", "The conversation context could not be verified. Refresh it before continuing.", "DISCOVERY_CHANGED");
    return { ...state, pendingDiscovery: summary.data };
  }
  if (event.type === "CUSTOM" && event.name === "bc.response") {
    // Purpose is server-owned and must arrive before text; late metadata cannot downgrade evidence warnings.
    if (state.response || state.messages.some((message) => message.runId === state.runId && message.role === "assistant" && message.content)) return state;
    const response = responseContextSchema.safeParse(event.value);
    if (!response.success) return terminate(state, "error", "The assistant returned unsupported response details. Your question has been kept.");
    return {
      ...state,
      response: response.data,
      messages: state.messages.map((message) => message.runId === state.runId && message.role === "assistant"
        ? { ...message, response: response.data }
        : message),
    };
  }
  if (event.type === "CUSTOM" && event.name === "status") {
    const progress = progressSchema.safeParse(event.value);
    if (!progress.success) return terminate(state, "error", "The assistant returned an unsupported progress update. Your question has been kept.");
    const labels = {
      connecting: "Connecting to the assistant...",
      retrieving: "Checking official BC sources...",
      thinking: "Thinking...",
      preparing: "Preparing your next steps...",
      locations: "Checking published service locations...",
      validating: "Checking the answer against its sources...",
    };
    const label = labels[progress.data.phase];
    return { ...state, progress: label, announcement: label };
  }
  if (event.type === "CUSTOM" && event.name === "bc.artifact") {
    const contextual = state.activeMode === "contextual-demo";
    const artifact = contextual
      ? contextArtifactSchema.safeParse(event.value)
      : anonymousArtifactSchema.safeParse(event.value);
    if (!artifact.success) return terminate(state, "error", "The assistant returned an unsupported result. Your question has been kept.");
    const previous = Object.hasOwn(state.artifacts, state.runId!) ? state.artifacts[state.runId!] : [];
    if (
      contextual
      && (
        previous.length >= contextArtifactOrder.length
        || artifact.data.kind !== contextArtifactOrder[previous.length]
        || previous.some((item) => item.id === artifact.data.id)
      )
    ) {
      return terminate(
        state,
        "error",
        "The assistant returned contextual results out of order. Your question has been kept.",
      );
    }
    if (previous.length >= 10 && !previous.some((item) => item.id === artifact.data.id)) {
      return terminate(state, "error", "The assistant returned too many preparation results. Please ask a more focused question.");
    }
    return {
      ...state,
      artifacts: {
        ...state.artifacts,
        [state.runId!]: contextual
          ? [...previous, artifact.data]
          : [...previous.filter((item) => item.id !== artifact.data.id), artifact.data],
      },
    };
  }
  switch (event.type) {
    case "RUN_STARTED":
      return { ...state, progress: "Thinking...", announcement: "Connected to the assistant." };
    case "STEP_STARTED": {
      const labels: Record<string, string> = {
        search_approved_sources: "Checking official BC sources...",
        search_approved_corpus: "Searching official BC sources…",
        search: "Searching official BC sources…",
        retrieve: "Retrieving source information…",
        research_public_web: "Checking public information with Web IQ…",
        read_consented_context: "Checking the consented synthetic context…",
        evaluate_program_rules: "Screening the fictional scenario against reviewed rules…",
        build_application_preview: "Preparing a review-only intake preview…",
      };
      const progress = labels[stringField(event.stepName)] || "The assistant is working on your question…";
      return { ...state, progress, announcement: progress };
    }
    case "TOOL_CALL_START": {
      const labels: Record<string, string> = {
        search_approved_sources: "Checking official BC sources...",
        search_approved_corpus: "Searching official BC sources…",
        read_approved_source: "Reading an official source…",
        find_service_locations: "Checking published service locations…",
        build_preparation_plan: "Preparing source-backed next steps…",
        research_public_web: "Checking public information with Web IQ…",
        read_consented_context: "Checking the consented synthetic context…",
        evaluate_program_rules: "Screening the fictional scenario against reviewed rules…",
        build_application_preview: "Preparing a review-only intake preview…",
      };
      const progress = labels[stringField(event.toolCallName)] || "Checking information…";
      return { ...state, progress, announcement: progress };
    }
    case "TEXT_MESSAGE_START": {
      if (event.role && event.role !== "assistant") return state;
      const id = stringField(event.messageId);
      if (!id || state.messages.some((item) => item.id === id)) return state;
      return {
        ...state,
        status: "streaming",
        progress: state.progress || "Thinking...",
        messages: [...state.messages, {
          id,
          runId: state.runId!,
          mode: state.activeMode ?? "general",
          role: "assistant",
          content: "",
          status: "pending",
          citations: citationsFor(state, id),
          ...(state.response ? { response: state.response } : {}),
          ...(state.discoveryRevision !== null ? { discovery: true as const } : {}),
          ...(state.conversationRevision !== null ? { conversation: true as const } : {}),
        }],
      };
    }
    case "TEXT_MESSAGE_CONTENT": {
      const id = stringField(event.messageId);
      const delta = stringField(event.delta, 60_000);
      if (!id || !delta) return state;
      const message = state.messages.find((item) => item.id === id && item.role === "assistant" && item.runId === state.runId);
      if (!message) return state;
      if (message.content.length + delta.length > 60_000) {
        return terminate(state, "interrupted", "The answer exceeded this pilot’s display limit. Please ask a more focused question.");
      }
      return {
        ...state,
        status: "streaming",
        progress: "",
        announcement: message.content ? state.announcement : "An answer is arriving.",
        messages: state.messages.map((item) => item === message ? { ...item, content: item.content + delta } : item),
      };
    }
    case "TEXT_MESSAGE_END": {
      const message = state.messages.find((item) => item.id === event.messageId && item.role === "assistant" && item.runId === state.runId);
      return { ...state, announcement: message?.content
        ? needsSources(message) ? "Answer text received. Waiting for source checks and run completion." : "Response text received."
        : state.announcement };
    }
    case "MESSAGES_SNAPSHOT": {
      if (!Array.isArray(event.messages)) return state;
      const messages = [...state.messages];
      for (const value of event.messages.slice(-40)) {
        const item = object.safeParse(value);
        if (!item.success || item.data.role !== "assistant" || typeof item.data.content !== "string") continue;
        const id = stringField(item.data.id);
        const previous = messages.findIndex((message) => message.id === id && message.runId === state.runId);
        if (previous >= 0) {
          messages[previous] = { ...messages[previous], content: item.data.content.slice(0, 60_000) };
        }
      }
      return { ...state, messages };
    }
    case "RUN_FINISHED": {
      const outcome = object.safeParse(event.outcome);
      if (outcome.success && outcome.data.type === "cancelled") {
        return terminate(state, "stopped", "The response was cancelled. Your question has been kept.");
      }
      if (outcome.success && outcome.data.type === "interrupt") {
        return terminate(state, "interrupted", "This answer needs an action the pilot cannot perform. Use an official service handoff instead.");
      }
      const hasAnswer = state.messages.some((item) => item.runId === state.runId && item.role === "assistant" && item.content.trim());
      if (!hasAnswer) return terminate(state, "error", "The assistant did not return an answer. Try a guided plan or rephrase your question.");
      if (state.discoveryRevision !== null && !state.pendingDiscovery) {
        return terminate(state, "error", "Your updated context was not received. Refresh it before continuing.", "DISCOVERY_CHANGED");
      }
      if (state.conversationRevision !== null && !state.pendingConversation) {
        return terminate(state, "error", "Your context update wasn't received. Refresh before continuing.", "CONVERSATION_CHANGED");
      }
      if (state.expectsTask && !state.pendingTask) {
        return terminate(state, "error", "The preparation update wasn't received. Refresh your context.", "TASK_CHANGED");
      }
      const sourcedAnswer = state.messages.some((item) => item.runId === state.runId && item.role === "assistant" && needsSources(item));
      return {
        ...state,
        status: "complete",
        progress: "",
        discovery: state.pendingDiscovery ?? state.discovery,
        pendingDiscovery: null,
        conversation: state.pendingConversation ?? state.conversation,
        pendingConversation: null,
        task: state.pendingTask ?? state.task,
        pendingTask: null,
        taskFromControl: false,
        artifacts: state.pendingTask ? Object.fromEntries(Object.entries(state.artifacts).map(([id, artifacts]) => [
          id, artifacts.filter((artifact) => !artifact.id.startsWith("task-") || artifact.id === `task-${state.pendingTask?.task?.id}`),
        ])) : state.artifacts,
        announcement: sourcedAnswer ? "Answer complete. Review the sources before acting." : "Response complete.",
        messages: state.messages.map((item) => item.runId === state.runId ? { ...item, status: "complete" } : item),
      };
    }
    case "RUN_ERROR": {
      const code = stringField(event.code, 64);
      const dialogue = recoverDialogue(state, code);
      if (dialogue) return dialogue;
      const errors: Record<string, string> = {
        GENERAL_AGENT_NOT_CONFIGURED: "General B.C. chat is not connected in this pilot. Your question has been kept. Try again later or use a guided plan.",
        SOURCES_UNAVAILABLE: "No current, approved evidence was found. Use a guided plan or the official service.",
        SOURCE_CONFLICT: "The source changed or conflicted during this answer. Please retry or check the official service.",
        CRITICAL_CLAIM_UNVERIFIED: "A fee, deadline or eligibility statement could not be verified. Check the official source.",
        WEBIQ_DISABLED: "Live public-web research is not enabled. You can still use approved sources and official services.",
        DISCOVERY_CHANGED: "Your conversation context changed. Refresh it before sending another answer.",
        DISCOVERY_EXPIRED: "Your conversation context expired or was cleared. Start over to continue without it.",
        DISCOVERY_UNAVAILABLE: "Your conversation context couldn't be updated. Your question has been kept.",
        DISCOVERY_ANSWER_INVALID: "Please use a short answer or choose not sure. No ID numbers are needed.",
        CONTEXT_PURPOSE_CHANGED: "That goal is outside this fictional scenario's consent. Return to anonymous conversation to continue without those records.",
        CONVERSATION_CHANGED: "Your conversation changed. Refresh your context before answering.",
        CONVERSATION_EXPIRED: "Your conversation context expired. Start over to continue.",
        CONVERSATION_DECISION_INVALID: "The assistant couldn't verify its next step. Please retry or use a guided plan.",
        CONVERSATION_AGENT_NOT_CONFIGURED: "AI-led conversation is not connected. The guided plans remain available.",
      };
      return terminate(state, "error", errors[code] || "The assistant couldn’t finish the answer. Your question has been kept; try again or choose a guided plan.", code);
    }
    default:
      // Reasoning, generated UI/state, tool arguments, and browser actions never render or execute.
      return state;
  }
}

export function historyForAgent(messages: ChatMessage[], mode: ChatMode = "general"): Message[] {
  return messages.filter((message) => (
    (mode === "contextual-demo"
      ? message.mode === "contextual-demo"
      : message.mode !== "contextual-demo")
    && message.status === "complete"
    && !message.discovery
    && !message.conversation
    && message.content.trim()
    && (
      message.role === "user"
      || (message.response?.kind === "dialogue" && message.response.origin === "model")
    )
  ))
    .slice(-20).map(({ id, role, content }) => ({ id, role, content }));
}
