"use client";

import { Dialog } from "@base-ui/react/dialog";
import {
  Check,
  ChevronRight,
  Database,
  RotateCcw,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  categoriesToScopes,
  contextCategoryDetails,
  humanizeContextIdentifier,
  humanizeContextPurpose,
  personaPlan,
  scopesToCategories,
  SYNTHETIC_CONTEXT_NOTICE,
} from "@/lib/citizen-context";
import type {
  ConsentScope,
  ContextCategory,
  ContextSummary,
  DemoPersonaSummary,
} from "@/lib/contract";
import { formatDate } from "@/lib/links";
import { useAssistant } from "./assistant-provider";
import { Button } from "./ui/button";

function provenanceLabel(value: "synthetic-government-record" | "citizen-answer") {
  return value === "synthetic-government-record"
    ? "Government record (synthetic)"
    : "Citizen answer";
}

function SyntheticNotice({ compact = false }: { compact?: boolean }) {
  return (
    <p className={compact ? "synthetic-notice synthetic-notice-compact" : "synthetic-notice"}>
      <ShieldCheck size={17} aria-hidden="true" />
      <span>{SYNTHETIC_CONTEXT_NOTICE}</span>
    </p>
  );
}

export function ContextSummaryDetails({
  summary,
  onRevoke,
  requiredScopes,
  disabled = false,
}: {
  summary: ContextSummary;
  onRevoke?: (scope: ConsentScope) => void;
  requiredScopes?: ReadonlySet<ConsentScope>;
  disabled?: boolean;
}) {
  return (
    <div className="context-summary-details">
      <div className="context-purpose">
        <span>Current purpose</span>
        <strong>{humanizeContextPurpose(summary.purpose)}</strong>
      </div>
      <section className="context-categories" aria-labelledby="context-categories-heading">
        <h3 id="context-categories-heading">Consented categories</h3>
        <ul>
          {summary.categories.map((category) => {
            const details = contextCategoryDetails[category];
            const required = requiredScopes?.has(details.scope) ?? false;
            return (
              <li key={category}>
                <span>{details.label}</span>
                {required && <span className="context-required-scope">Required for this flow</span>}
                {onRevoke && !required && (
                  <Button
                    variant="ghost"
                    disabled={disabled}
                    onClick={() => onRevoke(details.scope)}
                    aria-label={`Remove consent for ${details.label}`}
                  >
                    Remove
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      </section>
      <section className="context-facts" aria-labelledby="context-facts-heading">
        <h3 id="context-facts-heading">Information used</h3>
        {summary.facts.length ? (
          <dl>
            {summary.facts.map((fact) => (
              <div key={fact.key} className="context-fact">
                <dt>{fact.label}</dt>
                <dd className="context-fact-value">{fact.displayValue}</dd>
                <dd className="context-fact-meta">
                  <span>{contextCategoryDetails[fact.category].label}</span>
                  <span className="provenance-label">{provenanceLabel(fact.provenance)}</span>
                  <span>Checked {formatDate(fact.verifiedAt)}</span>
                  <span>{fact.mutableByCitizen ? "Can be corrected in this demo" : "Review with the source service"}</span>
                  {!!fact.usedBy.length && (
                    <span>Used for {fact.usedBy.map(humanizeContextIdentifier).join(", ")}</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="muted">No synthetic values are currently disclosed.</p>
        )}
      </section>
      {!!summary.missingFacts.length && (
        <section className="context-missing" aria-labelledby="context-missing-heading">
          <h3 id="context-missing-heading">Still needed</h3>
          <ul>
            {summary.missingFacts.map((fact) => (
              <li key={fact}>
                <span>{humanizeContextIdentifier(fact)}</span>
                <span className="provenance-label provenance-missing">Missing / needs confirmation</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="context-expiry">Consent expires {formatDate(summary.consentExpiresAt)}.</p>
    </div>
  );
}

export function SyntheticContextBanner() {
  const { activePersona, contextActive } = useAssistant();
  if (!contextActive || !activePersona) return null;
  return (
    <div className="synthetic-context-banner" role="status">
      <ShieldCheck size={20} aria-hidden="true" />
      <div>
        <strong>Synthetic citizen context</strong>
        <span>{SYNTHETIC_CONTEXT_NOTICE}</span>
      </div>
      <span>{activePersona.displayName} active</span>
    </div>
  );
}

function PersonaList({
  personas,
  activePersona,
  onChoose,
  onAnonymous,
}: {
  personas: DemoPersonaSummary[];
  activePersona: DemoPersonaSummary | null;
  onChoose: (persona: DemoPersonaSummary) => void;
  onAnonymous: () => void;
}) {
  return (
    <div className="persona-options" role="group" aria-label="Conversation context">
      <button
        type="button"
        className="persona-option"
        aria-pressed={!activePersona}
        onClick={onAnonymous}
      >
        <span className="persona-option-icon"><UserRound size={19} aria-hidden="true" /></span>
        <span><strong>Anonymous</strong><small>Default. No citizen context is used.</small></span>
        {!activePersona && <Check size={18} aria-hidden="true" />}
      </button>
      {personas.map((persona) => (
        <button
          type="button"
          className="persona-option"
          key={persona.id}
          aria-pressed={activePersona?.id === persona.id}
          onClick={() => onChoose(persona)}
        >
          <span className="persona-option-icon"><Database size={19} aria-hidden="true" /></span>
          <span>
            <strong>{persona.displayName} <em>synthetic</em></strong>
            <small>{persona.summary}</small>
          </span>
          <ChevronRight size={18} aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}

export function CitizenContextControl() {
  const assistant = useAssistant();
  const [chooserOpen, setChooserOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedPersona, setSelectedPersona] = useState<DemoPersonaSummary | null>(null);
  const [selectedCategories, setSelectedCategories] = useState<Set<ContextCategory>>(new Set());

  const selectedPlan = useMemo(
    () => selectedPersona ? personaPlan(selectedPersona) : null,
    [selectedPersona],
  );

  useEffect(() => {
    if (!assistant.contextActive) setDrawerOpen(false);
  }, [assistant.contextActive]);

  if (!assistant.capabilities.syntheticContextAvailable) return null;

  const choosePersona = (persona: DemoPersonaSummary) => {
    setSelectedPersona(persona);
    if (assistant.activePersona?.id === persona.id && assistant.consent) {
      setSelectedCategories(new Set(scopesToCategories(assistant.consent.scopes)));
    } else {
      setSelectedCategories(new Set(personaPlan(persona).proposedCategories));
    }
  };

  const returnToPersonaList = () => {
    setSelectedPersona(null);
    setSelectedCategories(new Set());
  };

  const closeChooser = (open: boolean) => {
    setChooserOpen(open);
    if (!open) returnToPersonaList();
  };

  const useAnonymous = () => {
    if (assistant.contextActive) void assistant.clearContext();
    closeChooser(false);
  };

  const saveConsent = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedPersona || !selectedCategories.size) return;
    const scopes = categoriesToScopes(selectedCategories);
    const success = assistant.activePersona?.id === selectedPersona.id
      ? await assistant.updateConsent(scopes)
      : await assistant.activatePersona(selectedPersona.id, scopes);
    if (success) closeChooser(false);
  };

  const openDrawer = (open: boolean) => {
    setDrawerOpen(open);
    if (open) void assistant.refreshContextSummary();
  };

  return (
    <div className="citizen-context-control">
      <Dialog.Root open={chooserOpen} onOpenChange={closeChooser}>
        <Dialog.Trigger
          render={<Button variant="ghost" className="context-selector-trigger" />}
          disabled={assistant.busy}
          aria-label={assistant.contextActive
            ? "Change synthetic persona or consent"
            : "Choose a synthetic demo persona"}
        >
          {assistant.contextActive && assistant.activePersona
            ? <><ShieldCheck size={15} aria-hidden="true" /><span>Synthetic: <strong>{assistant.activePersona.displayName}</strong></span></>
            : <><UserRound size={15} aria-hidden="true" /><span>Context: <strong>Anonymous</strong></span></>}
          <SlidersHorizontal size={15} aria-hidden="true" />
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Backdrop className="context-backdrop" />
          <Dialog.Popup className="context-consent-sheet">
            <div className="context-sheet-heading">
              <div>
                <Dialog.Title>{selectedPersona ? `Choose what ${selectedPersona.displayName} may share` : "Choose conversation context"}</Dialog.Title>
                <Dialog.Description>
                  {selectedPersona
                    ? selectedPlan?.explanation
                    : "Anonymous is the default. The other options are fixed fictional scenarios for this public demonstration."}
                </Dialog.Description>
              </div>
              <Dialog.Close render={<Button variant="ghost" size="icon" />} aria-label="Close context choices">
                <X size={20} aria-hidden="true" />
              </Dialog.Close>
            </div>
            <SyntheticNotice />
            {selectedPersona && selectedPlan ? (
              <form className="consent-form" onSubmit={saveConsent}>
                <div className="consent-purpose">
                  <span>Immediate purpose</span>
                  <strong>{selectedPlan.purpose}</strong>
                </div>
                <fieldset disabled={assistant.contextLoading || assistant.busy}>
                  <legend>Choose which categories the assistant may use for this conversation.</legend>
                  <p>Suggested categories start selected. You can remove any category now or later.</p>
                  <div className="consent-category-list">
                    {selectedPersona.availableCategories.map((category, index) => {
                      const details = contextCategoryDetails[category];
                      const checked = selectedCategories.has(category);
                      const required = selectedPlan.requiredCategories.includes(category);
                      const suggested = selectedPlan.proposedCategories.includes(category);
                      return (
                        <label className="consent-category" key={category}>
                          <input
                            autoFocus={index === 0}
                            type="checkbox"
                            checked={checked}
                            disabled={required}
                            onChange={(event) => {
                              setSelectedCategories((current) => {
                                const next = new Set(current);
                                if (event.target.checked) next.add(category);
                                else next.delete(category);
                                return next;
                              });
                            }}
                          />
                          <span className="consent-check" aria-hidden="true"><Check size={15} /></span>
                          <span>
                            <strong>{details.label}</strong>
                            <small>{details.reason}</small>
                            <em>{required
                              ? "Required for this synthetic flow"
                              : suggested
                                ? "Suggested for this flow"
                                : "Optional"}</em>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
                <div className="consent-assurance">
                  <p>All values are fictional. You can change or remove consent at any time.</p>
                  <p>No application is submitted and no real government record is accessed.</p>
                </div>
                {assistant.contextError && <p className="context-error" role="alert">{assistant.contextError}</p>}
                <div className="context-sheet-actions">
                  <Button type="button" variant="ghost" onClick={returnToPersonaList}>Back</Button>
                  <Button type="submit" disabled={!selectedCategories.size || assistant.contextLoading || assistant.busy}>
                    {assistant.contextLoading ? "Applying choices…" : assistant.activePersona?.id === selectedPersona.id ? "Save consent choices" : "Use selected context"}
                  </Button>
                </div>
              </form>
            ) : (
              <>
                <PersonaList
                  personas={assistant.personas}
                  activePersona={assistant.activePersona}
                  onChoose={choosePersona}
                  onAnonymous={useAnonymous}
                />
                {assistant.personasLoading && <p className="context-loading" role="status">Loading the fixed synthetic personas…</p>}
                {assistant.personaError && (
                  <div className="context-error" role="alert">
                    <p>{assistant.personaError}</p>
                    <Button variant="link" disabled={assistant.personasLoading} onClick={() => { void assistant.loadPersonas(); }}>
                      Try again
                    </Button>
                  </div>
                )}
              </>
            )}
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>

      {assistant.contextActive && assistant.activePersona && (
        <>
          <Dialog.Root open={drawerOpen} onOpenChange={openDrawer}>
            <Dialog.Trigger render={<Button variant="ghost" className="context-used-trigger" />}>
              What the assistant used
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Backdrop className="context-backdrop" />
              <Dialog.Popup className="context-drawer">
                <div className="context-sheet-heading">
                  <div>
                    <Dialog.Title>What the assistant used</Dialog.Title>
                    <Dialog.Description>A redacted view of the consented fictional information for this conversation.</Dialog.Description>
                  </div>
                  <Dialog.Close render={<Button variant="ghost" size="icon" />} aria-label="Close context details">
                    <X size={20} aria-hidden="true" />
                  </Dialog.Close>
                </div>
                <SyntheticNotice />
                {assistant.contextLoading && !assistant.contextSummary && <p className="context-loading" role="status">Checking the active synthetic context…</p>}
                {assistant.contextSummary && (
                  <ContextSummaryDetails
                    summary={assistant.contextSummary}
                    disabled={assistant.contextLoading}
                    requiredScopes={new Set(categoriesToScopes(
                      personaPlan(assistant.activePersona).requiredCategories,
                    ))}
                    onRevoke={(scope) => { void assistant.revokeConsentScope(scope); }}
                  />
                )}
                {assistant.contextError && <p className="context-error" role="alert">{assistant.contextError}</p>}
                <div className="context-drawer-actions">
                  <Button variant="outline" onClick={() => {
                    setDrawerOpen(false);
                    setChooserOpen(true);
                  }}>
                    <SlidersHorizontal size={16} aria-hidden="true" />
                    Change persona or consent
                  </Button>
                  <Button variant="ghost" onClick={() => { void assistant.clearContext(); }}>
                    <RotateCcw size={16} aria-hidden="true" />
                    Return to anonymous
                  </Button>
                </div>
              </Dialog.Popup>
            </Dialog.Portal>
          </Dialog.Root>
          <Button
            variant="ghost"
            className="context-clear-trigger"
            disabled={assistant.busy}
            onClick={() => { void assistant.clearContext(); }}
          >
            Clear
          </Button>
        </>
      )}
    </div>
  );
}
