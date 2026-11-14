import "@material/web/textfield/outlined-text-field.js";
import { useRef } from "react";
import { useElementEvent } from "./useElementEvent";

interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "number" | "url";
  supportingText?: string;
  errorText?: string;
  disabled?: boolean;
  required?: boolean;
  min?: number;
  max?: number;
  step?: number;
}

/** A Material 3 outlined text field. `errorText` marks it invalid and explains why. */
export function TextField({
  label,
  value,
  onChange,
  type = "text",
  supportingText,
  errorText,
  disabled,
  required,
  min,
  max,
  step,
}: TextFieldProps) {
  const ref = useRef<HTMLElement>(null);
  useElementEvent<InputEvent>(ref, "input", (event) =>
    onChange((event.target as HTMLInputElement).value),
  );
  return (
    <md-outlined-text-field
      ref={ref}
      label={label}
      value={value}
      type={type}
      supporting-text={supportingText}
      error={errorText ? true : undefined}
      error-text={errorText}
      disabled={disabled || undefined}
      required={required || undefined}
      min={min?.toString()}
      max={max?.toString()}
      step={step?.toString()}
    />
  );
}
