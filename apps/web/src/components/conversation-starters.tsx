"use client";

import { useId, useState } from "react";
import { retainComposerFocus } from "@/lib/utils";
import { useAssistant } from "./assistant-provider";
import { Button } from "./ui/button";

export const conversationStarters = [
  "I need to renew my drivers license",
  "I need to apply for guardianship",
  "I need to apply for disability",
  "I just lost my job, what do I do?",
] as const;

export function ConversationStarters({ heading, onPrepared }: { heading?: string; onPrepared?: () => void }) {
  const assistant = useAssistant();
  const instructions = useId();
  const [replacement, setReplacement] = useState<string | null>(null);
  if (assistant.contextActive || assistant.selectedId) return null;
  const prepare = (prompt: string) => {
    assistant.setDraft(prompt);
    setReplacement(null);
    onPrepared?.();
    const composer = document.querySelector<HTMLTextAreaElement>("[data-assistant-composer]");
    composer?.focus({ preventScroll: true });
    composer?.scrollIntoView({ block: "nearest", behavior: "instant" });
  };
  return <section className="conversation-starters" aria-label="Example questions">
    {heading && <h2>{heading}</h2>}
    <p id={instructions}>Choose a question, then make it your own before sending.</p>
    <ul>
      {conversationStarters.map((prompt) => <li key={prompt}>
        <Button variant="ghost" disabled={assistant.busy} aria-describedby={instructions}
          onMouseDown={retainComposerFocus} onClick={() => {
            if (assistant.draft.trim() && assistant.draft !== prompt) setReplacement(prompt);
            else prepare(prompt);
          }}>{prompt}</Button>
      </li>)}
    </ul>
    {replacement && <div className="starter-replacement" role="group" aria-label="Replace unsent question">
      <p>You have an unsent question. Replace it with this example?</p>
      <p className="muted">{replacement}</p>
      <div className="discovery-actions">
        <Button variant="outline" disabled={assistant.busy} onMouseDown={retainComposerFocus}
          onClick={() => prepare(replacement)}>Replace draft</Button>
        <Button variant="ghost" onMouseDown={retainComposerFocus}
          onClick={() => setReplacement(null)}>Keep my draft</Button>
      </div>
    </div>}
  </section>;
}
