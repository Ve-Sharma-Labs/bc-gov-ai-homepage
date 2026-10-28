"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Pause, Play, MapPin } from "lucide-react";
import { heroImages } from "@/lib/hero-images";
import { useScenePlayback } from "@/lib/use-scene-playback";
import { useAssistant } from "./assistant-provider";
import { Button } from "./ui/button";

export function HeroExperience() {
  const { catalog, selectJourney, draft, busy } = useAssistant();
  const { ref, step, setStep, paused, setPaused, reduced } = useScenePlayback(6500, 5);
  const [failedImage, setFailedImage] = useState("");
  const photoRef = useRef<HTMLImageElement>(null);
  const [inputFocused, setInputFocused] = useState(false);
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
  const journey = catalog?.journeys[step % catalog.journeys.length];
  useEffect(() => {
    const photo = photoRef.current;
    if (photo?.complete && photo.naturalWidth === 0) setFailedImage(image.id);
  }, [image.id]);
  const move = (direction: number) => {
    setPaused(true);
    setStep((current) => (current + direction + 5) % 5);
  };
  return (
    <section className="welcome-hero" aria-labelledby="home-heading">
      <div className="hero-stage">
        <div className="hero-introduction">
          <h1 id="home-heading">Hello, <span>British Columbia.</span></h1>
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
            </button> : <Link className="photo-question" href="/services"><span>Find your way through B.C. services.</span><span className="example-action">Browse official services <ArrowRight size={19} aria-hidden="true" /></span></Link>}
          </div>
        </div>
        <div className="example-controls" aria-label="Explore example journeys">
          <span>Everyday questions. A clearer way forward.</span>
          <div><Button variant="ghost" size="icon" aria-label="Previous example" onClick={() => move(-1)}><ArrowLeft size={18} /></Button>
            <span className="example-count" aria-live="off">{String(step + 1).padStart(2, "0")} <span>/ 05</span></span>
            <Button variant="ghost" size="icon" aria-label="Next example" onClick={() => move(1)}><ArrowRight size={18} /></Button>
            <Button variant="ghost" size="icon" aria-label={paused ? "Play examples" : "Pause examples"} disabled={!!reduced || !!draft || busy || inputFocused} onClick={() => setPaused(!paused)}>{paused || reduced ? <Play size={15} /> : <Pause size={15} />}</Button></div>
        </div>
      </div>
      <p className="hero-trust">A little guidance goes a long way.<br />Explore official information, prepare your plan, and take the next step with confidence.</p>
      <noscript><p className="no-script-guidance">The interactive assistant needs JavaScript. <Link href="/services">Browse official services instead.</Link></p></noscript>
    </section>
  );
}
