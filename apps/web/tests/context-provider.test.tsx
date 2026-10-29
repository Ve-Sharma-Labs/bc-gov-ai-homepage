import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantProvider, useAssistant } from "@/components/assistant-provider";
import type { ConsentScope, ContextCategory } from "@/lib/contract";
import {
  catalogFixture,
  consentReceiptFixture,
  contextSummaryFixture,
  demoPersonasFixture,
  guidedCapabilities,
  syntheticCapabilities,
} from "./fixtures";

type StartAgentRun = typeof import("@/lib/agent").startAgentRun;
type AgentRunOptions = Parameters<StartAgentRun>[0];

const { startAgentRunMock } = vi.hoisted(() => ({
  startAgentRunMock: vi.fn<StartAgentRun>(),
}));
vi.mock("@/lib/agent", () => ({ startAgentRun: startAgentRunMock }));

function scopeCategory(scope: ConsentScope): ContextCategory {
  const categories: Record<ConsentScope, ContextCategory> = {
    "identity.read": "identity-residency",
    "household.read": "household-dependants",
    "employment.read": "employment-income",
    "disability-caregiving.read": "disability-caregiving",
    "existing-programs.read": "existing-programs",
    "region-preferences.read": "region-preferences",
  };
  return categories[scope];
}

function contextApi(capabilities = syntheticCapabilities) {
  let scopes: ConsentScope[] = [];
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path === "/api/catalog") return Response.json(catalogFixture);
    if (path === "/api/capabilities") return Response.json(capabilities);
    if (path === "/api/demo/personas" && (!init?.method || init.method === "GET")) return Response.json(demoPersonasFixture);
    if (path === "/api/demo/session" && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      const persona = demoPersonasFixture.find((item) => item.id === body.personaId);
      return Response.json({ persona, expiresAt: "2099-10-28T20:30:00Z", synthetic: true }, { status: 201 });
    }
    if (path === "/api/demo/session" && init?.method === "DELETE") {
      scopes = [];
      return new Response(null, { status: 204 });
    }
    if (path === "/api/context/consents" && init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as { action: "grant" | "revoke"; scopes: ConsentScope[] };
      scopes = body.action === "grant"
        ? [...new Set([...scopes, ...body.scopes])]
        : scopes.filter((scope) => !body.scopes.includes(scope));
      return Response.json({
        ...consentReceiptFixture,
        scopes: scopes.length ? scopes : body.scopes,
        revokedAt: scopes.length ? null : "2026-10-28T20:10:00Z",
      });
    }
    if (path === "/api/context/summary") {
      const categories = scopes.map(scopeCategory);
      return Response.json({
        ...contextSummaryFixture,
        categories,
        facts: contextSummaryFixture.facts.filter((fact) => categories.includes(fact.category)),
        missingFacts: categories.includes("employment-income") ? contextSummaryFixture.missingFacts : [],
      });
    }
    throw new Error(`Unexpected context test request: ${path} ${init?.method ?? "GET"}`);
  });
  return fetcher;
}

function runHandle(options: AgentRunOptions) {
  let complete!: () => void;
  const done = new Promise<void>((resolve) => { complete = resolve; });
  return { options, done, cancel: vi.fn(complete), complete };
}

beforeEach(() => {
  startAgentRunMock.mockReset();
  startAgentRunMock.mockImplementation((options) => runHandle(options));
});

