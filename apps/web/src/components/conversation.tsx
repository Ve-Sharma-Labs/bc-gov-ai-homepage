"use client";

import { Fragment, memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button } from "react-aria-components";
import { ArrowDown, BookOpen, Compass, X } from "lucide-react";
import { Dialog } from "@base-ui/react/dialog";
import ReactMarkdown, { type Components } from "react-markdown";
import type { Catalog, Source } from "@/lib/contract";
import { needsSources, type ChatMessage, type Citation, type StreamState } from "@/lib/stream";
import { safeOfficialUrl, sourceDomain } from "@/lib/links";
import { OfficialLink } from "./official-link";
import { SourceCard } from "./sources";
import { Button as UiButton } from "./ui/button";
import { ChatArtifacts } from "./chat-artifacts";

export function resolveCitation(citation: Citation, catalog: Catalog | null, index: number): Source | null {
  const existing = catalog?.sources.find((source) => source.id === citation.sourceId || source.url === citation.url);
  const url = safeOfficialUrl(citation.url);
  if (existing) return {
    ...existing,
    id: `${existing.id}-${index}`,
    ...(url ? { url, title: citation.title || existing.title } : {}),
    ...(citation.section ? { description: `Source section: ${citation.section}` } : {}),
    ...(citation.checkedAt !== undefined ? { checkedAt: citation.checkedAt } : {}),
    ...(citation.publisherUpdatedAt !== undefined ? { publisherUpdatedAt: citation.publisherUpdatedAt } : {}),
    metadata: citation.metadata ?? null,
  };
  if (!url) return null;
  return {
    id: `reference-${index}`,
    title: citation.title || "Official source reference",
    publisher: citation.publisher || sourceDomain(url),
    url,
    description: "A reference returned by the connected assistant, outside the curated catalogue. Review the original page before acting.",
    checkedAt: citation.checkedAt ?? null,
    publisherUpdatedAt: citation.publisherUpdatedAt ?? null,
    status: "limited",
    topics: [],
    metadata: citation.metadata ?? null,
  };
}

const markdownElements = ["p", "a", "strong", "em", "ul", "ol", "li", "blockquote", "h1", "h2", "h3", "h4", "code", "pre", "br", "hr"];
const markdownComponents: Components = {
  a: ({ href, children }) => <OfficialLink href={href || ""}>{children}</OfficialLink>,
  h1: ({ children }) => <h3>{children}</h3>,
  h2: ({ children }) => <h3>{children}</h3>,
  h3: ({ children }) => <h3>{children}</h3>,
  h4: ({ children }) => <h3>{children}</h3>,
};
const markdownUrl = (url: string) => safeOfficialUrl(url) || "";

export const SafeMarkdown = memo(function SafeMarkdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      skipHtml
      allowedElements={markdownElements}
      urlTransform={markdownUrl}
      components={markdownComponents}
    >{children}</ReactMarkdown>
  );
});

function AnswerSources({ sources, messageId }: { sources: Source[]; messageId: string }) {
  return <Dialog.Root>
    <Dialog.Trigger render={<UiButton variant="ghost" className="answer-sources-trigger" />} onMouseDown={(event) => {
      // Keep the inline target still while focus leaves the fixed composer.
      if (event.button === 0) event.preventDefault();
    }}><BookOpen size={16} aria-hidden="true" />{sources.length} {sources.length === 1 ? "source" : "sources"}</Dialog.Trigger>
    <Dialog.Portal>
      <Dialog.Backdrop className="sources-backdrop" />
      <Dialog.Popup className="sources-panel">
        <div className="sources-panel-heading"><Dialog.Title>Sources for this answer</Dialog.Title><Dialog.Close render={<UiButton variant="ghost" size="icon" />} aria-label="Close sources"><X size={20} /></Dialog.Close></div>
        <Dialog.Description className="muted">Open the exact official pages used for this answer. Check source dates before acting.</Dialog.Description>
        {sources.map((source, index) => <SourceCard key={source.id} source={source} prefix={`answer-${messageId}-`} index={index} />)}
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>;
}

