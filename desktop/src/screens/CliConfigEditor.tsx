import { useEffect, useState } from "react";
import { errorMessage, readCliConfig, saveCliConfig } from "../engine/api";
import type { CliConfigFile } from "../engine/types";
import { CloneControls } from "./CloneControls";
import { cloneErrors, type CloneForm } from "./bookOptions";
import { Button } from "../ui/Button";

/** Edit the shared file while keeping environment overrides and app preferences separate. */
export function CliConfigEditor({ onSaved }: { onSaved: () => void }) {
  const [clone, setClone] = useState<CloneForm>({ voiceMode: "inherit" });
  const [file, setFile] = useState<CliConfigFile | null>(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  useEffect(() => {
    let current = true;
    void readCliConfig().then((next) => {
      if (current) {
        setFile(next);
        setText(next.text);
      }
    }).catch((error: unknown) => {
      if (current) setMessage({ text: errorMessage(error), error: true });
    }).finally(() => {
      if (current) setLoading(false);
    });


  return () => { current = false; };
  }, [attempt]);

  const save = async () => {
    if (!file) return;
    setSaving(true);
    setMessage(null);
    try {
      const next = await saveCliConfig(text, file.text);
      setFile(next);
      setText(next.text);
      setMessage({ text: "Configuration saved. New runs use these settings.", error: false });
      onSaved();
    } catch (error) {
      setMessage({ text: errorMessage(error), error: true });
    } finally {
      setSaving(false);
    }
  };

  const applyDefaults = () => {
    if (clone.voiceMode === "inherit") return;
    const setKey = (source: string, table: string, key: string, value: string) => {
      const lines = source.split("\n");
      const start = lines.findIndex((line) => line.split("#", 1)[0].trim() === `[${table}]`);
      if (start < 0) return `${source.trimEnd()}\n\n[${table}]\n${key} = ${value}\n`;
      let end = lines.findIndex((line, index) => index > start && /^\s*\[/.test(line));
      if (end < 0) end = lines.length;
      const found = lines.findIndex((line, index) => index > start && index < end && new RegExp(`^\\s*${key}\\s*=`).test(line));
      if (found >= 0) lines[found] = `${key} = ${value}`;
      else lines.splice(start + 1, 0, `${key} = ${value}`);
      return lines.join("\n");
    };
    let next = setKey(text, "tts.voice_clone", "enabled", String(clone.voiceMode === "clone"));
    if (clone.voiceMode === "clone") {
      next = setKey(next, "tts", "provider", '"kitten"');
      next = setKey(next, "tts.kitten", "model", '"kitten2"');
      next = setKey(next, "tts.voice_clone", "reference_audio", JSON.stringify(clone.referenceAudio ?? ""));
      next = setKey(next, "tts.voice_clone", "reference_text_file", JSON.stringify(clone.referenceTextFile ?? ""));
    }
    setText(next);
    setMessage({ text: "Voice defaults added to the editor. Review and save configuration to persist them.", error: false });
  };


  return (
    <div className="config-editor" aria-busy={loading || saving}>
      <p className="body-medium on-surface-variant">
        Shared settings for the CLI and desktop app. Changes are validated before saving.
        The table below shows CLI values and environment overrides. App preferences above
        apply separately to desktop runs. Keep API keys and passwords in environment variables.
      </p>
      {file ? (
        <>
          <h3 className="title-medium">Voice defaults</h3>
          <CloneControls form={clone} onChange={setClone} allowDraft={false} />
          <Button variant="text" disabled={clone.voiceMode === "inherit" || Object.keys(cloneErrors(clone)).length > 0 || saving} onClick={applyDefaults}>Apply voice defaults to editor</Button>
          <p className="body-small config-path"><code>{file.path}</code></p>
          <label className="title-small" htmlFor="cli-config-text">Configuration file (TOML)</label>
          <textarea
            id="cli-config-text"
            value={text}
            onChange={(event) => { setText(event.target.value); setMessage(null); }}
            disabled={loading || saving}
            spellCheck={false}
            autoCapitalize="off"
            rows={18}
          />
        </>
      ) : null}
      <div className="settings-save">
        <Button onClick={() => void save()} disabled={!file || text === file.text || loading || saving}>
          {saving ? "Saving configuration…" : "Save configuration"}
        </Button>
        <Button variant="text" onClick={() => {
          setLoading(true);
          setMessage(null);
          setAttempt((value) => value + 1);
        }} disabled={loading || saving}>
          Reload from disk
        </Button>
      </div>
      {loading ? <p className="body-medium">Loading configuration…</p> : null}
      {message ? (
        <p className={`body-medium settings-${message.error ? "problem" : "ok"}`} role={message.error ? "alert" : "status"}>
          {message.text}
        </p>
      ) : null}
    </div>
  );
}
