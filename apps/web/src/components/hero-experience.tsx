"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Pause, Play, MapPin } from "lucide-react";
import { heroImages } from "@/lib/hero-images";
import { useScenePlayback } from "@/lib/use-scene-playback";
import { useAssistant } from "./assistant-provider";
import { Button } from "./ui/button";
import { ConversationStarters } from "./conversation-starters";
import { jurisdiction, presentation } from "@/lib/jurisdiction";

export function HeroExperience() {
  return heroImages.length ? <PhotographicHero /> : <section className="welcome-hero site-container" aria-labelledby="home-heading">
    <div className="pilot-hero">
      <h1 id="home-heading">Hello, {presentation.greeting}</h1>
      <p>{presentation.pilotNotice}</p>
      <div className="composer-anchor" data-composer-anchor />
      <Link href="/services">Browse official {jurisdiction.shortName} services <ArrowRight size={19} aria-hidden="true" /></Link>
    </div>
    <noscript><p className="no-script-guidance">The interactive assistant needs JavaScript. <Link href="/services">Browse official services instead.</Link></p></noscript>
  </section>;
}

function PhotographicHero() {
  const { catalog, selectJourney, draft, busy } = useAssistant();
  const { ref, step, setStep, paused, setPaused, reduced } = useScenePlayback(6500, heroImages.length);
  const [failedImage, setFailedImage] = useState("");
  const photoRef = useRef<HTMLImageElement>(null);
  const [inputFocused, setInputFocused] = useState(false);
  const journeys = catalog?.journeys ?? [];
  const isSaskatchewan = jurisdiction.id === "sk";
  const slideLabel = isSaskatchewan ? "photograph" : "example";
  useEffect(() => {
    const update = () => setInputFocused(document.activeElement?.tagName === "TEXTAREA");
    document.addEventListener("focusin", update);
    document.addEventListener("focusout", update);
    return () => { document.removeEventListener("focusin", update); document.removeEventListener("focusout", update); };
  }, []);
  useEffect(() => {
    if (draft || busy || inputFocused) setPaused(true);
  }, [draft, busy, inputFocused, setPaused]);
  const image = heroImages[step % heroImages.length];
  const journey = journeys.length ? journeys[step % journeys.length] : undefined;
  useEffect(() => {
    const photo = photoRef.current;
    if (photo?.complete && photo.naturalWidth === 0) setFailedImage(image.id);
  }, [image.id]);
  const move = (direction: number) => {
    setPaused(true);
    setStep((current) => (current + direction + heroImages.length) % heroImages.length);
  };
  return (
    <section className="welcome-hero" aria-labelledby="home-heading">
      <div className="hero-stage">
        <div className="hero-introduction">
          <h1 id="home-heading">Hello, <span>{presentation.greeting}</span></h1>
          <p>Whatever your next step, start here.</p>
        </div>
        <div className="photo-story" ref={ref} data-example={step}>
          <AnimatePresence initial={false}>
            <motion.picture key={image.id} className="hero-photograph" data-failed={failedImage === image.id} initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : 0.7 }}>
              <source media="(max-width: 767px)" srcSet={image.mobileSrc} />
              <img ref={photoRef} src={image.src} width={image.width} height={image.height} alt={image.alt} fetchPriority={step === 0 ? "high" : "auto"} style={{ objectPosition: image.position }} onError={() => setFailedImage(image.id)} />
            </motion.picture>
          </AnimatePresence>
          {failedImage === image.id && <p className="photo-fallback">This photograph is unavailable. Your next step is still here.</p>}
          <div className="hero-composer-wrap"><div className="composer-anchor" data-composer-anchor /></div>
          <div className="photo-story-caption">
            <span className="photo-place"><MapPin size={14} aria-hidden="true" />{image.place}</span>
            {journey ? <button type="button" disabled={busy} className="photo-question" onClick={() => selectJourney(journey)}>
              <span>{journey.prompt}</span><span className="example-action">Open guided plan <ArrowRight size={19} aria-hidden="true" /></span>
            </button> : <Link className="photo-question" href="/services"><span>{presentation.serviceIntro}</span><span className="example-action">Browse official services <ArrowRight size={19} aria-hidden="true" /></span></Link>}
          </div>
        </div>
        <div className="example-controls" role="group" aria-label={isSaskatchewan ? "Explore Saskatchewan photographs" : "Explore example journeys"}>
          <span>{isSaskatchewan ? "Places across Saskatchewan." : "Everyday questions. A clearer way forward."}</span>
          <div><Button variant="ghost" size="icon" aria-label={`Previous ${slideLabel}`} onClick={() => move(-1)}><ArrowLeft size={18} aria-hidden="true" /></Button>
            <span className="example-count" aria-live={paused || reduced ? "polite" : "off"} aria-atomic="true">{String(step + 1).padStart(2, "0")} <span>/ {String(heroImages.length).padStart(2, "0")}</span></span>
            <Button variant="ghost" size="icon" aria-label={`Next ${slideLabel}`} onClick={() => move(1)}><ArrowRight size={18} aria-hidden="true" /></Button>
            <Button variant="ghost" size="icon" aria-label={paused || reduced ? (isSaskatchewan ? "Play slideshow" : "Play examples") : (isSaskatchewan ? "Pause slideshow" : "Pause examples")} disabled={!!reduced || !!draft || busy || inputFocused} onClick={() => setPaused(!paused)}>{paused || reduced ? <Play size={15} aria-hidden="true" /> : <Pause size={15} aria-hidden="true" />}</Button></div>
        </div>
        <ConversationStarters heading="Ask the assistant" />
      </div>
      <p className="hero-trust">{isSaskatchewan ? "Start with official Saskatchewan service information." : <>A little guidance goes a long way.<br />Explore official information, prepare your plan, and take the next step with confidence.</>}</p>
      <noscript><p className="no-script-guidance">The interactive assistant needs JavaScript. <Link href="/services">Browse official services instead.</Link></p></noscript>
    </section>
  );
}
