import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EventType } from "@ag-ui/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantProvider, useAssistant } from "@/components/assistant-provider";
import { AiConversationContext, ConversationNotice } from "@/components/ai-conversation";
import { Conversation } from "@/components/conversation";
import type { ConversationSummary, TaskSnapshot } from "@/lib/contract";
import { initialStreamState, streamReducer } from "@/lib/stream";
import { catalogFixture, guidedCapabilities } from "./fixtures";

type RunOptions = Parameters<typeof import("@/lib/agent").startAgentRun>[0];
const { startRun } = vi.hoisted(() => ({ startRun: vi.fn() }));
vi.mock("@/lib/agent", () => ({ startAgentRun: startRun }));
const journey = catalogFixture.journeys[0];
let runs: RunOptions[];
let controls: Record<string, unknown>[];
let currentSummary: ConversationSummary;
let currentTask: TaskSnapshot;

function initialTask(threadId: string): TaskSnapshot {
  return {
    version: 1, threadId, revision: 1,
    task: {
      id: "task-fixture", journeyId: journey.id, catalogVersion: "a".repeat(64),
      stepVersions: Object.fromEntries(journey.steps.map((step) => [step.id, "a".repeat(64)])),
      stepIds: journey.steps.map((step) => step.id), activeStepId: journey.steps[0].id,
      reviewedStepIds: [], skippedStepIds: [], phase: "preparing", waitingFor: "readiness",
      lastAction: "continue", municipality: null, service: "icbc-licensing",
    },
    step: journey.steps[0], handoffs: journey.handoffs, sources: catalogFixture.sources,
    guidance: "TEST FIXTURE: prepare the identification for this step.",
  };
}

function Harness() {
  const assistant = useAssistant();
  return <>
    <ConversationNotice />
    <Conversation state={assistant.state} catalog={assistant.catalog} hasDiscoveryContext={!!assistant.state.task}>
      <AiConversationContext />
    </Conversation>
    <p role="status">{assistant.notice}</p>
    <label>Message<input value={assistant.draft} onChange={(event) => assistant.setDraft(event.target.value)} /></label>
    <button disabled={assistant.loading || assistant.busy} onClick={() => { void assistant.submit(); }}>Send</button>
  </>;
}

function complete(run: RunOptions, emitGuide = true) {
  const id = `answer-${run.runId}`;
  run.onEvent({ type: EventType.CUSTOM, name: "bc.response", value: {
    version: 1, kind: "handoff", origin: "application", decisionOrigin: "model",
  } });
  run.onEvent({ type: EventType.TEXT_MESSAGE_START, messageId: id, role: "assistant" });
  run.onEvent({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: id, delta: "TEST FIXTURE: Let's work on your current preparation step." });
  run.onEvent({ type: EventType.TEXT_MESSAGE_END, messageId: id });
  run.onEvent({ type: EventType.CUSTOM, name: "bc.task", value: currentTask });
  run.onEvent({ type: EventType.CUSTOM, name: "bc.conversation", value: currentSummary });
  if (emitGuide) run.onEvent({ type: EventType.CUSTOM, name: "bc.artifact", value: {
    version: 1, id: "task-task-fixture", kind: "preparation", journey,
    sources: catalogFixture.sources, transactionsEnabled: false,
  } });
  run.onEvent({ type: EventType.RUN_FINISHED, runId: run.runId, threadId: run.threadId });
}

beforeEach(() => {
  runs = [];
  controls = [];
  startRun.mockReset().mockImplementation((options: RunOptions) => {
    runs.push(options);
    return { done: new Promise<void>(() => {}), cancel: vi.fn() };
  });
  vi.stubGlobal("fetch", vi.fn(async (url, init) => {
    if (url === "/api/catalog") return Response.json(catalogFixture);
    if (url === "/api/capabilities") return Response.json({
      ...guidedCapabilities, conversationAvailable: true, conversationAgentReady: true,
      taskAssistanceAvailable: true, requestVersions: [1, 2, 3, 5],
    });
    if (url === "/api/conversation/control") {
      const request = JSON.parse(init.body);
      controls.push(request);
      currentSummary = {
        ...currentSummary, revision: currentSummary.revision + 1,
        ...(request.action === "sharing" ? { shareContext: request.shareContext } : {}),
      };
      currentTask = { ...currentTask, revision: currentSummary.revision };
      if (request.action === "review" && currentTask.task) {
        currentTask = {
          ...currentTask, step: journey.steps[1],
          task: {
            ...currentTask.task, activeStepId: journey.steps[1].id,
            reviewedStepIds: [journey.steps[0].id], lastAction: "reviewed",
          },
          guidance: "TEST FIXTURE: choose the service office for the next step.",
        };
      }
      return Response.json({ summary: currentSummary, task: currentTask,
        notice: request.action === "sharing" ? "Optional context sharing is on." : "Preparation progress updated." });
    }
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    throw new Error("Unexpected fixture request");
  }));
});

