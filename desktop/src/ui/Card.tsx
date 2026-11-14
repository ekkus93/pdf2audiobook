import "@material/web/ripple/ripple.js";
import "@material/web/focus/md-focus-ring.js";
import type { ReactNode } from "react";
import "./shell.css";

interface CardProps {
  children: ReactNode;
  variant?: "filled" | "elevated" | "outlined";
  /** Makes the whole card a button with this accessible name. */
  onOpen?: () => void;
  label?: string;
}

/** Material 3 card; depth comes from the surface-container steps, not shadows. */
export function Card({ children, variant = "filled", onOpen, label }: CardProps) {
  const className = `card card-${variant}`;
  if (!onOpen) {
    return <section className={className} aria-label={label}>{children}</section>;
  }
  return (
    <button type="button" className={`${className} card-interactive`} aria-label={label} onClick={onOpen}>
      <md-ripple />
      <md-focus-ring />
      {children}
    </button>
  );
}
