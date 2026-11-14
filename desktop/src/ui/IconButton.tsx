import "@material/web/iconbutton/icon-button.js";
import "@material/web/iconbutton/filled-icon-button.js";
import "@material/web/iconbutton/filled-tonal-icon-button.js";
import "./buttons.css";
import { useRef } from "react";
import { Icon } from "./Icon";
import type { IconName } from "../theme/icons.generated";
import { useElementEvent } from "./useElementEvent";

const TAGS = {
  standard: "md-icon-button",
  filled: "md-filled-icon-button",
  tonal: "md-filled-tonal-icon-button",
} as const;

interface IconButtonProps {
  icon: IconName;
  /** Accessible name; icon buttons have no visible text. */
  label: string;
  variant?: keyof typeof TAGS;
  disabled?: boolean;
  onClick?: () => void;
}

export function IconButton({ icon, label, variant = "standard", disabled, onClick }: IconButtonProps) {
  const ref = useRef<HTMLElement>(null);
  useElementEvent(ref, "click", onClick ? () => !disabled && onClick() : undefined);
  const Tag = TAGS[variant];
  return (
    <Tag ref={ref} aria-label={label} title={label} disabled={disabled || undefined}>
      <Icon name={icon} />
    </Tag>
  );
}
