"use client";

import { useState, type FormEvent } from "react";
import type { ConversationSummary } from "@/lib/contract";
import { retainComposerFocus } from "@/lib/utils";
import { useAssistant } from "./assistant-provider";
import { CitizenContextControl } from "./citizen-context";
import { Button } from "./ui/button";
import { SafeMarkdown } from "./conversation";
import { ChatArtifacts } from "./chat-artifacts";
import { ComposerScope } from "./composer-scope";

export const AI_PROCESSING_NOTICE = "Your messages are processed by AI in Azure. No ID numbers, credentials, documents, or medical histories.";

export function ConversationNotice() {
  const assistant = useAssistant();
  if ((!assistant.capabilities.conversationAvailable && !assistant.state.conversation)
    || assistant.contextActive || assistant.selectedId) return null;
  return <div className="ai-conversation-notice" id="ai-processing-notice">
    <p>Sharing is optional and applies only to this conversation. Removing details stops future use; it cannot undo earlier AI processing.</p>
    <label>
      <input type="checkbox" checked={assistant.conversationSharing} disabled={assistant.busy}
        onChange={(event) => { void assistant.setConversationSharing(event.target.checked); }} />
      <span>Use personal details I choose to share for this conversation <span className="muted">(optional)</span></span>
    </label>
    {assistant.conversationControlError && <div role="alert" className="conversation-control-error">
      <p>{assistant.conversationControlError}</p>
      <Button variant="ghost" disabled={assistant.busy} onClick={() => {
        void assistant.retryConversationControl();
      }}>Retry change</Button>
      <Button variant="ghost" disabled={assistant.busy} onClick={() => {
        void assistant.refreshConversation();
      }}>Refresh context</Button>
    </div>}
  </div>;
}

function PreparationTask() {
  const assistant = useAssistant();
  const snapshot = assistant.state.task;
  const task = snapshot?.task;
  if (!task || !snapshot) return null;
  const guide = Object.values(assistant.state.artifacts).flat().reverse()
    .find((artifact) => artifact.kind === "preparation" && artifact.id === `task-${task.id}`);
  const busy = assistant.busy;
  return <section className="preparation-task" aria-label="Current preparation step">
    <div className="task-current-guidance"><SafeMarkdown>{snapshot.guidance}</SafeMarkdown></div>
    <p className="task-progress-label">{task.reviewedStepIds.length} of {task.stepIds.length} preparation steps reviewed by you</p>
    <div className="discovery-actions">
      {task.phase === "preparing" && task.waitingFor === "readiness" && <Button
        variant="outline" disabled={busy} onMouseDown={retainComposerFocus}
        onClick={() => { void assistant.taskControl("review"); }}>I have this ready</Button>}
      <Button variant="ghost" disabled={busy} onMouseDown={retainComposerFocus} onClick={() => {
        void assistant.submit({ prompt: "Help me with this step.", conversationAction: "respond" });
      }}>Help with this step</Button>
      {task.phase === "preparing" && <Button variant="ghost" disabled={busy}
        onMouseDown={retainComposerFocus} onClick={() => { void assistant.taskControl("skip"); }}>Skip for now</Button>}
      <Button variant="ghost" disabled={busy || task.activeStepId === task.stepIds[0]}
        onMouseDown={retainComposerFocus} onClick={() => { void assistant.taskControl("back"); }}>Previous step</Button>
    </div>
    {guide && <details className="full-preparation-guide" open={task.lastAction === "full-guide" ? true : undefined}>
      <summary onMouseDown={retainComposerFocus}>Full preparation guide</summary>
      <ChatArtifacts artifacts={[guide]} />
    </details>}
  </section>;
}

