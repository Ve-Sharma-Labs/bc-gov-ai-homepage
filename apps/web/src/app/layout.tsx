import type { Metadata } from "next";
import localFont from "next/font/local";
import { Footer, Header } from "@/components/chrome";
import { AssistantProvider } from "@/components/assistant-provider";
import { ComposerDock } from "@/components/composer-dock";
import { MotionProvider } from "@/components/motion-provider";
import { themeBootstrap } from "@/lib/theme";
import { siteMetadata } from "./site-metadata";
import "@bcgov/design-tokens/css-prefixed/variables.css";
import "./globals.css";

const bcSans = localFont({
  src: [
    { path: "../../node_modules/@bcgov/bc-sans/fonts/BCSans-Regular.woff2", weight: "400", style: "normal" },
    { path: "../../node_modules/@bcgov/bc-sans/fonts/BCSans-Bold.woff2", weight: "700", style: "normal" },
    { path: "../../node_modules/@bcgov/bc-sans/fonts/BCSans-Italic.woff2", weight: "400", style: "italic" },
  ],
  variable: "--font-bc-sans",
  display: "swap",
  fallback: ["Arial", "sans-serif"],
});

const displaySerif = localFont({
  src: "../../public/fonts/libre-caslon-display.woff2",
  variable: "--font-editorial",
  display: "swap",
  weight: "400",
  fallback: ["Georgia", "serif"],
});

export const metadata: Metadata = siteMetadata;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-CA" className={`${bcSans.variable} ${displaySerif.variable}`} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeBootstrap }} /></head>
      <body>
        <a className="skip-link" href="#main-content">Skip to main content</a>
        <MotionProvider><AssistantProvider>
          <Header />
          <main id="main-content">{children}</main>
          <Footer />
          <ComposerDock />
        </AssistantProvider></MotionProvider>
      </body>
    </html>
  );
}
