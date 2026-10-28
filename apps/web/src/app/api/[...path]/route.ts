import { proxyRequest } from "@/lib/proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const GET = proxyRequest;
export const POST = proxyRequest;
