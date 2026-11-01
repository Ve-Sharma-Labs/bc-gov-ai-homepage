import { afterEach, describe, expect, it, vi } from "vitest";
import { allowedApiRequest, proxyRequest } from "@/lib/proxy";

afterEach(() => vi.unstubAllEnvs());

describe("closed same-origin proxy boundary", () => {
  it.each([
    ["http://public.example/api/catalog", "127.0.0.1", {}],
    ["http://127.0.0.1:3000/api/catalog", "0.0.0.0", {}],
    ["http://127.0.0.1:3000/api/catalog", "127.0.0.1", { "x-forwarded-for": "192.0.2.1" }],
    ["http://127.0.0.1:3000/api/catalog", "127.0.0.1", { origin: "https://public.example" }],
    ["http://127.0.0.1:3000/api/catalog", "127.0.0.1", { forwarded: "for=127.0.0.1" }],
  ])("does not expose local evaluation sources via %s", async (url, host, headers) => {
    vi.stubEnv("LOCAL_EVIDENCE_EVALUATION_ENABLED", "true");
    vi.stubEnv("HOSTNAME", host);
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const response = await proxyRequest(new Request(url, { headers }));
    expect(response.status).toBe(403);
    expect((await response.json()).error.code).toBe("LOCAL_EVALUATION_ONLY");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("marks verified loopback evaluation requests without trusting a client scope header", async () => {
    vi.stubEnv("LOCAL_EVIDENCE_EVALUATION_ENABLED", "true");
    vi.stubEnv("HOSTNAME", "127.0.0.1");
    vi.stubEnv("API_BASE_URL", "http://127.0.0.1:8000");
    let headers = new Headers();
    vi.stubGlobal("fetch", vi.fn(async (_url, init: RequestInit) => {
      headers = new Headers(init.headers);
      return Response.json({ ok: true });
    }));
    const response = await proxyRequest(new Request("http://127.0.0.1:3000/api/catalog", {
      headers: { "x-forwarded-for": "127.0.0.1", "x-bc-evaluation-scope": "public" },
    }));
    expect(response.status).toBe(200);
    await response.json();
    expect(headers.get("x-bc-evaluation-scope")).toBe("local-noncommercial");
    expect(headers.has("x-forwarded-for")).toBe(false);
  });

  it.each([
    ["GET", "/api/catalog"],
    ["GET", "/healthz"],
    ["GET", "/api/capabilities"],
    ["GET", "/api/demo/personas"],
    ["GET", "/api/context/summary"],
    ["GET", "/api/discovery"],
    ["GET", "/api/journeys/licence-renewal"],
    ["GET", "/api/locations"],
    ["POST", "/api/agent"],
    ["POST", "/api/demo/session"],
    ["POST", "/api/context/consents"],
    ["DELETE", "/api/demo/session"],
    ["DELETE", "/api/discovery"],
    ["POST", "/api/runs/run-123/cancel"],
  ])("allows %s %s", (method, path) => expect(allowedApiRequest(method, path, new URLSearchParams())).toBe(true));

  it.each([
    ["GET", "/api/agent"],
    ["POST", "/api/catalog"],
    ["GET", "/api/journeys/unknown"],
    ["POST", "/api/runs/../cancel"],
    ["DELETE", "/api/agent"],
    ["DELETE", "/api/context/summary"],
    ["POST", "/api/context/summary"],
    ["POST", "/api/discovery"],
    ["GET", "/api/admin"],
    ["GET", "/api/http://example.com"],
    ["GET", "/api/healthz"],
  ])("rejects %s %s", (method, path) => expect(allowedApiRequest(method, path, new URLSearchParams())).toBe(false));

  it("rejects unexpected, duplicated or misplaced query parameters", () => {
    expect(allowedApiRequest("GET", "/api/catalog", new URLSearchParams("url=https://evil.test"))).toBe(false);
    expect(allowedApiRequest("GET", "/api/discovery", new URLSearchParams("age=30"))).toBe(false);
    expect(allowedApiRequest("GET", "/api/locations", new URLSearchParams("service=a&service=b"))).toBe(false);
    expect(allowedApiRequest("GET", "/api/locations", new URLSearchParams("host=evil.test"))).toBe(false);
    expect(allowedApiRequest("GET", "/api/locations", new URLSearchParams("service=icbc-licensing&municipality=Victoria"))).toBe(true);
  });

  it("does not fetch an unapproved route or malformed upstream configuration", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect((await proxyRequest(new Request("http://localhost:3000/api/private"))).status).toBe(404);
    vi.stubEnv("API_BASE_URL", "file:///private");
    expect((await proxyRequest(new Request("http://localhost:3000/api/catalog"))).status).toBe(503);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("forwards safe error status, origin and session cookies without provider headers", async () => {
    let requestHeaders: Headers | undefined;
    vi.stubGlobal("fetch", vi.fn(async (_url, init: RequestInit) => {
      requestHeaders = new Headers(init.headers);
      return Response.json({ error: { code: "RATE_LIMITED", message: "Please wait." } }, {
        status: 429,
        headers: { "Set-Cookie": "bc_pilot_session=opaque; HttpOnly; SameSite=Strict; Path=/api", "Retry-After": "30", "X-Provider-Internal": "private" },
      });
    }));
    const response = await proxyRequest(new Request("http://localhost:3000/api/agent", {
      method: "POST",
      headers: { "content-type": "application/json", Cookie: "bc_pilot_session=prior", Origin: "http://localhost:3000" },
      body: "{}",
    }));
    expect(response.status).toBe(429);
    expect(requestHeaders!.get("Cookie")).toBe("bc_pilot_session=prior");
    expect(requestHeaders!.get("Origin")).toBe("http://localhost:3000");
    expect(response.headers.get("Set-Cookie")).toContain("HttpOnly");
    expect(response.headers.get("Retry-After")).toBe("30");
    expect(response.headers.has("X-Provider-Internal")).toBe(false);
    expect(await response.json()).toEqual({ error: { code: "RATE_LIMITED", message: "Please wait." } });
  });

  it("forwards page-bound context cleanup without a request body", async () => {
    let upstreamMethod = "";
    let upstreamBody: BodyInit | null | undefined;
    let upstreamHeaders = new Headers();
    vi.stubGlobal("fetch", vi.fn(async (_url, init: RequestInit) => {
      upstreamMethod = init.method || "";
      upstreamBody = init.body;
      upstreamHeaders = new Headers(init.headers);
      return new Response(null, {
        status: 204,
        headers: {
          "Set-Cookie": "bc_synthetic_context=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/api",
        },
      });
    }));
    const response = await proxyRequest(new Request("http://localhost:3000/api/demo/session", {
      method: "DELETE",
      headers: {
        Cookie: "bc_synthetic_context=opaque",
        Origin: "http://localhost:3000",
        "X-BC-Context-Page": "context-proxy-page-00000001",
      },
    }));
    expect(response.status).toBe(204);
    expect(upstreamMethod).toBe("DELETE");
    expect(upstreamBody).toBeUndefined();
    expect(upstreamHeaders.get("x-bc-context-page")).toBe(
      "context-proxy-page-00000001",
    );
    expect(response.headers.get("Set-Cookie")).toContain("Max-Age=0");
  });

  it("returns the first stream chunk without buffering and aborts upstream on consumer cancellation", async () => {
    let upstreamSignal: AbortSignal | undefined;
    let upstreamCancelled = false;
    const encoder = new TextEncoder();
    vi.stubGlobal("fetch", vi.fn(async (_url, init: RequestInit) => {
      upstreamSignal = init.signal as AbortSignal;
      return new Response(new ReadableStream({
        start(controller) { controller.enqueue(encoder.encode("data: first\n\n")); },
        cancel() { upstreamCancelled = true; },
      }), { headers: { "Content-Type": "text/event-stream" } });
    }));
    const response = await proxyRequest(new Request("http://localhost:3000/api/agent", { method: "POST", body: "{}" }));
    expect(response.headers.get("Cache-Control")).toContain("no-transform");
    expect(response.headers.get("X-Accel-Buffering")).toBe("no");
    const reader = response.body!.getReader();
    const first = await reader.read();
    expect(new TextDecoder().decode(first.value)).toBe("data: first\n\n");
    expect(first.done).toBe(false);
    await reader.cancel();
    expect(upstreamSignal!.aborted).toBe(true);
    expect(upstreamCancelled).toBe(true);
  });

  it.each([
    ["/api/capabilities", 20_000, 200],
    ["/api/capabilities", 45_001, 504],
    ["/api/catalog", 15_001, 504],
  ])("bounds %s readiness at %i ms with HTTP %i", async (path, elapsed, status) => {
    vi.useFakeTimers();
    let upstreamSignal: AbortSignal | undefined;
    let complete!: () => void;
    vi.stubGlobal("fetch", vi.fn(async (_url, init: RequestInit) => {
      upstreamSignal = init.signal ?? undefined;
      return new Promise<Response>((resolve, reject) => {
        complete = () => resolve(Response.json({ ready: true }));
        upstreamSignal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      });
    }));
    try {
      const pending = proxyRequest(new Request(`http://localhost:3000${path}`));
      await vi.waitFor(() => expect(upstreamSignal).toBeDefined());
      await vi.advanceTimersByTimeAsync(elapsed);
      expect(upstreamSignal?.aborted).toBe(status === 504);
      if (status === 200) complete();
      const response = await pending;
      expect(response.status).toBe(status);
      await response.text();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not follow upstream redirects or leak network errors", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 302, headers: { Location: "https://elsewhere.test" } }));
    vi.stubGlobal("fetch", fetcher);
    expect((await proxyRequest(new Request("http://localhost:3000/api/catalog"))).status).toBe(502);
    expect(fetcher.mock.calls[0][1].redirect).toBe("manual");
    fetcher.mockRejectedValue(new Error("secret connection details"));
    const response = await proxyRequest(new Request("http://localhost:3000/api/catalog"));
    expect(response.status).toBe(502);
    expect(await response.text()).not.toContain("secret");
  });

  it("bounds the request body before it reaches the API", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const response = await proxyRequest(new Request("http://localhost:3000/api/agent", { method: "POST", body: "x".repeat(65_537) }));
    expect(response.status).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
