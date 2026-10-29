import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AssistantProvider } from "@/components/assistant-provider";
import { CitizenContextControl, SyntheticContextBanner } from "@/components/citizen-context";
import {
  catalogFixture,
  consentReceiptFixture,
  contextSummaryFixture,
  demoPersonasFixture,
  guidedCapabilities,
  syntheticCapabilities,
} from "./fixtures";

function contextUiApi(capabilities = syntheticCapabilities) {
  let scopes = consentReceiptFixture.scopes;
  const categoryByScope = {
    "identity.read": "identity-residency",
    "household.read": "household-dependants",
    "employment.read": "employment-income",
    "disability-caregiving.read": "disability-caregiving",
    "existing-programs.read": "existing-programs",
    "region-preferences.read": "region-preferences",
  } as const;
  return vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path === "/api/catalog") return Response.json(catalogFixture);
    if (path === "/api/capabilities") return Response.json(capabilities);
    if (path === "/api/demo/personas") return Response.json(demoPersonasFixture);
    if (path === "/api/demo/session" && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      return Response.json({
        persona: demoPersonasFixture.find((persona) => persona.id === body.personaId),
        expiresAt: "2099-10-28T20:30:00Z",
        synthetic: true,
      }, { status: 201 });
    }
    if (path === "/api/demo/session" && init?.method === "DELETE") return new Response(null, { status: 204 });
    if (path === "/api/context/consents") {
      const body = JSON.parse(String(init?.body));
      scopes = body.action === "grant"
        ? [...new Set([...scopes, ...body.scopes])]
        : scopes.filter((scope) => !body.scopes.includes(scope));
      return Response.json({ ...consentReceiptFixture, scopes });
    }
    if (path === "/api/context/summary") {
      const categories = scopes.map((scope) => categoryByScope[scope]);
      const facts = [
        ...contextSummaryFixture.facts,
        {
          key: "region.service-area",
          label: "Preferred service region",
          category: "region-preferences" as const,
          displayValue: "Interior service region",
          provenance: "synthetic-government-record" as const,
          verifiedAt: "2026-10-28T20:00:00Z",
          mutableByCitizen: true,
          usedBy: ["service-bc-assisted-navigation"],
        },
      ];
      return Response.json({
        ...contextSummaryFixture,
        categories,
        facts: facts.filter((fact) => categories.includes(fact.category)),
      });
    }
    throw new Error(`Unexpected context UI request: ${path}`);
  });
}

function ContextSurface() {
  return <AssistantProvider>
    <SyntheticContextBanner />
    <CitizenContextControl />
  </AssistantProvider>;
}

describe("public synthetic citizen context controls", () => {
  it("is hidden cleanly when the capability is unavailable", async () => {
    vi.stubGlobal("fetch", contextUiApi(guidedCapabilities));
    render(<ContextSurface />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/capabilities", expect.anything()));
    expect(screen.queryByRole("button", { name: /synthetic demo persona/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Synthetic demo - no real government records are accessed/)).not.toBeInTheDocument();
  });

  it("offers Anonymous, Maya, Alex and Sam and opens granular consent without profile fields", async () => {
    vi.stubGlobal("fetch", contextUiApi());
    render(<ContextSurface />);
    const trigger = await screen.findByRole("button", { name: "Choose a synthetic demo persona" });
    expect(trigger).toHaveTextContent("Anonymous");
    fireEvent.click(trigger);

    expect(screen.getByRole("dialog", { name: "Choose conversation context" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic demo - no real government records are accessed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Anonymous/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Maya synthetic/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Alex synthetic/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sam synthetic/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Sam synthetic/ }));
    expect(screen.getByRole("dialog", { name: "Choose what Sam may share" })).toBeInTheDocument();
    expect(screen.getByText(/All values are fictional/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Identity and B.C. residency/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Household and dependants/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Employment and income status/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Region and service preferences/ })).toBeChecked();
    expect(screen.queryByRole("button", { name: /^Submit$/i })).not.toBeInTheDocument();
  });

  it("uses the merged minimum presets for guardianship without preselecting identity", async () => {
    vi.stubGlobal("fetch", contextUiApi());
    render(<ContextSurface />);
    fireEvent.click(await screen.findByRole("button", { name: "Choose a synthetic demo persona" }));
    fireEvent.click(screen.getByRole("button", { name: /Maya synthetic/ }));
    expect(screen.queryByRole("checkbox", { name: /Identity and B.C. residency/ })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Household and dependants/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Disability or caregiving circumstances/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Existing programs and applications/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Region and service preferences/ })).toBeChecked();
  }, 15_000);

  it("matches the disability-support runtime scopes without preselecting household", async () => {
    vi.stubGlobal("fetch", contextUiApi());
    render(<ContextSurface />);
    fireEvent.click(await screen.findByRole("button", { name: "Choose a synthetic demo persona" }));
    fireEvent.click(screen.getByRole("button", { name: /Alex synthetic/ }));
    expect(screen.getByRole("checkbox", { name: /Identity and B.C. residency/ })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: /Household and dependants/ })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Employment and income status/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Disability or caregiving circumstances/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Existing programs and applications/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Region and service preferences/ })).toBeChecked();
  });

  it("shows persistent synthetic labeling, an accessible context drawer, provenance and revocation", async () => {
    vi.stubGlobal("fetch", contextUiApi());
    const user = userEvent.setup();
    render(<ContextSurface />);
    const trigger = await screen.findByRole("button", { name: "Choose a synthetic demo persona" });
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: /Alex synthetic/ }));
    await user.click(screen.getByRole("button", { name: "Use selected context" }));

    await screen.findByText("Synthetic citizen context");
    expect(screen.getAllByText("Synthetic demo - no real government records are accessed").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "What the assistant used" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "What the assistant used" }));

    const drawer = await screen.findByRole("dialog", { name: "What the assistant used" });
    expect(drawer).toHaveTextContent("Government record (synthetic)");
    expect(drawer).toHaveTextContent("Missing / needs confirmation");
    expect(drawer).toHaveTextContent("Current purpose");
    expect(drawer).toHaveTextContent("Required for this flow");
    expect(screen.queryByRole("button", { name: "Remove consent for Employment and income status" })).not.toBeInTheDocument();
    const removeRegion = screen.getByRole("button", { name: "Remove consent for Region and service preferences" });
    await user.click(removeRegion);
    await waitFor(() => expect(screen.queryByText("Interior service region")).not.toBeInTheDocument());

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "What the assistant used" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What the assistant used" })).toHaveFocus();
  });

  it("keeps mobile sheets bounded and reduced-motion behavior explicit in the shipped styles", () => {
    const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");
    expect(styles).toMatch(/@media \(max-width: 767px\)[\s\S]*\.context-consent-sheet, \.context-drawer \{ inset: auto 0 0;/u);
    expect(styles).toMatch(/max-height: 90dvh/u);
    expect(styles).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*transition-duration: 0s/u);
  });
});
