import "@material/web/progress/linear-progress.js";
import "@material/web/progress/circular-progress.js";

interface ProgressProps {
  /** 0 to 1; omit for an indeterminate indicator. */
  value?: number;
  label: string;
}

export function LinearProgress({ value, label }: ProgressProps) {
  return (
    <md-linear-progress
      role="progressbar"
      aria-label={label}
      aria-valuenow={value === undefined ? undefined : Math.round(value * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      value={value}
      indeterminate={value === undefined || undefined}
    />
  );
}

export function CircularProgress({ value, label }: ProgressProps) {
  return (
    <md-circular-progress
      role="progressbar"
      aria-label={label}
      value={value}
      indeterminate={value === undefined || undefined}
    />
  );
}
