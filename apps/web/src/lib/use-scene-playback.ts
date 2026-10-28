"use client";

import { useEffect, useRef, useState } from "react";
import { useInView, useReducedMotion } from "motion/react";

export function useScenePlayback(interval = 2800, frames = 4) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.2 });
  const preference = useReducedMotion();
  const [hydrated, setHydrated] = useState(false);
  const reduced = hydrated ? !!preference : true;
  const [paused, setPaused] = useState(false);
  const [visible, setVisible] = useState(true);
  const [step, setStep] = useState(0);
  const playing = inView && visible && !paused && !reduced;
  useEffect(() => { setHydrated(true); }, []);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setStep((value) => (value + 1) % frames), interval);
    return () => clearInterval(timer);
  }, [playing, interval, frames]);
  return { ref, step, setStep, playing, paused, setPaused, reduced };
}
