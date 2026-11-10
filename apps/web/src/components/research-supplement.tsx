"use client";

import { useState, type ReactNode } from "react";
import { researchGeographySchema, type ResearchGeography, type ResearchOffer } from "@/lib/research-schema";
import { retainComposerFocus } from "@/lib/utils";
import { useAssistant } from "./assistant-provider";
import { OfficialLink } from "./official-link";
import { Button } from "./ui/button";

export function ResearchSupplement({ offer, renderText }: {
  offer: ResearchOffer; renderText: (text: string) => ReactNode;
}) {
  const assistant = useAssistant();
  const [geography, setGeography] = useState<ResearchGeography>("british-columbia");
  const [controlError, setControlError] = useState("");
  const capabilities = assistant.capabilities.research;
  const actions = offer.actions.filter((action) => action === "corpus-explore"
    ? capabilities?.foundryIq.available : capabilities?.webIq.available);
  const entries = offer.actions.flatMap((action) => {
    const entry = assistant.research.items[`${offer.parentMessageId}:${action}`];
    return entry ? [entry] : [];
  });
  const active = Object.values(assistant.research.items).some((entry) =>
    entry.phase === "retrieving" || entry.phase === "summarizing");
  if ((!actions.length && !entries.length) || assistant.contextActive) return null;
  return <aside className="research-supplement" aria-label="Optional research">
    {!!actions.length && <details>
      <summary onMouseDown={retainComposerFocus}>Optional research</summary>
      <p className="muted">Your answer stays unchanged. Only these public topics and the selected region are used, not your conversation or personal context.</p>
      <p>{offer.topics.map((topic) => assistant.catalog?.journeys.find((journey) => journey.id === topic)?.title
        ?? topic.replaceAll("-", " ")).join("; ")}</p>
      <label className="research-region">Public region
        <select value={geography} onChange={(event) => {
          const parsed = researchGeographySchema.safeParse(event.target.value);
          if (parsed.success) setGeography(parsed.data);
        }}>
          {researchGeographySchema.options.map((value) => <option key={value} value={value}>
            {value === "british-columbia" ? "British Columbia" : value.split("-").map((word) => word[0].toUpperCase() + word.slice(1)).join(" ")}
          </option>)}
        </select>
      </label>
      <p className="muted">Foundry IQ uses preview query planning on indexed sources. Web IQ checks approved public pages; it does not guarantee a fresh fetch. Both may take longer than a standard answer.</p>
      {actions.includes("web-check") && <p className="muted">Microsoft Web IQ may log the fixed public-topic query under its own privacy terms. Your conversation and personal context are not sent.</p>}
      <div className="research-actions">
        {actions.map((action) => <Button key={action} variant="outline"
          disabled={assistant.busy || active}
          onMouseDown={retainComposerFocus}
          onClick={() => { setControlError(""); void assistant.research.start(offer, action, geography); }}>
          {action === "corpus-explore" ? "Explore across sources (Preview)" : "Check current official information"}
        </Button>)}
      </div>
    </details>}
    {entries.map((entry) => <section key={entry.action} className="research-result"
      aria-label={entry.action === "web-check" ? "Public-web research supplement" : "Indexed research supplement"}>
      <h3>{entry.action === "web-check" ? "Public-web research" : "Across indexed sources (Preview)"}</h3>
      {(entry.phase === "retrieving" || entry.phase === "summarizing") && <div role="status">
        <p>{entry.phase === "retrieving" ? "Checking the selected sources..." : "Preparing a sourced supplement..."}</p>
        <Button variant="ghost" onClick={() => {
          void assistant.research.stop()?.catch(() => setControlError("Research cancellation could not be confirmed."));
        }}>Stop research</Button>
      </div>}
      {entry.error && <p className="answer-warning" role="status">{entry.error}</p>}
      {entry.phase === "stopped" && <p role="status">Research stopped. Your original answer is unchanged.</p>}
      {entry.phase === "complete" && entry.result && <>
        <p className="muted">{entry.result.notice}</p>
        {renderText(entry.result.text)}
        <ul className="research-sources">
          {entry.result.citations.map((citation, index) => {
            const source = citation.kind === "indexed" ? citation.reference : citation;
            return <li key={`${source.url}-${index}`}>
              <OfficialLink href={source.url}>{source.title}</OfficialLink>
              <p className="muted">{source.publisher}</p>
              <p className="muted">Retrieved: <time dateTime={citation.retrievedAt}>{citation.retrievedAt}</time></p>
              {citation.kind === "web"
                ? <p className="muted">Crawled: {citation.crawledAt ?? "Unknown"}. Publisher updated: {citation.publisherUpdatedAt ?? "Unknown"}. Not reviewed indexed evidence.</p>
                : <p className="muted">Indexed source checked: {citation.reference.checkedAt}</p>}
            </li>;
          })}
        </ul>
      </>}
    </section>)}
    {controlError && <p className="answer-warning" role="status">{controlError}</p>}
  </aside>;
}
