import { createHmac } from "node:crypto";
import { isIP } from "node:net";
import { ManagedIdentityCredential } from "@azure/identity";

let credential: ManagedIdentityCredential | undefined;

export async function internalHeaders(request: Request): Promise<Headers> {
  const headers = new Headers();
  const scope = process.env.API_AUTH_SCOPE;
  if (!scope) return headers;
  if (!/^api:\/\/[0-9a-f-]{36}\/\.default$/i.test(scope)) {
    throw new Error("Use the registered internal API application scope.");
  }
  const frontDoorId = process.env.FRONT_DOOR_ID;
  const hashKey = process.env.CLIENT_HASH_KEY;
  const address = request.headers.get("x-azure-socketip");
  if (!frontDoorId || !hashKey || hashKey.length < 32 ||
      request.headers.get("x-azure-fdid") !== frontDoorId ||
      !address || !isIP(address)) {
    throw new Error("Trusted public ingress is not configured or verified.");
  }
  credential ??= process.env.AZURE_CLIENT_ID
    ? new ManagedIdentityCredential({ clientId: process.env.AZURE_CLIENT_ID })
    : new ManagedIdentityCredential();
  const token = await credential.getToken(scope);
  if (!token?.token) throw new Error("The internal API token is unavailable.");
  headers.set("authorization", `Bearer ${token.token}`);
  headers.set("x-bc-client", createHmac("sha256", hashKey).update(address).digest("hex"));
  return headers;
}
