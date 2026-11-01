import { useRef } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EventType } from "@ag-ui/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantProvider, useAssistant } from "@/components/assistant-provider";
import { ChatExperience } from "@/components/chat-experience";
import { Composer } from "@/components/composer";
import { AI_PROCESSING_NOTICE } from "@/components/ai-conversation";
import { conversationStarters } from "@/components/conversation-starters";
import type { ConversationSummary, TaskSnapshot } from "@/lib/contract";
import { catalogFixture, guidedCapabilities } from "./fixtures";

type RunOptions = Parameters<typeof import("@/lib/agent").startAgentRun>[0];
const { startRun } = vi.hoisted(() => ({ startRun: vi.fn() }));
vi.mock("@/lib/agent", () => ({ startAgentRun: startRun }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
let runs: RunOptions[];

function Harness() {
  const assistant = useAssistant();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  return <>
    <ChatExperience />
    <Composer inputRef={inputRef} value={assistant.draft} onChange={assistant.setDraft}
      busy={assistant.busy || assistant.loading} onSubmit={() => { void assistant.submit(); }} onStop={assistant.stop}
      privacyText={AI_PROCESSING_NOTICE} />
  </>;
}

function complete(run: RunOptions, overrides: Partial<ConversationSummary> = {}, withTask = false) {
  const summary: ConversationSummary = {
    version: 1, noticeVersion: "ai-conversation-v1", threadId: run.threadId, revision: runs.length,
    expiresAt: "2099-01-01T00:00:00Z", goal: "licence-renewal", goalLabel: "Licence renewal",
    subject: "you", phase: "clarify", questionCount: 1,
    question: {
      id: "issuer-question", kind: "context", factKey: "licence-jurisdiction",
      text: "Is it a B.C.-issued licence?", reason: "Choose the appropriate licensing route.",
      choices: ["Yes, issued in B.C.", "Issued somewhere else", "Not sure"], candidates: [], personal: false,
    },
    facts: [], shareContext: false, journeyId: null, suggestedDemoId: null,
    limitation: "missing-context", decisionOrigin: "application", ...overrides,
  };
  const journey = catalogFixture.journeys[0];
  const snapshot: TaskSnapshot = {
    version: 1, threadId: run.threadId, revision: summary.revision,
    task: withTask ? {
      id: "fixture-task", journeyId: journey.id, catalogVersion: "a".repeat(64),
      stepVersions: Object.fromEntries(journey.steps.map((step) => [step.id, "a".repeat(64)])),
      stepIds: journey.steps.map((step) => step.id), activeStepId: journey.steps[0].id,
      reviewedStepIds: [], skippedStepIds: [], phase: "preparing", waitingFor: "readiness",
      lastAction: "continue", municipality: null, service: null,
    } : null,
    step: withTask ? journey.steps[0] : null,
    sources: withTask ? catalogFixture.sources : [], handoffs: withTask ? journey.handoffs : [],
    guidance: withTask ? "TEST FIXTURE: Check the accepted ID privately." : "",
  };
  const id = `answer-${run.runId}`;
  run.onEvent({ type: EventType.CUSTOM, name: "bc.response", value: {
    version: 1, kind: "dialogue", origin: "application", decisionOrigin: "application",
  } });
  run.onEvent({ type: EventType.TEXT_MESSAGE_START, messageId: id, role: "assistant" });
  run.onEvent({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: id,
    delta: summary.question?.text ?? "Use the [ICBC ID guide](https://www.icbc.com/driver-licensing/visit-dl-office/Accepted-ID) to prepare." });
  run.onEvent({ type: EventType.TEXT_MESSAGE_END, messageId: id });
  run.onEvent({ type: EventType.CUSTOM, name: "bc.conversation", value: summary });
  run.onEvent({ type: EventType.CUSTOM, name: "bc.task", value: snapshot });
  if (withTask) run.onEvent({ type: EventType.CUSTOM, name: "bc.artifact", value: {
    version: 1, id: "task-fixture-task", kind: "preparation", journey, sources: catalogFixture.sources, transactionsEnabled: false,
  } });
  run.onEvent({ type: EventType.RUN_FINISHED, runId: run.runId, threadId: run.threadId });
}

beforeEach(() => {
  runs = [];
  startRun.mockReset().mockImplementation((options: RunOptions) => {
    runs.push(options);
    return { done: new Promise<void>(() => {}), cancel: vi.fn() };
  });
  vi.stubGlobal("fetch", vi.fn(async (url, init) => {
    if (url === "/api/catalog") return Response.json(catalogFixture);
    if (url === "/api/capabilities") return Response.json({
      ...guidedCapabilities, conversationAvailable: true, conversationAgentReady: true,
      taskAssistanceAvailable: true, syntheticContextAvailable: false, requestVersions: [1, 2, 3, 5],
      localEvidenceEvaluation: true,
    });
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    throw new Error("Unexpected fixture request");
  }));
});

async function ready() {
  render(<AssistantProvider><Harness /></AssistantProvider>);
  await screen.findByRole("button", { name: "Details" });
  return userEvent.setup();
}

describe("text-first service chat", () => {
  it.each(conversationStarters)("fills, focuses, and waits for Send: %s", async (prompt) => {
    const user = await ready();
    await user.click(screen.getByRole("button", { name: prompt }));
    const composer = screen.getByRole("textbox", { name: "What would you like help with?" });
    expect(composer).toHaveValue(prompt);
    expect(composer).toHaveFocus();
    expect(runs).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Send question" }));
    await waitFor(() => expect(runs).toHaveLength(1));
    expect(runs[0].messages.at(-1)?.content).toBe(prompt);
    expect(runs[0].mode).toBe("general");
    expect(runs[0].conversation?.shareContext).toBe(false);
  });

  it("preserves an existing draft until replacement is explicitly chosen", async () => {
    const user = await ready();
    const composer = screen.getByRole("textbox");
    await user.type(composer, "My unfinished question");
    await user.click(screen.getByRole("button", { name: conversationStarters[0] }));
    expect(composer).toHaveValue("My unfinished question");
    await user.click(screen.getByRole("button", { name: "Keep my draft" }));
    expect(composer).toHaveValue("My unfinished question");
    await user.click(screen.getByRole("button", { name: conversationStarters[1] }));
    await user.click(screen.getByRole("button", { name: "Replace draft" }));
    expect(composer).toHaveValue(conversationStarters[1]);
    expect(composer).toHaveFocus();
    expect(runs).toHaveLength(0);
  });

  it("keeps settings optional and returns focus on Escape without sending anything", async () => {
    const user = await ready();
    const calls = vi.mocked(fetch).mock.calls.length;
    expect(screen.queryByRole("checkbox", { name: /Use personal details/ })).not.toBeInTheDocument();
    expect(screen.getByText("Local evaluation only.")).not.toBeVisible();
    await user.type(screen.getByRole("textbox"), "Keep this draft");
    await user.click(screen.getByRole("button", { name: "Details" }));
    const sharing = screen.getByRole("checkbox", { name: /Use personal details/ });
    const details = document.querySelector<HTMLElement>(".conversation-details-content")!;
    expect(within(details).getByText(AI_PROCESSING_NOTICE)).toBeVisible();
    expect(within(details).getByText("Local evaluation only.")).toBeVisible();
    expect(sharing).not.toBeChecked();
    expect(screen.getByRole("textbox")).toBeEnabled();
    sharing.focus();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Details" })).toHaveFocus();
    expect(screen.queryByRole("checkbox", { name: /Use personal details/ })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Keep this draft");
    expect(vi.mocked(fetch).mock.calls.length).toBe(calls);
    expect(runs).toHaveLength(0);
  });

  it("answers the issuer in plain text and replaces pending state without answer widgets", async () => {
    const user = await ready();
    await user.type(screen.getByRole("textbox"), conversationStarters[0]);
    await user.click(screen.getByRole("button", { name: "Send question" }));
    await waitFor(() => expect(runs).toHaveLength(1));
    act(() => complete(runs[0]));
    expect(screen.getByText("Is it a B.C.-issued licence?")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Issued somewhere else" })).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox"), "Issued somewhere else");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    await waitFor(() => expect(runs).toHaveLength(2));
    expect(runs[1].conversation).toMatchObject({ questionId: "issuer-question", revision: 1 });
    const question = {
      id: "route-question", kind: "intent" as const, factKey: null,
      text: "Renew with the original issuer or get a B.C. licence?",
      reason: "These are different services.", choices: ["Renew with the original issuer", "Get a B.C. licence"],
      candidates: [], personal: false,
    };
    act(() => complete(runs[1], { question, questionCount: 2 }));
    expect(screen.getByText(question.text)).toBeVisible();
    expect(document.querySelector(".conversation .ai-conversation-context")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Examples" }));
    await user.click(screen.getByRole("button", { name: conversationStarters[2] }));
    expect(runs).toHaveLength(2);
    expect(screen.getByRole("textbox")).toHaveValue(conversationStarters[2]);
    await user.click(screen.getByRole("button", { name: "Send question" }));
    await waitFor(() => expect(runs).toHaveLength(3));
    expect(runs[2].messages.at(-1)?.content).toBe(conversationStarters[2]);
    expect(runs[2].conversation?.questionId).toBe("route-question");
  });

  it("keeps the current guide in Details but the actionable source link in chat", async () => {
    const user = await ready();
    await user.type(screen.getByRole("textbox"), "Renew my BC licence");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    await waitFor(() => expect(runs).toHaveLength(1));
    act(() => complete(runs[0], { phase: "guide", question: null, journeyId: catalogFixture.journeys[0].id }, true));
    const conversation = screen.getByRole("region", { name: "Conversation" });
    expect(within(conversation).getByRole("link", { name: /ICBC ID guide/ })).toBeVisible();
    expect(within(conversation).queryByRole("button", { name: "I have this ready" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "I have this ready" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByRole("button", { name: "I have this ready" })).toBeVisible();
    expect(screen.getByText("Full preparation guide")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Close details" }));
    expect(screen.getByText("Full preparation guide")).not.toBeVisible();
    expect(runs).toHaveLength(1);
  });
});
