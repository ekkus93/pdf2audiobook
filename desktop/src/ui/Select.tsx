import "@material/web/select/outlined-select.js";
import "@material/web/select/select-option.js";
import { useRef } from "react";
import { useElementEvent } from "./useElementEvent";

interface SelectProps {
  label: string;
  value: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export function Select({ label, value, options, onChange, disabled }: SelectProps) {
  const ref = useRef<HTMLElement>(null);
  useElementEvent(ref, "change", (event) =>
    onChange((event.target as HTMLElement & { value: string }).value),
  );
  return (
    <md-outlined-select ref={ref} label={label} disabled={disabled || undefined}>
      {options.map((option) => (
        <md-select-option key={option.value} value={option.value} selected={option.value === value || undefined}>
          <div slot="headline">{option.label}</div>
        </md-select-option>
      ))}
    </md-outlined-select>
  );
}
