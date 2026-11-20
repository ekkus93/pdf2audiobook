import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useId, useState } from "react";
import { errorMessage, run } from "../engine/api";
import type { TtsModels, TtsReadiness } from "../engine/types";
import { Button } from "../ui/Button";
import { Select } from "../ui/Select";
import { TextField } from "../ui/TextField";
import { cloneErrors, isCloning, type CloneForm } from "./bookOptions";

/** Local-only reference controls. Drafts are never persisted by this component. */
export function CloneControls({ form, onChange, onDownload, allowDraft = true }: {
  form: CloneForm; onChange: (form: CloneForm) => void; onDownload?: () => void; allowDraft?: boolean;
}) {
  const id = useId();
  const active = isCloning(form);
  const errors = cloneErrors(form);
  const [ready, setReady] = useState<Partial<TtsReadiness> | null>(null);
  const [problem, setProblem] = useState("");
  const [confirmDownload, setConfirmDownload] = useState(false);
  useEffect(() => {
    if (!active) return;
    let current = true;
    void run<TtsModels>({ command: "tts_models" }).then((result) => {
      if (!current) return;
      if (result.outcome === "success") setReady(result.result.models.find((item) => item.name === "kitten2") ?? null);
      else setProblem(result.outcome === "failed" ? result.error.message : "Model readiness is unavailable");
    }).catch((error) => current && setProblem(errorMessage(error)));
    return () => { current = false; };
  }, [active]);
  const set = (change: Partial<CloneForm>) => onChange({ ...form, ...change });
  const pick = async (transcript: boolean) => {
    try {
      const path = await open({ multiple: false, directory: false, filters: [{
        name: transcript ? "UTF-8 transcript" : "Reference recording", extensions: transcript ? ["txt"] : ["wav", "flac", "mp3"],
      }] });
      if (typeof path === "string") set(transcript ? { referenceTextFile: path, referenceText: "" } : { referenceAudio: path, referenceTextFile: "", referenceText: "" });
    } catch (error) { setProblem(errorMessage(error)); }
  };
  return <div className="clone-controls">
    <Select label="Voice source" value={form.voiceMode ?? "inherit"} options={[
      { value: "inherit", label: "Use shared configuration" }, { value: "builtin", label: "Built-in voice" },
      { value: "clone", label: "Clone a voice (KittenTTS 2)" },
    ]} onChange={(value) => set({ voiceMode: value as CloneForm["voiceMode"] })} />
    {active ? <>
      <p className="body-medium on-surface-variant">Full KittenTTS 2 · English · local inference. Choose one speaker, 5–30 seconds, up to 10 MiB. Chapter voice overrides must be cleared for selected chapters.</p>
      <TextField label="Reference recording" value={form.referenceAudio ?? ""} errorText={errors.referenceAudio}
        supportingText={form.inheritedReference && !form.referenceAudio ? "Uses the private recording configured in the CLI" : undefined}
        onChange={(value) => set({ referenceAudio: value, referenceTextFile: "", referenceText: "" })} />
      <Button variant="text" onClick={() => void pick(false)}>Choose recording</Button>
      <TextField label="Reference transcript file (optional)" value={form.referenceTextFile ?? ""}
        onChange={(value) => set({ referenceTextFile: value, referenceText: "" })} />
      <Button variant="text" onClick={() => void pick(true)}>Choose transcript file</Button>
      {allowDraft ? <>
      <label htmlFor={id} className="label-large">Reference transcript (optional)</label>
      <textarea id={id} rows={3} value={form.referenceText ?? ""} spellCheck={false} aria-invalid={!!errors.referenceText}
        aria-describedby={`${id}-help`} onChange={(event) => set({ referenceText: event.target.value, referenceTextFile: "" })} />
      <p id={`${id}-help`} className="body-small" role={errors.referenceText ? "alert" : undefined}>{errors.referenceText ?? "Type the words spoken in the recording. Drafts stay transient; omitting text requires an already downloaded local Whisper model."}</p>
      </> : null}
      {ready ? <p className="body-medium" role="status">{ready.ready ? `Model ready (${ready.detected_device})` : !ready.package_installed ? "Install the optional kitten dependencies in the CLI environment." : "Model weights need downloading."}{!ready.transcription_ready && !form.referenceText?.trim() && !form.referenceTextFile && !(form.inheritedTranscript && !form.referenceAudio) ? " Add a transcript or set up local Whisper." : ""}</p> : <p className="body-small">Checking model readiness…</p>}
      {onDownload && ready && !ready.weights_present ? <>
        <Button variant="text" onClick={() => setConfirmDownload((value) => !value)}>Set up KittenTTS 2</Button>
        {confirmDownload ? <div role="group" aria-label="Confirm model download">
          <p className="body-medium">Download {((ready.download_bytes ?? 0) / 1e9).toFixed(2)} GB from KittenML/kitten-tts-2 and ResembleAI/chatterbox-turbo on Hugging Face into <code>{ready.directory}</code>. Pinned revisions and checksums are verified. Model license terms apply; see the voice cloning guide.</p>
          <Button onClick={onDownload}>Download model</Button>
        </div> : null}
      </> : null}
    </> : null}
    {problem ? <p className="body-medium" role="alert">{problem}</p> : null}
  </div>;
}
