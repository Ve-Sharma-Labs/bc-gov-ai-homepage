import { afterEach, describe, expect, it, vi } from "vitest";
import { allowedApiRequest, proxyRequest } from "@/lib/proxy";

afterEach(() => vi.unstubAllEnvs());

describe("closed same-origin proxy boundary", () => {
  it.each([
    ["GET", "/api/catalog"],
    ["GET", "/healthz"],
    ["GET", "/api/capabilities"],
    ["GET", "/api/journeys/licence-renewal"],
    ["GET", "/api/locations"],
    ["POST", "/api/agent"],
    ["POST", "/api/runs/run-123/cancel"],
  ])("allows %s %s", (method, path) => expect(allowedApiRequest(method, path, new URLSearchParams())).toBe(true));

  it.each([
    ["GET", "/api/agent"],
    ["POST", "/api/catalog"],
    ["GET", "/api/journeys/unknown"],
    ["POST", "/api/runs/../cancel"],
    ["DELETE", "/api/agent"],
    ["GET", "/api/admin"],
    ["GET", "/api/http://example.com"],
    ["GET", "/api/healthz"],
  ])("rejects %s %s", (method, path) => expect(allowedApiRequest(method, path, new URLSearchParams())).toBe(false));

  it("rejects unexpected, duplicated or misplaced query parameters", () => {
    expect(allowedApiRequest("GET", "/api/catalog", new URLSearchParams("url=https://evil.test"))).toBe(false);
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
