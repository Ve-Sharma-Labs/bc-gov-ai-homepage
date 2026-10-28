import { AlertCircle, Check, ChevronDown, FileText } from "lucide-react";
import type { EvidenceMetadata, Source } from "@/lib/contract";
import { formatDate, sourceDomain, sourceNeedsReview } from "@/lib/links";
import { OfficialLink } from "./official-link";

const statusLabels = {
  available: "Available snapshot",
  limited: "Limited source",
  pending: "Approval pending",
  blocked: "Access restricted",
} as const;

const documentLabels = { guidance: "Guidance", legal: "Legal document", "service-directory": "Service directory", notice: "Notice" };
const legalLabels = { "in-force": "In force", "not-yet-in-force": "Not yet in force", repealed: "Repealed", historical: "Historical", unknown: "Unknown" };

function SourceProvenance({ metadata }: { metadata: EvidenceMetadata }) {
  const calendarDates = [
    ["Effective from (inclusive)", metadata.effectiveFrom],
    ["Effective to (exclusive)", metadata.effectiveTo],
    ["Consolidation date", metadata.consolidationDate],
    ["Repealed on", metadata.repealedAt],
  ] as const;
  const hashes = [
    ["Content hash", metadata.contentHash],
    ["Extraction hash", metadata.extractionHash],
    ["Review hash", metadata.reviewHash],
    ["Rights hash", metadata.rightsHash],
  ];
  return <>
    <dl className="source-dates">
      <div><dt>Document type</dt><dd>{documentLabels[metadata.documentType]}</dd></div>
      {metadata.language && <div><dt>Language</dt><dd>{metadata.language}</dd></div>}
      {metadata.legalStatus && <div><dt>Legal status</dt><dd>{legalLabels[metadata.legalStatus]}</dd></div>}
      {calendarDates.map(([label, value]) => value && <div key={label}><dt>{label}</dt><dd><time dateTime={value}>{value}</time></dd></div>)}
      {metadata.legalSectionId && <div><dt>Legal section</dt><dd>{metadata.legalSectionId}</dd></div>}
      {metadata.isHistorical !== null && <div><dt>Historical snapshot</dt><dd>{metadata.isHistorical ? "Yes" : "No"}</dd></div>}
    </dl>
    <details className="source-provenance">
      <summary>Review provenance</summary>
      <p className="source-freshness">This provenance describes the cited document snapshot, not whole-site coverage.</p>
      <dl className="source-dates">
        <div><dt>Source registry IDs</dt><dd>{metadata.sourceIds.join(", ")}</dd></div>
        <div><dt>Rights review</dt><dd>{metadata.rightsReviewId}</dd></div>
        {hashes.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><code>{value}</code></dd></div>)}
      </dl>
    </details>
  </>;
}

export function SourceCard({ source, prefix = "source-", index }: { source: Source; prefix?: string; index?: number }) {
  const review = sourceNeedsReview(source);
  return (
    <details className="source-card" id={`${prefix}${source.id}`}>
      <summary>
        <span className="source-symbol" aria-hidden="true">{index !== undefined ? index + 1 : <FileText size={17} />}</span>
        <span className="source-summary">
          <span className="source-publisher">{source.publisher}</span>
          <span className="source-title">{source.title}</span>
          <span className={`source-status ${review ? "needs-review" : ""}`}>
            {review ? <AlertCircle size={12} aria-hidden="true" /> : <Check size={12} aria-hidden="true" />}
            {source.status === "available" && review ? "Recheck before acting" : statusLabels[source.status]}
          </span>
        </span>
        <ChevronDown className="disclosure-chevron" size={18} aria-hidden="true" />
      </summary>
      <div className="source-content">
        <p>{source.description}</p>
        <dl className="source-dates">
          <div><dt>Checked</dt><dd>{formatDate(source.checkedAt)}</dd></div>
          <div><dt>Publisher updated</dt><dd>{formatDate(source.publisherUpdatedAt)}</dd></div>
        </dl>
        {source.metadata && <SourceProvenance metadata={source.metadata} />}
        <p className="source-freshness">A dated source snapshot, not live verification. Confirm changing requirements on the official site.</p>
        <OfficialLink href={source.url}>Open {sourceDomain(source.url)}</OfficialLink>
      </div>
    </details>
  );
}

export function SourceReferences({ ids, sources, prefix = "guide-source-" }: { ids: string[]; sources: Source[]; prefix?: string }) {
  const resolved = ids.map((id) => sources.find((source) => source.id === id)).filter((source): source is Source => !!source);
  if (!resolved.length) return <span className="missing-source">Source information unavailable</span>;
  return (
    <span className="source-references">
      <span>Sources</span>
      {resolved.map((source) => (
        <a key={source.id} href={`#${prefix}${source.id}`} aria-label={`Read source: ${source.title}`}>
          {sources.indexOf(source) + 1}
        </a>
      ))}
    </span>
  );
}
