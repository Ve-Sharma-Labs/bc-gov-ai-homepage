import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantApp } from "@/components/assistant-app";
import { AssistantProvider } from "@/components/assistant-provider";
import { ComposerDock } from "@/components/composer-dock";
import { filterLocations, LocationFinder } from "@/components/locations";
import { catalogSchema, type Capabilities } from "@/lib/contract";
import { catalogFixture, guidedCapabilities } from "./fixtures";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }),
}));

function Pilot() {
  return <AssistantProvider><AssistantApp /><ComposerDock /></AssistantProvider>;
}

const mockApi = (capabilities: Capabilities = guidedCapabilities) => vi.fn(async (url: RequestInfo | URL) => {
  if (String(url).includes("/api/catalog")) return Response.json(catalogFixture);
  if (String(url).includes("/api/capabilities")) return Response.json(capabilities);
  if (String(url).includes("/api/locations")) return Response.json({ locations: catalogFixture.locations });
  return Response.json({ error: { code: "UNAVAILABLE", message: "Test unavailable" } }, { status: 503 });
});

describe("guided journeys", () => {
  beforeEach(() => vi.stubGlobal("fetch", mockApi()));

  it("rejects unresolved evidence and accepts the seven fixed journey IDs", () => {
    expect(catalogSchema.parse(catalogFixture).journeys).toHaveLength(7);
    const broken = structuredClone(catalogFixture);
    broken.journeys[0].steps[0].sourceIds = ["missing"];
    expect(catalogSchema.safeParse(broken).success).toBe(false);
    const invalidDate = structuredClone(catalogFixture);
    invalidDate.sources[0].checkedAt = "October 24, 2026";
    expect(catalogSchema.safeParse(invalidDate).success).toBe(false);
  });

  it("keeps the rejected question and real guided plans after one authoritative agent request", async () => {
    const user = userEvent.setup();
    render(<Pilot />);
    await screen.findByRole("button", { name: /Prepare a licence renewal/u });
    const input = screen.getByRole("textbox");
    await user.type(input, "I would like help with my licence");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/api/agent"))).toHaveLength(1));
    await waitFor(() => expect(input).toHaveValue("I would like help with my licence"));
    expect(screen.getByRole("button", { name: /Prepare a licence renewal/u })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "AI answer" })).not.toBeInTheDocument();
  });

  it("reports model readiness for the visible scope instead of implying a specialist enables general chat", async () => {
    vi.stubGlobal("fetch", mockApi({
      ...guidedCapabilities, mode: "foundry", aiConfigured: true, generalChatConfigured: false,
      journeys: { "licence-renewal": true },
    }));
    const user = userEvent.setup();
    render(<Pilot />);
    await screen.findByText(/AI answers not connected/);
    expect(screen.queryByText("AI answers configured")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Prepare a licence renewal/u }));
    expect(screen.getByText("AI answers configured")).toBeVisible();
  });

  it("renders catalogue steps, evidence, honest handoffs and local checklist state", async () => {
    const user = userEvent.setup();
    render(<Pilot />);
    await user.click(await screen.findByRole("button", { name: /Prepare a licence renewal/u }));
    expect(screen.getByText("Guided plan · Not AI-generated")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Prepare a licence renewal", level: 1 })).toBeVisible();
    const step = screen.getByRole("checkbox", { name: "Review the accepted identification guidance" });
    await user.click(step);
    expect(step).toBeChecked();
    expect(screen.getByText("1 of 2 steps reviewed")).toBeVisible();
    expect(screen.getByText(/Nothing has been booked, renewed or submitted here/u)).toBeVisible();
    expect(screen.getByRole("link", { name: /Open the official service/u })).toHaveAttribute("target", "_blank");
    await user.click(screen.getByText("Fixture licensing evidence"));
    expect(screen.getByText("Not provided")).toBeVisible();
    expect(screen.getByText(/limited dynamic content/u)).toBeVisible();
  });

  it("requires reset confirmation and clears drafts and checklist progress", async () => {
    const user = userEvent.setup();
    render(<Pilot />);
    await user.click(await screen.findByRole("button", { name: /Prepare a licence renewal/u }));
    await user.click(screen.getByRole("checkbox", { name: "Review the accepted identification guidance" }));
    await user.type(screen.getByRole("textbox"), "My unsent draft");
    await user.click(screen.getByRole("button", { name: "Start over" }));
    let dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Keep this conversation" }));
    expect(screen.getByRole("textbox")).toHaveValue("My unsent draft");
    await user.click(screen.getByRole("button", { name: "Start over" }));
    dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Start over" }));
    expect(screen.getByRole("textbox")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: /Prepare a licence renewal/u }));
    expect(screen.getByText("0 of 2 steps reviewed")).toBeVisible();
  });

  it("keeps the offline shell useful and does not fabricate catalogue steps", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Network down")));
    render(<Pilot />);
    expect(screen.getByRole("heading", { name: /Hello, British Columbia/u })).toBeVisible();
    await screen.findByText(/catalogue is temporarily unavailable/u);
    expect(screen.getByRole("link", { name: /All services/u })).toHaveAttribute("href", "/services");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});

describe("location capability filters", () => {
  it("lets exclusions override inclusions and never assumes unknown support", () => {
    expect(filterLocations(catalogFixture.locations, "icbc-licensing", "Test Town").map((location) => location.id)).toEqual(["fixture-office-b"]);
    expect(filterLocations(catalogFixture.locations, "income-assistance", "")).toEqual([]);
  });

  it("applies the filter to API results and labels the curated snapshot", async () => {
    vi.stubGlobal("fetch", mockApi());
    const user = userEvent.setup();
    render(<LocationFinder catalog={catalogFixture} />);
    await user.selectOptions(screen.getByLabelText("Service"), "icbc-licensing");
    await user.click(screen.getByRole("button", { name: "Find locations" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Fixture limited office" })).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Fixture licensing office" })).toBeVisible();
    expect(screen.getByText(/not a complete or live directory/u)).toBeVisible();
    expect(screen.getByText(/not photo-card issuance/u)).toBeVisible();
  });
});
