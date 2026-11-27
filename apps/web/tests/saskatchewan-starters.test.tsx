import { useRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantProvider, useAssistant } from "@/components/assistant-provider";
import { ChatExperience } from "@/components/chat-experience";
import { Composer } from "@/components/composer";
import { HeroExperience } from "@/components/hero-experience";
import { conversationStarters } from "@/components/conversation-starters";
import { catalogFixture, guidedCapabilities } from "./fixtures";

vi.mock("@/generated/jurisdiction.json", async () => ({
  default: (await import("../../../jurisdictions/sk/jurisdiction.json")).default,
}));
vi.mock("@/lib/hero-images", () => ({
  heroImages: [{
    id: "fixture", src: "/fixture.webp", mobileSrc: "/fixture.webp",
    width: 800, height: 600, alt: "Test landscape", place: "Saskatchewan", position: "center",
  }],
}));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a>,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }) }));

type RunOptions = Parameters<typeof import("@/lib/agent").startAgentRun>[0];
const { startRun } = vi.hoisted(() => ({ startRun: vi.fn() }));
vi.mock("@/lib/agent", () => ({ startAgentRun: startRun }));

function Harness({ surface }: { surface: "home" | "chat" }) {
  const assistant = useAssistant();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  return <>
    {surface === "home" ? <HeroExperience /> : <ChatExperience />}
    <Composer inputRef={inputRef} value={assistant.draft} onChange={assistant.setDraft}
      busy={assistant.busy || assistant.loading} onSubmit={() => { void assistant.submit(); }}
      onStop={assistant.stop} />
  </>;
}

beforeEach(() => {
  startRun.mockReset().mockReturnValue({ done: new Promise<void>(() => {}), cancel: vi.fn() });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/catalog") return Response.json({ ...catalogFixture, jurisdiction: "sk" });
    if (url === "/api/capabilities") return Response.json({
      ...guidedCapabilities, jurisdiction: "sk", mode: "foundry", aiConfigured: true,
      generalChatConfigured: true, requestVersions: [2],
    });
    throw new Error("Unexpected fixture request");
  }));
});

describe("Saskatchewan example questions", () => {
  it.each(["home", "chat"] as const)("prefills an editable question on %s without sending", async (surface) => {
    render(<AssistantProvider><Harness surface={surface} /></AssistantProvider>);
    const user = userEvent.setup();
    const composer = screen.getByRole("textbox", { name: "What would you like help with?" });
    await waitFor(() => expect(composer).toBeEnabled());
    if (surface === "home") expect(screen.getByRole("heading", { name: "Ask the assistant" })).toBeVisible();
    for (const prompt of conversationStarters) expect(screen.getByRole("button", { name: prompt })).toBeVisible();

    await user.click(screen.getByRole("button", { name: conversationStarters[0] }));
    expect(composer).toHaveValue(conversationStarters[0]);
    expect(composer).toHaveFocus();
    expect(startRun).not.toHaveBeenCalled();
    await user.type(composer, " Please help.");
    await user.click(screen.getByRole("button", { name: "Send question" }));
    await waitFor(() => expect(startRun).toHaveBeenCalledOnce());
    expect((startRun.mock.calls[0][0] as RunOptions).messages.at(-1)?.content)
      .toBe(`${conversationStarters[0]} Please help.`);
  });

  it("asks before replacing an unsent question", async () => {
    render(<AssistantProvider><Harness surface="chat" /></AssistantProvider>);
    const user = userEvent.setup();
    const composer = screen.getByRole("textbox");
    await waitFor(() => expect(composer).toBeEnabled());
    await user.type(composer, "An unfinished question");
    await user.click(screen.getByRole("button", { name: conversationStarters[0] }));
    await user.click(screen.getByRole("button", { name: "Keep my draft" }));
    expect(composer).toHaveValue("An unfinished question");
    await user.click(screen.getByRole("button", { name: conversationStarters[1] }));
    await user.click(screen.getByRole("button", { name: "Replace draft" }));
    expect(composer).toHaveValue(conversationStarters[1]);
    expect(composer).toHaveFocus();
    expect(startRun).not.toHaveBeenCalled();
  });
});
