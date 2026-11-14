import "@material/web/switch/switch.js";
import { useId, useRef } from "react";
import { useElementEvent } from "./useElementEvent";

interface SwitchProps {
  label: string;
  selected: boolean;
  onChange: (selected: boolean) => void;
  disabled?: boolean;
}

/** A labelled Material 3 switch. */
export function Switch({ label, selected, onChange, disabled }: SwitchProps) {
  const ref = useRef<HTMLElement>(null);
  const id = useId();
  useElementEvent(ref, "change", (event) =>
    onChange(Boolean((event.target as HTMLElement & { selected: boolean }).selected)),
  );
  return (
    <label className="switch-row" htmlFor={id}>
      <span>{label}</span>
      <md-switch ref={ref} id={id} selected={selected || undefined} disabled={disabled || undefined} icons />
    </label>
  );
}
