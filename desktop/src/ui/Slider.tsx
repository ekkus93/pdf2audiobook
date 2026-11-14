import "@material/web/slider/slider.js";
import { useRef } from "react";
import { useElementEvent } from "./useElementEvent";

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}

export function Slider({ label, value, min, max, step, onChange }: SliderProps) {
  const ref = useRef<HTMLElement>(null);
  useElementEvent(ref, "change", (event) =>
    onChange(Number((event.target as HTMLElement & { value: number }).value)),
  );
  return (
    <md-slider
      ref={ref}
      aria-label={label}
      value={value}
      min={min}
      max={max}
      step={step}
      labeled
    />
  );
}
