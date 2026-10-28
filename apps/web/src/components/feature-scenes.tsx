"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { ArrowRight, ArrowUpRight, Check, CheckCheck, FileText, MapPin, Pause, Play, ShieldCheck } from "lucide-react";
import { useScenePlayback } from "@/lib/use-scene-playback";
import { useAssistant } from "./assistant-provider";
import { Button } from "./ui/button";
import { BlurFade } from "./ui/blur-fade";

type SceneKind = "sources" | "checklist" | "locations" | "handoff";
const copy: Record<SceneKind, { title: string; description: string }> = {
  sources: { title: "Straight from the source.", description: "Find information from official B.C. services, with sources you can open and check for yourself." },
  checklist: { title: "A plan, not another search.", description: "Break your next step into a useful checklist. Know what to read, what to prepare, and where to go." },
  locations: { title: "The right place for your next step.", description: "Match the service you need to published office information. See what is offered before you travel." },
  handoff: { title: "You're in control.", description: "When you're ready, continue with the official service. Nothing is booked, paid or submitted by this pilot." },
};

function SourceArtwork({ step }: { step: number }) {
  const { catalog } = useAssistant();
  const sources = catalog?.sources.filter((source) => ["icbc", "bc-housing", "service-bc"].includes(source.id)) ?? [];
  return <div className="source-artwork">
    <div className="evidence-orbit" />
    <div className="evidence-orbit orbit-two" />
    <div className="source-emblem"><ShieldCheck size={46} strokeWidth={1.3} /></div>
    <motion.div className="illustrated-source-stack" animate={{ y: step % 2 ? -8 : 0, rotate: step % 2 ? 1 : -2 }} transition={{ duration: 0.8 }}>
      <div className="illustrated-label"><FileText size={15} /> Official sources</div>
      {sources.length ? sources.map((source, index) => <div key={source.id} className="illustrated-source"><span>{index + 1}</span><div><strong>{source.publisher}</strong><small>{new URL(source.url).hostname.replace("www.", "")}</small></div><ArrowUpRight size={15} /></div>) : <p>Official source details appear when the catalogue is available.</p>}
    </motion.div>
  </div>;
}

function ChecklistArtwork({ step }: { step: number }) {
  const { catalog } = useAssistant();
  const journey = catalog?.journeys.find((item) => item.id === "licence-renewal");
  return <div className="checklist-artwork">
    <div className="illustrated-question">I need to renew my licence.</div>
    <motion.div className="illustrated-plan" animate={{ y: step === 0 ? 7 : 0 }} transition={{ type: "spring", bounce: 0.1 }}>
      <div className="illustrated-label"><CheckCheck size={18} />Your next steps</div>
      <h4>Let&apos;s get you ready.</h4>
      {journey ? journey.steps.slice(0, 3).map((item, index) => <div className="illustrated-step" key={item.id}><span className={step > index ? "illustrated-check is-checked" : "illustrated-check"}>{step > index ? <Check size={14} /> : index + 1}</span><span>{item.title}</span></div>) : <p>Preparation steps load from the source-backed catalogue.</p>}
      <span className="illustration-disclaimer">Illustration of a guided plan</span>
    </motion.div>
  </div>;
}

function LocationArtwork({ step }: { step: number }) {
  const { catalog } = useAssistant();
  const offices = catalog?.locations.filter((location) => ["Nanaimo", "Kelowna"].includes(location.municipality)) ?? [];
  return <div className="location-artwork">
    <svg className="map-contours" viewBox="0 0 688 453" preserveAspectRatio="xMidYMid slice"><path d="M-80 95Q85 220 210 78T470 155T780 52M-80 175Q85 300 210 158T470 235T780 132M-80 255Q85 380 210 238T470 315T780 212M-80 335Q85 460 210 318T470 395T780 292" /></svg>
    <div className="map-dot dot-one"><MapPin size={25} /></div><div className="map-dot dot-two"><MapPin size={20} /></div>
    <motion.div className="illustrated-offices" animate={{ y: step % 2 ? 0 : 5 }} transition={{ duration: 0.65 }}>
      <div className="illustrated-label"><MapPin size={16} />ICBC driver licensing</div>
      {offices.map((office) => {
        const offers = office.services.includes("icbc-licensing") && !office.excludedServices.includes("icbc-licensing");
        return <div className="illustrated-office" key={office.id}><strong>{office.municipality}</strong><span className={offers ? "office-offers" : ""}>{offers ? "Listed at this office" : "Not listed at this office"}{offers && <Check size={14} />}</span></div>;
      })}
      {!offices.length && <p>Check which offices offer your service.</p>}
      <span className="illustration-disclaimer">Published information, not live availability</span>
    </motion.div>
  </div>;
}

function HandoffArtwork({ step }: { step: number }) {
  return <div className="handoff-artwork">
    <motion.div className="handoff-letter" animate={{ rotate: step % 2 ? -5 : -8 }} transition={{ duration: 0.8 }}><span className="letter-sun" /><span>Your next step<br />starts with you.</span><div className="letter-rule" /><div className="letter-rule short" /></motion.div>
    <motion.div className="illustrated-browser" animate={{ y: step % 2 ? -4 : 4 }} transition={{ duration: 0.8 }}>
      <div className="browser-address"><span /><span /><span /><strong>icbc.com</strong><ShieldCheck size={13} /></div>
      <div className="browser-content"><ArrowUpRight size={35} strokeWidth={1.3} /><h4>Ready when you are.</h4><p>Continue on the official website.</p><div className="illustrated-action">Go to ICBC <ArrowRight size={16} /></div><span className="illustration-disclaimer">Handoff illustration. Nothing submitted.</span></div>
    </motion.div>
  </div>;
}

function FeatureScene({ kind }: { kind: SceneKind }) {
  const playback = useScenePlayback();
  const step = playback.reduced ? 3 : playback.step;
  return <figure className={`feature-scene scene-${kind}`}>
    <div className="scene-frame" ref={playback.ref} data-playing={playback.playing}>
      <div className="scene-art" aria-hidden="true">
        {kind === "sources" && <SourceArtwork step={step} />}
        {kind === "checklist" && <ChecklistArtwork step={step} />}
        {kind === "locations" && <LocationArtwork step={step} />}
        {kind === "handoff" && <HandoffArtwork step={step} />}
      </div>
      <Button variant="ghost" size="icon" className="scene-pause" disabled={!!playback.reduced} aria-label={`${playback.paused ? "Play" : "Pause"} ${kind} illustration`} onClick={() => playback.setPaused(!playback.paused)}>{playback.paused || playback.reduced ? <Play size={16} /> : <Pause size={16} />}</Button>
    </div>
    <figcaption><h3>{copy[kind].title}</h3>{" "}<p>{copy[kind].description}</p></figcaption>
  </figure>;
}

export function FeatureScenes({ compact = false }: { compact?: boolean }) {
  const kinds: SceneKind[] = compact ? ["sources", "checklist"] : ["sources", "checklist", "locations", "handoff"];
  return <div className="feature-grid">{kinds.map((kind) => <BlurFade key={kind}><FeatureScene kind={kind} /></BlurFade>)}</div>;
}

export function HowItWorksInvitation() {
  return <section className="editorial-invitation site-container">
    <h2>Government information.<br />A little more human.</h2>
    <p>Less time finding your way. More time getting on with your day.</p>
    <Link href="/how-it-works" className="pill-link">See how it works <ArrowRight size={18} /></Link>
    <FeatureScenes compact />
  </section>;
}
