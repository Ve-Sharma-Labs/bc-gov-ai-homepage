import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EventType, type BaseEvent } from "@ag-ui/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantProvider, useAssistant } from "@/components/assistant-provider";
import { unavailableCapabilities, type Capabilities } from "@/lib/contract";
import { initialStreamState } from "@/lib/stream";
import { catalogFixture, guidedCapabilities } from "./fixtures";

type StartAgentRun = typeof import("@/lib/agent").startAgentRun;
type AgentRunOptions = Parameters<StartAgentRun>[0];

const { startAgentRunMock } = vi.hoisted(() => ({
  startAgentRunMock: vi.fn<StartAgentRun>(),
}));

vi.mock("@/lib/agent", () => ({ startAgentRun: startAgentRunMock }));

const connectedCapabilities: Capabilities = {
  ...guidedCapabilities,
  mode: "foundry",
  aiConfigured: true,
  message: "TEST FIXTURE: connected transport.",
};

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function mockApi(capabilities: unknown = guidedCapabilities, catalog: unknown = catalogFixture) {
  return vi.fn(async (url: RequestInfo | URL, _init?: RequestInit) => {
    if (String(url) === "/api/catalog") return Response.json(catalog);
    if (String(url) === "/api/capabilities") return Response.json(capabilities);
    throw new Error(`Unexpected test request: ${String(url)}`);
  });
}

function createRun(options: AgentRunOptions) {
  const completion = deferred<void>();
  return {
    options,
    done: completion.promise,
    cancel: vi.fn(() => completion.resolve(undefined)),
    finish: () => completion.resolve(undefined),
    reject: completion.reject,
  };
}

type TestRun = ReturnType<typeof createRun>;
let runs: TestRun[];

function recordRun(options: AgentRunOptions) {
  const run = createRun(options);
  runs.push(run);
  return run;
}

function unavailableRun(options: AgentRunOptions) {
  const run = recordRun(options);
  options.onFailure("AI answers are not connected in this pilot. Your question has been kept.", "FOUNDRY_NOT_CONFIGURED");
  return run;
}

function emit<T extends BaseEvent>(run: TestRun, event: T) {
  run.options.onEvent(event);
}

function answer(run: TestRun, content: string, messageId = "fixture-answer") {
  emit(run, { type: EventType.TEXT_MESSAGE_START, messageId, role: "assistant" });
  emit(run, { type: EventType.TEXT_MESSAGE_CONTENT, messageId, delta: content });
}

function finishAnswer(run: TestRun) {
  emit(run, { type: EventType.RUN_FINISHED, runId: run.options.runId, threadId: run.options.threadId });
}

function annotate(run: TestRun, messageId = "fixture-answer") {
  emit(run, {
    type: EventType.CUSTOM,
    name: "annotations",
    value: { messageId, annotations: [{ sourceId: "fixture-icbc", title: "TEST FIXTURE citation" }] },
  });
}

async function readyAssistant(capabilities: Capabilities = guidedCapabilities) {
  const fetcher = mockApi(capabilities);
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(useAssistant, { wrapper: AssistantProvider });
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  return { ...hook, fetcher };
}

function MemoryEditor() {
  const { catalog, draft, setDraft, selected, selectJourney, checked, setChecked } = useAssistant();
  const stepKey = selected ? `${selected.id}:${selected.steps[0].id}` : "";
  return <>
    <label>Question<input value={draft} onChange={(event) => setDraft(event.target.value)} /></label>
    {catalog && <button onClick={() => selectJourney(catalog.journeys[0])}>Open guided plan</button>}
    {selected && <>
      <h1>{selected.title}</h1>
      <label><input
        type="checkbox"
        checked={checked.has(stepKey)}
        onChange={(event) => {
          const reviewed = event.target.checked;
          setChecked((previous) => {
            const next = new Set(previous);
            if (reviewed) next.add(stepKey); else next.delete(stepKey);
            return next;
          });
        }}
      />{selected.steps[0].title}</label>
    </>}
  </>;
}

beforeEach(() => {
  runs = [];
  startAgentRunMock.mockReset();
  startAgentRunMock.mockImplementation(recordRun);
  vi.stubGlobal("fetch", mockApi());
});

