import type { Metadata } from "next";
import { connection } from "next/server";
import { Footer, Header } from "@/components/chrome";
import { AssistantProvider, type AssistantProviderProps } from "@/components/assistant-provider";
import { ComposerDock } from "@/components/composer-dock";
import { MotionProvider } from "@/components/motion-provider";
import { themeBootstrap } from "@/lib/theme";
import { siteMetadata } from "./site-metadata";
import { fontClasses } from "@/generated/fonts";
import { jurisdiction, presentation } from "@/lib/jurisdiction";
import "./globals.css";
import "../generated/brand.css";

export const metadata: Metadata = siteMetadata;

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  await connection();
  const conversationBootstrap: AssistantProviderProps["conversationBootstrap"] =
    jurisdiction.id === "bc" && process.env.AI_CONVERSATION_ENABLED === "true"
      && process.env.GROUNDED_CONVERSATION_ENABLED !== "true"
      && process.env.LOCAL_EVIDENCE_EVALUATION_ENABLED !== "true"
      ? { version: 5, taskAssistance: process.env.TASK_ASSISTANCE_ENABLED === "true" }
      : undefined;
  return (
    <html lang={jurisdiction.locale} data-jurisdiction={jurisdiction.id} className={fontClasses} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeBootstrap }} /></head>
      <body>
        <a className="skip-link" href="#main-content">Skip to main content</a>
        <MotionProvider><AssistantProvider conversationBootstrap={conversationBootstrap}>
          <Header />
          {presentation.pilotNotice && <p className="pilot-notice">{presentation.pilotNotice}</p>}
          <main id="main-content">{children}</main>
          <Footer />
          <ComposerDock />
        </AssistantProvider></MotionProvider>
      </body>
    </html>
  );
}
