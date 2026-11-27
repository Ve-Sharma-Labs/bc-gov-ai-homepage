import type { Metadata } from "next";
import { jurisdiction, presentation } from "@/lib/jurisdiction";

export const siteUrl = new URL(process.env.SITE_URL || presentation.siteUrl);
export const siteTitle = presentation.title;
export const socialTitle = jurisdiction.id === "sk" ? "AI at Government of Saskatchewan" : siteTitle;
export const siteDescription = presentation.pilotNotice || (jurisdiction.id === "sk" ? presentation.aboutLead : jurisdiction.description);
export const socialImageAlt = jurisdiction.id === "sk" ? `${socialTitle} — Saskatchewan logo` : presentation.socialAlt;

export const siteMetadata: Metadata = {
  metadataBase: siteUrl,
  title: { default: siteTitle, template: `%s · ${siteTitle}` },
  description: siteDescription,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    url: "/",
    title: socialTitle,
    description: siteDescription,
    siteName: socialTitle,
    locale: "en_CA",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: socialImageAlt }],
  },
  twitter: {
    card: "summary_large_image",
    title: socialTitle,
    description: siteDescription,
    images: [{ url: "/twitter-image", width: 1200, height: 630, alt: socialImageAlt }],
  },
  robots: { index: false, follow: false },
  icons: jurisdiction.id === "bc" ? {
    icon: { url: "/favicon.ico", type: "image/x-icon", sizes: "16x16 32x32 48x48" },
    shortcut: "/favicon.ico",
    apple: { url: "/apple-touch-icon.png", type: "image/png", sizes: "180x180" },
  } : jurisdiction.id === "sk" ? {
    icon: { url: "/favicon-saskatchewan.ico", type: "image/x-icon", sizes: "16x16 32x32 48x48" },
    shortcut: "/favicon-saskatchewan.ico",
  } : { icon: { url: "/pilot-icon.svg", type: "image/svg+xml" }, shortcut: "/pilot-icon.svg" },
};
