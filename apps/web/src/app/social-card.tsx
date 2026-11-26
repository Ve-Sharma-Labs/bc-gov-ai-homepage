import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { CSSProperties } from "react";
import { siteTitle } from "./site-metadata";

export const socialImageSize = { width: 1200, height: 630 };
export const socialImageContentType = "image/png";

// Next runs from the app root, with public copied beside the standalone server.
const logo = await readFile(join(process.cwd(), "public", "brand", "bc-logo-horizontal-transparent.png"));
const logoSrc = `data:image/png;base64,${logo.toString("base64")}`;

const cardStyle: CSSProperties = {
  width: "100%",
  height: "100%",
  display: "flex",
  flexDirection: "column",
  justifyContent: "space-between",
  background: "#013366",
  color: "#ffffff",
  padding: "72px 84px",
  fontFamily: "Arial, sans-serif",
};

export function SocialCard() {
  return (
    <div style={cardStyle}>
      <div style={{ display: "flex", alignItems: "center", background: "#ffffff", padding: "26px 34px", width: 530 }}>
        <img
          alt="Government of British Columbia"
          src={logoSrc}
          style={{ width: 361, height: 120 }}
        />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ display: "flex", fontSize: 88, fontWeight: 700, letterSpacing: "-3px" }}>{siteTitle}</div>
        <div style={{ display: "flex", width: 180, height: 10, background: "#fdb813" }} />
        <div style={{ display: "flex", fontSize: 34 }}>Government services, made easier to navigate.</div>
      </div>
    </div>
  );
}
