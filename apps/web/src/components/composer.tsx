"use client";

import { useId, useLayoutEffect, type FormEvent, type RefObject } from "react";
import { ArrowRight, Square } from "lucide-react";
import { Button } from "./ui/button";

export function Composer({ value, onChange, onSubmit, onStop, busy, inputRef, compact = false, onFocusChange }: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  busy: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  compact?: boolean;
  onFocusChange?: (focused: boolean) => void;
}) {
  const id = useId();
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    let previousWidth = -1;
    let disposed = false;
    const resize = () => {
      if (disposed || input.clientWidth <= 0) return;
      input.style.height = "0px";
      input.style.height = `${Math.min(192, Math.max(compact ? 24 : 32, input.scrollHeight))}px`;
    };
    resize();
    const observer = new ResizeObserver(() => {
      if (input.clientWidth !== previousWidth) {
        previousWidth = input.clientWidth;
        resize();
      }
    });
    observer.observe(input);
    void document.fonts?.ready.then(resize);
    return () => { disposed = true; observer.disconnect(); };
  }, [value, compact, inputRef]);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!busy && value.trim()) onSubmit();
  };
  return (
    <form
      className={`composer ${compact ? "composer-compact" : ""}`}
      onSubmit={submit}
      onFocus={() => onFocusChange?.(true)}
      onBlur={(event) => {
        if (!(event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget))) {
          onFocusChange?.(false);
        }
      }}
    >
      <label className="sr-only" htmlFor={id}>What would you like help with?</label>
      <textarea
        id={id}
        ref={inputRef}
        value={value}
        rows={1}
        maxLength={4000}
        placeholder={compact ? "Ask a question..." : "Describe what you need..."}
        aria-describedby={`${id}-privacy ${id}-keyboard`}
        autoComplete="off"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
            event.preventDefault();
            if (!busy && value.trim()) onSubmit();
          }
        }}
      />
      {busy
        ? <Button className="send-button stop-button" size="icon" type="button" aria-label="Stop answer" onClick={(event) => {
          // Stopping reuses this node as Submit before the click's default action.
          event.preventDefault();
          onStop();
        }}><Square size={18} fill="currentColor" aria-hidden="true" /></Button>
        : <Button className="send-button" size="icon" type="submit" disabled={!value.trim()} aria-label="Send question" onClick={(event) => {
          // Base UI normalizes press behavior; own the form action so a moved fixed composer cannot lose native submit.
          event.preventDefault();
          if (value.trim()) onSubmit();
        }}><ArrowRight size={24} aria-hidden="true" /></Button>}
      <span className="sr-only" id={`${id}-privacy`}>Do not include names, ID numbers or personal details.</span>
      <span className="sr-only" id={`${id}-keyboard`}>Enter sends your question. Shift and Enter adds a new line. Maximum 4,000 characters.</span>
      {value.length > 3600 && <span className="character-count" role="status">{4000 - value.length} characters left</span>}
    </form>
  );
}