const ConversationMessage = memo(function ConversationMessage({ message, catalog }: { message: ChatMessage; catalog: Catalog | null }) {
  const sources = useMemo(() => message.citations
    .map((citation, index) => resolveCitation(citation, catalog, index))
    .filter((source): source is Source => !!source), [message.citations, catalog]);
  if (message.role === "assistant" && !message.content.trim()) return null;
  const heading = message.role === "user" ? "Your question"
    : message.response?.origin === "application" ? "BC service assistant"
      : message.response?.kind === "dialogue" ? "AI assistant" : "AI answer";
  return <article className={`message message-${message.role}`}>
    <div className="message-heading">
      {message.role === "assistant" && <Compass size={19} strokeWidth={1.6} aria-hidden="true" />}
      <h2>{heading}</h2>
      {message.role === "assistant" && message.status === "partial" && <span className="message-state">Unfinished</span>}
    </div>
    {message.role === "user"
      ? <p className="question-text">{message.content}</p>
      : <div className="answer-content">
        <SafeMarkdown>{message.content}</SafeMarkdown>
        {message.status === "partial" && <p className="answer-warning">{needsSources(message)
          ? "This answer is unfinished. Do not rely on it as complete guidance."
          : "This response was interrupted."}</p>}
        {!!sources.length && <div className="answer-sources"><AnswerSources sources={sources} messageId={message.id} /></div>}
        {message.status === "complete" && needsSources(message) && !sources.length && <p className="answer-warning">Source details were not returned. Treat this answer as unverified and check official guidance.</p>}
      </div>}
  </article>;
});

export function Conversation({ state, catalog, children }: { state: StreamState; catalog: Catalog | null; children?: ReactNode }) {
  const bottom = useRef<HTMLDivElement>(null);
  const visible = useRef(true);
  const positioned = useRef(false);
  const [newContent, setNewContent] = useState(false);
  const lastMessageByRun = useMemo(() => new Map(state.messages.map((message) => [message.runId, message.id])), [state.messages]);
  useEffect(() => {
    if (!bottom.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      visible.current = entry.isIntersecting;
      if (entry.isIntersecting) setNewContent(false);
    });
    observer.observe(bottom.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!state.messages.length) return;
    // Route scroll restoration and composer measurement must settle before following content.
    const frame = requestAnimationFrame(() => {
      if (!positioned.current || visible.current) {
        bottom.current?.scrollIntoView({ behavior: "instant", block: "end" });
      } else {
        setNewContent(true);
      }
      positioned.current = true;
    });
    return () => cancelAnimationFrame(frame);
  }, [state.messages, state.artifacts, state.error, state.warning]);
  const jump = () => {
    bottom.current?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "end" });
    bottom.current?.focus({ preventScroll: true });
    setNewContent(false);
  };
  return (
    <section className="conversation" aria-label="Conversation">
      {state.messages.map((message) => {
        const artifacts = Object.hasOwn(state.artifacts, message.runId) ? state.artifacts[message.runId] : [];
        return (
          <Fragment key={message.id}>
            <ConversationMessage message={message} catalog={catalog} />
            {lastMessageByRun.get(message.runId) === message.id && !!artifacts.length && <ChatArtifacts artifacts={artifacts} />}
          </Fragment>
        );
      })}
      {state.warning && <p className="answer-warning conversation-warning" role="status">{state.warning}</p>}
      {state.progress && <div className="run-progress"><span className="thinking-mark" aria-hidden="true"><Compass size={20} /></span><span>{state.progress}</span></div>}
      {children}
      <div className="conversation-bottom" ref={bottom} tabIndex={-1}><span className="sr-only">Latest conversation content</span></div>
      {newContent && <Button className="new-content-button" onPress={jump}><ArrowDown size={16} aria-hidden="true" />New conversation update</Button>}
    </section>
  );
}
