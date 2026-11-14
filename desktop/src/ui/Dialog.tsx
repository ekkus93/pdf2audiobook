import "@material/web/dialog/dialog.js";
import { type ReactNode, useRef } from "react";
import { useElementEvent } from "./useElementEvent";

interface DialogProps {
  open: boolean;
  headline: string;
  children: ReactNode;
  actions: ReactNode;
  /** Called when the dialog closes by any means (Escape, scrim, or an action). */
  onClose: () => void;
}

/** A Material 3 dialog. The caller owns `open`; closing always reports back through `onClose`. */
export function Dialog({ open, headline, children, actions, onClose }: DialogProps) {
  const ref = useRef<HTMLElement>(null);
  useElementEvent(ref, "closed", onClose);
  return (
    <md-dialog ref={ref} open={open || undefined}>
      <div slot="headline">{headline}</div>
      <div slot="content">{children}</div>
      <div slot="actions">{actions}</div>
    </md-dialog>
  );
}
