import type { Metadata } from "next";
import { ChatExperience } from "@/components/chat-experience";

export const metadata: Metadata = { title: "Chat" };

export default function ChatPage() {
  return <ChatExperience />;
}
