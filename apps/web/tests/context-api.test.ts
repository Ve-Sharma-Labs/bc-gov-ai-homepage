import { describe, expect, it, vi } from "vitest";
import {
  changeContextConsent,
  createDemoSession,
  deleteDemoSession,
  getContextSummary,
  getDemoPersonas,
} from "@/lib/api";
import {
  consentReceiptFixture,
  contextSummaryFixture,
  demoPersonasFixture,
} from "./fixtures";

describe("synthetic context API client", () => {
  it("loads only the fixed public persona summaries", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(demoPersonasFixture));
    vi.stubGlobal("fetch", fetcher);
    await expect(getDemoPersonas()).resolves.toEqual(demoPersonasFixture);
    expect(fetcher).toHaveBeenCalledWith("/api/demo/personas", expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    }));

    fetcher.mockResolvedValueOnce(Response.json([
      demoPersonasFixture[0],
      demoPersonasFixture[0],
      demoPersonasFixture[2],
    ]));
    await expect(getDemoPersonas()).rejects.toMatchObject({ code: "INVALID_CONTENT" });
  });

  it("sends an allowlisted persona ID and typed scopes without profile fields", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({
        persona: demoPersonasFixture[2],
        expiresAt: "2099-10-28T20:30:00Z",
        synthetic: true,
      }, { status: 201 }))
      .mockResolvedValueOnce(Response.json(consentReceiptFixture))
      .mockResolvedValueOnce(Response.json(contextSummaryFixture));
    vi.stubGlobal("fetch", fetcher);

    await createDemoSession("sam-job-loss");
    await changeContextConsent("grant", ["identity.read", "employment.read"]);
    await getContextSummary();

    const session = JSON.parse(String(fetcher.mock.calls[0][1].body));
    const consent = JSON.parse(String(fetcher.mock.calls[1][1].body));
    const pageHeaders = fetcher.mock.calls.slice(0, 3).map(([, init]) => (
      new Headers(init.headers).get("x-bc-context-page")
    ));
    expect(session).toEqual({ personaId: "sam-job-loss" });
    expect(JSON.stringify(session)).not.toMatch(/facts|profile|context|state/iu);
    expect(consent).toEqual({ action: "grant", scopes: ["identity.read", "employment.read"] });
    expect(JSON.stringify(consent)).not.toMatch(/facts|profile|value/iu);
    expect(fetcher.mock.calls[2][0]).toBe("/api/context/summary");
    expect(pageHeaders.every((value) => /^[A-Za-z0-9-]{20,128}$/u.test(value ?? ""))).toBe(true);
    expect(new Set(pageHeaders).size).toBe(1);
  });

  it("clears the server-owned session with a same-origin keepalive DELETE", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetcher);
    await deleteDemoSession({ keepalive: true });
    expect(fetcher).toHaveBeenCalledExactlyOnceWith("/api/demo/session", expect.objectContaining({
      method: "DELETE",
      headers: expect.objectContaining({
        "x-bc-context-page": expect.any(String),
      }),
      credentials: "same-origin",
      cache: "no-store",
      keepalive: true,
    }));
    expect(new Headers(fetcher.mock.calls[0][1].headers).get("x-bc-context-page")).toBeTruthy();
  });
});
