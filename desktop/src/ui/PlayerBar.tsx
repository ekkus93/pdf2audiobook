import { IconButton } from "./IconButton";
import { LinearProgress } from "./Progress";
import { Icon } from "./Icon";
import "./shell.css";

interface PlayerBarProps {
  title: string;
  subtitle: string;
  playing: boolean;
  /** 0 to 1. */
  position: number;
  onTogglePlay: () => void;
  onPrevious?: () => void;
  onNext?: () => void;
  onClose: () => void;
}

/** The persistent bottom player shown once a chapter is playing (spec D11.e). */
export function PlayerBar({
  title,
  subtitle,
  playing,
  position,
  onTogglePlay,
  onPrevious,
  onNext,
  onClose,
}: PlayerBarProps) {
  return (
    <section className="player-bar" aria-label="Player">
      <div className="player-art" aria-hidden="true">
        <Icon name="graphic_eq" size={28} />
      </div>
      <div className="player-text">
        <div className="player-title">{title}</div>
        <div className="player-subtitle">{subtitle}</div>
        <LinearProgress value={position} label="Playback position" />
      </div>
      <div className="player-controls">
        <IconButton icon="skip_previous" label="Previous chapter" onClick={onPrevious} disabled={!onPrevious} />
        <IconButton
          icon={playing ? "pause" : "play_arrow"}
          label={playing ? "Pause" : "Play"}
          variant="filled"
          onClick={onTogglePlay}
        />
        <IconButton icon="skip_next" label="Next chapter" onClick={onNext} disabled={!onNext} />
        <IconButton icon="close" label="Close player" onClick={onClose} />
      </div>
    </section>
  );
}
