import { journeyIds } from "./contract";
import { internalHeaders } from "./internal-auth";

const READ_PATHS = new Set([
  "/healthz",
  "/api/catalog",
  "/api/capabilities",
  "/api/locations",
  "/api/demo/personas",
  "/api/context/summary",
  "/api/discovery",
  "/api/conversation",
  "/api/conversation/task",
]);
const MAX_BODY_BYTES = 64 * 1024;

export function allowedApiRequest(method: string, pathname: string, query: URLSearchParams): boolean {
  if (query.size && pathname !== "/api/locations") return false;
  if (pathname === "/api/locations") {
    if ([...query.keys()].some((key) => !["service", "municipality"].includes(key))) return false;
    if (["service", "municipality"].some((key) => query.getAll(key).length > 1 || (query.get(key)?.length ?? 0) > 160)) return false;
  }
  if (method === "GET") {
    return READ_PATHS.has(pathname) || journeyIds.some((id) => pathname === `/api/journeys/${id}`);
  }
  if (method === "DELETE") return ["/api/demo/session", "/api/discovery", "/api/conversation"].includes(pathname);
  return method === "POST" && (
    pathname === "/api/agent"
    || pathname === "/api/demo/session"
    || pathname === "/api/context/consents"
    || pathname === "/api/conversation/control"
    || /^\/api\/runs\/[A-Za-z0-9_-]{1,128}\/cancel$/u.test(pathname)
  );
}

function failure(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status, headers: { "Cache-Control": "no-store" } });
}

function loopbackHost(host: string): boolean {
  return ["localhost", "127.0.0.1", "::1", "[::1]", "::ffff:127.0.0.1"].includes(host.toLowerCase());
}

function localEvaluationRequest(request: Request, incoming: URL, base: URL): boolean {
  if (!loopbackHost(incoming.hostname) || !loopbackHost(base.hostname)
    || !loopbackHost(process.env.HOSTNAME || "") || process.env.API_AUTH_SCOPE
    || request.headers.has("forwarded")) return false;
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded && !forwarded.split(",").every((value) => loopbackHost(value.trim()))) return false;
  try {
    const forwardedHost = request.headers.get("x-forwarded-host");
    if (forwardedHost && !loopbackHost(new URL(`http://${forwardedHost}`).hostname)) return false;
    const origin = request.headers.get("origin");
    return !origin || loopbackHost(new URL(origin).hostname);
  } catch {
    return false;
  }
}

export async function proxyRequest(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  if (!allowedApiRequest(request.method, incoming.pathname, incoming.searchParams)) {
    return failure(404, "UNSUPPORTED_ENDPOINT", "That service endpoint is not available.");
  }

  let base: URL;
  try {
    base = new URL(process.env.API_BASE_URL || "http://127.0.0.1:8000");
    if (!["http:", "https:"].includes(base.protocol) || base.username || base.password || base.search || base.hash || base.pathname !== "/") throw new Error();
    if (process.env.API_AUTH_SCOPE && (base.protocol !== "https:" || !base.hostname.endsWith(".azurecontainerapps.io"))) throw new Error();
  } catch {
    return failure(503, "CONFIGURATION_ERROR", "The service connection is not configured correctly.");
  }
  const localEvaluation = process.env.LOCAL_EVIDENCE_EVALUATION_ENABLED === "true";
  if (localEvaluation && !localEvaluationRequest(request, incoming, base)) {
    return failure(403, "LOCAL_EVALUATION_ONLY", "These sources are restricted to the loopback, non-commercial evaluation app.");
  }

  const controller = new AbortController();
  const abort = () => controller.abort();
  request.signal.addEventListener("abort", abort, { once: true });
  if (request.signal.aborted) abort();
  // Readiness can include CLI credential priming followed by agent/source metadata checks.
  const timeoutMs = incoming.pathname === "/api/agent" ? 180_000
    : incoming.pathname === "/api/capabilities" ? 45_000 : 15_000;
  const timeout = setTimeout(abort, timeoutMs);
  const cleanup = () => {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abort);
  };

  try {
    if (controller.signal.aborted) throw new Error("Request cancelled");
    let body: Uint8Array | undefined;
    if (request.method === "POST") {
      if (Number(request.headers.get("content-length") || 0) > MAX_BODY_BYTES) {
        cleanup();
        return failure(413, "REQUEST_TOO_LARGE", "That message is too long. Please shorten it and try again.");
      }
      const reader = request.body?.getReader();
      if (reader) {
        const chunks: Uint8Array[] = [];
        let size = 0;
        const cancelBody = () => { void reader.cancel().catch(() => undefined); };
        controller.signal.addEventListener("abort", cancelBody, { once: true });
        try {
          while (true) {
            const part = await reader.read();
            if (part.done) break;
            size += part.value.byteLength;
            if (size > MAX_BODY_BYTES) {
              await reader.cancel();
              cleanup();
              return failure(413, "REQUEST_TOO_LARGE", "That message is too long. Please shorten it and try again.");
            }
            chunks.push(part.value);
          }
        } finally {
          controller.signal.removeEventListener("abort", cancelBody);
        }
        if (controller.signal.aborted) throw new Error("Request cancelled");
        body = new Uint8Array(size);
        let offset = 0;
        for (const chunk of chunks) {
          body.set(chunk, offset);
          offset += chunk.byteLength;
        }
      }
    }
    const headers = new Headers();
    for (const name of ["accept", "content-type", "cookie", "origin", "x-bc-context-page", "x-bc-discovery-page", "x-bc-conversation-page", "x-bc-client-version"]) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    const serviceHeaders = await internalHeaders(request);
    serviceHeaders.forEach((value, name) => headers.set(name, value));
    if (localEvaluation) headers.set("X-BC-Evaluation-Scope", "local-noncommercial");
    const response = await fetch(new URL(incoming.pathname + incoming.search, base), {
      method: request.method,
      headers,
      body: body as BodyInit | undefined,
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal,
    });
    if (response.status >= 300 && response.status < 400) {
      await response.body?.cancel();
      cleanup();
      return failure(502, "UNEXPECTED_REDIRECT", "The service returned an unexpected redirect. Please try again later.");
    }
    const outputHeaders = new Headers({
      "Cache-Control": "no-store, no-transform",
      "X-Accel-Buffering": "no",
    });
    for (const name of ["content-type", "retry-after"]) {
      const value = response.headers.get(name);
      if (value) outputHeaders.set(name, value);
    }
    for (const cookie of response.headers.getSetCookie()) outputHeaders.append("set-cookie", cookie);
    if (!response.body) {
      cleanup();
      return new Response(null, { status: response.status, headers: outputHeaders });
    }
    const reader = response.body.getReader();
    const stream = new ReadableStream<Uint8Array>({
      async pull(destination) {
        try {
          const next = await reader.read();
          if (next.done) {
            cleanup();
            destination.close();
          } else {
            destination.enqueue(next.value);
          }
        } catch {
          cleanup();
          destination.error(new Error("The service stream was interrupted."));
        }
      },
      async cancel() {
        abort();
        cleanup();
        await reader.cancel().catch(() => undefined);
      },
    });
    return new Response(stream, { status: response.status, headers: outputHeaders });
  } catch {
    cleanup();
    if (controller.signal.aborted) {
      return failure(504, "UPSTREAM_TIMEOUT", "The service took too long to respond. Your question has been kept.");
    }
    return failure(502, "UPSTREAM_UNAVAILABLE", "The service API is not reachable. You can still use the official service links.");
  }
}
