"use client";

import {
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  MapPin,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";
import {
  contextCategoryDetails,
  humanizeContextIdentifier,
  humanizeContextPurpose,
  SYNTHETIC_CONTEXT_NOTICE,
} from "@/lib/citizen-context";
import type { Artifact, ConsentRequest, ProgramMatch } from "@/lib/contract";
import { formatDate } from "@/lib/links";
import { useAssistant } from "./assistant-provider";
import { ContextSummaryDetails } from "./citizen-context";
import { OfficialLink } from "./official-link";
import { TaskPanel } from "./task-panel";
import { SourceCard, SourceReferences } from "./sources";

const matchLabels: Record<ProgramMatch["status"], string> = {
  "potential-match": "Potential match",
  "needs-information": "Needs information",
  "already-enrolled": "Already receiving",
  "not-indicated": "Not indicated by current facts",
};

const auditActionLabels = {
  "consent-granted": "Consent granted",
  "consent-revoked": "Consent revoked",
  "context-category-accessed": "Context category accessed",
  "rule-evaluated": "Screening rule evaluated",
  "preview-generated": "Review preview generated",
  "approved-source-accessed": "Reviewed source accessed",
  "handoff-offered": "Official handoff offered",
  "handoff-opened": "Official handoff opened",
  "access-denied": "Access denied",
  "session-cleared": "Context session cleared",
  "context-run-completed": "Contextual run completed",
} as const;

function SyntheticArtifactHeader({ title, description }: { title: string; description: string }) {
  return (
    <header className="context-artifact-heading">
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      <span><ShieldCheck size={16} aria-hidden="true" />Synthetic context</span>
      <p className="context-artifact-notice">{SYNTHETIC_CONTEXT_NOTICE}</p>
    </header>
  );
}

function ProgramMatchesArtifact({ matches }: { matches: ProgramMatch[] }) {
  return (
    <>
      <SyntheticArtifactHeader
        title="Program screening"
        description="Deterministic indicators from the consented fictional scenario and pinned rule versions."
      />
      <div className="program-match-list">
        {matches.map((match) => (
          <article className={`program-match program-match-${match.status}`} key={match.programId}>
            <div className="program-match-title">
              {match.status === "needs-information"
                ? <TriangleAlert size={19} aria-hidden="true" />
                : <CheckCircle2 size={19} aria-hidden="true" />}
              <div>
                <h4>{humanizeContextIdentifier(match.programId)}</h4>
                <strong>{matchLabels[match.status]}</strong>
              </div>
            </div>
            <p className="screening-notice">{match.notice}</p>
            <dl className="program-match-meta">
              <div><dt>Rule version</dt><dd>{match.ruleVersion}</dd></div>
              <div><dt>Policy date</dt><dd>{formatDate(match.policyEffectiveDate)}</dd></div>
            </dl>
            {!!match.satisfiedConditions.length && (
              <div className="match-facts">
                <h5>What supports this indicator</h5>
                <ul>{match.satisfiedConditions.map((item) => <li key={item}>{humanizeContextIdentifier(item)}</li>)}</ul>
              </div>
            )}
            {!!match.missingFacts.length && (
              <div className="match-facts">
                <h5>Still needed</h5>
                <ul>{match.missingFacts.map((item) => <li key={item}>{humanizeContextIdentifier(item)}</li>)}</ul>
              </div>
            )}
            {!!match.disqualifyingFacts.length && (
              <div className="match-facts">
                <h5>Current facts that do not indicate this program</h5>
                <ul>{match.disqualifyingFacts.map((item) => <li key={item}>{humanizeContextIdentifier(item)}</li>)}</ul>
              </div>
            )}
            <p className="match-sources">
              Reviewed source versions: {match.sourceVersions
                .map((source) => `${humanizeContextIdentifier(source.sourceId)} (${source.version})`)
                .join(", ")}.
            </p>
          </article>
        ))}
      </div>
    </>
  );
}

function ApplicationPreviewArtifact({ preview }: {
  preview: Extract<Artifact, { kind: "application-preview" }>["payload"];
}) {
  return (
    <>
      <SyntheticArtifactHeader
        title="Application or intake preview"
        description="A review aid prepared from consented fictional context. It is not an application."
      />
      <div className="preview-boundary">
        <FileSearch size={20} aria-hidden="true" />
        <p><strong>Review only.</strong> Nothing can be submitted from this preview and a person must review every field.</p>
      </div>
      <dl className="preview-fields">
        {preview.fields.map((field) => (
          <div className="preview-field" key={field.field}>
            <dt>{field.label}</dt>
            <dd className="preview-value">{field.value === null ? "Not provided" : String(field.value)}</dd>
            <dd className="preview-provenance">
              <span>{field.source === "synthetic-record"
                ? "Government record (synthetic)"
                : field.source === "citizen-answer"
                  ? "Citizen answer"
                  : "Missing / needs confirmation"}</span>
              <span>{humanizeContextIdentifier(field.sensitivity)}</span>
              <span>{field.editable ? "Can be corrected" : "Review with the source service"}</span>
              {field.requiresConfirmation && <span>Confirmation required</span>}
            </dd>
          </div>
        ))}
      </dl>
      {!!preview.missingItems.length && (
        <section className="preview-missing" aria-labelledby={`preview-${preview.previewId}-missing`}>
          <h4 id={`preview-${preview.previewId}-missing`}>Missing items or confirmations</h4>
          <ul>{preview.missingItems.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      )}
      <p className="preview-expiry">Preview expires {formatDate(preview.expiresAt)}. Human review is required.</p>
    </>
  );
}

function ConsentCheckpointArtifact({ checkpoint }: { checkpoint: ConsentRequest }) {
  const [reviewed, setReviewed] = useState(checkpoint.reviewedByCitizen);
  return (
    <>
      <SyntheticArtifactHeader
        title="Consent checkpoint"
        description="Review what a future approved integration could share. This release transfers nothing."
      />
      <div className="checkpoint-destination">
        <ClipboardCheck size={21} aria-hidden="true" />
        <div>
          <span>Future official destination</span>
          <strong>{checkpoint.destinationName}</strong>
        </div>
      </div>
      <dl className="checkpoint-details">
        <div>
          <dt>Purpose</dt>
          <dd>{humanizeContextPurpose(checkpoint.purpose)}</dd>
        </div>
        <div>
          <dt>Categories reviewed</dt>
          <dd>{checkpoint.categoriesToShare.length
            ? checkpoint.categoriesToShare.map((category) => contextCategoryDetails[category].label).join(", ")
            : "No context categories"}</dd>
        </div>
        <div>
          <dt>Fields reviewed</dt>
          <dd>{checkpoint.fieldNamesToShare.length
            ? checkpoint.fieldNamesToShare.map(humanizeContextIdentifier).join(", ")
            : "No fields"}</dd>
        </div>
        <div>
          <dt>Transfer in this demo</dt>
          <dd>None</dd>
        </div>
      </dl>
      <label className="checkpoint-review">
        <input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />
        <span>I reviewed what would be shared in a future approved service.</span>
      </label>
      <p className="checkpoint-boundary">Opening the official service sends no preview values, identifiers or context.</p>
      {reviewed
        ? <OfficialLink href={checkpoint.destinationUrl} className="checkpoint-link">Continue to official service</OfficialLink>
        : <span className="checkpoint-link checkpoint-link-disabled" aria-disabled="true">Continue to official service</span>}
    </>
  );
}

function AuditReceiptArtifact({ receipt }: {
  receipt: Extract<Artifact, { kind: "audit-receipt" }>["payload"];
}) {
  return (
    <>
      <SyntheticArtifactHeader
        title="Audit receipt"
        description="A value-free record of the demo actions. It contains no raw context values."
      />
      <ol className="audit-events">
        {receipt.events.map((event) => (
          <li key={event.eventId}>
            <span className="audit-marker" aria-hidden="true" />
            <div>
              <div className="audit-event-heading">
                <strong>{auditActionLabels[event.action]}</strong>
                <time dateTime={event.occurredAt}>{formatDate(event.occurredAt)}</time>
              </div>
              <p>{event.outcome}</p>
              {event.category && <p>Category: {contextCategoryDetails[event.category].label}</p>}
              {event.ruleVersion && <p>Rule version: {event.ruleVersion}</p>}
              {!!event.sourceVersions.length && (
                <p>Sources: {event.sourceVersions
                  .map((source) => `${humanizeContextIdentifier(source.sourceId)} (${source.version})`)
                  .join(", ")}</p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </>
  );
}

export function ChatArtifacts({ artifacts }: { artifacts: Artifact[] }) {
  const { checked, setChecked, state, taskControl, busy } = useAssistant();
  return (
    <div className="chat-artifacts">
      {artifacts.map((artifact) => {
        const prefix = `artifact-${artifact.id}-`;
        if (artifact.kind === "preparation") {
          const task = state.task?.task;
          const activeTask = task?.journeyId === artifact.journey.id && artifact.id === `task-${task.id}` ? task : null;
          return (
            <section className="chat-artifact" key={artifact.id} aria-label="Source-backed preparation">
              <TaskPanel
                journey={artifact.journey}
                sources={artifact.sources}
                checked={activeTask ? new Set(activeTask.reviewedStepIds.map((id) => `${activeTask.journeyId}:${id}`)) : checked}
                disabled={!!activeTask && busy}
                sourcePrefix={prefix}
                onCheck={(key, value) => activeTask ? void taskControl(
                  "review", key.slice(activeTask.journeyId.length + 1), value,
                ) : setChecked((previous) => {
                  const next = new Set(previous);
                  if (value) next.add(key);
                  else next.delete(key);
                  return next;
                })}
              />
              <div className="artifact-sources">
                {artifact.sources.map((source, index) => <SourceCard key={source.id} source={source} prefix={prefix} index={index} />)}
              </div>
            </section>
          );
        }
        if (artifact.kind === "locations") {
          return (
            <section className="chat-artifact" key={artifact.id} aria-label="Published office matches">
              <div className="chat-office-results">
                <h3>Published office matches</h3>
                <p className="muted">{artifact.notice}</p>
                {!artifact.locations.length && <p>No matching office was found in the reviewed snapshot. Check the official Service BC directory.</p>}
                <ul className="location-results">
                  {artifact.locations.map((location) => (
                    <li className="location" key={location.id}>
                      <div className="location-title"><MapPin size={18} aria-hidden="true" /><h4>{location.name}</h4></div>
                      <p>{location.address}</p><p>{location.municipality}</p>
                      <dl><dt>Published hours</dt><dd>{location.hours}</dd><dt>Snapshot checked</dt><dd>{formatDate(location.checkedAt)}</dd></dl>
                      {!!location.excludedServices.length && <p>Not offered here: {location.excludedServices.map((service) => service.replaceAll("-", " ")).join(", ")}.</p>}
                      <SourceReferences ids={location.sourceIds} sources={artifact.sources} prefix={prefix} />
                    </li>
                  ))}
                </ul>
              </div>
              <div className="artifact-sources">
                {artifact.sources.map((source, index) => <SourceCard key={source.id} source={source} prefix={prefix} index={index} />)}
              </div>
            </section>
          );
        }
        return (
          <section className={`chat-artifact context-artifact context-artifact-${artifact.kind}`} key={artifact.id} aria-label={{
            "context-summary": "Synthetic context summary",
            "program-matches": "Synthetic program screening",
            "application-preview": "Synthetic application or intake preview",
            "consent-request": "Synthetic consent checkpoint",
            "audit-receipt": "Synthetic audit receipt",
          }[artifact.kind]}>
            {artifact.kind === "context-summary" && (
              <>
                <SyntheticArtifactHeader
                  title="Context summary"
                  description="The redacted fictional information available for this result."
                />
                <ContextSummaryDetails summary={artifact.payload} />
              </>
            )}
            {artifact.kind === "program-matches" && <ProgramMatchesArtifact matches={artifact.payload} />}
            {artifact.kind === "application-preview" && <ApplicationPreviewArtifact preview={artifact.payload} />}
            {artifact.kind === "consent-request" && <ConsentCheckpointArtifact checkpoint={artifact.payload} />}
            {artifact.kind === "audit-receipt" && <AuditReceiptArtifact receipt={artifact.payload} />}
          </section>
        );
      })}
    </div>
  );
}
