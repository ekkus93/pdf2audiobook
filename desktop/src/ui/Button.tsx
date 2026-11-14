import "@material/web/button/filled-button.js";
import "@material/web/button/filled-tonal-button.js";
import "@material/web/button/outlined-button.js";
import "@material/web/button/text-button.js";
import { type ReactNode, useRef } from "react";
import { Icon } from "./Icon";
import type { IconName } from "../theme/icons.generated";
import { useElementEvent } from "./useElementEvent";

const TAGS = {
  filled: "md-filled-button",
  tonal: "md-filled-tonal-button",
  outlined: "md-outlined-button",
  text: "md-text-button",
} as const;

interface ButtonProps {
  variant?: keyof typeof TAGS;
  icon?: IconName;
  disabled?: boolean;
  onClick?: () => void;
  children: ReactNode;
}

/** A Material 3 common button. */
export function Button({ variant = "filled", icon, disabled, onClick, children }: ButtonProps) {
  const ref = useRef<HTMLElement>(null);
  useElementEvent(ref, "click", onClick ? () => !disabled && onClick() : undefined);
  const Tag = TAGS[variant];
  return (
    <Tag ref={ref} disabled={disabled || undefined} has-icon={icon ? true : undefined}>
      {icon ? <Icon name={icon} slot="icon" size={18} /> : null}
      {children}
    </Tag>
  );
}