function ContextFact({ fact }: { fact: ConversationSummary["facts"][number] }) {
  const assistant = useAssistant();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(fact.displayValue);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (await assistant.submit({
      prompt: value, conversationAction: "correct", conversationFactKey: fact.key,
    })) setEditing(false);
  };
  return <div className="discovery-fact">
    <dt>{fact.label}{fact.subject === "someone-else" ? " (for someone else)" : ""}</dt>
    <dd>{editing ? <form className="discovery-edit" onSubmit={save}>
      <label htmlFor={`ai-fact-${fact.key}`}>Change {fact.label.toLowerCase()}</label>
      <input id={`ai-fact-${fact.key}`} value={value} onChange={(event) => setValue(event.target.value)}
        autoFocus maxLength={100} disabled={assistant.busy} />
      <div className="discovery-actions">
        <Button type="submit" variant="outline" disabled={assistant.busy || !value.trim()}>Save change</Button>
        <Button type="button" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
      </div>
    </form> : <>
      <span>{fact.displayValue}</span>
      <span className="discovery-provenance">{fact.status === "provided" ? "You told me" : "Not assumed"}</span>
      <div className="discovery-fact-actions">
        <Button variant="ghost" disabled={assistant.busy} onMouseDown={retainComposerFocus}
          aria-label={`Change ${fact.label.toLowerCase()}`} onClick={() => setEditing(true)}>Change</Button>
        {fact.status !== "declined" && <Button variant="ghost" disabled={assistant.busy}
          onMouseDown={retainComposerFocus} aria-label={`Remove ${fact.label.toLowerCase()}`}
          onClick={() => { void assistant.submit({
            prompt: `Stop using ${fact.label.toLowerCase()}.`,
            conversationAction: "remove", conversationFactKey: fact.key,
          }); }}>Remove</Button>}
      </div>
    </>}</dd>
  </div>;
}

export function AiConversationContext() {
  const assistant = useAssistant();
  const summary = assistant.state.conversation;
  if (!summary || assistant.contextActive || assistant.selectedId) return null;
  const question = summary.question;
  return <section className="ai-conversation-context" aria-label="Your conversation context">
    <PreparationTask />
    {question && <p className="discovery-reason">{question.reason} You can also type &quot;not sure&quot; or &quot;skip&quot; in chat.</p>}
    {(summary.goal !== "unknown" || summary.facts.length > 0) && <details className="ai-context-summary">
      <summary onMouseDown={retainComposerFocus}>What I understand</summary>
      <p className="discovery-goal">{summary.goalLabel}</p>
      <p className="discovery-privacy">For this page only. You can correct or remove these details. Removing a detail stops future use; it cannot undo earlier AI processing.</p>
      {!!summary.facts.length && <dl className="discovery-facts">
        {summary.facts.map((fact) => <ContextFact key={`${fact.key}-${fact.value}-${fact.status}`} fact={fact} />)}
      </dl>}
    </details>}
  </section>;
}

export function ConversationDetailsContent() {
  const assistant = useAssistant();
  const demo = assistant.state.conversation?.suggestedDemoId;
  const currentJourney = assistant.state.conversation?.journeyId;
  const guides = currentJourney && !assistant.contextActive && !assistant.selectedId
    ? Object.values(assistant.state.artifacts).reverse().find((artifacts) => artifacts.some((artifact) =>
      artifact.kind === "preparation" && !artifact.id.startsWith("task-") && artifact.journey.id === currentJourney,
    ))?.filter((artifact) => artifact.kind === "preparation")
    : undefined;
  return <div className="conversation-details-content">
    <p className="discovery-privacy">{AI_PROCESSING_NOTICE}</p>
    {assistant.capabilities.localEvidenceEvaluation && <p className="discovery-privacy">
      <strong>Local evaluation only.</strong> Not for public or commercial use.
    </p>}
    <AiConversationContext />
    {!assistant.state.task?.task && guides && <ChatArtifacts artifacts={guides} />}
    <ConversationNotice />
    <div className="conversation-detail-options">
      <ComposerScope />
      {demo && assistant.capabilities.syntheticContextAvailable && <p className="discovery-demo-note">
        A separate fictional scenario can show how consented records might help. It does not describe you.
      </p>}
      <CitizenContextControl recommendedPersonaId={demo ?? undefined} />
    </div>
  </div>;
}
