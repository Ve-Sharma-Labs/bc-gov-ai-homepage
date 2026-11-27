import { createHash } from "node:crypto";
import { ManagedIdentityCredential } from "@azure/identity";

try {
  const { API_BASE_URL, API_AUTH_SCOPE, AZURE_CLIENT_ID, RELEASE_COMMIT, RELEASE_ID, PUBLIC_ORIGIN } = process.env;
  const base = new URL(API_BASE_URL);
  const origin = new URL(PUBLIC_ORIGIN);
  if (!process.env.IDENTITY_ENDPOINT || !process.env.IDENTITY_HEADER
    || base.protocol !== "https:" || !/^[a-z0-9-]+\.internal\.[a-z0-9.-]+\.azurecontainerapps\.io$/.test(base.hostname)
    || !base.hostname.endsWith(".azurecontainerapps.io") || base.username || base.password
    || base.pathname !== "/" || base.search || base.hash || (base.port && base.port !== "443")
    || origin.protocol !== "https:" || origin.origin !== PUBLIC_ORIGIN
    || !/^[a-f0-9-]{36}$/i.test(AZURE_CLIENT_ID || "")
    || !/^api:\/\/[a-f0-9-]{36}\/\.default$/i.test(API_AUTH_SCOPE || "")
    || !/^[a-f0-9]{40}$/.test(RELEASE_COMMIT || "")
    || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(RELEASE_ID || "")) {
    throw new Error("PRIVATE_PROBE_CONFIGURATION_REQUIRED");
  }
  const credential = new ManagedIdentityCredential({ clientId: AZURE_CLIENT_ID });
  const token = await credential.getToken(API_AUTH_SCOPE, { abortSignal: AbortSignal.timeout(20_000) });
  if (!token?.token) throw new Error("PRIVATE_PROBE_AUTH_FAILED");
  const response = await fetch(new URL("/api/capabilities", base), {
    redirect: "error", signal: AbortSignal.timeout(60_000),
    headers: {
      authorization: `Bearer ${token.token}`,
      origin: PUBLIC_ORIGIN,
      "x-bc-client": createHash("sha256").update(`synthetic-release-probe:${RELEASE_ID}`).digest("hex"),
      "x-bc-client-version": "6",
    },
  });
  if (response.status !== 200 || response.headers.get("x-bc-api-release") !== RELEASE_COMMIT
    || response.headers.get("x-bc-api-deployment") !== RELEASE_ID) {
    throw new Error("PRIVATE_PROBE_IDENTITY_FAILED");
  }
  const body = await response.json();
  if (body.mode !== "foundry" || !body.conversationAgentReady || !body.taskAssistanceAvailable
    || !body.retrievalReady || body.sourceHealth?.status !== "ready"
    || body.transactionsEnabled !== false || body.webIqEnabled !== false) {
    throw new Error("PRIVATE_PROBE_NOT_READY");
  }
  console.log("PRIVATE_READINESS_PASSED");
} catch {
  console.error("PRIVATE_READINESS_FAILED");
  process.exitCode = 1;
}
