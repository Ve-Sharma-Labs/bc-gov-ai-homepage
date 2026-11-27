import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { BaseEvent } from "@ag-ui/core";
import sk from "../../../jurisdictions/sk/jurisdiction.json";
import bc from "../../../jurisdictions/bc/jurisdiction.json";
import { catalogFixture, guidedCapabilities } from "./fixtures";
import { assertRuntimeJurisdiction, loadPresentation, publicProjection } from "../scripts/prepare-jurisdiction.mjs";

vi.mock("next/link", () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));

async function selectPack(pack: typeof sk | typeof bc) {
  vi.resetModules();
  vi.doMock("@/generated/jurisdiction.json", () => ({ default: pack }));
}

afterEach(() => {
  vi.doUnmock("@/generated/jurisdiction.json");
  vi.doUnmock("@/components/assistant-provider");
  vi.doUnmock("@/components/hero-experience");
  vi.doUnmock("next/navigation");
  vi.doUnmock("next/og");
  vi.doUnmock("node:fs/promises");
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("selected jurisdiction presentation", () => {
  it("preserves the selected pack's examples outside Saskatchewan", async () => {
    for (const pack of [bc, { ...bc, id: "other", presentation: { ...bc.presentation, starters: ["Another government's question"] } }]) {
      await selectPack(pack);
      const { conversationStarters } = await import("@/components/conversation-starters");
      expect(conversationStarters).toEqual(pack.presentation.starters);
    }
  });

  it("keeps the Saskatchewan disclosure in metadata and social previews without a banner", async () => {
    await selectPack(sk);
    const { siteDescription, siteMetadata } = await import("@/app/site-metadata");
    const { SocialCard } = await import("@/app/social-card");
    expect(siteDescription).toBe(sk.presentation.aboutLead);
    expect(siteMetadata.openGraph).toMatchObject({ title: "AI at Government of Saskatchewan" });
    expect(siteMetadata.twitter).toMatchObject({ title: "AI at Government of Saskatchewan" });
    render(<SocialCard logo="data:image/png;base64,c2Fzaw==" />);
    expect(screen.getByText("AI at Government of Saskatchewan")).toBeVisible();
    expect(screen.getByRole("img", { name: sk.name })).toHaveAttribute("src", "data:image/png;base64,c2Fzaw==");
    expect(screen.getByText(sk.presentation.aboutLead)).toBeVisible();
  });

  it("renders the Saskatchewan social card with the bundled logo, without fetching it", async () => {
    await selectPack(sk);
    const readFile = vi.fn().mockResolvedValue(Buffer.from("sask-logo"));
    const imageResponse = vi.fn(function ImageResponse() {});
    vi.doMock("node:fs/promises", () => ({ readFile }));
    vi.doMock("next/og", () => ({ ImageResponse: imageResponse }));
    vi.stubGlobal("fetch", vi.fn());

    const { renderSocialImage } = await import("@/app/social-card");
    await renderSocialImage();

    expect(readFile).toHaveBeenCalledWith(expect.stringMatching(/public[\\/]brand[\\/]sk-wordmark\.png$/u));
    expect(imageResponse).toHaveBeenCalledOnce();
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });
  it("emits an explicit public projection without synthetic private records or content paths", () => {
    const privateMarker = "private-review-marker-must-not-ship";
    const serialized = JSON.stringify(publicProjection({
      ...sk,
      privateDeployment: { token: privateMarker },
      sourcePolicy: { ...sk.sourcePolicy, reviewRecords: [{ reviewer: privateMarker }] },
      researchPolicy: { grants: [{ evidence: privateMarker }] },
      brand: { ...sk.brand, privateApprovalContact: privateMarker },
      helpChannel: { ...sk.helpChannel, privateContact: privateMarker },
      presentation: { ...sk.presentation, privateReviewRecord: privateMarker },
    }));
    expect(serialized).not.toContain(privateMarker);
    const output = JSON.parse(serialized);
    expect(output).not.toHaveProperty("content");
    expect(output).not.toHaveProperty("sourcePolicy");
    expect(output).not.toHaveProperty("researchHosts");
    expect(output).not.toHaveProperty("researchPolicy");
    expect(output.presentation).not.toHaveProperty("privateReviewRecord");
    expect(output).toMatchObject({ id: "sk", officialDomains: ["saskatchewan.ca", "sgi.sk.ca", "ehealthsask.ca"] });
  });

  it("rejects unknown packs and a production runtime identity change", () => {
    expect(loadPresentation("bc").id).toBe("bc");
    expect(() => loadPresentation("../sk")).toThrow("Invalid JURISDICTION");
    expect(() => loadPresentation("unknown")).toThrow();
    expect(() => assertRuntimeJurisdiction("sk", "bc")).toThrow(/Rebuild/u);
    expect(() => assertRuntimeJurisdiction("sk", "sk")).not.toThrow();
  });

  it("keeps legacy BC API fixtures working but rejects an explicit government mismatch", async () => {
    await selectPack(bc);
    const { getCatalog } = await import("@/lib/api");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(catalogFixture))));
    expect((await getCatalog()).journeys).toHaveLength(7);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...catalogFixture, jurisdiction: "sk" }))));
    await expect(getCatalog()).rejects.toMatchObject({ code: "JURISDICTION_MISMATCH" });
  });

  it.each([undefined, "bc"])("rejects missing or wrong SK API identity (%s) without a BC fallback", async (remoteId) => {
    await selectPack(sk);
    const { getCatalog, getCapabilities } = await import("@/lib/api");
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify({
      ...(url.includes("capabilities") ? guidedCapabilities : catalogFixture),
      ...(remoteId ? { jurisdiction: remoteId } : {}),
    })))));
    await expect(getCatalog()).rejects.toMatchObject({ code: "JURISDICTION_MISMATCH" });
    await expect(getCapabilities()).rejects.toMatchObject({ code: "JURISDICTION_MISMATCH" });
  });

  it("honours SK feature flags even when an API claims unsupported context or journeys", async () => {
    await selectPack(sk);
    const { getCatalog, getCapabilities } = await import("@/lib/api");
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify({
      ...(url.includes("capabilities") ? {
        ...guidedCapabilities, syntheticContextAvailable: true, requestVersions: [1, 3, 4],
        discoveryAvailable: true, journeys: { "licence-renewal": true },
      } : catalogFixture),
      jurisdiction: "sk",
    })))));
    expect(await getCatalog()).toMatchObject({ journeys: [], locations: [] });
    expect(await getCapabilities()).toMatchObject({ syntheticContextAvailable: false, discoveryAvailable: false, journeys: {} });
  });

  it("accepts a verified SK response header but rejects a conflicting exposed identity", async () => {
    await selectPack(sk);
    const { getCapabilities } = await import("@/lib/api");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(guidedCapabilities), {
      headers: { "x-jurisdiction": "sk" },
    })));
    expect(await getCapabilities()).toMatchObject({ aiConfigured: false });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...guidedCapabilities, jurisdiction: "sk" }), {
      headers: { "x-jurisdiction": "bc" },
    })));
    await expect(getCapabilities()).rejects.toMatchObject({ code: "JURISDICTION_MISMATCH" });
  });

  it.each([undefined, "bc"])("cancels an unverified SK SSE body (%s) before forwarding any answer", async (upstreamId) => {
    await selectPack(sk);
    const { proxyRequest } = await import("@/lib/proxy");
    const cancel = vi.fn();
    const body = new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode("data: must not be forwarded\n\n")); },
      cancel,
    });
    const fetcher = vi.fn().mockResolvedValue(new Response(body, { headers: {
      "content-type": "text/event-stream",
      ...(upstreamId ? { "x-jurisdiction": upstreamId } : {}),
    } }));
    vi.stubGlobal("fetch", fetcher);
    const response = await proxyRequest(new Request("http://localhost:3000/api/agent", {
      method: "POST", body: "{}", headers: { "X-Expected-Jurisdiction": "bc" },
    }));
    expect(response.status).toBe(502);
    expect((await response.json()).error.code).toBe("JURISDICTION_MISMATCH");
    expect(cancel).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledOnce();
    expect(new Headers(fetcher.mock.calls[0][1].headers).get("x-expected-jurisdiction")).toBe("sk");
    expect(fetcher.mock.calls[0][0].pathname).toBe("/api/agent");
  });

  it.each([
    ["GET", "/api/conversation"],
    ["POST", "/api/conversation/control"],
    ["DELETE", "/api/conversation"],
  ])("checks jurisdiction on %s %s without a capabilities lookup", async (method, path) => {
    await selectPack(sk);
    const { proxyRequest } = await import("@/lib/proxy");
    const cancel = vi.fn();
    const body = new ReadableStream({ cancel });
    const fetcher = vi.fn().mockResolvedValue(new Response(body, {
      status: 409, headers: { "x-jurisdiction": "bc" },
    }));
    vi.stubGlobal("fetch", fetcher);
    const response = await proxyRequest(new Request(`http://localhost:3000${path}`, {
      method, ...(method === "POST" ? { body: "{}" } : {}),
    }));
    expect(response.status).toBe(502);
    expect((await response.json()).error.code).toBe("JURISDICTION_MISMATCH");
    expect(cancel).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledOnce();
    expect(new Headers(fetcher.mock.calls[0][1].headers).get("x-expected-jurisdiction")).toBe("sk");
  });

  it("forwards a verified SK stream and never trusts a browser expectation header", async () => {
    await selectPack(sk);
    const { proxyRequest } = await import("@/lib/proxy");
    const fetcher = vi.fn().mockResolvedValue(new Response("data: verified answer\n\n", { headers: {
      "content-type": "text/event-stream", "x-jurisdiction": "sk",
    } }));
    vi.stubGlobal("fetch", fetcher);
    const response = await proxyRequest(new Request("http://localhost:3000/api/agent", {
      method: "POST", body: "{}", headers: { "X-Expected-Jurisdiction": "bc" },
    }));
    expect(response.status).toBe(200);
    expect(response.headers.get("x-jurisdiction")).toBe("sk");
    expect(await response.text()).toBe("data: verified answer\n\n");
    expect(new Headers(fetcher.mock.calls[0][1].headers).get("x-expected-jurisdiction")).toBe("sk");
  });

  it("rejects browser government selection before any upstream request", async () => {
    await selectPack(sk);
    const { proxyRequest } = await import("@/lib/proxy");
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const response = await proxyRequest(new Request("http://localhost:3000/api/agent", {
      method: "POST", body: "{}", headers: { "X-Jurisdiction": "bc" },
    }));
    expect(response.status).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("keeps the BC favicon for the BC jurisdiction", async () => {
    await selectPack(bc);
    const { siteMetadata } = await import("@/app/site-metadata");
    expect(siteMetadata.icons).toMatchObject({
      icon: { url: "/favicon.ico" },
      shortcut: "/favicon.ico",
    });
  });

  it("uses the configured Saskatchewan public origin for canonical and social URLs", async () => {
    vi.stubEnv("SITE_URL", "https://sk.example.test");
    await selectPack(sk);
    const { siteMetadata } = await import("@/app/site-metadata");
    expect(siteMetadata.metadataBase).toEqual(new URL("https://sk.example.test"));
    expect(siteMetadata.alternates).toEqual({ canonical: "/" });
    expect(siteMetadata.openGraph).toMatchObject({
      url: "/", images: [{ url: "/opengraph-image" }],
    });
    expect(siteMetadata.twitter).toMatchObject({
      images: [{ url: "/twitter-image" }],
    });
  });

  it("uses Saskatchewan recovery messages for stream and HTTP errors without changing BC", async () => {
    for (const pack of [sk, bc]) {
      await selectPack(pack);
      const { initialStreamState, streamReducer } = await import("@/lib/stream");
      const start = () => streamReducer(initialStreamState, { type: "start", runId: "run", messageId: "user", prompt: "Question" });
      for (const code of ["SOURCES_UNAVAILABLE", "BUDGET_EXHAUSTED", "GENERAL_AGENT_NOT_CONFIGURED", "CONVERSATION_AGENT_NOT_CONFIGURED", "AGENT_UNAVAILABLE"]) {
        const state = streamReducer(start(), { type: "failure", runId: "run", code, message: "Use a guided plan." });
        expect(state.error).toEqual(pack.features.guidedJourneys ? "Use a guided plan." : expect.not.stringMatching(/guided plan/iu));
      }
      for (const data of [{ type: "RUN_ERROR", code: "SOURCES_UNAVAILABLE" }, { type: "RUN_ERROR", code: "OTHER" }, { type: "RUN_FINISHED" }]) {
        const state = streamReducer(start(), { type: "event", runId: "run", event: data as unknown as BaseEvent });
        expect(state.error).toEqual(pack.features.guidedJourneys ? expect.stringMatching(/guided plan/iu) : expect.stringMatching(/official services/iu));
      }
    }
  });

  it("offers official services instead of missing Saskatchewan journeys in recovery and notices", async () => {
    await selectPack(sk);
    const assistant = {
      state: { messages: [], error: "Connection failed.", errorCode: null, announcement: "" },
      capabilities: { conversationAvailable: false, discoveryAvailable: false },
      contextActive: false, selectedId: null, busy: false, draft: "Question",
      notice: "Connection failed.", setNotice: vi.fn(), load: vi.fn(),
      setDraft: vi.fn(), stop: vi.fn(), submit: vi.fn(),
    };
    vi.doMock("@/components/assistant-provider", () => ({ useAssistant: () => assistant }));
    vi.doMock("next/navigation", () => ({
      usePathname: () => "/", useRouter: () => ({ prefetch: vi.fn(), push: vi.fn() }),
    }));
    const { ChatExperience } = await import("@/components/chat-experience");
    const { ComposerDock } = await import("@/components/composer-dock");
    render(<><ChatExperience /><ComposerDock /></>);
    const links = screen.getAllByRole("link", { name: "Browse official services" });
    expect(links).toHaveLength(2);
    for (const link of links) expect(link).toHaveAttribute("href", "/services");
    expect(screen.queryByRole("link", { name: /guided plan/iu })).not.toBeInTheDocument();
  }, 20000);

  it("reports unavailable Saskatchewan evidence without claiming source answers are ready", async () => {
    await selectPack(sk);
    const assistant = {
      catalog: null, capabilities: { aiConfigured: true, retrievalReady: false },
      loading: false, catalogError: null, selected: null, selectedId: null,
      state: { messages: [] },
    };
    vi.doMock("@/components/assistant-provider", () => ({ useAssistant: () => assistant }));
    vi.doMock("@/components/hero-experience", () => ({ HeroExperience: () => null }));
    const { AssistantApp } = await import("@/components/assistant-app");
    const { rerender } = render(<AssistantApp />);
    expect(screen.getByText(/Current reviewed source answers unavailable/u)).toBeVisible();
    expect(screen.getByRole("link", { name: "Browse official services" })).toHaveAttribute("href", "/services");
    expect(screen.queryByText(/AI answers configured/u)).not.toBeInTheDocument();

    assistant.capabilities.aiConfigured = false;
    rerender(<AssistantApp />);
    expect(screen.getByText(/Current reviewed source answers unavailable/u)).toBeVisible();

    assistant.capabilities.aiConfigured = true;
    assistant.capabilities.retrievalReady = true;
    rerender(<AssistantApp />);
    expect(screen.getByText(/AI answers configured/u)).toBeVisible();
  });

  it("uses Saskatchewan official destinations, metadata and honest handoffs", async () => {
    await selectPack(sk);
    const { safeOfficialUrl } = await import("@/lib/links");
    const { siteMetadata, siteTitle } = await import("@/app/site-metadata");
    const { default: ServicesPage } = await import("@/app/services/page");
    expect(safeOfficialUrl("https://www.saskatchewan.ca/residents")).toBe("https://www.saskatchewan.ca/residents");
    expect(safeOfficialUrl("https://www2.gov.bc.ca/gov/content/home")).toBeNull();
    expect(safeOfficialUrl("https://saskatchewan.ca.evil.test/")).toBeNull();
    expect(siteTitle).toBe("Saskatchewan assistant pilot");
    expect(siteMetadata.description).toContain("not an official");
    expect(siteMetadata.icons).toMatchObject({
      icon: { url: "/favicon-saskatchewan.ico", type: "image/x-icon" },
      shortcut: "/favicon-saskatchewan.ico",
    });
    render(<ServicesPage />);
    expect(screen.getByText(sk.presentation.emptyJourneys)).toBeVisible();
    expect(screen.queryByRole("link", { name: /Explore guided plans/u })).not.toBeInTheDocument();
    const externalLinks = screen.getAllByRole("link").filter((link) => link.getAttribute("target") === "_blank");
    expect(externalLinks).toHaveLength(3);
    for (const link of externalLinks) expect(link.getAttribute("href")).toMatch(/^https:\/\/www\.saskatchewan\.ca\//u);
  });
});
