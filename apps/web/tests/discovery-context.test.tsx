import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EventType } from "@ag-ui/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantProvider, useAssistant } from "@/components/assistant-provider";
import { DiscoveryContext } from "@/components/discovery-context";
import type { DiscoverySummary } from "@/lib/contract";
import { catalogFixture, guidedCapabilities } from "./fixtures";
import { discoveryFixture } from "./discovery-fixtures";

type StartRun = typeof import("@/lib/agent").startAgentRun;
type Options = Parameters<StartRun>[0];
const { startRun } = vi.hoisted(() => ({ startRun: vi.fn<StartRun>() }));
vi.mock("@/lib/agent", () => ({ startAgentRun: startRun }));

let runs: Options[];
let fetcher: ReturnType<typeof vi.fn>;
function Harness() {
  const assistant = useAssistant();
  return <>
    <DiscoveryContext />
    <label>Fixture message<input value={assistant.draft} onChange={(event) => assistant.setDraft(event.target.value)} /></label>
    <button disabled={assistant.loading || assistant.busy} onClick={() => { void assistant.submit(); }}>Send fixture message</button>
    <button onClick={assistant.reset}>Reset fixture</button>
    {assistant.state.error && <p role="alert">{assistant.state.error}</p>}
  </>;
}

function complete(options: Options, summary: DiscoverySummary) {
  const id = "answer-" + options.runId;
  options.onEvent({ type: EventType.CUSTOM, name: "bc.response", value: { version: 1, kind: "dialogue", origin: "application" } });
  options.onEvent({ type: EventType.TEXT_MESSAGE_START, messageId: id, role: "assistant" });
  options.onEvent({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: id, delta: summary.question?.text ?? "TEST FIXTURE plan" });
  options.onEvent({ type: EventType.TEXT_MESSAGE_END, messageId: id });
  options.onEvent({ type: EventType.CUSTOM, name: "bc.discovery", value: { ...summary, threadId: options.threadId } });
  options.onEvent({ type: EventType.RUN_FINISHED, runId: options.runId, threadId: options.threadId });
}

beforeEach(() => {
  runs = [];
  startRun.mockReset().mockImplementation((options) => {
    runs.push(options);
    let finish!: () => void;
    const done = new Promise<void>((resolve) => { finish = resolve; });
    return { done, cancel: () => finish() };
  });
  fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (url === "/api/catalog") return Response.json(catalogFixture);
    if (url === "/api/capabilities") return Response.json({
      ...guidedCapabilities, discoveryAvailable: true, requestVersions: [1, 2, 3, 4],
    });
    if (url === "/api/discovery" && init?.method === "DELETE") return new Response(null, { status: 204 });
    if (url === "/api/demo/session" && init?.method === "DELETE") return new Response(null, { status: 204 });
    throw new Error(`Unexpected test request: ${String(url)}`);
  });
  vi.stubGlobal("fetch", fetcher);
});

async function openQuestion() {
  const user = userEvent.setup();
  render(<AssistantProvider><Harness /></AssistantProvider>);
  await waitFor(() => expect(screen.getByRole("button", { name: "Send fixture message" })).toBeEnabled());
  await user.type(screen.getByLabelText("Fixture message"), "TEST FIXTURE motorcycle next year");
  await user.click(screen.getByRole("button", { name: "Send fixture message" }));
  await waitFor(() => expect(runs).toHaveLength(1));
  act(() => complete(runs[0], discoveryFixture()));
  return user;
}

describe("context-first conversation controls", () => {
  it("negotiates discovery, shows relevant context, and submits one answer without old personal history", async () => {
    const user = await openQuestion();
    expect(runs[0].discovery).toEqual({ action: "respond", revision: 0 });
    expect(screen.getByRole("heading", { name: "What I understand" })).toBeInTheDocument();
    expect(screen.getByText("Next year")).toBeInTheDocument();
    expect(screen.getByText("You told me")).toBeInTheDocument();
    await user.click(screen.getByText("Why I'm asking"));
    expect(screen.getByText(/optional planning context/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Under 19" }));
    await waitFor(() => expect(runs).toHaveLength(2));
    expect(runs[1].discovery).toEqual({ action: "respond", revision: 1, questionId: "fixture-age-question" });
    expect(runs[1].messages).toHaveLength(1);
    expect(runs[1].messages[0].content).toBe("Under 19");
    expect(screen.getByRole("button", { name: "Skip this question" })).toBeDisabled();
  });

  it("offers skip and general guidance without activating a fictional persona", async () => {
    const user = await openQuestion();
    await user.click(screen.getByRole("button", { name: "Skip this question" }));
    await waitFor(() => expect(runs).toHaveLength(2));
    expect(runs[1].discovery?.action).toBe("skip");
    act(() => complete(runs[1], discoveryFixture({ revision: 2 })));
    await user.click(screen.getByRole("button", { name: "Give me general guidance" }));
    await waitFor(() => expect(runs).toHaveLength(3));
    expect(runs[2].discovery).toEqual({ action: "general", revision: 2 });
    expect(fetcher.mock.calls.some(([url]) => url === "/api/demo/session")).toBe(false);
  });

  it("preserves an explicit correction when retrying a failed request", async () => {
    const user = await openQuestion();
    await user.click(screen.getByRole("button", { name: "Change when you are planning" }));
    const input = screen.getByLabelText("Change when you are planning");
    await user.clear(input);
    await user.type(input, "Later");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    await waitFor(() => expect(runs).toHaveLength(2));
    expect(runs[1].discovery).toEqual({ action: "correct", revision: 1, factKey: "timeframe" });
    act(() => runs[1].onFailure("TEST FIXTURE unavailable", "DISCOVERY_UNAVAILABLE"));
    expect(screen.getByLabelText("Fixture message")).toHaveValue("Later");
    await user.click(screen.getByRole("button", { name: "Send fixture message" }));
    await waitFor(() => expect(runs).toHaveLength(3));
    expect(runs[2].discovery).toEqual(runs[1].discovery);
    expect(runs[2].messages).toHaveLength(1);
  });

  it("removes context and ignores a late event after reset", async () => {
    const user = await openQuestion();
    await user.click(screen.getByRole("button", { name: "Remove when you are planning" }));
    await waitFor(() => expect(runs).toHaveLength(2));
    expect(runs[1].discovery).toEqual({ action: "remove", revision: 1, factKey: "timeframe" });
    await user.click(screen.getByRole("button", { name: "Reset fixture" }));
    act(() => complete(runs[1], discoveryFixture({ revision: 2 })));
    expect(screen.queryByRole("heading", { name: "What I understand" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls.some(([url, init]) => url === "/api/discovery" && init?.method === "DELETE")).toBe(true);
  });
});