async function ready() {
  const user = userEvent.setup();
  render(<AssistantProvider><Harness /></AssistantProvider>);
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  await user.type(screen.getByLabelText("Message"), "Renew my BC licence");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(runs).toHaveLength(1));
  currentSummary = {
    version: 1, noticeVersion: "ai-conversation-v1", threadId: runs[0].threadId, revision: 1,
    expiresAt: "2099-01-01T00:00:00Z", goal: "licence-renewal", goalLabel: "Licence renewal",
    subject: "you", phase: "guide", questionCount: 0, question: null, facts: [],
    shareContext: false, journeyId: journey.id, suggestedDemoId: null,
    limitation: "none", decisionOrigin: "model",
  };
  currentTask = initialTask(runs[0].threadId);
  act(() => complete(runs[0]));
  return user;
}

describe("useful preparation continuation", () => {
  it("changes sharing without creating messages, invoking the model, or clearing the draft", async () => {
    const user = await ready();
    const messages = document.querySelectorAll(".message").length;
    await user.type(screen.getByLabelText("Message"), "My unfinished question");
    await user.click(screen.getByRole("checkbox", { name: /Use personal details/ }));
    await waitFor(() => expect(controls).toHaveLength(1));
    expect(controls[0]).toMatchObject({ action: "sharing", shareContext: true, revision: 1 });
    expect(runs).toHaveLength(1);
    expect(document.querySelectorAll(".message")).toHaveLength(messages);
    expect(screen.getByLabelText("Message")).toHaveValue("My unfinished question");
    expect(screen.getByText("Optional context sharing is on.")).toBeInTheDocument();
    expect(screen.queryByText("Use the optional details I choose to share.")).not.toBeInTheDocument();
    expect(screen.getByText("Full preparation guide")).toBeInTheDocument();
  });

  it("connects readiness controls to the next practical step without a fake chat turn", async () => {
    const user = await ready();
    const messages = document.querySelectorAll(".message").length;
    await user.click(screen.getByRole("button", { name: "I have this ready" }));
    await waitFor(() => expect(controls).toHaveLength(1));
    expect(controls[0]).toMatchObject({
      action: "review", reviewed: true, taskId: "task-fixture", stepId: journey.steps[0].id,
    });
    expect(screen.getByText(/choose the service office for the next step/)).toBeInTheDocument();
    expect(document.querySelectorAll(".message")).toHaveLength(messages);
    await user.click(screen.getByText("Full preparation guide"));
    expect(screen.getByRole("checkbox", { name: journey.steps[0].title })).toBeChecked();
  });

  it("keeps the guide through a follow-up and does not repeat per-turn boilerplate", async () => {
    const user = await ready();
    await user.type(screen.getByLabelText("Message"), "Are you helping?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(runs).toHaveLength(2));
    expect(screen.getByText("Full preparation guide")).toBeInTheDocument();
    currentSummary = { ...currentSummary, revision: 2 };
    currentTask = { ...currentTask, revision: 2 };
    act(() => complete(runs[1], false));
    expect(screen.getAllByText("Full preparation guide")).toHaveLength(1);
    expect(screen.queryByText("AI-assisted guidance · reviewed wording and preparation")).not.toBeInTheDocument();
  });

  it("does not discard validated task data when a new run is stopped", () => {
    const task = initialTask("thread");
    const started = streamReducer({ ...initialStreamState, task }, {
      type: "start", runId: "run", messageId: "user", prompt: "Continue",
      conversation: { revision: 1, threadId: "thread" }, taskAssistance: true,
    });
    const stopped = streamReducer(started, { type: "stop", runId: "run" });
    expect(stopped.task).toEqual(task);
    expect(stopped.pendingTask).toBeNull();
  });
});
