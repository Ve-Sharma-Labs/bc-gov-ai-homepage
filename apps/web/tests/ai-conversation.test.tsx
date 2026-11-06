import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EventType } from "@ag-ui/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantProvider, useAssistant } from "@/components/assistant-provider";
import { AI_PROCESSING_NOTICE, AiConversationContext, ConversationNotice } from "@/components/ai-conversation";
import { conversationSummarySchema, runOptionsSchema, type ConversationSummary } from "@/lib/contract";
import { historyForAgent, initialStreamState, streamReducer } from "@/lib/stream";
import { catalogFixture, guidedCapabilities } from "./fixtures";

type RunOptions = Parameters<typeof import("@/lib/agent").startAgentRun>[0];
const { startRun } = vi.hoisted(() => ({ startRun: vi.fn() }));
vi.mock("@/lib/agent", () => ({ startAgentRun: startRun }));
let runs: RunOptions[];
let groundedAvailable = false;

function summary(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    version: 1, noticeVersion: "ai-conversation-v1", threadId: "test-thread", revision: 1,
    expiresAt: "2099-01-01T00:00:00Z", goal: "licence-renewal",
    goalLabel: "Renew a driver's licence", subject: "you", phase: "clarify",
    questionCount: 1, question: {
      id: "issuer-question", kind: "context", factKey: "licence-jurisdiction",
      text: "Is it a B.C.-issued licence?", reason: "Use the appropriate preparation guide.",
      choices: ["Yes, issued in B.C.", "Issued somewhere else", "Not sure"],
      candidates: [], personal: false,
    },
    facts: [], shareContext: false, journeyId: null, suggestedDemoId: null,
    limitation: "missing-context", decisionOrigin: "model", ...overrides,
  };
}

function Harness() {
  const assistant = useAssistant();
  return <>
    <p>{AI_PROCESSING_NOTICE}</p>
    <ConversationNotice />
    <AiConversationContext />
    <label>Message<input value={assistant.draft} onChange={(event) => assistant.setDraft(event.target.value)} /></label>
    <button disabled={assistant.loading || assistant.busy} onClick={() => { void assistant.submit(); }}>Send</button>
    <button onClick={assistant.reset}>Reset</button>
    <button onClick={() => { void assistant.load(); }}>Reload capabilities</button>
  </>;
}

function complete(run: RunOptions, value = summary()) {
  const id = `answer-${run.runId}`;
  run.onEvent({ type: EventType.CUSTOM, name: "bc.response", value: {
    version: 1, kind: "dialogue", origin: "application", decisionOrigin: "model",
  } });
  run.onEvent({ type: EventType.TEXT_MESSAGE_START, messageId: id, role: "assistant" });
  run.onEvent({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: id, delta: "Is it a B.C.-issued licence?" });
  run.onEvent({ type: EventType.TEXT_MESSAGE_END, messageId: id });
  run.onEvent({ type: EventType.CUSTOM, name: "bc.conversation", value: { ...value, threadId: run.threadId } });
  run.onEvent({ type: EventType.RUN_FINISHED, runId: run.runId, threadId: run.threadId });
}

beforeEach(() => {
  runs = [];
  groundedAvailable = false;
  startRun.mockReset().mockImplementation((options: RunOptions) => {
    runs.push(options);
    let resolve!: () => void;
    const done = new Promise<void>((finish) => { resolve = finish; });
    return { done, cancel: resolve };
  });
  vi.stubGlobal("fetch", vi.fn(async (url, init) => {
    if (url === "/api/catalog") return Response.json(catalogFixture);
    if (url === "/api/capabilities") return Response.json({
      ...guidedCapabilities, conversationAvailable: true, conversationAgentReady: true,
      discoveryAvailable: true, requestVersions: groundedAvailable ? [1, 2, 3, 4, 5, 6] : [1, 2, 3, 4, 5],
      taskAssistanceAvailable: groundedAvailable,
    });
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    throw new Error("Unexpected fixture request");
  }));
});

