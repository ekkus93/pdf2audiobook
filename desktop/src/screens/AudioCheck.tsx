import { useEffect, useState } from "react";
import { bookAudio, errorMessage, run } from "../engine/api";
import type {
  AsrModel,
  AsrModels,
  AsrReadiness,
  AudioFile,
  AudioReport,
  ChapterVerification,
  InspectManifest,
  Request,
  VerificationFlag,
  Voices,
} from "../engine/types";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { Icon } from "../ui/Icon";
import { Select } from "../ui/Select";
import { Slider } from "../ui/Slider";
import "./audio.css";

const MODEL_NAMES: Record<AsrModel, string> = {
  whisper: "Whisper",
  wav2vec2: "Wav2Vec2",
  vosk: "Vosk",
};

const VERDICTS: Record<ChapterVerification["status"], string> = {
  no_mismatch_detected: "No mismatch detected",
  possible_mismatch: "Possible mismatch",
  model_disagreement: "Models disagree",
  verification_unavailable: "Not checked",
};

const REASONS: Record<string, string> = {
  audio_missing: "no audio to check",
  audio_stale: "the audio no longer matches its chapter text; convert it again first",
  narration_not_spoken: "the chapter text or pronunciations changed since it was spoken, so it wasn't compared; speak it again first",
  no_models: "no speech recognizer was available",
  unsupported_language: "only English voices can be checked",
  model_not_installed: "the recognizer isn't installed",
  model_not_downloaded: "the recognizer's model isn't downloaded",
  model_failed: "a recognizer failed",
  cancelled: "the check was stopped",
};

const KINDS: Record<VerificationFlag["kind"], string> = {
  insertion: "Extra words heard",
  omission: "Words not heard",
  substitution: "Different words heard",
};

/** Seconds of audio to play before a flagged passage, for context. */
export const LEAD_IN = 2;

