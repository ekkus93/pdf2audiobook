import type { ReactNode } from "react";
import "./shell.css";

interface TopAppBarProps {
  title: string;
  /** Trailing actions, such as icon buttons. */
  actions?: ReactNode;
  /** Leading navigation, such as a back button. */
  leading?: ReactNode;
}

/** Material 3 small top app bar. */
export function TopAppBar({ title, actions, leading }: TopAppBarProps) {
  return (
    <header className="top-app-bar">
      {leading}
      <h1 className="top-app-bar-title">{title}</h1>
      <div className="top-app-bar-actions">{actions}</div>
    </header>
  );
}
