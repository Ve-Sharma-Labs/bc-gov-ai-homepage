"use client";

import { Check, ClipboardList, ExternalLink } from "lucide-react";
import { Checkbox } from "react-aria-components";
import { useId } from "react";
import type { Journey, Source } from "@/lib/contract";
import { sourceDomain } from "@/lib/links";
import { OfficialLink } from "./official-link";
import { SourceReferences } from "./sources";

export function TaskPanel({ journey, sources, checked, onCheck, sourcePrefix = "guide-source-", disabled = false }: {
  journey: Journey;
  sources: Source[];
  checked: Set<string>;
  onCheck: (id: string, selected: boolean) => void;
  sourcePrefix?: string;
  disabled?: boolean;
}) {
  const headingId = useId();
  const completed = journey.steps.filter((step) => checked.has(`${journey.id}:${step.id}`)).length;
  return (
    <aside className="task-panel" aria-labelledby={headingId}>
      <div className="task-panel-heading">
        <ClipboardList size={22} strokeWidth={1.6} aria-hidden="true" />
        <div><h2 id={headingId}>Your preparation plan</h2><p>{completed} of {journey.steps.length} steps reviewed</p></div>
      </div>
      <p className="task-intro">Use this checklist to get ready. Checking a step does not complete a government service.</p>
      <ol className="checklist">
        {journey.steps.map((step) => {
          const key = `${journey.id}:${step.id}`;
          return (
            <li key={step.id} className={checked.has(key) ? "step-reviewed" : ""}>
              <Checkbox className="task-checkbox" isSelected={checked.has(key)} isDisabled={disabled} onChange={(selected) => onCheck(key, selected)}>
                <span className="checkbox-box" aria-hidden="true"><Check size={14} strokeWidth={2.5} /></span>
                <span>{step.title}</span>
              </Checkbox>
              <div className="step-description">
                <p>{step.description}</p>
                <SourceReferences ids={step.sourceIds} sources={sources} prefix={sourcePrefix} />
              </div>
            </li>
          );
        })}
      </ol>
      <div className="handoffs">
        <h3><ExternalLink size={17} aria-hidden="true" />Continue with the official service</h3>
        <p>You’ll leave this pilot to take the next step. Nothing has been booked, renewed or submitted here.</p>
        {journey.handoffs.map((handoff) => (
          <div className="handoff" key={`${handoff.url}-${handoff.label}`}>
            <span className="handoff-domain">{sourceDomain(handoff.url)}</span>
            <OfficialLink className="handoff-link" href={handoff.url}>{handoff.label}</OfficialLink>
            <p>{handoff.description}</p>
            <SourceReferences ids={handoff.sourceIds} sources={sources} prefix={sourcePrefix} />
          </div>
        ))}
      </div>
      <p className="local-progress">Checklist progress stays in this tab while you explore, and clears when you start over or reload.</p>
    </aside>
  );
}
