import "@material/web/checkbox/checkbox.js";
import { useId, useRef } from "react";
import { useElementEvent } from "./useElementEvent";

interface CheckboxProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export function Checkbox({ label, checked, onChange }: CheckboxProps) {
  const ref = useRef<HTMLElement>(null);
  const id = useId();
  useElementEvent(ref, "change", (event) =>
    onChange(Boolean((event.target as HTMLElement & { checked: boolean }).checked)),
  );
  return (
    <label className="checkbox-row" htmlFor={id}>
      <md-checkbox ref={ref} id={id} checked={checked || undefined} />
      <span>{label}</span>
    </label>
  );
}
