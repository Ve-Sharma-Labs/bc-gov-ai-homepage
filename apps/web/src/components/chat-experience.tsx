"use client";

import Link from "next/link";
import { useId, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Info, RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { retainComposerFocus } from "@/lib/utils";
import { useAssistant } from "./assistant-provider";
import { Conversation } from "./conversation";
import { DiscoveryContext } from "./discovery-context";
import { ConversationDetailsContent } from "./ai-conversation";
import { ConversationStarters } from "./conversation-starters";
import { ResetDialog } from "./reset-dialog";
import { Button } from "./ui/button";

export function ChatExperience() {
  const assistant = useAssistant();
  const router = useRouter();
  const hasMessages = assistant.state.messages.length > 0;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const detailsId = useId();
  const examplesId = useId();
  const detailsTrigger = useRef<HTMLButtonElement>(null);
  const textFirst = assistant.capabilities.conversationAvailable && !assistant.contextActive && !assistant.selectedId;
  const closeDetails = () => {
    setDetailsOpen(false);
    detailsTrigger.current?.focus();
  };
  const allowanceExhausted = assistant.state.errorCode === "BUDGET_EXHAUSTED";
  const contextChanged = ["DISCOVERY_CHANGED", "CONVERSATION_CHANGED", "TASK_CHANGED"].includes(assistant.state.errorCode ?? "");
  const contextExpired = ["DISCOVERY_EXPIRED", "CONVERSATION_EXPIRED"].includes(assistant.state.errorCode ?? "");
  const purposeChanged = assistant.state.errorCode === "CONTEXT_PURPOSE_CHANGED";
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
      {contextChanged && <Button variant="outline" disabled={assistant.busy} onMouseDown={retainComposerFocus} onClick={() => {
        void (assistant.state.conversationRevision !== null ? assistant.refreshConversation() : assistant.refreshDiscovery());
      }}>Refresh conversation context</Button>}
      {contextExpired && <ResetDialog onReset={reset} />}
      {purposeChanged && <Button variant="outline" disabled={assistant.busy} onMouseDown={retainComposerFocus} onClick={() => { void assistant.clearContext(); }}>Continue anonymously</Button>}
      {!allowanceExhausted && !contextChanged && !contextExpired && !purposeChanged && <Button variant="outline" disabled={assistant.busy || !assistant.draft.trim()} onMouseDown={retainComposerFocus} onClick={() => { void assistant.submit(); }}><RotateCcw size={15} aria-hidden="true" />Try again</Button>}
      <Link href="/#journeys">Use a guided plan <ArrowRight size={16} aria-hidden="true" /></Link>
      {allowanceExhausted && <Link href="/services">Browse official services <ArrowRight size={16} aria-hidden="true" /></Link>}
    </div>
  </div>;
  return <section className={`chat-page${hasMessages ? "" : " chat-empty"}`} aria-labelledby="chat-heading">
    <div className="chat-toolbar">
      <Link href="/"><ArrowLeft size={16} aria-hidden="true" />Home</Link>
      <div className="chat-toolbar-actions">
        {hasMessages && !assistant.contextActive && !assistant.selectedId && <Button variant="ghost"
          aria-expanded={examplesOpen} aria-controls={examplesId} onMouseDown={retainComposerFocus}
          onClick={() => setExamplesOpen(!examplesOpen)}>Examples</Button>}
        {assistant.capabilities.conversationAvailable && <Button variant="ghost" ref={detailsTrigger}
          aria-expanded={detailsOpen} aria-controls={detailsId} onMouseDown={retainComposerFocus}
          onClick={() => setDetailsOpen(!detailsOpen)}>Details</Button>}
        {hasMessages && <ResetDialog onReset={reset} />}
      </div>
    </div>
    {assistant.capabilities.conversationAvailable && <section id={detailsId} hidden={!detailsOpen}
      className="conversation-details" aria-label="Conversation details" onKeyDown={(event) => {
        if (event.key === "Escape" && !event.defaultPrevented
          && event.target instanceof Node && event.currentTarget.contains(event.target)) {
          event.stopPropagation();
          closeDetails();
        }
      }}>
      <div className="conversation-details-heading">
        <h2>Conversation details</h2>
        <Button variant="ghost" onMouseDown={retainComposerFocus} onClick={closeDetails}>Close details</Button>
      </div>
      <ConversationDetailsContent />
    </section>}
    {hasMessages && <div id={examplesId} hidden={!examplesOpen}>
      <ConversationStarters onPrepared={() => setExamplesOpen(false)} />
    </div>}
    <h1 id="chat-heading" className={hasMessages ? "sr-only" : ""}>{hasMessages ? "Conversation with the BC service assistant" : "How can we help?"}</h1>
    {!hasMessages && <div className="chat-empty-copy">
      <p>Tell me what you need. We can work through the next step together.</p>
    </div>}
    {!hasMessages && <ConversationStarters />}
    {hasMessages
      ? <Conversation state={assistant.state} catalog={assistant.catalog} textFirst={textFirst} hasDiscoveryContext={
        !!assistant.state.discovery?.goalId && !assistant.contextActive && !assistant.selectedId
      }>
        {!assistant.capabilities.conversationAvailable && <DiscoveryContext />}
        {assistant.notice && <p className="chat-context-notice"
          role={assistant.state.announcement === assistant.notice ? undefined : "status"}>{assistant.notice}</p>}
        {recovery}
      </Conversation>
      : recovery}
  </section>;
}
