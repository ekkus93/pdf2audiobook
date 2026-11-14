import "@material/web/chips/chip-set.js";
import "@material/web/chips/filter-chip.js";
import "@material/web/chips/assist-chip.js";
import { type ReactNode, useRef } from "react";
import { Icon } from "./Icon";
import type { IconName } from "../theme/icons.generated";
import { useElementEvent } from "./useElementEvent";

export function ChipSet({ children }: { children: ReactNode }) {
  return <md-chip-set>{children}</md-chip-set>;
}

interface FilterChipProps {
  label: string;
  selected: boolean;
  onChange: (selected: boolean) => void;
}

export function FilterChip({ label, selected, onChange }: FilterChipProps) {
  const ref = useRef<HTMLElement>(null);
  useElementEvent(ref, "click", () => onChange(!selected));
  return <md-filter-chip ref={ref} label={label} selected={selected || undefined} />;
}

interface AssistChipProps {
  label: string;
  icon?: IconName;
  onClick?: () => void;
}

export function AssistChip({ label, icon, onClick }: AssistChipProps) {
  const ref = useRef<HTMLElement>(null);
  useElementEvent(ref, "click", onClick);
  return (
    <md-assist-chip ref={ref} label={label}>
      {icon ? <Icon name={icon} slot="icon" size={18} /> : null}
    </md-assist-chip>
  );
}
