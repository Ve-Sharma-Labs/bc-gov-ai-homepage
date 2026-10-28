import { z } from "zod";
import { catalogSchema, capabilitiesSchema, locationSchema } from "./contract";

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

export async function readApi<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { signal, cache: "no-store", credentials: "same-origin" });
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

export const getCatalog = (signal?: AbortSignal) => readApi("/api/catalog", catalogSchema, signal);
export const getCapabilities = (signal?: AbortSignal) => readApi("/api/capabilities", capabilitiesSchema, signal);

export function getLocations(service: string, municipality: string, signal?: AbortSignal) {
  const query = new URLSearchParams();
  if (service) query.set("service", service);
  if (municipality) query.set("municipality", municipality);
  return readApi(`/api/locations?${query}`, z.object({ locations: z.array(locationSchema).max(500) }), signal);
}
