import "@material/web/fab/fab.js";
import "./buttons.css";
import { useRef } from "react";
import { Icon } from "./Icon";
import type { IconName } from "../theme/icons.generated";
import { useElementEvent } from "./useElementEvent";

interface FabProps {
  icon: IconName;
  /** Visible label: an extended FAB. */
  label: string;
  onClick: () => void;
  variant?: "primary" | "secondary" | "tertiary" | "surface";
}

/** A Material 3 extended floating action button for a screen's main action. */
export function Fab({ icon, label, onClick, variant = "primary" }: FabProps) {
  const ref = useRef<HTMLElement>(null);
  useElementEvent(ref, "click", onClick);
  return (
    <md-fab ref={ref} label={label} variant={variant} aria-label={label}>
      <Icon name={icon} slot="icon" />
    </md-fab>
  );
}
