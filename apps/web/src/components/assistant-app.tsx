"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { ArrowLeft, ArrowRight, Info } from "lucide-react";
import { useAssistant } from "./assistant-provider";
import { HeroExperience } from "./hero-experience";
import { HowItWorksInvitation } from "./feature-scenes";
import { JourneyCards } from "./journeys";
import { LocationFinder } from "./locations";
import { ResetDialog } from "./reset-dialog";
import { SourceCard } from "./sources";
import { TaskPanel } from "./task-panel";
import { Button } from "./ui/button";
import { formatDate } from "@/lib/links";

export function AssistantApp() {
  const { catalog, capabilities, loading, catalogError, selected, selectedId, selectJourney, checked, setChecked, state, busy, load, reset } = useAssistant();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const workspace = !!selected;
  const aiConfigured = selectedId
    ? capabilities.journeys?.[selectedId] ?? capabilities.aiConfigured
    : capabilities.conversationAvailable ? capabilities.conversationAgentReady
      : capabilities.generalChatConfigured ?? capabilities.aiConfigured;
  useEffect(() => {
    if (workspace) headingRef.current?.focus({ preventScroll: true });
  }, [workspace, selectedId]);
  const sourceIds = new Set(selected ? [...selected.sourceIds, ...selected.steps.flatMap((step) => step.sourceIds), ...selected.handoffs.flatMap((handoff) => handoff.sourceIds)] : []);
  const selectedSources = catalog?.sources.filter((source) => sourceIds.has(source.id)) ?? [];
  const journeys = <section className="journeys-section site-container" id="journeys" aria-labelledby="journeys-heading">
    <div className="section-heading"><div><h2 id="journeys-heading">{workspace ? "Another question, another next step." : "A few good places to start."}</h2><p>Real information. Practical plans. You take it from here.</p></div><Link className="browse-link" href="/services">All services <ArrowRight size={18} aria-hidden="true" /></Link></div>
    {catalog && <JourneyCards journeys={catalog.journeys} onSelect={selectJourney} disabled={busy} />}
    {loading && !catalog && <p className="catalog-loading" role="status">Loading the service catalogue...</p>}
    {catalogError && <div className="catalog-error" role="status"><Info size={20} /><div><p>{catalogError}</p><Button variant="link" onClick={() => { void load(); }}>Try again</Button></div></div>}
    <p className="snapshot-note">{catalog ? `Curated guidance · ${formatDate(catalog.asOf)}` : "Official service links remain available."}<span>Guided plans are not AI-generated.</span></p>
  </section>;
  return <>
    {!workspace ? <>
      <HeroExperience />
      <p className="connection-status">{loading ? "Checking available services..." : aiConfigured ? "AI answers configured" : "Guided plans available · AI answers not connected"}<Link href="/about#how-it-works">About this pilot</Link></p>
      {!!state.messages.length && <p className="connection-status"><Link href="/chat">Return to your conversation <ArrowRight size={16} aria-hidden="true" /></Link></p>}
      <HowItWorksInvitation />
      {journeys}
    </> : <div className="workspace-container site-container">
      <div className="workspace-toolbar"><a href="#journeys"><ArrowLeft size={16} />All guided plans</a><ResetDialog onReset={reset} /></div>
      <div className="workspace-grid">
        <div className="workspace-main">
          <div className="workspace-title"><h1 ref={headingRef} tabIndex={-1}>{selected?.title ?? "Let's work through it."}</h1>{selected && <span className="guided-tag">Guided plan · Not AI-generated</span>}</div>
          {selected && <section className="guided-introduction" aria-label="About this guided plan"><p className="guided-summary">{selected.summary}</p><div className="plan-notice"><Info size={18} /><p>{selected.notice}</p></div></section>}
          {!!state.messages.length && <p className="connection-status"><Link href="/chat">Return to your conversation <ArrowRight size={16} aria-hidden="true" /></Link></p>}
        </div>
        {selected && <TaskPanel journey={selected} sources={selectedSources} checked={checked} onCheck={(key, value) => setChecked((previous) => { const next = new Set(previous); if (value) next.add(key); else next.delete(key); return next; })} />}
        <div className="workspace-followup">
          {selected?.id === "service-bc" && catalog && <LocationFinder catalog={catalog} />}
          <div className="workspace-composer"><div className="composer-anchor" data-composer-anchor /><p className="connection-status">{aiConfigured ? "AI answers configured" : "Guided plans available · AI answers not connected"}</p></div>
        </div>
        {selected && <section className="evidence-section" aria-labelledby="evidence-heading"><h2 id="evidence-heading">The information behind your plan.</h2><p>Open the sources. Check the details. Know your next step.</p><p className="snapshot-note">Curated snapshot · {formatDate(catalog!.asOf)}</p><div className="source-list">{selectedSources.map((source, index) => <SourceCard key={source.id} source={source} prefix="guide-source-" index={index} />)}</div></section>}
      </div>
      {journeys}
    </div>}
  </>;
}
