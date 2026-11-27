import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { CSSProperties } from "react";
import { ImageResponse } from "next/og";
import { socialTitle } from "./site-metadata";
import { jurisdiction, presentation } from "@/lib/jurisdiction";

export const socialImageSize = { width: 1200, height: 630 };
export const socialImageContentType = "image/png";

const cardStyle: CSSProperties = {
  width: "100%",
  height: "100%",
  display: "flex",
  flexDirection: "column",
  justifyContent: "space-between",
  background: presentation.socialBackground,
  color: "#ffffff",
  padding: "72px 84px",
  fontFamily: "Arial, sans-serif",
};

export function SocialCard({ logo }: { logo?: string }) {
  return (
    <div style={cardStyle}>
      {jurisdiction.id === "bc" && <div style={{ display: "flex", alignItems: "center", background: "#ffffff", padding: "26px 34px", width: 530 }}>
        <img
          alt={jurisdiction.name}
          src={logo}
          style={{ width: 361, height: 120 }}
        />
      </div>}
      {jurisdiction.id === "sk" && logo && <div style={{ display: "flex", alignItems: "center", background: "#ffffff", padding: "20px 28px" }}>
        <img alt={jurisdiction.name} src={logo} style={{ width: 373, height: 79 }} />
      </div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ display: "flex", fontSize: jurisdiction.id === "bc" ? 88 : 64, fontWeight: 700, letterSpacing: "-3px" }}>{socialTitle}</div>
        <div style={{ display: "flex", width: 180, height: 10, background: presentation.socialAccent }} />
        <div style={{ display: "flex", fontSize: 34 }}>{presentation.pilotNotice || (jurisdiction.id === "sk" ? presentation.aboutLead : "Government services, made easier to navigate.")}</div>
      </div>
    </div>
  );
}

export async function renderSocialImage() {
  const logo = jurisdiction.id === "sk" || jurisdiction.id === "bc"
    ? `data:image/png;base64,${(await readFile(join(process.cwd(), "public", jurisdiction.brand.logo.slice(1)))).toString("base64")}`
    : undefined;
  return new ImageResponse(<SocialCard logo={logo} />, socialImageSize);
}
