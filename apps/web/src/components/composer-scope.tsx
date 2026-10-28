"use client";

import { useEffect, useRef, useState } from "react";
import { Popover } from "@base-ui/react/popover";
import { Check, X } from "lucide-react";
import { useAssistant } from "./assistant-provider";
import { Button } from "./ui/button";

export function ComposerScope() {
  const { catalog, catalogError, loading, load, selected, selectedId, selectJourney, clearJourney, busy } = useAssistant();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (busy) setOpen(false); }, [busy]);
  return <div className="composer-scope" role="group" aria-label="Conversation scope">
    <span className="composer-scope-label">{selectedId
      ? <>Pathway: <strong>{selected?.title ?? "Selected guided pathway"}</strong></>
      : "General B.C. chat"}</span>
    <div className="composer-scope-actions">
      <Popover.Root open={open && !busy} onOpenChange={setOpen}>
        <Popover.Trigger
          ref={trigger}
          render={<Button variant="ghost" className="composer-scope-action" />}
          disabled={busy}
          aria-label={selectedId ? "Change pathway" : "Choose a guided pathway"}
        >{selectedId ? "Change" : "Choose a pathway"}</Popover.Trigger>
        <Popover.Portal>
          <Popover.Positioner className="scope-positioner" side="top" align="end" sideOffset={12} collisionPadding={16}>
            <Popover.Popup className="scope-picker">
              <div className="scope-picker-heading">
                <Popover.Title>Choose a pathway</Popover.Title>
                <Popover.Close render={<Button variant="ghost" size="icon" />} aria-label="Close pathway choices"><X size={18} aria-hidden="true" /></Popover.Close>
              </div>
              <Popover.Description>Optional: focus your questions on a service, or keep asking about B.C. government in general.</Popover.Description>
              <div className="scope-options" role="group" aria-label="Available conversation scopes">
                <Button variant="ghost" aria-pressed={!selectedId} onClick={() => { clearJourney(); setOpen(false); }}>
                  <span>General B.C. chat</span>{!selectedId && <Check size={16} aria-hidden="true" />}
                </Button>
                {catalog?.journeys.map((journey) => <Button key={journey.id} variant="ghost" aria-pressed={selectedId === journey.id} onClick={() => { selectJourney(journey); setOpen(false); }}>
                  <span>{journey.title}</span>{selectedId === journey.id && <Check size={16} aria-hidden="true" />}
                </Button>)}
              </div>
              {!catalog && loading && <p className="scope-availability" role="status">Loading guided pathways. You can still ask a general question.</p>}
              {catalogError && <div className="scope-availability"><p>{catalogError}</p><Button variant="link" disabled={loading} onClick={() => { void load(); }}>Reload pathways</Button></div>}
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      </Popover.Root>
      {selectedId && <Button variant="ghost" className="composer-scope-action" disabled={busy} aria-label="Clear pathway and use general B.C. chat" onClick={() => {
        clearJourney();
        trigger.current?.focus();
      }}>Clear</Button>}
    </div>
  </div>;
}
