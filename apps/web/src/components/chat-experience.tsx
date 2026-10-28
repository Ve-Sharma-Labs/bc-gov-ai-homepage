"use client";

import Link from "next/link";
import { ArrowLeft, ArrowRight, Info, RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAssistant } from "./assistant-provider";
import { Conversation } from "./conversation";
import { ResetDialog } from "./reset-dialog";
import { Button } from "./ui/button";

export function ChatExperience() {
  const assistant = useAssistant();
  const router = useRouter();
  const hasMessages = assistant.state.messages.length > 0;
  const allowanceExhausted = assistant.state.errorCode === "BUDGET_EXHAUSTED";
  const resetTime = allowanceExhausted && assistant.state.retryAt
    ? new Intl.DateTimeFormat(undefined, {
      weekday: "short",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(new Date(assistant.state.retryAt))
    : null;
  const reset = () => {
    assistant.reset();
    router.push("/");
  };
  const recovery = assistant.state.error && <div className="chat-recovery" role="alert">
    <div className="chat-recovery-message"><Info size={20} aria-hidden="true" /><p>{assistant.state.error}</p></div>
    <p>{allowanceExhausted
      ? `Model answers will be available again after ${resetTime ?? "the next daily reset"}. Your question has been kept.`
      : "We won't automatically resend your question."}</p>
    <div className="chat-recovery-actions">
      {!allowanceExhausted && <Button variant="outline" disabled={assistant.busy || !assistant.draft.trim()} onClick={() => { void assistant.submit(); }}><RotateCcw size={15} aria-hidden="true" />Try again</Button>}
      <Link href="/#journeys">Use a guided plan <ArrowRight size={16} aria-hidden="true" /></Link>
      {allowanceExhausted && <Link href="/services">Browse official services <ArrowRight size={16} aria-hidden="true" /></Link>}
    </div>
  </div>;
  return <section className={`chat-page${hasMessages ? "" : " chat-empty"}`} aria-labelledby="chat-heading">
    <div className="chat-toolbar">
      <Link href="/"><ArrowLeft size={16} aria-hidden="true" />Home</Link>
      {hasMessages && <ResetDialog onReset={reset} />}
    </div>
    <h1 id="chat-heading" className={hasMessages ? "sr-only" : ""}>{hasMessages ? "Conversation with the BC service assistant" : "How can we help?"}</h1>
    {!hasMessages && <div className="chat-empty-copy">
      <p>Ask about B.C. government information and services. Start with your question, or choose an optional guided pathway.</p>
      <p>Keep names, ID numbers and personal details out of your question.</p>
      <Link href="/#journeys">Explore guided plans <ArrowRight size={16} aria-hidden="true" /></Link>
    </div>}
    {hasMessages
      ? <Conversation state={assistant.state} catalog={assistant.catalog}>{recovery}</Conversation>
      : recovery}
  </section>;
}