/** 75.4 → "1:15". */
export function clock(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "?";
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** 1528006491 → "1.5 GB". */
export function size(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / 1e6))} MB`;
}

/** Models whose package is installed but whose weights still need downloading. */
export function downloadable(models: AsrReadiness[]): AsrReadiness[] {
  return models.filter((model) => !model.ready && model.reason === "model_not_downloaded");
}

/** Whether a flag still needs a listen: confirmed by two models and not yet reviewed. */
export function needsListening(flag: VerificationFlag): boolean {
  return flag.confirmed && !flag.reviewed;
}

/** "Whisper and Vosk", "Vosk only". */
export function heardBy(models: AsrModel[]): string {
  const names = models.map((model) => MODEL_NAMES[model]);
  if (names.length === 1) return `${names[0]} only`;
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** Chapters worth showing: anything but a clean, current result. */
export function chaptersToShow(report: AudioReport): ChapterVerification[] {
  const stale = new Set(report.stale);
  return (report.report?.chapters ?? []).filter((chapter) => chapter.status !== "no_mismatch_detected" || stale.has(chapter.number));
}

interface AudioCheckProps {
  manifest: string;
  workspace: string;
  inspect: InspectManifest;
  voices: Voices | null;
  /** The voice and speed the book's options would use, to start a retry from. */
  voice: string;
  speed: number;
  /** Starts a long run (verify, speak again) for this book. */
  onStart: (request: Request) => void;
  /** Plays chapter `index` of `files` from `start` seconds. */
  onPlay: (files: AudioFile[], index: number, start?: number) => void;
  /** Opens the review page to correct a chapter's text. */
  onEditNarration: () => void;
}

type Loaded = { phase: "loading" } | { phase: "failed"; message: string } | { phase: "ready"; models: AsrReadiness[]; report: AudioReport };

function isModels(value: unknown): value is AsrModels {
  return typeof value === "object" && value !== null && Array.isArray((value as AsrModels).models);
}

/** The shape the panel relies on (contracts/audio-report.schema.json); anything else is unreadable. */
export function isReport(value: unknown): value is AudioReport {
  if (typeof value !== "object" || value === null) return false;
  const { report, stale } = value as AudioReport;
  if (!Array.isArray(stale) || !stale.every((n) => Number.isInteger(n))) return false;
  if (report === null) return true;
  return (
    typeof report === "object" &&
    Array.isArray(report.chapters) &&
    report.chapters.every((chapter) => Number.isInteger(chapter?.number) && Array.isArray(chapter.flags) && Array.isArray(chapter.models))
  );
}

async function load(manifest: string): Promise<Loaded> {
  try {
    const [models, report] = await Promise.all([
      run<AsrModels>({ command: "asr_list" }),
      run<AudioReport>({ command: "audio_report", manifest }),
    ]);
    if (models.outcome !== "success" || report.outcome !== "success") {
      const failed = [models, report].find((outcome) => outcome.outcome === "failed");
      const message = failed?.outcome === "failed" ? failed.error.message : "The engine returned an unreadable result";
      return { phase: "failed", message };
    }
    if (!isModels(models.result) || !isReport(report.result)) {
      return { phase: "failed", message: "The engine returned an unreadable result" };
    }
    return { phase: "ready", models: models.result.models, report: report.result };
  } catch (error) {
    return { phase: "failed", message: errorMessage(error) };
  }
}

/**
 * Audio check (verification spec §7): which speech recognizers are ready, "Verify existing
 * audio", each chapter's result with the passages the models heard differently, and the repair
 * actions of §6. Nothing here changes audio or text by itself.
 */
export function AudioCheck({ manifest, workspace, inspect, voices, voice, speed, onStart, onPlay, onEditNarration }: AudioCheckProps) {
  const [loaded, setLoaded] = useState<Loaded>({ phase: "loading" });
  const [files, setFiles] = useState<AudioFile[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [setup, setSetup] = useState(false);
  const [retry, setRetry] = useState<number | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let current = true;
    void load(manifest).then((next) => current && setLoaded(next));
    void bookAudio(workspace)
      .then((found) => current && setFiles(found))
      .catch(() => current && setFiles([]));
    return () => {
      current = false;
    };
  }, [manifest, workspace, inspect, reload]);

  if (loaded.phase === "loading") {
    return (
      <section className="audio audio-check" aria-labelledby="check-heading">
        <h3 id="check-heading" className="title-medium">
          Audio check
        </h3>
        <p className="body-medium on-surface-variant">Loading…</p>
      </section>
    );
  }
  if (loaded.phase === "failed") {
    return (
      <section className="audio audio-check" aria-labelledby="check-heading">
        <h3 id="check-heading" className="title-medium">
          Audio check
        </h3>
        <p className="body-medium audio-problem">{loaded.message}</p>
      </section>
    );
  }

  const { models, report } = loaded;
  const ready = models.filter((model) => model.ready);
  const converted = files.length;
  const titles = new Map(inspect.chapters.map((chapter) => [chapter.number, chapter.title]));
  const fileOf = (number: number) => files.find((file) => file.name.startsWith(`${String(number).padStart(3, "0")} - `)) ?? null;
  const shown = chaptersToShow(report);
  const checked = report.report?.chapters.length ?? 0;
  const clean = (report.report?.chapters ?? []).filter(
    (c) => c.status === "no_mismatch_detected" && !report.stale.includes(c.number),
  ).length;

  const listen = (number: number, flag: VerificationFlag) => {
    const file = fileOf(number);
    if (!file) return;
    onPlay(files, files.indexOf(file), flag.start === null ? 0 : Math.max(0, flag.start - LEAD_IN));
  };

  const mark = async (number: number, index: number, undo: boolean) => {
    setProblem(null);
    try {
      const outcome = await run(
        {
          command: "audio_dismiss",
          manifest,
          chapter: number,
          flag: index,
          undo,
        },
        workspace,
      );
      if (outcome.outcome === "failed") setProblem(outcome.error.message);
      setReload((value) => value + 1);
    } catch (error) {
      setProblem(errorMessage(error));
    }
  };

  return (
    <section className="audio audio-check" aria-labelledby="check-heading">
      <div className="audio-top">
        <div>
          <h3 id="check-heading" className="title-medium">
            Audio check
          </h3>
          <p className="body-medium on-surface-variant">
            {checked === 0
              ? "Not checked yet."
              : `${checked} chapter${checked === 1 ? "" : "s"} checked · ${clean} with no mismatch detected`}
          </p>
        </div>
        <Button
          variant="tonal"
          icon="hearing"
          disabled={ready.length === 0 || converted === 0}
          onClick={() => onStart({ command: "verify_audio", manifest })}
        >
          Verify existing audio
        </Button>
      </div>
      <ModelList models={models} onSetup={() => setSetup(true)} />
      <p className="body-small on-surface-variant audio-check-limits">
        Local speech recognizers listen to each chapter and compare what they hear with the text that was spoken. A flag is a reason to
        listen, not proof of a mistake: recognizers mishear names, numbers and unusual words, and they were tested on synthetic speech.
        Nothing leaves this computer, and nothing is changed until you choose.
      </p>
      {report.stale.length > 0 ? (
        <p className="body-medium audio-check-stale" role="status">
          <Icon name="warning" size={18} /> Out of date for chapter
          {report.stale.length === 1 ? "" : "s"} {report.stale.join(", ")}: the audio or its text changed since the check. Verify again.
        </p>
      ) : null}
      {shown.length > 0 ? (
        <ol className="check-list" aria-label="Checked chapters">
          {shown.map((chapter) => (
            <ChapterResult
              key={chapter.number}
              chapter={chapter}
              title={titles.get(chapter.number) ?? ""}
              stale={report.stale.includes(chapter.number)}
              playable={fileOf(chapter.number) !== null}
              onListen={(flag) => listen(chapter.number, flag)}
              onMark={(index, undo) => void mark(chapter.number, index, undo)}
              onRetry={() => setRetry(chapter.number)}
              onEditNarration={onEditNarration}
            />
          ))}
        </ol>
      ) : null}
      {problem ? (
        <p className="body-medium audio-problem" role="status">
          {problem}
        </p>
      ) : null}
      <SetupDialog open={setup} models={models} onClose={() => setSetup(false)} onDone={() => setReload((value) => value + 1)} />
      {retry !== null ? (
        <RetryDialog
          key={retry}
          chapter={retry}
          voices={voices}
          voice={voice}
          speed={speed}
          verify={ready.length > 0}
          onClose={() => setRetry(null)}
          onStart={(request) => {
            setRetry(null);
            onStart({ ...request, manifest });
          }}
        />
      ) : null}
    </section>
  );
}

function ModelList({ models, onSetup }: { models: AsrReadiness[]; onSetup: () => void }) {
  const missing = downloadable(models);
  const uninstalled = models.filter((model) => model.reason === "model_not_installed");
  return (
    <div className="check-models">
      <ul className="check-model-list" aria-label="Speech recognizers">
        {models.map((model) => (
          <li key={model.model} className={`check-model ${model.ready ? "check-model-ready" : ""}`}>
            <Icon name={model.ready ? "check_circle" : "hourglass_top"} filled size={16} />
            {MODEL_NAMES[model.model]}
            <span className="on-surface-variant">
              {model.ready
                ? "ready"
                : model.reason === "model_not_downloaded"
                  ? `not downloaded (${size(model.size_bytes)})`
                  : "not installed"}
            </span>
          </li>
        ))}
      </ul>
      {missing.length > 0 ? (
        <Button variant="text" icon="download" onClick={onSetup}>
          Download recognizers…
        </Button>
      ) : null}
      {uninstalled.length > 0 ? (
        <p className="body-small on-surface-variant">
          {uninstalled.length === models.length ? "The speech recognizers aren't installed. " : "Some recognizers aren't installed. "}
          They're optional; install them with <code>uv sync --extra asr</code> (see the README, “Installing the speech recognizers”). Two of
          the three are needed to confirm a flag.
        </p>
      ) : null}
    </div>
  );
}

interface ChapterResultProps {
  chapter: ChapterVerification;
  title: string;
  stale: boolean;
  playable: boolean;
  onListen: (flag: VerificationFlag) => void;
  onMark: (index: number, undo: boolean) => void;
  onRetry: () => void;
  onEditNarration: () => void;
}

function ChapterResult({ chapter, title, stale, playable, onListen, onMark, onRetry, onEditNarration }: ChapterResultProps) {
  const voted = chapter.models.filter((model) => model.outcome === "ok").map((model) => MODEL_NAMES[model.model]);
  return (
    <li className={`check-chapter check-${chapter.status}`} aria-label={`Chapter ${chapter.number}: ${VERDICTS[chapter.status]}`}>
      <div className="check-chapter-top">
        <span className="chapter-number">{chapter.number}</span>
        <div>
          <div className="title-small">{title}</div>
          <div className="body-medium">
            {VERDICTS[chapter.status]}
            {chapter.reason ? ` — ${REASONS[chapter.reason] ?? "see the report"}` : ""}
            {stale ? " · out of date" : ""}
          </div>
          <div className="body-small on-surface-variant">
            {voted.length ? `Checked by ${voted.join(", ")}` : "No recognizer finished"}
            {chapter.partial ? " · partial: fewer than three recognizers voted" : ""}
          </div>
        </div>
      </div>
      {chapter.flags.length > 0 ? (
        <ul className="check-flags" aria-label={`Passages in chapter ${chapter.number}`}>
          {chapter.flags.map((flag, index) => (
            <li key={`${flag.ref_start}-${flag.kind}-${index}`} className={`check-flag ${flag.reviewed ? "check-flag-reviewed" : ""}`}>
              <div className="check-flag-head">
                <span className="label-large">{KINDS[flag.kind]}</span>
                <span className="body-small on-surface-variant">
                  at {clock(flag.start)} ·{" "}
                  {flag.confirmed ? `heard by ${heardBy(flag.models)}` : `${heardBy(flag.models)}: the others disagree`}
                  {flag.reviewed ? " · reviewed" : ""}
                </span>
              </div>
              <p className="body-medium check-excerpt">
                <span className="on-surface-variant">…{flag.before} </span>
                <mark>{flag.expected || "(nothing)"}</mark>
                <span className="on-surface-variant"> {flag.after}…</span>
              </p>
              <dl className="check-heard body-small">
                {Object.entries(flag.heard).map(([model, words]) => (
                  <div key={model}>
                    <dt>{MODEL_NAMES[model as AsrModel]} heard</dt>
                    <dd>{words || "(nothing)"}</dd>
                  </div>
                ))}
              </dl>
              <div className="button-row">
                <Button variant="text" icon="play_arrow" disabled={!playable || flag.start === null} onClick={() => onListen(flag)}>
                  Listen
                </Button>
                <Button variant="text" icon={flag.reviewed ? "undo" : "check"} onClick={() => onMark(index, flag.reviewed)}>
                  {flag.reviewed ? "Not reviewed" : "Sounds right"}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {chapter.status !== "no_mismatch_detected" || stale ? (
        <div className="button-row check-repair">
          <Button variant="tonal" icon="replay" onClick={onRetry}>
            Speak again…
          </Button>
          <Button variant="text" icon="edit_note" onClick={onEditNarration}>
            Correct the text
          </Button>
        </div>
      ) : null}
    </li>
  );
}

function SetupDialog({
  open,
  models,
  onClose,
  onDone,
}: {
  open: boolean;
  models: AsrReadiness[];
  onClose: () => void;
  onDone: () => void;
}) {
  const missing = downloadable(models);
  const [state, setState] = useState<{ phase: "idle" } | { phase: "working" } | { phase: "failed"; message: string }>({ phase: "idle" });
  const total = missing.reduce((sum, model) => sum + model.size_bytes, 0);
  const download = async () => {
    setState({ phase: "working" });
    try {
      const outcome = await run({
        command: "asr_fetch",
        models: missing.map((model) => model.model),
      });
      if (outcome.outcome === "success") {
        setState({ phase: "idle" });
        onDone();
        onClose();
      } else {
        setState({
          phase: "failed",
          message: outcome.outcome === "failed" ? outcome.error.message : "The engine returned an unreadable result",
        });
      }
    } catch (error) {
      setState({ phase: "failed", message: errorMessage(error) });
    }
  };
  return (
    <Dialog
      open={open}
      headline="Download the speech recognizers?"
      onClose={onClose}
      actions={
        <>
          <Button variant="text" onClick={onClose} disabled={state.phase === "working"}>
            Not now
          </Button>
          <Button icon="download" onClick={() => void download()} disabled={state.phase === "working" || missing.length === 0}>
            {state.phase === "working" ? "Downloading…" : `Download ${size(total)}`}
          </Button>
        </>
      }
    >
      <p className="body-medium">
        The engine downloads these pinned models once, checks each file's checksum, and keeps them on this computer. This is the only time
        audio checking uses the network; the app itself doesn't connect anywhere.
      </p>
      <ul className="body-medium">
        {missing.map((model) => (
          <li key={model.model}>
            {MODEL_NAMES[model.model]} ({model.model_id}), {size(model.size_bytes)}, into <code>{model.location}</code>
          </li>
        ))}
      </ul>
      {state.phase === "failed" ? <p className="body-medium audio-problem">{state.message}</p> : null}
    </Dialog>
  );
}

interface RetryProps {
  chapter: number;
  voices: Voices | null;
  voice: string;
  speed: number;
  /** Whether a recognizer is ready to check the new audio. */
  verify: boolean;
  onClose: () => void;
  onStart: (request: Omit<Extract<Request, { command: "resynthesize" }>, "manifest">) => void;
}

function RetryDialog({ chapter, voices, voice, speed, verify, onClose, onStart }: RetryProps) {
  const [chosenVoice, setVoice] = useState(voice);
  const [chosenSpeed, setSpeed] = useState(speed);
  const options = (voices?.listable ? voices.voices : [voice]).filter(Boolean).map((name) => ({ value: name, label: name }));
  return (
    <Dialog
      open
      headline={`Speak chapter ${chapter} again?`}
      onClose={onClose}
      actions={
        <>
          <Button variant="text" onClick={onClose}>
            Cancel
          </Button>
          <Button
            icon="replay"
            onClick={() =>
              onStart({
                command: "resynthesize",
                chapters: [chapter],
                voice: chosenVoice || null,
                speed: chosenSpeed,
                verify_audio: verify ? true : null,
              })
            }
          >
            Speak again
          </Button>
        </>
      }
    >
      <p className="body-medium">
        Only this chapter is synthesized again, from the same text. Its current audio stays playable until the new audio is ready, and is
        then kept as a backup in the book's <code>audio/.backup</code> folder.
        {verify ? " The new audio is checked afterwards." : ""}
      </p>
      {options.length > 0 ? <Select label="Voice" value={chosenVoice} options={options} onChange={setVoice} /> : null}
      <div className="slider-row">
        <span className="label-large">Speed</span>
        <Slider label="Speed" value={chosenSpeed} min={0.5} max={2} step={0.05} onChange={setSpeed} />
        <span className="body-medium slider-value">{chosenSpeed.toFixed(2)}×</span>
      </div>
    </Dialog>
  );
}