describe("assistant synthetic context state", () => {
  it("stays anonymous by default and does not request personas when the capability is disabled", async () => {
    const fetcher = contextApi(guidedCapabilities);
    vi.stubGlobal("fetch", fetcher);
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const { result } = renderHook(useAssistant, { wrapper: AssistantProvider });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.contextActive).toBe(false);
    expect(result.current.activePersona).toBeNull();
    expect(result.current.consent).toBeNull();
    expect(result.current.personas).toEqual([]);
    expect(fetcher.mock.calls.some(([url]) => String(url) === "/api/demo/personas")).toBe(false);
    expect(storage).not.toHaveBeenCalled();
  });

  it("loads the three fixed personas, creates consent, and enables only explicit contextual mode", async () => {
    const fetcher = contextApi();
    vi.stubGlobal("fetch", fetcher);
    const runs: ReturnType<typeof runHandle>[] = [];
    startAgentRunMock.mockImplementation((options) => {
      const run = runHandle(options);
      runs.push(run);
      return run;
    });
    const { result } = renderHook(useAssistant, { wrapper: AssistantProvider });
    await waitFor(() => expect(result.current.personas).toHaveLength(3));
    expect(result.current.personas.map((persona) => persona.displayName)).toEqual(["Maya", "Alex", "Sam"]);

    await act(async () => {
      expect(await result.current.activatePersona("sam-job-loss", [
        "identity.read",
        "employment.read",
        "existing-programs.read",
      ])).toBe(true);
    });
    expect(result.current.contextActive).toBe(true);
    expect(result.current.activePersona?.displayName).toBe("Sam");
    expect(result.current.contextSummary?.facts[0].provenance).toBe("synthetic-government-record");

    const sessionCall = fetcher.mock.calls.find(([url, init]) => String(url) === "/api/demo/session" && init?.method === "POST")!;
    expect(JSON.parse(String(sessionCall[1]?.body))).toEqual({ personaId: "sam-job-loss" });
    expect(String(sessionCall[1]?.body)).not.toMatch(/facts|profile|value/iu);

    await act(async () => {
      result.current.setDraft("What should I do after losing my job?");
      expect(await result.current.submit()).toBe(true);
    });
    expect(runs[0].options.mode).toBe("contextual-demo");
    expect(runs[0].options).not.toHaveProperty("journeyId");
    expect(runs[0].options.messages).toEqual([
      expect.objectContaining({ role: "user", content: "What should I do after losing my job?" }),
    ]);
    expect(JSON.stringify(runs[0].options)).not.toContain("Recently ended");
    expect(JSON.stringify(runs[0].options)).not.toContain("employment.status");
  });

  it("revokes a category immediately, clears contextual results, and calls the typed consent route", async () => {
    const fetcher = contextApi();
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(useAssistant, { wrapper: AssistantProvider });
    await waitFor(() => expect(result.current.personas).toHaveLength(3));
    await act(async () => {
      await result.current.activatePersona("sam-job-loss", ["identity.read", "employment.read"]);
    });
    expect(result.current.contextSummary?.facts.some((fact) => fact.category === "employment-income")).toBe(true);

    let update!: Promise<boolean>;
    act(() => {
      update = result.current.updateConsent(["identity.read"]);
    });
    expect(result.current.consent?.scopes).toEqual(["identity.read"]);
    expect(result.current.contextSummary?.facts.some((fact) => fact.category === "employment-income")).toBe(false);
    expect(result.current.state.messages.filter((message) => message.mode === "contextual-demo")).toEqual([]);
    await act(async () => { expect(await update).toBe(true); });

    const revoke = fetcher.mock.calls.find(([url, init]) => {
      if (String(url) !== "/api/context/consents" || init?.method !== "POST") return false;
      return JSON.parse(String(init.body)).action === "revoke";
    });
    expect(JSON.parse(String(revoke?.[1]?.body))).toEqual({
      action: "revoke",
      scopes: ["employment.read"],
    });
    expect(result.current.contextSummary?.categories).toEqual(["identity-residency"]);
  });

  it("uses DELETE for explicit clear, Start over, page reload and active-provider unmount", async () => {
    const fetcher = contextApi();
    vi.stubGlobal("fetch", fetcher);
    const mounted = renderHook(useAssistant, { wrapper: AssistantProvider });
    await waitFor(() => expect(mounted.result.current.personas).toHaveLength(3));
    await act(async () => {
      await mounted.result.current.activatePersona("sam-job-loss", ["employment.read"]);
      await mounted.result.current.clearContext();
    });
    expect(mounted.result.current.contextActive).toBe(false);

    await act(async () => {
      await mounted.result.current.activatePersona("sam-job-loss", ["employment.read"]);
      mounted.result.current.reset();
    });
    expect(mounted.result.current.contextActive).toBe(false);

    await act(async () => {
      await mounted.result.current.activatePersona("sam-job-loss", ["employment.read"]);
      window.dispatchEvent(new Event("pagehide"));
    });
    mounted.unmount();

    const deletes = fetcher.mock.calls.filter(([url, init]) => (
      String(url) === "/api/demo/session" && init?.method === "DELETE"
    ));
    expect(deletes.length).toBeGreaterThanOrEqual(3);
    expect(deletes.every(([, init]) => init?.keepalive === true)).toBe(true);
  });
});