describe("assistant catalogue and capability lifetime", () => {
  it("loads once, exposes loading and verified capabilities, and does not reload on rerender", async () => {
    const content = deferred<Response>();
    const connection = deferred<Response>();
    const fetcher = mockApi().mockReturnValueOnce(content.promise).mockReturnValueOnce(connection.promise);
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(useAssistant, { wrapper: AssistantProvider });

    expect(result.current.loading).toBe(true);
    expect(result.current.catalog).toBeNull();
    expect(result.current.capabilities).toEqual(unavailableCapabilities);
    expect(result.current.state).toEqual(initialStreamState);

    await act(async () => {
      content.resolve(Response.json(catalogFixture));
      connection.resolve(Response.json(connectedCapabilities));
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.catalog).toEqual(catalogFixture);
    expect(result.current.capabilities).toEqual(connectedCapabilities);
    expect(result.current.catalogError).toBe("");
    rerender();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(startAgentRunMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not cache invalid data and clears errors and the disconnected notice on a valid retry", async () => {
    vi.stubGlobal("fetch", mockApi({ aiConfigured: "yes" }, { journeys: [] }));
    const { result } = renderHook(useAssistant, { wrapper: AssistantProvider });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.catalog).toBeNull();
    expect(result.current.catalogError).toContain("catalogue is temporarily unavailable");
    expect(result.current.capabilities).toEqual(unavailableCapabilities);
    startAgentRunMock.mockImplementationOnce(unavailableRun);
    await act(async () => {
      result.current.setDraft("Keep this question");
      expect(await result.current.submit()).toBe(true);
    });

    const content = deferred<Response>();
    const fetcher = mockApi(connectedCapabilities).mockReturnValueOnce(content.promise);
    vi.stubGlobal("fetch", fetcher);
    let retry!: Promise<void>;
    act(() => { retry = result.current.load(); });
    expect(result.current.loading).toBe(true);
    expect(result.current.catalogError).toBe("");
    await act(async () => {
      content.resolve(Response.json(catalogFixture));
      await retry;
    });
    expect(result.current.catalog).toEqual(catalogFixture);
    expect(result.current.capabilities.aiConfigured).toBe(true);
    expect(result.current.catalogError).toBe("");
    expect(result.current.notice).toBe("");
    expect(result.current.draft).toBe("Keep this question");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("retains verified guided plans when a capabilities request fails", async () => {
    const fetcher = mockApi().mockResolvedValueOnce(Response.json(catalogFixture))
      .mockRejectedValueOnce(new TypeError("TEST FIXTURE: disconnected"));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(useAssistant, { wrapper: AssistantProvider });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.catalog).toEqual(catalogFixture);
    expect(result.current.catalogError).toBe("");
    expect(result.current.capabilities.aiConfigured).toBe(false);
  });

  it("aborts superseded loads and ignores responses that arrive out of order despite abort", async () => {
    const { result } = await readyAssistant();
    const oldContent = deferred<Response>();
    const oldConnection = deferred<Response>();
    const fetcher = mockApi(connectedCapabilities)
      .mockReturnValueOnce(oldContent.promise).mockReturnValueOnce(oldConnection.promise);
    vi.stubGlobal("fetch", fetcher);
    let stale!: Promise<void>;
    act(() => { stale = result.current.load(); });
    const signal = fetcher.mock.calls[0][1]?.signal;
    expect(signal?.aborted).toBe(false);
    await act(async () => { await result.current.load(); });
    expect(signal?.aborted).toBe(true);
    expect(result.current.capabilities.aiConfigured).toBe(true);

    await act(async () => {
      oldContent.resolve(Response.json({ invalid: true }));
      oldConnection.resolve(Response.json(guidedCapabilities));
      await stale;
    });
    expect(result.current.catalog).toEqual(catalogFixture);
    expect(result.current.catalogError).toBe("");
    expect(result.current.capabilities.aiConfigured).toBe(true);
    expect(result.current.loading).toBe(false);
  });

  it("aborts a pending load on unmount and prevents retained load actions from fetching again", async () => {
    const content = deferred<Response>();
    const connection = deferred<Response>();
    const fetcher = mockApi().mockReturnValueOnce(content.promise).mockReturnValueOnce(connection.promise);
    vi.stubGlobal("fetch", fetcher);
    const { result, unmount } = renderHook(useAssistant, { wrapper: AssistantProvider });
    const load = result.current.load;
    const signal = fetcher.mock.calls[0][1]?.signal;
    expect(signal?.aborted).toBe(false);
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      content.resolve(Response.json(catalogFixture));
      connection.resolve(Response.json(connectedCapabilities));
      await load();
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(startAgentRunMock).not.toHaveBeenCalled();
  });
});

describe("assistant tab memory", () => {
  it("accepts a question immediately and lets the endpoint report an unavailable connection without inventing an answer", async () => {
    const { result, fetcher } = await readyAssistant();
    startAgentRunMock.mockImplementationOnce(unavailableRun);
    await act(async () => {
      result.current.setDraft("  Help with my licence  ");
      expect(await result.current.submit()).toBe(true);
    });
    expect(result.current.draft).toBe("Help with my licence");
    expect(result.current.notice).toBe("");
    expect(result.current.state.status).toBe("error");
    expect(result.current.state.error).toContain("AI answers are not connected");
    expect(result.current.state.messages).toEqual([expect.objectContaining({ role: "user", content: "Help with my licence" })]);
    expect(result.current.busy).toBe(false);
    expect(startAgentRunMock).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("does not add a second question bubble when retrying the same unavailable turn", async () => {
    const { result } = await readyAssistant();
    startAgentRunMock.mockImplementation(unavailableRun);
    await act(async () => {
      result.current.setDraft("Help with my licence");
      await result.current.submit();
    });
    const firstRunId = result.current.state.runId;
    await act(async () => { await result.current.submit(); });
    expect(result.current.state.runId).not.toBe(firstRunId);
    expect(result.current.state.messages).toHaveLength(1);
    expect(startAgentRunMock).toHaveBeenCalledTimes(2);
  });

  it("dispatches the question while capabilities are still pending and ignores stale connection discovery for that run", async () => {
    const connection = deferred<Response>();
    vi.stubGlobal("fetch", mockApi().mockResolvedValueOnce(Response.json(catalogFixture)).mockReturnValueOnce(connection.promise));
    const { result } = renderHook(useAssistant, { wrapper: AssistantProvider });
    await waitFor(() => expect(result.current.catalog).toEqual(catalogFixture));
    expect(result.current.loading).toBe(true);
    let pending!: Promise<boolean>;
    act(() => {
      result.current.setDraft("Help with my licence");
      pending = result.current.submit();
    });
    expect(result.current.state.messages[0].content).toBe("Help with my licence");
    expect(result.current.state.status).toBe("connecting");
    expect(result.current.draft).toBe("");
    await act(async () => { expect(await pending).toBe(true); });
    expect(result.current.loading).toBe(true);
    expect(startAgentRunMock).toHaveBeenCalledOnce();
    expect(runs[0].options).toMatchObject({ mode: "general" });
    expect(runs[0].options).not.toHaveProperty("journeyId");
    await act(async () => { connection.resolve(Response.json(guidedCapabilities)); });
    expect(result.current.busy).toBe(true);
    expect(runs[0].cancel).not.toHaveBeenCalled();
    expect(startAgentRunMock).toHaveBeenCalledOnce();
  });

  it.each(["pending", "failed"])("uses the configured conversation when capability discovery is %s", async (discovery) => {
    const connection = deferred<Response>();
    vi.stubGlobal("fetch", mockApi().mockResolvedValueOnce(Response.json(catalogFixture)).mockReturnValueOnce(connection.promise));
    const { result } = renderHook(useAssistant, {
      wrapper: ({ children }) => <AssistantProvider conversationBootstrap={{ version: 5, taskAssistance: true }}>
        {children}
      </AssistantProvider>,
    });
    await waitFor(() => expect(result.current.catalog).toEqual(catalogFixture));
    if (discovery === "failed") {
      await act(async () => connection.reject(new TypeError("Synthetic discovery outage")));
    }
    expect(result.current.loading).toBe(discovery === "pending");
    expect(result.current.capabilities.conversationAgentReady).not.toBe(true);
    await act(async () => {
      result.current.setDraft("please help me renew my drivers license");
      await result.current.submit();
    });
    expect(runs[0].options).toMatchObject({
      conversationVersion: 5,
      conversation: { revision: 0, noticeVersion: "ai-conversation-v1", shareContext: false },
    });
    expect(result.current.state.expectsTask).toBe(true);
    act(() => result.current.stop());
    await act(async () => connection.resolve(Response.json({
      ...guidedCapabilities, conversationAvailable: true, conversationAgentReady: true,
      taskAssistanceAvailable: true, requestVersions: [1, 2, 3, 5], retrievalReady: false,
    })));
    expect(result.current.state.status).toBe("stopped");
    expect(result.current.draft).toBe("please help me renew my drivers license");
    expect(startAgentRunMock).toHaveBeenCalledOnce();
  });

  it("keeps drafts, the selected journey and checks when route children unmount and return", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const pushState = vi.spyOn(history, "pushState");
    const replaceState = vi.spyOn(history, "replaceState");
    const user = userEvent.setup();
    const { rerender } = render(<AssistantProvider><MemoryEditor /></AssistantProvider>);
    await screen.findByRole("button", { name: "Open guided plan" });
    await user.type(screen.getByRole("textbox", { name: "Question" }), "An unsent draft");
    await user.click(screen.getByRole("button", { name: "Open guided plan" }));
    await user.click(screen.getByRole("checkbox"));
    rerender(<AssistantProvider><p>Another internal route</p></AssistantProvider>);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    rerender(<AssistantProvider><MemoryEditor /></AssistantProvider>);

    expect(screen.getByRole("textbox")).toHaveValue("An unsent draft");
    expect(screen.getByRole("heading")).toHaveTextContent(catalogFixture.journeys[0].title);
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(startAgentRunMock).not.toHaveBeenCalled();
    expect(storage).not.toHaveBeenCalled();
    expect(pushState).not.toHaveBeenCalled();
    expect(replaceState).not.toHaveBeenCalled();
  });

  it("resets user memory and the thread without discarding the loaded catalogue", async () => {
    const { result, fetcher } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.selectJourney(catalogFixture.journeys[0]);
      result.current.setChecked(new Set(["licence-renewal:prepare"]));
      result.current.setDraft("First question");
      await result.current.submit();
    });
    const first = runs[0];
    act(() => {
      answer(first, "TEST FIXTURE unfinished answer");
      result.current.setDraft("Unsent follow-up");
      result.current.setNotice("A test notice");
      result.current.reset();
    });
    expect(first.cancel).toHaveBeenCalledOnce();
    expect(result.current.state).toEqual(initialStreamState);
    expect(result.current.draft).toBe("");
    expect(result.current.notice).toBe("");
    expect(result.current.selectedId).toBeNull();
    expect(result.current.selected).toBeNull();
    expect(result.current.checked.size).toBe(0);
    expect(result.current.catalog).toEqual(catalogFixture);
    expect(result.current.capabilities).toEqual(connectedCapabilities);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher).toHaveBeenCalledWith("/api/demo/session", expect.objectContaining({ method: "DELETE", keepalive: true }));

    await act(async () => {
      result.current.setDraft("A fresh question");
      await result.current.submit();
    });
    expect(runs[1].options.threadId).not.toBe(first.options.threadId);
    expect(runs[1].options.messages).toEqual([
      expect.objectContaining({ role: "user", content: "A fresh question" }),
    ]);
  });

  it("cancels on provider unmount and starts a new provider with no retained user memory", async () => {
    const { result, unmount } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.selectJourney(catalogFixture.journeys[0]);
      result.current.setChecked(new Set(["licence-renewal:prepare"]));
      result.current.setDraft("A question");
      await result.current.submit();
      result.current.setDraft("An unsent follow-up");
    });
    const first = runs[0];
    unmount();
    expect(first.cancel).toHaveBeenCalledOnce();
    act(() => {
      answer(first, "TEST FIXTURE late answer");
      annotate(first);
      first.options.onFailure("TEST FIXTURE late failure");
    });
    const fresh = await readyAssistant(connectedCapabilities);
    expect(fresh.result.current.draft).toBe("");
    expect(fresh.result.current.checked.size).toBe(0);
    expect(fresh.result.current.selectedId).toBeNull();
    expect(fresh.result.current.state).toEqual(initialStreamState);
  });

  it("requires a provider instead of creating a second implicit state owner", () => {
    expect(() => renderHook(useAssistant)).toThrow("useAssistant must be used within an AssistantProvider.");
  });
});

