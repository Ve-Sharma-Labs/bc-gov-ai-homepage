"use client";

import { useState, type FormEvent } from "react";
import type { DiscoveryFact } from "@/lib/contract";
import { retainComposerFocus } from "@/lib/utils";
import { useAssistant } from "./assistant-provider";
import { CitizenContextControl } from "./citizen-context";
import { Button } from "./ui/button";

function EditableFact({ fact }: { fact: DiscoveryFact }) {
  const assistant = useAssistant();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(fact.value ?? "");
  const display = fact.status === "provided" ? fact.value
    : fact.status === "declined" ? "Not shared"
      : fact.status === "disputed" ? "Needs confirmation" : "Not sure";
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (await assistant.submit({ prompt: value, action: "correct", factKey: fact.key })) {
      setEditing(false);
    }
  };
  return <div className="discovery-fact">
    <dt>{fact.label}</dt>
    <dd>
      {editing ? <form onSubmit={save} className="discovery-edit">
        <label htmlFor={`discovery-${fact.key}`}>Change {fact.label.toLowerCase()}</label>
        <input
          id={`discovery-${fact.key}`}
          value={value}
          maxLength={100}
          autoFocus
          disabled={assistant.busy}
          onChange={(event) => setValue(event.target.value)}
          aria-describedby="discovery-privacy"
        />
        <div className="discovery-actions">
          <Button type="submit" variant="outline" disabled={assistant.busy || !value.trim()}>Save change</Button>
          <Button type="button" variant="ghost" disabled={assistant.busy} onClick={() => setEditing(false)}>Cancel</Button>
        </div>
      </form> : <>
        <span>{display}</span>
        <span className="discovery-provenance">{fact.status === "provided" ? "You told me" : "Not assumed"}</span>
        <div className="discovery-fact-actions">
          <Button variant="ghost" disabled={assistant.busy} onMouseDown={retainComposerFocus} aria-label={`Change ${fact.label.toLowerCase()}`} onClick={() => {
            setValue(fact.value ?? "");
            setEditing(true);
          }}>Change</Button>
          {fact.status !== "declined" && <Button
            variant="ghost"
            disabled={assistant.busy}
            onMouseDown={retainComposerFocus}
            aria-label={`Remove ${fact.label.toLowerCase()}`}
            onClick={() => { void assistant.submit({
              prompt: `Please stop using ${fact.label.toLowerCase()}.`,
              action: "remove", factKey: fact.key,
            }); }}
          >Remove</Button>}
        </div>
      </>}
    </dd>
  </div>;
}

export function DiscoveryContext() {
  const assistant = useAssistant();
  const summary = assistant.state.discovery;
  if (!summary?.goalId || assistant.contextActive || assistant.selectedId) return null;
  const question = summary.question;
  const blocked = assistant.busy || !!assistant.state.error;
  return <section className="discovery-context" aria-labelledby="discovery-heading" data-conversation-latest>
    <div className="discovery-heading">
      <h2 id="discovery-heading">What I understand</h2>
      <span>For this conversation only</span>
    </div>
    <p className="discovery-goal">{summary.goalLabel}{summary.about === "someone-else" ? " - for someone else" : ""}</p>
    <p className="discovery-privacy" id="discovery-privacy">
      Only share what you are comfortable with. No names, ID numbers, documents, or health histories.
      You can change or remove these details.
    </p>
    {!!summary.facts.length && <dl className="discovery-facts">
      {summary.facts.map((fact) => <EditableFact key={`${fact.key}-${fact.value}-${fact.status}`} fact={fact} />)}
    </dl>}
    {question && <div className="discovery-question">
      <fieldset disabled={blocked}>
        <legend className="sr-only">{question.text}</legend>
        <div className="discovery-choices">
          {question.choices.map((choice) => <Button key={choice} variant="outline" onMouseDown={retainComposerFocus} onClick={() => {
            void assistant.submit({ prompt: choice, action: "respond" });
          }}>{choice}</Button>)}
        </div>
        <div className="discovery-actions">
          <Button variant="ghost" onMouseDown={retainComposerFocus} onClick={() => { void assistant.submit({ prompt: "Skip this question.", action: "skip" }); }}>Skip this question</Button>
          <Button variant="ghost" onMouseDown={retainComposerFocus} onClick={() => { void assistant.submit({ prompt: "Keep it general.", action: "general" }); }}>Give me general guidance</Button>
        </div>
      </fieldset>
      <details className="discovery-reason"><summary>Why I&apos;m asking</summary><p>{question.reason}</p></details>
      <p className="discovery-count">Question {summary.questionCount} of at most 3 before a starting plan.</p>
    </div>}
    {summary.phase === "plan" && <div className="discovery-recommendations">
      {summary.suggestions.map((suggestion) => {
        const journey = assistant.catalog?.journeys.find((item) => item.id === suggestion.journeyId);
        return journey ? <div className="discovery-suggestion" key={journey.id}>
          <Button variant="outline" disabled={blocked} onMouseDown={retainComposerFocus} onClick={() => assistant.selectJourney(journey)}>
            Continue with {journey.title.toLowerCase()}
          </Button>
          <p>{suggestion.reason}</p>
        </div> : null;
      })}
      <div className="discovery-actions">
        <Button variant="ghost" disabled={blocked} onMouseDown={retainComposerFocus} onClick={() => {
          void assistant.submit({ prompt: "Let's explore another option.", action: "explore" });
        }}>Explore another option</Button>
        <Button variant="ghost" disabled={blocked} onMouseDown={retainComposerFocus} onClick={() => {
          void assistant.submit({ prompt: "Keep it general.", action: "general" });
        }}>Keep it general</Button>
      </div>
      {summary.suggestedDemoId && assistant.capabilities.syntheticContextAvailable && <>
        <p className="discovery-demo-note">Want to see how shared context could help? You can try a separate fictional scenario. It does not describe you or access your records.</p>
        <CitizenContextControl recommendedPersonaId={summary.suggestedDemoId} />
      </>}
    </div>}
  </section>;
}
