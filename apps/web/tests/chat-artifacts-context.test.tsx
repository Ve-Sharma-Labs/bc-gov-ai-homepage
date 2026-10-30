import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AssistantProvider } from "@/components/assistant-provider";
import { ChatArtifacts } from "@/components/chat-artifacts";
import {
  catalogFixture,
  contextArtifactsFixture,
  guidedCapabilities,
} from "./fixtures";

describe("synthetic context artifacts", () => {
  it("renders all five validated artifact families with provenance and no submission action", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url) === "/api/catalog") return Response.json(catalogFixture);
      if (String(url) === "/api/capabilities") return Response.json(guidedCapabilities);
      if (String(url) === "/api/demo/session" && init?.method === "DELETE") return new Response(null, { status: 204 });
      throw new Error(`Unexpected artifact test request: ${String(url)}`);
    }));
    const user = userEvent.setup();
    render(<AssistantProvider><ChatArtifacts artifacts={contextArtifactsFixture} /></AssistantProvider>);

    expect(screen.getByRole("region", { name: "Synthetic context summary" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Synthetic program screening" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Synthetic application or intake preview" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Synthetic consent checkpoint" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Synthetic audit receipt" })).toBeInTheDocument();
    expect(screen.getAllByText("Synthetic demo - no real government records are accessed")).toHaveLength(5);

    expect(screen.getByText("Potential match")).toBeInTheDocument();
    expect(screen.getByText("This is a screening indicator, not an eligibility decision.")).toBeInTheDocument();
    expect(screen.getAllByText("Government record (synthetic)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Missing / needs confirmation").length).toBeGreaterThan(0);
    expect(screen.getByText(/Nothing can be submitted from this preview/)).toBeInTheDocument();
    expect(screen.getByText(/Transfer in this demo/)).toBeInTheDocument();
    expect(screen.getByText("None")).toBeInTheDocument();
    expect(screen.getByText("Screening rule evaluated")).toBeInTheDocument();
    expect(screen.getByText(/contains no raw context values/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Submit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Submit$/i })).not.toBeInTheDocument();

    const continueDisabled = screen.getByText("Continue to official service");
    expect(continueDisabled).toHaveAttribute("aria-disabled", "true");
    await user.click(screen.getByRole("checkbox", { name: /I reviewed what would be shared/ }));
    expect(screen.getByRole("link", { name: /Continue to official service/ })).toHaveAttribute("href", "https://www.workbc.ca/");
  });
});
