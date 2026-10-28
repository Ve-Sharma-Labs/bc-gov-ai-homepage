import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BaseEvent } from "@ag-ui/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantProvider } from "@/components/assistant-provider";
import { ChatExperience } from "@/components/chat-experience";
import { ComposerDock } from "@/components/composer-dock";
import { catalogFixture, guidedCapabilities } from "./fixtures";

type AgentOptions = Parameters<typeof import("@/lib/agent").startAgentRun>[0];
const { navigation, startAgentRun } = vi.hoisted(() => ({
  navigation: { pathname: "/", push: vi.fn(), prefetch: vi.fn() },
  startAgentRun: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => navigation,
}));
vi.mock("@/lib/agent", () => ({ startAgentRun }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}
function testRun(options: AgentOptions) {
  const completion = deferred<void>();
  return {
    options,
    done: completion.promise,
    cancel: vi.fn(() => completion.resolve(undefined)),
    finish: () => completion.resolve(undefined),
    emit: (event: object) => options.onEvent(event as BaseEvent),
  };
}
let runs: ReturnType<typeof testRun>[];
const shell = () => render(<AssistantProvider><div data-composer-anchor /><ChatExperience /><ComposerDock /></AssistantProvider>);

beforeEach(() => {
  navigation.pathname = "/";
  navigation.prefetch.mockReset();
  navigation.push.mockImplementation((path: string) => { navigation.pathname = path; });
  runs = [];
  startAgentRun.mockReset().mockImplementation((options: AgentOptions) => {
    const run = testRun(options);
    runs.push(run);
    return run;
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => Response.json(url === "/api/catalog" ? catalogFixture : guidedCapabilities)));
});

describe("single composer and optional scope", () => {
  it("prefetches the conversation route without submitting a question", async () => {
    shell();
    await waitFor(() => expect(navigation.prefetch).toHaveBeenCalledExactlyOnceWith("/chat"));
    expect(navigation.push).not.toHaveBeenCalled();
    expect(startAgentRun).not.toHaveBeenCalled();
  });

  it("keeps the same composer above the mobile visual viewport when the keyboard opens and closes", async () => {
    navigation.pathname = "/chat";
    const viewport = Object.assign(new EventTarget(), { height: 500, offsetTop: 0 });
    vi.stubGlobal("visualViewport", viewport);
    vi.stubGlobal("innerHeight", 844);
    const { container } = shell();
    const input = screen.getByRole("textbox");
    const dock = container.querySelector(".composer-float");
    await waitFor(() => expect(dock).toHaveStyle({ bottom: "364px" }));
    act(() => {
      viewport.height = 844;
      viewport.dispatchEvent(new Event("resize"));
    });
    await waitFor(() => expect(dock).toHaveStyle({ bottom: "20px" }));
    expect(screen.getByRole("textbox")).toBe(input);
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(startAgentRun).not.toHaveBeenCalled();
    expect(navigation.prefetch).not.toHaveBeenCalled();
  });

  it("echoes, navigates and dispatches once while capability discovery remains pending", async () => {
    const connection = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/catalog" ? Response.json(catalogFixture) : connection.promise));
    const user = userEvent.setup();
    shell();
    await user.type(screen.getByRole("textbox"), "What does the B.C. government do?");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    expect(navigation.push).toHaveBeenCalledExactlyOnceWith("/chat");
    expect(screen.getByText("What does the B.C. government do?")).toBeInTheDocument();
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.getByRole("textbox")).toHaveValue("");
    await waitFor(() => expect(startAgentRun).toHaveBeenCalledOnce());
    expect(runs[0].options.mode).toBe("general");
    expect(runs[0].options).not.toHaveProperty("journeyId");
    expect(screen.getByRole("button", { name: "Stop answer" })).toBeInTheDocument();
    await act(async () => { connection.resolve(Response.json(guidedCapabilities)); });
    expect(startAgentRun).toHaveBeenCalledOnce();
    expect(runs[0].cancel).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each(catalogFixture.journeys)("selects $id explicitly without submitting or replacing the draft", async (journey) => {
    const user = userEvent.setup();
    shell();
    await user.type(screen.getByRole("textbox"), "Keep my unsent draft");
    await user.click(screen.getByRole("button", { name: "Choose a guided pathway" }));
    await user.click(await screen.findByRole("button", { name: journey.title }));
    expect(screen.getByRole("textbox")).toHaveValue("Keep my unsent draft");
    expect(screen.getByRole("button", { name: "Change pathway" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear pathway and use general B.C. chat" })).toBeInTheDocument();
    expect(startAgentRun).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Send question" }));
    expect(runs[0].options).toMatchObject({ mode: "pathway", journeyId: journey.id });
    expect(screen.getByRole("button", { name: "Change pathway" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clear pathway and use general B.C. chat" })).toBeDisabled();
  });

  it("changes and clears a pathway in place, preserving the draft and returning keyboard focus", async () => {
    const user = userEvent.setup();
    shell();
    await user.type(screen.getByRole("textbox"), "Do not replace this draft");
    await user.click(screen.getByRole("button", { name: "Choose a guided pathway" }));
    await user.click(await screen.findByRole("button", { name: catalogFixture.journeys[0].title }));
    await user.click(screen.getByRole("button", { name: "Change pathway" }));
    await user.click(screen.getByRole("button", { name: catalogFixture.journeys[1].title }));
    expect(screen.getByRole("textbox")).toHaveValue("Do not replace this draft");
    await user.click(screen.getByRole("button", { name: "Clear pathway and use general B.C. chat" }));
    expect(screen.getByText("General B.C. chat")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Do not replace this draft");
    expect(screen.getByRole("button", { name: "Choose a guided pathway" })).toHaveFocus();
    expect(startAgentRun).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Send question" }));
    expect(runs[0].options.mode).toBe("general");
    expect(runs[0].options).not.toHaveProperty("journeyId");
  });

  it("closes optional pathway choices on Escape without changing the scope or draft", async () => {
    const user = userEvent.setup();
    shell();
    await user.type(screen.getByRole("textbox"), "An unsent draft");
    const choose = screen.getByRole("button", { name: "Choose a guided pathway" });
    await user.click(choose);
    await screen.findByRole("heading", { name: "Choose a pathway" });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("heading", { name: "Choose a pathway" })).not.toBeInTheDocument();
    expect(choose).toHaveFocus();
    expect(screen.getByRole("textbox")).toHaveValue("An unsent draft");
    expect(startAgentRun).not.toHaveBeenCalled();
  });

  it("keeps one explicit retry available even when capabilities say AI is disconnected", async () => {
    const user = userEvent.setup();
    shell();
    await user.type(screen.getByRole("textbox"), "Keep this question");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    act(() => { runs[0].options.onFailure("General B.C. chat is not connected.", "GENERAL_AGENT_NOT_CONFIGURED"); });
    expect(screen.getByRole("textbox")).toHaveValue("Keep this question");
    expect(screen.getByRole("alert")).toHaveTextContent("General B.C. chat is not connected.");
    expect(screen.queryByRole("button", { name: "Retry connection" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(startAgentRun).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText("Keep this question")).toHaveLength(1);
    expect(runs[1].options.mode).toBe("general");
    expect(runs[1].options).not.toHaveProperty("journeyId");
  });

  it("hides immediate retry at the daily allowance and keeps guided fallbacks", async () => {
    const user = userEvent.setup();
    shell();
    await user.type(screen.getByRole("textbox"), "Keep this grounded question");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    act(() => {
      runs[0].options.onFailure(
        "The pilot has reached its daily processing allowance. Guided plans remain available.",
        "BUDGET_EXHAUSTED",
        "2026-10-28T00:00:00.000Z",
      );
    });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("daily processing allowance");
    expect(alert).toHaveTextContent("Model answers will be available again after");
    expect(screen.getByRole("textbox")).toHaveValue("Keep this grounded question");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Use a guided plan" })).toHaveAttribute("href", "/#journeys");
    expect(screen.getByRole("link", { name: "Browse official services" })).toHaveAttribute("href", "/services");
  });

  it("stops once without resubmitting and ignores late response metadata or text", async () => {
    const user = userEvent.setup();
    shell();
    await user.type(screen.getByRole("textbox"), "Stop this question");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    await user.click(screen.getByRole("button", { name: "Stop answer" }));
    expect(runs[0].cancel).toHaveBeenCalledOnce();
    expect(startAgentRun).toHaveBeenCalledOnce();
    expect(screen.getByRole("textbox")).toHaveValue("Stop this question");
    act(() => {
      runs[0].emit({ type: "CUSTOM", name: "bc.response", value: { version: 1, kind: "dialogue", origin: "application" } });
      runs[0].emit({ type: "TEXT_MESSAGE_START", messageId: "late", role: "assistant" });
      runs[0].emit({ type: "TEXT_MESSAGE_CONTENT", messageId: "late", delta: "Late text must not appear" });
      runs[0].emit({ type: "RUN_FINISHED", runId: runs[0].options.runId, threadId: runs[0].options.threadId });
    });
    expect(screen.queryByText("Late text must not appear")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Response stopped");
    expect(startAgentRun).toHaveBeenCalledOnce();
  });

  it.each(["GREETING", "JOURNEY_REQUIRED"])("renders legacy %s as dialogue, not a connection failure or a required service gate", async (code) => {
    const user = userEvent.setup();
    shell();
    await user.type(screen.getByRole("textbox"), "Hello");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    await act(async () => {
      runs[0].emit({ type: "RUN_ERROR", code, message: "Ignore raw provider detail" });
      runs[0].finish();
      await runs[0].done;
    });
    expect(screen.getByRole("heading", { name: "BC service assistant" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/Source details were not returned/)).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Choose a service" })).not.toBeInTheDocument();
    expect(screen.getByText("General B.C. chat")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox"), "Tell me about public parks");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    expect(runs[1].options.mode).toBe("general");
  });

  it.each(["dialogue", "handoff"])("renders a server-authored %s normally even without a model binding", async (kind) => {
    const user = userEvent.setup();
    shell();
    await user.type(screen.getByRole("textbox"), "Help with B.C. services");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    act(() => {
      runs[0].emit({ type: "RUN_STARTED", runId: runs[0].options.runId, threadId: runs[0].options.threadId });
      runs[0].emit({ type: "CUSTOM", name: "bc.response", value: { version: 1, kind, origin: "application" } });
      runs[0].emit({ type: "TEXT_MESSAGE_START", messageId: "app-reply", role: "assistant" });
      runs[0].emit({ type: "TEXT_MESSAGE_CONTENT", messageId: "app-reply", delta: kind === "dialogue"
        ? "Hello! How can I help with B.C. services?"
        : "You can check the [official guidance](https://www2.gov.bc.ca/gov/content/home)." });
      runs[0].emit({ type: "RUN_FINISHED", runId: runs[0].options.runId, threadId: runs[0].options.threadId });
    });
    expect(screen.getByRole("heading", { name: "BC service assistant" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "AI answer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/Source details were not returned/)).not.toBeInTheDocument();
    if (kind === "handoff") expect(screen.getByRole("link", { name: /official guidance/ })).toHaveAttribute("href", "https://www2.gov.bc.ca/gov/content/home");
  });
});
