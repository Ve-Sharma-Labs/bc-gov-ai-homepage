"use client";

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { CircleHelp, X } from "lucide-react";
import { Composer } from "./composer";
import { ComposerScope } from "./composer-scope";
import { useAssistant } from "./assistant-provider";
import { FooterCredit } from "./chrome";

interface Position { top: number; left: number; width: number; docked: boolean; keyboard: number }

export function ComposerDock() {
  const assistant = useAssistant();
  const pathname = usePathname();
  const router = useRouter();
  const isChat = pathname === "/chat";
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const floatRef = useRef<HTMLDivElement>(null);
  const restoreSubmissionFocus = useRef(false);
  const [position, setPosition] = useState<Position | null>(null);
  const [focused, setFocused] = useState(false);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (!isChat) router.prefetch("/chat");
  }, [isChat, router]);

  useLayoutEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      const anchor = document.querySelector<HTMLElement>("[data-composer-anchor]");
      const rect = anchor?.getBoundingClientRect();
      const viewport = window.visualViewport;
      const keyboard = viewport ? Math.max(0, innerHeight - viewport.height - viewport.offsetTop) : 0;
      const docked = isChat || !rect || rect.width === 0 || rect.bottom < 100 || rect.top > innerHeight - 100 || (focused && keyboard > 150);
      setPosition({
        top: rect ? rect.top + scrollY : 0,
        left: rect?.left ?? 16,
        width: rect?.width ?? Math.min(676, innerWidth - 32),
        docked,
        keyboard,
      });
      if (anchor && floatRef.current && !docked) {
        const height = floatRef.current.querySelector("form")?.getBoundingClientRect().height;
        if (height) anchor.style.minHeight = `${height}px`;
      }
      if (isChat && floatRef.current) {
        document.documentElement.style.setProperty("--chat-composer-height", `${floatRef.current.getBoundingClientRect().height + keyboard}px`);
      }
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    measure();
    if (isChat && restoreSubmissionFocus.current) {
      inputRef.current?.focus({ preventScroll: true });
      restoreSubmissionFocus.current = false;
    }
    const observer = new ResizeObserver(schedule);
    const anchor = document.querySelector<HTMLElement>("[data-composer-anchor]");
    if (anchor) observer.observe(anchor);
    if (floatRef.current) observer.observe(floatRef.current);
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    window.visualViewport?.addEventListener("resize", schedule);
    window.visualViewport?.addEventListener("scroll", schedule);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      window.visualViewport?.removeEventListener("resize", schedule);
      window.visualViewport?.removeEventListener("scroll", schedule);
      if (isChat) document.documentElement.style.removeProperty("--chat-composer-height");
    };
  }, [pathname, isChat, assistant.selectedId, assistant.state.messages.length, assistant.draft, focused]);

  const submit = () => {
    if (!assistant.draft.trim() || assistant.draft.trim().length > 4000 || assistant.busy) return;
    restoreSubmissionFocus.current = true;
    void assistant.submit();
    if (!isChat) router.push("/chat");
    else {
      inputRef.current?.focus({ preventScroll: true });
      restoreSubmissionFocus.current = false;
    }
  };
  const style: CSSProperties = position?.docked
    ? { bottom: position.keyboard + 20 }
    : { top: position?.top ?? 0, left: position?.left ?? 0, width: position?.width ?? 0 };

  return (
    <motion.div
      ref={floatRef}
      layout="position"
      layoutId="bc-composer"
      initial={false}
      transition={reduced ? { duration: 0 } : { type: "spring", bounce: 0.08, duration: 0.45 }}
      className={`composer-float ${position?.docked ? "is-docked" : "is-anchored"}${isChat ? " is-chat" : ""}`}
      data-ready={!!position}
      data-focused={focused}
      style={style}
      onFocusCapture={() => setFocused(true)}
      onBlurCapture={(event) => {
        if (!(event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget))) setFocused(false);
      }}
    >
      <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">{assistant.state.announcement}</span>
      {position?.docked && !isChat && <div className="dock-caption">
        {assistant.busy ? <span>Answer in progress</span> : <Link href="/about#privacy">Your privacy</Link>}<span aria-hidden="true">·</span><Link href="/how-it-works">How it works</Link>
      </div>}
      <Composer value={assistant.draft} onChange={assistant.setDraft} onSubmit={submit} onStop={assistant.stop} busy={assistant.busy} inputRef={inputRef} compact={position?.docked} />
      <ComposerScope />
      <p className="composer-privacy">Keep names, ID numbers and personal details out of your question.</p>
      {isChat && <footer className="chat-composer-footer"><div><Link href="/about#privacy">Privacy</Link><span aria-hidden="true">·</span><Link href="/how-it-works">How it works</Link></div><FooterCredit /></footer>}
      {assistant.notice && !isChat && <div className="composer-notice" role="status">
        <div><CircleHelp size={18} aria-hidden="true" /><p>{assistant.notice}</p></div>
        <div className="notice-actions"><Link href="/#journeys">Explore guided plans</Link><button type="button" onClick={() => { void assistant.load(); }}>Retry connection</button><button type="button" aria-label="Dismiss notice" onClick={() => assistant.setNotice("")}><X size={16} aria-hidden="true" /></button></div>
      </div>}
    </motion.div>
  );
}
