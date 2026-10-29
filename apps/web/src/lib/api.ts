import { z } from "zod";
import {
  catalogSchema,
  capabilitiesSchema,
  consentReceiptSchema,
  consentScopeSchema,
  contextSummarySchema,
  demoPersonaIds,
  demoPersonaIdSchema,
  demoPersonaSummarySchema,
  locationSchema,
  type ConsentScope,
  type DemoPersonaId,
} from "./contract";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly retryAt: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let contextPageToken: string | null = null;

export function getContextPageToken(): string {
  contextPageToken ??= crypto.randomUUID();
  return contextPageToken;
}

export async function readApi<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
  return requestApi(path, schema, { signal });
}

async function requestApi<T>(
  path: string,
  schema: z.ZodType<T>,
  options: {
    method?: "GET" | "POST";
    body?: unknown;
    signal?: AbortSignal;
    keepalive?: boolean;
    contextPage?: boolean;
  } = {},
): Promise<T> {
  let response: Response;
  try {
    const headers = new Headers();
    if (options.body !== undefined) headers.set("content-type", "application/json");
    if (options.contextPage) headers.set("x-bc-context-page", getContextPageToken());
    response = await fetch(path, {
      method: options.method ?? "GET",
      ...(options.body === undefined ? {} : {
        body: JSON.stringify(options.body),
      }),
      ...(options.body !== undefined || options.contextPage ? { headers } : {}),
      signal: options.signal,
      keepalive: options.keepalive,
      cache: "no-store",
      credentials: "same-origin",
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(0, "DISCONNECTED", "We couldn’t reach the service. Check your connection and try again.");
  }
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      typeof error?.error?.code === "string" ? error.error.code : "UNAVAILABLE",
      typeof error?.error?.message === "string" ? error.error.message.slice(0, 600) : "This service is unavailable. Please try again.",
    );
  }
  const result = schema.safeParse(await response.json().catch(() => null));
  if (!result.success) throw new ApiError(502, "INVALID_CONTENT", "We couldn’t verify the service information. Please try again later.");
  return result.data;
}

const demoSessionSchema = z.object({
  persona: demoPersonaSummarySchema,
  expiresAt: z.string().datetime({ offset: true }),
  synthetic: z.literal(true),
}).strict();
const demoPersonasSchema = z.array(demoPersonaSummarySchema).length(3)
  .superRefine((personas, context) => {
    const ids = personas.map((persona) => persona.id);
    if (
      new Set(ids).size !== demoPersonaIds.length
      || demoPersonaIds.some((personaId) => !ids.includes(personaId))
    ) {
      context.addIssue({ code: "custom", message: "The fixed synthetic persona catalogue is incomplete" });
    }
  });

const consentChangeSchema = z.object({
  action: z.enum(["grant", "revoke"]),
  scopes: z.array(consentScopeSchema).min(1).max(6),
}).strict();

export const getCatalog = (signal?: AbortSignal) => readApi("/api/catalog", catalogSchema, signal);
export const getCapabilities = (signal?: AbortSignal) => readApi("/api/capabilities", capabilitiesSchema, signal);
export const getDemoPersonas = (signal?: AbortSignal) => readApi(
  "/api/demo/personas",
  demoPersonasSchema,
  signal,
);
export const getContextSummary = (signal?: AbortSignal) => requestApi(
  "/api/context/summary",
  contextSummarySchema,
  { signal, contextPage: true },
);

export function createDemoSession(personaId: DemoPersonaId, signal?: AbortSignal) {
  return requestApi("/api/demo/session", demoSessionSchema, {
    method: "POST",
    body: { personaId: demoPersonaIdSchema.parse(personaId) },
    signal,
    contextPage: true,
  });
}

export function changeContextConsent(
  action: "grant" | "revoke",
  scopes: ConsentScope[],
  signal?: AbortSignal,
) {
  const body = consentChangeSchema.parse({ action, scopes });
  return requestApi("/api/context/consents", consentReceiptSchema, {
    method: "POST",
    body,
    signal,
    contextPage: true,
  });
}

export async function deleteDemoSession(options: { signal?: AbortSignal; keepalive?: boolean } = {}) {
  let response: Response;
  try {
    response = await fetch("/api/demo/session", {
      method: "DELETE",
      headers: { "x-bc-context-page": getContextPageToken() },
      signal: options.signal,
      keepalive: options.keepalive,
      cache: "no-store",
      credentials: "same-origin",
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(0, "DISCONNECTED", "We couldn’t clear the synthetic demo session. Please try again.");
  }
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      typeof error?.error?.code === "string" ? error.error.code : "UNAVAILABLE",
      typeof error?.error?.message === "string"
        ? error.error.message.slice(0, 600)
        : "We couldn’t clear the synthetic demo session. Please try again.",
    );
  }
}

export function getLocations(service: string, municipality: string, signal?: AbortSignal) {
  const query = new URLSearchParams();
  if (service) query.set("service", service);
  if (municipality) query.set("municipality", municipality);
  return readApi(`/api/locations?${query}`, z.object({ locations: z.array(locationSchema).max(500) }), signal);
}
