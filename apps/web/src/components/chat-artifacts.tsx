"use client";

import { MapPin } from "lucide-react";
import type { ChatArtifact } from "@/lib/contract";
import { formatDate } from "@/lib/links";
import { useAssistant } from "./assistant-provider";
import { TaskPanel } from "./task-panel";
import { SourceCard, SourceReferences } from "./sources";

export function ChatArtifacts({ artifacts }: { artifacts: ChatArtifact[] }) {
  const { checked, setChecked } = useAssistant();
  return <div className="chat-artifacts">{artifacts.map((artifact) => {
    const prefix = `artifact-${artifact.id}-`;
    return <section className="chat-artifact" key={artifact.id} aria-label={artifact.kind === "preparation" ? "Source-backed preparation" : "Published office matches"}>
      {artifact.kind === "preparation"
        ? <TaskPanel journey={artifact.journey} sources={artifact.sources} checked={checked} sourcePrefix={prefix} onCheck={(key, value) => setChecked((previous) => {
          const next = new Set(previous);
          if (value) next.add(key); else next.delete(key);
          return next;
        })} />
        : <div className="chat-office-results">
          <h3>Published office matches</h3>
          <p className="muted">{artifact.notice}</p>
          {!artifact.locations.length && <p>No matching office was found in the reviewed snapshot. Check the official Service BC directory.</p>}
          <ul className="location-results">{artifact.locations.map((location) => <li className="location" key={location.id}>
            <div className="location-title"><MapPin size={18} aria-hidden="true" /><h4>{location.name}</h4></div>
            <p>{location.address}</p><p>{location.municipality}</p>
            <dl><dt>Published hours</dt><dd>{location.hours}</dd><dt>Snapshot checked</dt><dd>{formatDate(location.checkedAt)}</dd></dl>
            {!!location.excludedServices.length && <p>Not offered here: {location.excludedServices.map((service) => service.replaceAll("-", " ")).join(", ")}.</p>}
            <SourceReferences ids={location.sourceIds} sources={artifact.sources} prefix={prefix} />
          </li>)}</ul>
        </div>}
      <div className="artifact-sources">{artifact.sources.map((source, index) => <SourceCard key={source.id} source={source} prefix={prefix} index={index} />)}</div>
    </section>;
  })}</div>;
}
