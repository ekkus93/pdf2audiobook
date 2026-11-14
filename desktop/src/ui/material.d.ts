// JSX types for the @material/web elements the wrappers in this folder use.
import type { DetailedHTMLProps, HTMLAttributes, Ref } from "react";

type Element<Props> = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> &
  Props & { ref?: Ref<HTMLElement>; class?: string };

interface ButtonProps {
  disabled?: boolean;
  type?: "button" | "submit" | "reset";
  "has-icon"?: boolean;
  "trailing-icon"?: boolean;
}

interface FieldProps {
  label?: string;
  value?: string;
  type?: string;
  disabled?: boolean;
  required?: boolean;
  error?: boolean;
  "error-text"?: string;
  "supporting-text"?: string;
  placeholder?: string;
  min?: string;
  max?: string;
  step?: string;
}

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "md-filled-button": Element<ButtonProps>;
      "md-filled-tonal-button": Element<ButtonProps>;
      "md-outlined-button": Element<ButtonProps>;
      "md-text-button": Element<ButtonProps>;
      "md-icon-button": Element<{ disabled?: boolean; toggle?: boolean; selected?: boolean }>;
      "md-filled-icon-button": Element<{ disabled?: boolean; toggle?: boolean; selected?: boolean }>;
      "md-filled-tonal-icon-button": Element<{ disabled?: boolean }>;
      "md-outlined-text-field": Element<FieldProps>;
      "md-outlined-select": Element<{ label?: string; disabled?: boolean; value?: string }>;
      "md-select-option": Element<{ value?: string; selected?: boolean; disabled?: boolean }>;
      "md-switch": Element<{ selected?: boolean; disabled?: boolean; icons?: boolean }>;
      "md-checkbox": Element<{ checked?: boolean; disabled?: boolean }>;
      "md-filter-chip": Element<{ label?: string; selected?: boolean; disabled?: boolean }>;
      "md-assist-chip": Element<{ label?: string; disabled?: boolean }>;
      "md-chip-set": Element<object>;
      "md-dialog": Element<{ open?: boolean }>;
      "md-linear-progress": Element<{ value?: number; max?: number; indeterminate?: boolean }>;
      "md-circular-progress": Element<{ value?: number; max?: number; indeterminate?: boolean }>;
      "md-slider": Element<{
        value?: number;
        min?: number;
        max?: number;
        step?: number;
        labeled?: boolean;
        disabled?: boolean;
      }>;
      "md-ripple": Element<object>;
      "md-focus-ring": Element<{ inward?: boolean }>;
      "md-elevation": Element<object>;
    }
  }
}
