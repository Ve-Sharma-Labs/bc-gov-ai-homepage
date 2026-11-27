import type { NextConfig } from "next";
import path from "node:path";
import { prepareJurisdiction, stampJurisdiction } from "./scripts/prepare-jurisdiction.mjs";

const selectedJurisdiction = prepareJurisdiction();
stampJurisdiction(selectedJurisdiction);

const requestedDistDir = process.env.NEXT_DIST_DIR;
if (requestedDistDir && !/^\.next(?:-[a-z0-9-]+)?$/u.test(requestedDistDir)) {
  throw new Error("NEXT_DIST_DIR must be a local .next or .next-* directory.");
}

const config: NextConfig = {
  distDir: requestedDistDir || ".next",
  output: "standalone",
  serverExternalPackages: ["@azure/identity"],
  poweredByHeader: false,
  reactStrictMode: true,
  compiler: {
    runAfterProductionCompile: async () => { stampJurisdiction(selectedJurisdiction); },
  },
  turbopack: { root: path.resolve(__dirname) },
  experimental: { proxyClientMaxBodySize: "64kb" },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default config;
