import type { ReactNode } from "react";
import "./shell.css";

interface SnackbarProps {
  message: string | null;
  action?: ReactNode;
}

/** Material 3 snackbar: a brief message at the bottom, announced politely to screen readers. */
export function Snackbar({ message, action }: SnackbarProps) {
  return (
    <div className="snackbar-region" role="status" aria-live="polite">
      {message ? (
        <div className="snackbar">
          <span className="snackbar-message">{message}</span>
          {action}
        </div>
      ) : null}
    </div>
  );
}