describe("AI-led conversation", () => {
  it("does not downgrade an active conversation when capability discovery becomes unavailable", async () => {
    const { result } = renderHook(useAssistant, { wrapper: AssistantProvider });
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => { await result.current.submit({ prompt: "Renew my licence" }); });
    act(() => complete(runs[0]));
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      if (url === "/api/catalog") return Response.json(catalogFixture);
      if (url === "/api/capabilities") throw new TypeError("Synthetic discovery outage");
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      throw new Error("Unexpected fixture request");
    });
    await act(async () => { await result.current.load(); });
    await act(async () => { await result.current.submit({ prompt: "Yes" }); });
    expect(runs).toHaveLength(2);
    expect(runs[1].conversationVersion).toBe(5);
    expect(runs[1].conversation).toMatchObject({ questionId: "issuer-question", revision: 1 });
    expect(runs[1].messages).toHaveLength(1);
  });

  it("pins the negotiated version until a new page-owned conversation starts", async () => {
    const user = userEvent.setup();
    render(<AssistantProvider><Harness /></AssistantProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    await user.type(screen.getByLabelText("Message"), "Renew my licence");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(runs).toHaveLength(1));
    expect(runs[0].conversationVersion).toBe(5);
    act(() => complete(runs[0]));
    groundedAvailable = true;
    await user.click(screen.getByRole("button", { name: "Reload capabilities" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    await user.type(screen.getByLabelText("Message"), "yes");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(runs).toHaveLength(2));
    expect(runs[1].conversationVersion).toBe(5);
    await user.click(screen.getByRole("button", { name: "Reset" }));
    await user.type(screen.getByLabelText("Message"), "I want EI guidance");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(runs).toHaveLength(3));
    expect(runs[2].conversationVersion).toBe(6);
  });

  it("discloses AI processing, uses fresh v5 context, and understands the next short reply", async () => {
    const user = userEvent.setup();
    render(<AssistantProvider><Harness /></AssistantProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    expect(screen.getByText(/messages are processed by AI in Azure/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    await user.type(screen.getByLabelText("Message"), "PLEASE HELP ME RENEW MY DRIVERS LICENESE PELASE");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(runs).toHaveLength(1));
    expect(runs[0].conversation).toEqual({
      action: "respond", revision: 0, noticeVersion: "ai-conversation-v1", shareContext: false,
    });
    expect(runs[0].discovery).toBeUndefined();
    act(() => complete(runs[0]));
    expect(screen.queryByRole("button", { name: "Yes, issued in B.C." })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Message"), "Yes, issued in B.C.");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(runs).toHaveLength(2));
    expect(runs[1].conversation?.questionId).toBe("issuer-question");
    expect(runs[1].messages).toHaveLength(1);
  });

  it("requires explicit optional sharing and clears it on reset", async () => {
    const user = userEvent.setup();
    render(<AssistantProvider><Harness /></AssistantProvider>);
    const checkbox = await screen.findByRole("checkbox");
    await user.click(checkbox);
    await user.type(screen.getByLabelText("Message"), "Help me prepare");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(runs).toHaveLength(1));
    expect(runs[0].conversation?.shareContext).toBe(true);
    act(() => complete(runs[0], summary({ shareContext: true })));
    await user.click(checkbox);
    await waitFor(() => expect(runs).toHaveLength(2));
    expect(runs[1].conversation).toMatchObject({ action: "sharing", shareContext: false });
    await user.click(screen.getByRole("button", { name: "Reset" }));
    act(() => complete(runs[1], summary({ revision: 2 })));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.queryByText("What I understand")).not.toBeInTheDocument();
  });

  it("validates v5 data separately and never replays those turns to legacy agents", () => {
    expect(runOptionsSchema.safeParse({
      version: 5, mode: "general", conversation: {
        action: "respond", revision: 0, noticeVersion: "ai-conversation-v1", shareContext: false,
      },
    }).success).toBe(true);
    expect(conversationSummarySchema.safeParse(summary()).success).toBe(true);
    expect(conversationSummarySchema.safeParse(summary({ phase: "guide" })).success).toBe(false);
    let state = streamReducer(initialStreamState, {
      type: "start", runId: "run", messageId: "user", prompt: "Personal fixture",
      conversation: { revision: 0, threadId: "test-thread" },
    });
    state.messages[0].status = "complete";
    expect(historyForAgent(state.messages)).toEqual([]);
    state = streamReducer(state, { type: "event", runId: "run", event: {
      type: EventType.CUSTOM, name: "bc.conversation", value: summary(),
    } });
    expect(state.conversation).toBeNull();
    expect(state.pendingConversation).not.toBeNull();
    const stopped = streamReducer(state, { type: "stop", runId: "run" });
    expect(stopped.pendingConversation).toBeNull();
    expect(streamReducer(stopped, { type: "event", runId: "run", event: {
      type: EventType.CUSTOM, name: "bc.conversation", value: summary(),
    } })).toBe(stopped);
  });
});