describe("assistant run coordination", () => {
  it("accepts the next prompt after RUN_FINISHED without waiting for the old connection to close", async () => {
    const { result } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.setDraft("First question");
      await result.current.submit();
      answer(runs[0], "TEST FIXTURE completed answer");
      finishAnswer(runs[0]);
      annotate(runs[0]);
      result.current.setDraft("Next question");
      expect(await result.current.submit()).toBe(true);
    });
    expect(startAgentRunMock).toHaveBeenCalledTimes(2);
    expect(runs[0].cancel).toHaveBeenCalledOnce();
    expect(runs[1].options.messages.map((message) => message.content)).toEqual([
      "First question", "Next question",
    ]);
    expect(result.current.state.messages[1].citations).toHaveLength(1);
    const current = result.current.state;
    act(() => {
      runs[0].options.onFailure("Late failure");
      annotate(runs[0]);
    });
    expect(result.current.state).toBe(current);
  });

  it("keeps pathway scope explicit and clears it without discarding a draft, checks or conversation", async () => {
    const { result } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.selectJourney(catalogFixture.journeys[0]);
      result.current.setChecked(new Set(["licence-renewal:prepare"]));
      result.current.setDraft("Pathway question");
      await result.current.submit();
    });
    expect(runs[0].options).toMatchObject({ mode: "pathway", journeyId: "licence-renewal" });
    act(() => {
      result.current.clearJourney();
      result.current.setSelectedId(null);
    });
    expect(result.current.selectedId).toBe("licence-renewal");
    await act(async () => {
      answer(runs[0], "TEST FIXTURE completed pathway answer");
      finishAnswer(runs[0]);
      runs[0].finish();
      await runs[0].done;
    });
    const messages = result.current.state.messages;
    act(() => {
      result.current.setDraft("A different B.C. government question");
      result.current.clearJourney();
    });
    expect(result.current.selectedId).toBeNull();
    expect(result.current.draft).toBe("A different B.C. government question");
    expect(result.current.checked).toEqual(new Set(["licence-renewal:prepare"]));
    expect(result.current.state.messages).toBe(messages);
    await act(async () => { await result.current.submit(); });
    expect(runs[1].options.mode).toBe("general");
    expect(runs[1].options).not.toHaveProperty("journeyId");
    expect(runs[1].options.threadId).toBe(runs[0].options.threadId);
  });

  it("does not fall back to a specialist when general chat is unconfigured", async () => {
    const { result } = await readyAssistant({
      ...connectedCapabilities,
      generalChatConfigured: false,
      journeys: { "licence-renewal": true, "rental-assistance": true, "health-coverage": true, "primary-care": true, "service-bc": true },
    });
    await act(async () => {
      result.current.setDraft("What can the provincial government help with?");
      await result.current.submit();
      runs[0].options.onFailure("General B.C. chat is not connected.", "GENERAL_AGENT_NOT_CONFIGURED");
    });
    expect(startAgentRunMock).toHaveBeenCalledOnce();
    expect(runs[0].options.mode).toBe("general");
    expect(runs[0].options).not.toHaveProperty("journeyId");
    expect(result.current.selectedId).toBeNull();
    expect(result.current.state.status).toBe("error");
    expect(result.current.draft).toBe("What can the provincial government help with?");
  });

  it("preserves a genuine model clarification in the next request's history", async () => {
    const { result } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.setDraft("I need help with a permit");
      await result.current.submit();
      emit(runs[0], { type: EventType.CUSTOM, name: "bc.response", value: { version: 1, kind: "dialogue", origin: "model" } });
      answer(runs[0], "Which type of permit do you mean?");
      finishAnswer(runs[0]);
      runs[0].finish();
      await runs[0].done;
      result.current.setDraft("A business permit");
      await result.current.submit();
    });
    expect(runs[1].options.messages.map((message) => message.content)).toEqual([
      "I need help with a permit", "Which type of permit do you mean?", "A business permit",
    ]);
    expect(result.current.state.error).toBeNull();
  });

  it.each(["GREETING", "JOURNEY_REQUIRED"])("recovers a legacy %s as application dialogue and permits a general follow-up", async (code) => {
    const { result } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.setDraft("Help me");
      await result.current.submit();
      runs[0].options.onFailure("Do not display raw provider details", code);
      runs[0].finish();
      await runs[0].done;
    });
    expect(result.current.state.status).toBe("complete");
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.messages[1]).toMatchObject({ response: { kind: "dialogue", origin: "application" } });
    expect(result.current.busy).toBe(false);
    await act(async () => {
      result.current.setDraft("Tell me about B.C. parks");
      await result.current.submit();
    });
    expect(runs[1].options.mode).toBe("general");
    expect(runs[1].options.messages.every((message) => message.role === "user")).toBe(true);
    expect(runs[1].options.messages.map((message) => message.content)).toEqual(["Help me", "Tell me about B.C. parks"]);
  });

  it("rejects blank and duplicate submissions and guards journey changes before React rerenders", async () => {
    const { result } = await readyAssistant(connectedCapabilities);
    const controller = result.current;
    await act(async () => {
      controller.setDraft(" \n ");
      expect(await controller.submit()).toBe(false);
      controller.setSelectedId(() => "licence-renewal");
      controller.setDraft("First");
      controller.setDraft((previous) => `${previous} question`);
      const first = controller.submit();
      controller.selectJourney(catalogFixture.journeys[1]);
      const duplicate = controller.submit();
      expect(await Promise.all([first, duplicate])).toEqual([true, false]);
    });
    expect(startAgentRunMock).toHaveBeenCalledOnce();
    expect(result.current.selectedId).toBe("licence-renewal");
    expect(result.current.busy).toBe(true);
    expect(result.current.state.status).toBe("connecting");
    expect(result.current.state.announcement).toContain("Question sent");
    expect(runs[0].options.messages).toEqual([
      expect.objectContaining({ role: "user", content: "First question" }),
    ]);
    await act(async () => {
      controller.setDraft("Another question");
      expect(await controller.submit()).toBe(false);
    });
    expect(result.current.draft).toBe("Another question");
    expect(startAgentRunMock).toHaveBeenCalledOnce();
  });

  it.each(["stop", "reset"] as const)("prevents a transport start when %s runs during the dynamic import", async (action) => {
    const { result } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.setDraft("Question before import");
      const pending = result.current.submit();
      result.current[action]();
      expect(await pending).toBe(false);
    });
    expect(startAgentRunMock).not.toHaveBeenCalled();
    expect(result.current.busy).toBe(false);
    expect(result.current.state.status).toBe(action === "reset" ? "idle" : "stopped");
    expect(result.current.draft).toBe(action === "reset" ? "" : "Question before import");
  });

  it.each(["stop", "reset"] as const)("cancels the returned handle when %s happens synchronously inside subscribe", async (action) => {
    const { result } = await readyAssistant(connectedCapabilities);
    startAgentRunMock.mockImplementationOnce((options) => {
      const run = recordRun(options);
      result.current[action]();
      answer(run, "TEST FIXTURE late synchronous answer");
      return run;
    });
    await act(async () => {
      result.current.setDraft("Question during subscribe");
      expect(await result.current.submit()).toBe(true);
    });
    expect(runs[0].cancel).toHaveBeenCalledOnce();
    expect(result.current.busy).toBe(false);
    expect(result.current.state.messages.some((message) => message.role === "assistant")).toBe(false);
    expect(result.current.state.status).toBe(action === "reset" ? "idle" : "stopped");
    await act(async () => {
      result.current.setDraft("A newer question");
      expect(await result.current.submit()).toBe(true);
    });
    expect(startAgentRunMock).toHaveBeenCalledTimes(2);
  });

  it.each(["stop", "reset"] as const)("ignores late events, failures, close and completion after %s and during a newer run", async (action) => {
    const { result } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.setDraft("Old question");
      await result.current.submit();
    });
    const first = runs[0];
    act(() => {
      answer(first, "TEST FIXTURE partial answer");
      result.current[action]();
    });
    const stoppedState = result.current.state;
    act(() => {
      annotate(first);
      first.options.onFailure("TEST FIXTURE stale failure");
      first.options.onClose();
      finishAnswer(first);
    });
    expect(result.current.state).toBe(stoppedState);
    expect(first.cancel).toHaveBeenCalledOnce();

    await act(async () => {
      result.current.setDraft("New question");
      await result.current.submit();
    });
    const nextRunId = result.current.state.runId;
    await act(async () => {
      answer(first, "TEST FIXTURE stale delta", "late-answer");
      annotate(first, "late-answer");
      first.options.onFailure("TEST FIXTURE stale failure");
      first.options.onClose();
      first.finish();
      await first.done;
      result.current.setDraft("Do not duplicate");
      expect(await result.current.submit()).toBe(false);
    });
    expect(result.current.state.runId).toBe(nextRunId);
    expect(result.current.state.status).toBe("connecting");
    expect(result.current.state.pendingCitations).toEqual({});
    expect(result.current.state.error).toBeNull();
    expect(startAgentRunMock).toHaveBeenCalledTimes(2);
    expect(runs[1].cancel).not.toHaveBeenCalled();
  });

  it("keeps an edited draft when stopping instead of replacing it with the previous question", async () => {
    const { result } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.setDraft("Original question");
      await result.current.submit();
    });
    act(() => {
      answer(runs[0], "TEST FIXTURE partial answer");
      result.current.setDraft("An edited follow-up");
      result.current.stop();
    });
    expect(result.current.draft).toBe("An edited follow-up");
    expect(result.current.state.status).toBe("stopped");
    expect(result.current.state.messages.every((message) => message.status === "partial")).toBe(true);
  });

  it.each([
    { label: "transport failure", status: "error", terminate: (run: TestRun) => run.options.onFailure("TEST FIXTURE connection lost") },
    { label: "early close", status: "interrupted", terminate: (run: TestRun) => run.options.onClose() },
    {
      label: "server cancellation",
      status: "stopped",
      terminate: (run: TestRun) => emit(run, {
        type: EventType.RUN_FINISHED, runId: run.options.runId, outcome: { type: "cancelled" },
      }),
    },
  ])("recovers the question and releases the run on $label", async ({ status, terminate }) => {
    const { result } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.setDraft("Keep my question");
      await result.current.submit();
    });
    act(() => {
      answer(runs[0], "TEST FIXTURE unfinished answer");
      terminate(runs[0]);
    });
    expect(result.current.state.status).toBe(status);
    expect(result.current.draft).toBe("Keep my question");
    expect(result.current.busy).toBe(false);
    expect(result.current.state.messages.every((message) => message.status === "partial")).toBe(true);
    expect(runs[0].cancel).toHaveBeenCalledOnce();
    await act(async () => { expect(await result.current.submit()).toBe(true); });
    expect(runs[1].options.messages).toEqual([
      expect.objectContaining({ role: "user", content: "Keep my question" }),
    ]);
  });

  it("uses current completed history on synchronous repeats and excludes cancelled turns", async () => {
    const { result } = await readyAssistant(connectedCapabilities);
    const controller = result.current;
    await act(async () => {
      controller.setDraft("First question");
      await controller.submit();
    });
    const first = runs[0];
    await act(async () => {
      answer(first, "TEST FIXTURE completed answer");
      finishAnswer(first);
      annotate(first);
      first.finish();
      await first.done;
      controller.setDraft("Second question");
      expect(await controller.submit()).toBe(true);
    });
    expect(runs[1].options.messages).toEqual([
      expect.objectContaining({ role: "user", content: "First question" }),
      expect.objectContaining({ role: "user", content: "Second question" }),
    ]);
    expect(result.current.state.messages[1].citations).toEqual([
      expect.objectContaining({ sourceId: "fixture-icbc" }),
    ]);

    await act(async () => {
      answer(runs[1], "TEST FIXTURE cancelled answer", "cancelled-answer");
      controller.stop();
      controller.setDraft("Third question");
      expect(await controller.submit()).toBe(true);
    });
    expect(runs[2].options.messages).toEqual([
      expect.objectContaining({ role: "user", content: "First question" }),
      expect.objectContaining({ role: "user", content: "Third question" }),
    ]);
    expect(runs[2].options.threadId).toBe(first.options.threadId);
  });

  it("recovers from a startup exception without locking future submissions", async () => {
    const { result } = await readyAssistant(connectedCapabilities);
    startAgentRunMock.mockImplementationOnce(() => { throw new Error("TEST FIXTURE startup failure"); });
    await act(async () => {
      result.current.setDraft("Retry this question");
      expect(await result.current.submit()).toBe(false);
    });
    expect(result.current.state.status).toBe("error");
    expect(result.current.draft).toBe("Retry this question");
    await act(async () => { expect(await result.current.submit()).toBe(true); });
    expect(startAgentRunMock).toHaveBeenCalledTimes(2);
  });

  it("handles an unexpectedly rejected completion promise without leaving a busy run", async () => {
    const { result } = await readyAssistant(connectedCapabilities);
    await act(async () => {
      result.current.setDraft("Recover this question");
      await result.current.submit();
    });
    await act(async () => {
      runs[0].reject(new Error("TEST FIXTURE rejected completion"));
      await Promise.resolve();
    });
    expect(result.current.state.status).toBe("error");
    expect(result.current.busy).toBe(false);
    expect(result.current.draft).toBe("Recover this question");
    expect(runs[0].cancel).toHaveBeenCalledOnce();
  });
});
