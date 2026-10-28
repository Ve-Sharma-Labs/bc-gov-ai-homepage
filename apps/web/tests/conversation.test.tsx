import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BaseEvent } from "@ag-ui/core";
import { describe, expect, it, vi } from "vitest";
import { Conversation } from "@/components/conversation";
import type { ResponseContext } from "@/lib/contract";
import { initialStreamState, streamReducer, type StreamState } from "@/lib/stream";
import { catalogFixture } from "./fixtures";

const { markdownRender } = vi.hoisted(() => ({ markdownRender: vi.fn() }));
vi.mock("react-markdown", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-markdown")>();
  const Markdown = actual.default;
  return {
    ...actual,
    default: (props: Parameters<typeof Markdown>[0]) => {
      markdownRender(props.children);
      return <Markdown {...props} />;
    },
  };
});

const event = (state: StreamState, value: object) => streamReducer(state, {
  type: "event", runId: state.runId!, event: value as BaseEvent,
});
const start = () => streamReducer(initialStreamState, { type: "start", runId: "run-1", messageId: "user-1", prompt: "My B.C. question" });
function response(context?: ResponseContext) {
  let state = start();
  if (context) state = event(state, { type: "CUSTOM", name: "bc.response", value: context });
  state = event(state, { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" });
  return event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "TEST FIXTURE response text." });
}
const finish = (state: StreamState) => event(state, { type: "RUN_FINISHED" });

describe("conversation rendering", () => {
  it("shows one truthful activity indicator until actual text arrives, without a second empty answer", () => {
    let state = event(start(), { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" });
    const { container, rerender } = render(<Conversation state={state} catalog={null} />);
    expect(container.querySelectorAll(".run-progress")).toHaveLength(1);
    expect(screen.getByText("Sending your question…")).toBeInTheDocument();
    expect(screen.queryByText(/Waiting for answer text/)).not.toBeInTheDocument();
    expect(screen.queryByText("In progress")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "AI answer" })).not.toBeInTheDocument();
    state = event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "Real streamed content" });
    rerender(<Conversation state={state} catalog={null} />);
    expect(screen.getByText("Real streamed content")).toBeInTheDocument();
    expect(container.querySelector(".run-progress")).toBeNull();
    expect(screen.queryByText(/Source details were not returned/)).not.toBeInTheDocument();
    state = event(state, { type: "CUSTOM", name: "status", value: { version: 1, phase: "validating" } });
    rerender(<Conversation state={state} catalog={null} />);
    expect(container.querySelectorAll(".run-progress")).toHaveLength(1);
    expect(screen.getByText("Checking the answer against its sources...")).toBeInTheDocument();
  });

  it.each([
    { kind: "dialogue", origin: "application", warning: false, heading: "BC service assistant" },
    { kind: "dialogue", origin: "model", warning: false, heading: "AI assistant" },
    { kind: "grounded", origin: "model", warning: true, heading: "AI answer" },
    { kind: "handoff", origin: "application", warning: false, heading: "BC service assistant" },
    { kind: "handoff", origin: "model", warning: true, heading: "AI answer" },
  ] as const)("labels $origin $kind honestly and applies its source-warning policy", ({ kind, origin, warning, heading }) => {
    render(<Conversation state={finish(response({ version: 1, kind, origin }))} catalog={null} />);
    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    expect(!!screen.queryByText(/Source details were not returned/)).toBe(warning);
    if (origin === "application") expect(screen.queryByRole("heading", { name: /AI/ })).not.toBeInTheDocument();
  });

  it("retains missing-source warnings for legacy text and rejected source destinations", () => {
    let state = response();
    state = event(state, { type: "CUSTOM", name: "annotations", value: {
      messageId: "answer-1", annotations: [{ url: "https://www2.gov.bc.ca.evil.test/claim", title: "Untrusted" }],
    } });
    render(<Conversation state={finish(state)} catalog={catalogFixture} />);
    expect(screen.getByText(/Source details were not returned/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /source$/ })).not.toBeInTheDocument();
  });

  it("does not reparse unchanged Markdown on progress, new turns, completion or late sources", async () => {
    let state = finish(response());
    const { rerender } = render(<Conversation state={state} catalog={catalogFixture} />);
    expect(markdownRender).toHaveBeenCalledTimes(1);
    state = streamReducer(state, { type: "start", runId: "run-2", messageId: "user-2", prompt: "A follow-up" });
    rerender(<Conversation state={state} catalog={catalogFixture} />);
    state = event(state, { type: "TEXT_MESSAGE_START", messageId: "answer-2", role: "assistant" });
    rerender(<Conversation state={state} catalog={catalogFixture} />);
    expect(markdownRender).toHaveBeenCalledTimes(1);
    state = event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-2", delta: "A second streamed response." });
    rerender(<Conversation state={state} catalog={catalogFixture} />);
    expect(markdownRender).toHaveBeenCalledTimes(2);
    state = event(state, { type: "CUSTOM", name: "status", value: { phase: "validating" } });
    rerender(<Conversation state={state} catalog={catalogFixture} />);
    state = finish(state);
    rerender(<Conversation state={state} catalog={catalogFixture} />);
    state = event(state, { type: "CUSTOM", name: "annotations", value: {
      messageId: "answer-2", annotations: [{
        sourceId: "fixture-icbc", url: "https://www.icbc.com/driver-licensing/visit-a-dl-office",
        title: "Specific official office guidance", checkedAt: "2026-10-24",
      }],
    } });
    rerender(<Conversation state={state} catalog={catalogFixture} />);
    expect(markdownRender).toHaveBeenCalledTimes(2);
    await userEvent.setup().click(screen.getByRole("button", { name: "1 source" }));
    expect(screen.getByRole("dialog", { name: "Sources for this answer" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open icbc.com/ })).toHaveAttribute("href", "https://www.icbc.com/driver-licensing/visit-a-dl-office");
    expect(markdownRender).toHaveBeenCalledTimes(2);
  });

  it("keeps an existing official link mounted and focused when the next genuine text chunk arrives", () => {
    let state = event(start(), { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" });
    state = event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "[Official guidance](https://www.icbc.com/driver-licensing)" });
    const { rerender } = render(<Conversation state={state} catalog={null} />);
    const link = screen.getByRole("link", { name: /Official guidance/ });
    link.focus();
    state = event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "\n\nThe next part of the answer." });
    rerender(<Conversation state={state} catalog={null} />);
    expect(screen.getByRole("link", { name: /Official guidance/ })).toBe(link);
    expect(link).toHaveFocus();
    expect(screen.getByText("The next part of the answer.")).toBeInTheDocument();
  });
});
