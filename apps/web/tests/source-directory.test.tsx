import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SourceDirectory } from "@/components/source-directory";
import { catalogFixture } from "./fixtures";

describe("the complete source registry", () => {
  it("includes blocked and pending sources rather than pretending they are covered", async () => {
    const catalog = structuredClone(catalogFixture);
    catalog.sources.push({ ...catalog.sources[0], id: "blocked-test", title: "Fixture restricted source", status: "blocked" });
    catalog.sources.push({ ...catalog.sources[0], id: "pending-test", title: "Fixture pending source", status: "pending" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(catalog)));
    const user = userEvent.setup();
    render(<SourceDirectory />);
    await screen.findByText("4 sources in this curated catalogue");
    expect(screen.getByText("Fixture restricted source")).toBeVisible();
    expect(screen.getByText("Fixture pending source")).toBeVisible();
    await user.selectOptions(screen.getByLabelText("Source status"), "blocked");
    expect(screen.getByText("1 source shown")).toBeVisible();
    expect(screen.queryByText("Fixture licensing evidence")).not.toBeInTheDocument();
  });

  it("reports unavailability without supplying substitute source data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Offline")));
    render(<SourceDirectory />);
    await screen.findByText(/source catalogue is unavailable/u);
    expect(screen.queryByText("ICBC")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});
