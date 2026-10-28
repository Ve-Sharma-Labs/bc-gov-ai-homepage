"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "react-aria-components";
import { getCatalog } from "@/lib/api";
import type { Catalog, Source } from "@/lib/contract";
import { formatDate } from "@/lib/links";
import { SourceCard } from "./sources";

export function SourceDirectory() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [filter, setFilter] = useState<Source["status"] | "all">("all");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const request = useRef<AbortController | null>(null);

  const load = async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError("");
    try {
      const result = await getCatalog(controller.signal);
      if (!controller.signal.aborted) setCatalog(result);
    } catch {
      if (!controller.signal.aborted) setError("The source catalogue is unavailable. Please try again or use the official service directory.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };
  useEffect(() => { void load(); return () => request.current?.abort(); }, []);
  const sources = catalog?.sources.filter((source) => filter === "all" || source.status === filter) || [];

  return (
    <div className="source-directory">
      {catalog && <>
        <div className="source-directory-toolbar">
          <div><p>{catalog.sources.length} sources in this curated catalogue</p><p className="snapshot-note">Snapshot · {formatDate(catalog.asOf)}</p></div>
          <label>Source status<select value={filter} onChange={(event) => setFilter(event.target.value as Source["status"] | "all")}>
            <option value="all">All sources</option>
            <option value="available">Available snapshots</option>
            <option value="limited">Limited sources</option>
            <option value="pending">Approval pending</option>
            <option value="blocked">Access restricted</option>
          </select></label>
        </div>
        <p className="source-result-count" role="status">{sources.length} {sources.length === 1 ? "source" : "sources"} shown</p>
        <div className="source-directory-list">{sources.map((source) => <SourceCard key={source.id} source={source} />)}</div>
        {!sources.length && <p className="empty-state">There are no sources with this status in the current snapshot.</p>}
      </>}
      {loading && <p role="status" className="catalog-loading">Loading the source catalogue…</p>}
      {error && <div className="inline-notice" role="status"><p>{error}</p><Button className="text-button" onPress={() => { void load(); }}>Try again</Button></div>}
      <noscript><p>Source details need JavaScript to load. You can still <Link href="/services">browse official service links</Link>.</p></noscript>
    </div>
  );
}
