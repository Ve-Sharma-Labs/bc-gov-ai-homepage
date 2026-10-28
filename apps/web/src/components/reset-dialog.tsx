"use client";

import { Button, Dialog, DialogTrigger, Heading, Modal, ModalOverlay } from "react-aria-components";
import { RotateCcw } from "lucide-react";

export function ResetDialog({ onReset }: { onReset: () => void }) {
  return (
    <DialogTrigger>
      <Button className="text-button reset-button"><RotateCcw size={15} aria-hidden="true" />Start over</Button>
      <ModalOverlay className="modal-overlay" isDismissable>
        <Modal className="modal">
          <Dialog className="dialog">
            {({ close }) => <>
              <Heading slot="title">Start fresh?</Heading>
              <p>This clears the conversation, your draft and checklist progress from this page. Any active response will stop. Your theme choice stays.</p>
              <p className="muted">This is not a request to delete records held by an official service or AI provider.</p>
              <div className="dialog-actions">
                <Button className="secondary-button" onPress={close}>Keep this conversation</Button>
                <Button className="primary-button" onPress={() => { onReset(); close(); }}>Start over</Button>
              </div>
            </>}
          </Dialog>
        </Modal>
      </ModalOverlay>
    </DialogTrigger>
  );
}
