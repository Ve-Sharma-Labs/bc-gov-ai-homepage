import type { Metadata } from "next";

export const siteUrl = new URL("https://bcassist-xufhsendpx-ddabgxfdera9azbp.b01.azurefd.net/");
export const siteTitle = "BC.Gov";
export const siteDescription = "Find British Columbia government services, understand what you need, and prepare your next steps.";
export const socialImageAlt = "BC.Gov — Government of British Columbia";

export const siteMetadata: Metadata = {
  metadataBase: siteUrl,
  title: { default: siteTitle, template: `%s · ${siteTitle}` },
  description: siteDescription,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    url: "/",
    title: siteTitle,
    description: siteDescription,
    siteName: siteTitle,
    locale: "en_CA",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: socialImageAlt }],
  },
  twitter: {
    card: "summary_large_image",
    title: siteTitle,
    description: siteDescription,
    images: [{ url: "/twitter-image", width: 1200, height: 630, alt: socialImageAlt }],
  },
  robots: { index: false, follow: false },
  icons: {
    icon: { url: "/favicon.ico", type: "image/x-icon", sizes: "16x16 32x32 48x48" },
    shortcut: "/favicon.ico",
    apple: { url: "/apple-touch-icon.png", type: "image/png", sizes: "180x180" },
  },
};
