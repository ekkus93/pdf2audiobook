import { ICONS, type IconName } from "../theme/icons.generated";
import "./icon.css";

interface IconProps {
  name: IconName;
  /** Filled glyph instead of the outline (the FILL axis). */
  filled?: boolean;
  size?: number;
  slot?: string;
  className?: string;
}

/** A Material Symbols Rounded icon drawn from the bundled subset font; always decorative. */
export function Icon({ name, filled = false, size = 24, slot, className }: IconProps) {
  return (
    <span
      aria-hidden="true"
      data-icon={name}
      slot={slot}
      className={["icon", className].filter(Boolean).join(" ")}
      style={{
        fontSize: size,
        fontVariationSettings: `"FILL" ${filled ? 1 : 0}, "wght" 400, "GRAD" 0, "opsz" ${size}`,
      }}
    >
      {String.fromCodePoint(ICONS[name])}
    </span>
  );
}
