import { save } from "@tauri-apps/plugin-dialog";
import { useEffect, useState } from "react";
import { bookAudio, errorMessage, exportZip, openAudioFolder, run } from "../engine/api";
import type { AudioFile, InspectManifest } from "../engine/types";
import { AssistChip, ChipSet } from "../ui/Chip";
import { Checkbox } from "../ui/Checkbox";
import { Icon } from "../ui/Icon";
import { IconButton } from "../ui/IconButton";
import { Button } from "../ui/Button";
import "./audio.css";

export interface ChapterRow {
  number: number;
  title: string;
  status: "converted" | "failed" | "not_converted";
  file: AudioFile | null;
}

/** Each chapter with its audio state and file (spec D4.7). */
export function chapterRows(inspect: InspectManifest, files: AudioFile[]): ChapterRow[] {
  const statuses = new Map((inspect.conversion_status?.chapters ?? []).map((chapter) => [chapter.number, chapter.status]));
  return inspect.chapters.map((chapter) => {
    const file = files.find((item) => item.name.startsWith(`${String(chapter.number).padStart(3, "0")} - `)) ?? null;
    const status = statuses.get(chapter.number);
    return {
      number: chapter.number,
      title: chapter.title,
      file,
      status: status === "failed" ? "failed" : file && (status === undefined || status === "complete") ? "converted" : "not_converted",
    };
  });
}

interface ChaptersAudioProps {
  title: string;
  workspace: string;
  manifest: string;
  source: string;
  inspect: InspectManifest;
  cover: string | null;
  /** Plays chapter `index` of `files`. */
  onPlay: (files: AudioFile[], index: number) => void;
  /** Starts converting again, when the M4B finds stale chapters. */
  onContinueConverting: () => void;
}

/** Chapters and audio (spec D4.7, D7): states, playback, open folder, M4B and zip. */
export function ChaptersAudio({ title, workspace, manifest, source, inspect, cover, onPlay, onContinueConverting }: ChaptersAudioProps) {
  const [files, setFiles] = useState<AudioFile[] | null>(null);
  const [message, setMessage] = useState<{ text: string; tone: "ok" | "problem" } | null>(null);
  const [stale, setStale] = useState(false);
  const [includeBook, setIncludeBook] = useState(true);
  const [busy, setBusy] = useState<"m4b" | "zip" | null>(null);

  useEffect(() => {
    let current = true;
    void bookAudio(workspace)
      .then((found) => current && setFiles(found))
      .catch(() => current && setFiles([]));
    return () => {
      current = false;
    };
  }, [workspace, inspect]);

  const rows = chapterRows(inspect, files ?? []);
  const playable = rows.filter((row) => row.file).map((row) => row.file as AudioFile);
  const converted = rows.filter((row) => row.status === "converted").length;

  const makeM4b = async () => {
    const output = await save({ defaultPath: `${title}.m4b`, filters: [{ name: "Audiobook", extensions: ["m4b"] }] });
    if (!output) return;
    setBusy("m4b");
    setMessage(null);
    setStale(false);
    try {
      const outcome = await run({ command: "pack_m4b", manifest, output, cover }, workspace);
      if (outcome.outcome === "success") setMessage({ text: `Saved ${output.split(/[\\/]/).pop()}`, tone: "ok" });
      else if (outcome.outcome === "failed") {
        setMessage({ text: outcome.error.message, tone: "problem" });
        setStale(/stale or missing/.test(outcome.error.message));
      } else setMessage({ text: "The engine returned an unreadable result", tone: "problem" });
    } catch (error) {
      setMessage({ text: errorMessage(error), tone: "problem" });
    }
    setBusy(null);
  };

  const makeZip = async () => {
    const destination = await save({ defaultPath: `${title}.zip`, filters: [{ name: "Zip", extensions: ["zip"] }] });
    if (!destination) return;
    setBusy("zip");
    setMessage(null);
    try {
      const count = await exportZip(workspace, destination, title, includeBook ? source : null);
      setMessage({ text: `Saved ${destination.split(/[\\/]/).pop()} with ${count} files`, tone: "ok" });
    } catch (error) {
      setMessage({ text: errorMessage(error), tone: "problem" });
    }
    setBusy(null);
  };

  return (
    <section className="audio" aria-labelledby="audio-heading">
      <div className="audio-top">
        <div>
          <h3 id="audio-heading" className="title-medium">Chapters and audio</h3>
          <p className="body-medium on-surface-variant">
            {converted} of {rows.length} chapters converted
          </p>
        </div>
        <ChipSet>
          <AssistChip label="Open folder" icon="folder_open" onClick={() => void openAudioFolder(workspace)} />
        </ChipSet>
      </div>
      <ol className="chapter-list" aria-label="Chapters">
        {rows.map((row) => (
          <li key={row.number} className={`chapter chapter-${row.status}`} aria-label={`Chapter ${row.number}: ${row.title}`}>
            <span className="chapter-number">{row.number}</span>
            <span className="chapter-title">{row.title}</span>
            <span className={`chapter-state state-${row.status}`}>
              <Icon name={row.status === "converted" ? "check_circle" : row.status === "failed" ? "error" : "hourglass_top"} filled size={16} />
              {row.status === "converted" ? "Converted" : row.status === "failed" ? "Failed" : "Not converted"}
            </span>
            {row.file ? (
              <IconButton
                icon="play_arrow"
                label={`Play chapter ${row.number}`}
                onClick={() => onPlay(playable, playable.indexOf(row.file as AudioFile))}
              />
            ) : (
              <span className="chapter-play-placeholder" />
            )}
          </li>
        ))}
      </ol>
      <div className="audio-actions">
        <Button variant="tonal" icon="headphones" onClick={() => void makeM4b()} disabled={busy !== null || converted === 0}>
          {busy === "m4b" ? "Making M4B…" : "Make M4B"}
        </Button>
        <Button variant="tonal" icon="download" onClick={() => void makeZip()} disabled={busy !== null || converted === 0}>
          {busy === "zip" ? "Exporting…" : "Export zip"}
        </Button>
        <Checkbox label="Include the book file in the zip" checked={includeBook} onChange={setIncludeBook} />
      </div>
      {message ? (
        <p className={`body-medium audio-message audio-${message.tone}`} role="status">
          {message.text}
        </p>
      ) : null}
      {stale ? (
        <Button icon="graphic_eq" onClick={onContinueConverting}>
          Continue converting
        </Button>
      ) : null}
    </section>
  );
}
