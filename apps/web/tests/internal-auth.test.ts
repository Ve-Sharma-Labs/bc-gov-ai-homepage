import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { internalHeaders } from "@/lib/internal-auth";

const { getToken } = vi.hoisted(() => ({ getToken: vi.fn() }));
vi.mock("@azure/identity", () => ({
  ManagedIdentityCredential: class { getToken = getToken; },
}));

beforeEach(() => {
  getToken.mockReset().mockResolvedValue({ token: "fixture-service-token", expiresOnTimestamp: Date.now() + 60000 });
});
afterEach(() => vi.unstubAllEnvs());

describe("private service boundary", () => {
  it("keeps local development credential-free", async () => {
    vi.stubEnv("API_AUTH_SCOPE", "");
    expect([...(await internalHeaders(new Request("http://localhost/api/catalog")))]).toEqual([]);
    expect(getToken).not.toHaveBeenCalled();
  });

  it("requires the configured edge and replaces public identity headers", async () => {
    vi.stubEnv("API_AUTH_SCOPE", "api://33333333-3333-4333-8333-333333333333/.default");
    vi.stubEnv("FRONT_DOOR_ID", "fixture-front-door");
    vi.stubEnv("CLIENT_HASH_KEY", "fixture-hash-key-not-a-production-secret");
    const request = new Request("https://preview.example/api/agent", { headers: {
      "x-azure-fdid": "fixture-front-door", "x-azure-socketip": "203.0.113.10",
      "x-azure-clientip": "198.51.100.99",
      "authorization": "Bearer attacker", "x-bc-client": "attacker",
    } });
    const headers = await internalHeaders(request);
    expect(headers.get("authorization")).toBe("Bearer fixture-service-token");
    expect(headers.get("x-bc-client")).toMatch(/^[a-f0-9]{64}$/);
    expect(headers.get("x-bc-client")).not.toContain("203.0.113.10");
    await expect(internalHeaders(new Request("https://preview.example/api/agent"))).rejects.toThrow("ingress");
  });
});
