import { Slider } from "../ui/Slider";
import { TEMPERATURE } from "./bookOptions";

/** The Kitten 2 sampling temperature, shown only when Kitten 2 speaks (desktop temperature spec DT3). */
export function TemperatureControl({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  return (
    <>
      <div className="slider-row">
        <span className="label-large">Temperature</span>
        <Slider label="Temperature" value={value} min={TEMPERATURE.min} max={TEMPERATURE.max} step={TEMPERATURE.step} onChange={onChange} />
        <span className="body-medium slider-value">{value.toFixed(2)}</span>
      </div>
      <p className="body-small on-surface-variant">
        KittenTTS 2 only. Lower keeps the narration closer to the text; higher can sound more expressive but slips more often.
        The default is {TEMPERATURE.fallback}.
      </p>
    </>
  );
}
