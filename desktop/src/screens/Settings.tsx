import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useRef, useState } from "react";
import { errorMessage, getSettings, run, saveSettings } from "../engine/api";
import type { AppSettings, CliConfig, LlmProvider, Theme, Voices } from "../engine/types";
import { Button } from "../ui/Button";
import { Select } from "../ui/Select";
import { Switch } from "../ui/Switch";
import { TextField } from "../ui/TextField";
import { blobUrl } from "./Player";
import { Setup } from "./Setup";
import { CliConfigEditor } from "./CliConfigEditor";
import { About } from "./About";
import { ModelField } from "./ModelField";
import { AddonsPanel, OcrLanguages } from "./Addons";
import "./settings.css";

/** The README's Kitten voice samples (docs/audio/voices), bundled with the app. */
const SAMPLE_FILES = import.meta.glob("../../../docs/audio/voices/*.mp3", {
  query: "?url",
  import: "default",
  eager: true,
}) as Record<string, string>;

export const VOICE_SAMPLES: Record<string, string> = Object.fromEntries(
  Object.entries(SAMPLE_FILES).map(([path, url]) => [path.replace(/^.*\//, "").replace(/\.mp3$/, ""), url]),
);

const PROVIDERS: ReadonlyArray<{ value: LlmProvider; label: string }> = [
  { value: "ollama", label: "Ollama (on this computer)" },
  { value: "llama-server", label: "llama-server (on this computer)" },
  { value: "openai", label: "OpenAI (sends book text to OpenAI)" },
];

const THEMES: ReadonlyArray<{ value: Theme; label: string }> = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "system", label: "Follow the system" },
];

type CliConfigWithSources = CliConfig & { _sources?: Record<string, string> };

export interface ConfigRow {
  key: string;
  value: string;
  source: string;
}

/** Where a value comes from, in words: `built-in`, `file:<path>` or an environment variable. */
export function sourceLabel(source: string | undefined): string {
  if (!source || source === "built-in") return "Built-in default";
  if (source.startsWith("file:")) return `Config file (${source.slice(5)})`;
  if (source.startsWith("env:")) return `Environment (${source.slice(4)})`;
  return source;
}

/** `config show --sources --json` as rows: each setting, its value and where it comes from. */
export function configRows(config: CliConfigWithSources): ConfigRow[] {
  const rows: ConfigRow[] = [];
  const walk = (value: unknown, key: string) => {
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      for (const [name, inner] of Object.entries(value)) walk(inner, key ? `${key}.${name}` : name);
      return;
    }
    rows.push({
      key,
      value: value === null ? "—" : typeof value === "string" ? value : JSON.stringify(value),
      source: sourceLabel(config._sources?.[key]),
    });
  };
  for (const [name, value] of Object.entries(config)) {
    if (name !== "_sources" && name !== "warnings") walk(value, name);
  }
  return rows;
}

function blank(value: string): string | null {
  return value.trim() ? value.trim() : null;
}

type Loaded =
  | { phase: "loading" }
  | { phase: "failed"; message: string }
  | { phase: "ready"; config: CliConfigWithSources | null; configProblem: string | null; voices: Voices | null };

async function loadCliConfiguration(): Promise<Extract<Loaded, { phase: "ready" }>> {
  let config: CliConfigWithSources | null = null;
  let configProblem: string | null = null;
  try {
    const outcome = await run<CliConfigWithSources>({ command: "config_show" });
    if (outcome.outcome === "success") config = outcome.result;
    else configProblem = outcome.outcome === "failed" ? outcome.error.message : "The engine returned an unreadable result";
  } catch (error) {
    configProblem = errorMessage(error);
  }
  let voices: Voices | null = null;
  try {
    const outcome = await run<Voices>({ command: "voices" });
    if (outcome.outcome === "success") voices = outcome.result;
  } catch {
    // Without the list the samples' voices are offered.
  }
  return { phase: "ready", config, configProblem, voices };
}

/** Settings (spec D4.8): the app's own settings file, the setup check, and the CLI's configuration. */
export function Settings() {
  const [saved, setSaved] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [loaded, setLoaded] = useState<Loaded>({ phase: "loading" });
  const [status, setStatus] = useState<{ text: string; tone: "ok" | "problem" } | null>(null);
  const [saving, setSaving] = useState(false);
  const sample = useRef<HTMLAudioElement>(null);
  const sampleUrl = useRef<string | null>(null);

  const refreshCliConfig = async () => {
    setLoaded(await loadCliConfiguration());
  };

  useEffect(() => {
    let current = true;
    void (async () => {
      try {
        const settings = await getSettings();
        if (!current) return;
        setSaved(settings);
        setDraft(settings);
      } catch (error) {
        if (current) setLoaded({ phase: "failed", message: errorMessage(error) });
        return;
      }
      const next = await loadCliConfiguration();
      if (current) setLoaded(next);
    })();
    return () => {
      current = false;
      if (sampleUrl.current) URL.revokeObjectURL(sampleUrl.current);
    };
  }, []);

  if (loaded.phase === "failed") {
    return (
      <div className="screen settings">
        <p className="body-medium settings-problem">{loaded.message}</p>
      </div>
    );
  }
  if (!draft || !saved) return <div className="screen settings" aria-busy="true" />;

  const config = loaded.phase === "ready" ? loaded.config : null;
  const voices = loaded.phase === "ready" ? loaded.voices : null;
  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setStatus(null);
    setDraft({ ...draft, [key]: value });
  };
  const changed = JSON.stringify(draft) !== JSON.stringify(saved);
  const cliVoice = config ? (config.tts.provider === "piper" ? config.tts.piper.voice : config.tts.kitten.voice) : null;
  const voiceNames = voices?.voices ?? Object.keys(VOICE_SAMPLES);
  const shownVoice = draft.default_voice ?? cliVoice;
  const cliProvider = config?.llm.provider ?? null;

  const browse = async (key: "cli_path" | "uv_project" | "output_dir", directory: boolean) => {
    const picked = await open({ multiple: false, directory });
    if (typeof picked === "string") set(key, picked);
  };

  const playSample = async (voice: string) => {
    const url = VOICE_SAMPLES[voice];
    const element = sample.current;
    if (!url || !element) return;
    try {
      if (sampleUrl.current) URL.revokeObjectURL(sampleUrl.current);
      sampleUrl.current = await blobUrl(url);
      element.src = sampleUrl.current;
      await element.play();
    } catch {
      setStatus({ text: "The sample couldn't be played", tone: "problem" });
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await saveSettings(draft);
      setSaved(draft);
      document.documentElement.dataset.theme = draft.theme;
      setStatus({ text: "Saved. New books and runs use these settings.", tone: "ok" });
    } catch (error) {
      setStatus({ text: errorMessage(error), tone: "problem" });
    }
    setSaving(false);
  };

  return (
    <div className="screen settings">
      <section className="settings-group" aria-labelledby="settings-engine">
        <h3 id="settings-engine" className="title-medium">Engine</h3>
        <p className="body-medium on-surface-variant">
          The engine built into this app is used. Nothing else needs installing.
        </p>
        <Switch label="Use a development engine" selected={draft.developer_engine} onChange={(value) => set("developer_engine", value)} />
        {draft.developer_engine ? (
          <>
            <p className="body-small on-surface-variant">
              For developing pdf2audiobook: the CLI below, then PATH, then a source checkout are tried before the built-in engine.
            </p>
            <div className="settings-field">
              <TextField
                label="CLI location"
                value={draft.cli_path ?? ""}
                onChange={(value) => set("cli_path", blank(value))}
                supportingText="Empty uses pdf2audiobook from your PATH."
              />
              <Button variant="text" icon="folder_open" onClick={() => void browse("cli_path", false)}>
                Browse
              </Button>
            </div>
            <div className="settings-field">
              <TextField
                label="Source checkout"
                value={draft.uv_project ?? ""}
                onChange={(value) => set("uv_project", blank(value))}
                supportingText="Optional: a pdf2audiobook checkout to run with uv run --project."
              />
              <Button variant="text" icon="folder_open" onClick={() => void browse("uv_project", true)}>
                Browse
              </Button>
            </div>
          </>
        ) : null}
      </section>

      <section className="settings-group" aria-label="Add-ons and OCR languages">
        <AddonsPanel />
        <OcrLanguages />
      </section>

      <section className="settings-group" aria-labelledby="settings-library">
        <h3 id="settings-library" className="title-medium">Library</h3>
        <div className="settings-field">
          <TextField
            label="Output folder"
            value={draft.output_dir ?? ""}
            onChange={(value) => set("output_dir", blank(value))}
            supportingText={`Empty uses the CLI's output folder${config ? `: ${config.general.output_dir}` : ""}.`}
          />
          <Button variant="text" icon="folder_open" onClick={() => void browse("output_dir", true)}>
            Browse
          </Button>
        </div>
      </section>

      <section className="settings-group" aria-labelledby="settings-voice">
        <h3 id="settings-voice" className="title-medium">Default voice</h3>
        <p className="body-medium on-surface-variant">New books start with this voice; each book can still choose its own.</p>
        <Select
          // Material's select keeps the option text it first rendered; remount once the CLI's
          // voice is known so "The CLI's voice (…)" shows it.
          key={`voice-${cliVoice ?? ""}`}
          label="Voice"
          value={draft.default_voice ?? ""}
          options={[
            { value: "", label: cliVoice ? `The CLI's voice (${cliVoice})` : "The CLI's voice" },
            ...voiceNames.map((name) => ({ value: name, label: name })),
          ]}
          onChange={(value) => set("default_voice", blank(value))}
        />
        <ul className="voice-samples" aria-label="Voice samples">
          {Object.keys(VOICE_SAMPLES).map((name) => (
            <li key={name}>
              <Button
                variant={name === shownVoice ? "tonal" : "text"}
                icon="play_arrow"
                onClick={() => void playSample(name)}
              >
                {name}
              </Button>
            </li>
          ))}
        </ul>
        <audio ref={sample} data-testid="voice-sample" />
      </section>

      <section className="settings-group" aria-labelledby="settings-llm">
        <h3 id="settings-llm" className="title-medium">LLM</h3>
        <p className="body-medium on-surface-variant">The provider and model new books start with.</p>
        <Select
          key={`provider-${cliProvider ?? ""}`}
          label="Provider"
          value={draft.llm_provider ?? ""}
          options={[
            { value: "", label: cliProvider ? `The CLI's provider (${cliProvider})` : "The CLI's provider" },
            ...PROVIDERS,
          ]}
          onChange={(value) => set("llm_provider", (blank(value) as LlmProvider | null) ?? null)}
        />
        <ModelField
          provider={draft.llm_provider ?? null}
          value={draft.llm_model ?? ""}
          onChange={(value) => set("llm_model", blank(value))}
          emptyLabel="The CLI's model for the provider"
        />
      </section>

      <section className="settings-group" aria-labelledby="settings-appearance">
        <h3 id="settings-appearance" className="title-medium">Appearance</h3>
        <Select label="Theme" value={draft.theme} options={THEMES} onChange={(value) => set("theme", value as Theme)} />
      </section>

      <div className="settings-save">
        <Button icon="check" onClick={() => void save()} disabled={!changed || saving}>
          Save settings
        </Button>
        {status ? (
          <span className={`body-medium settings-${status.tone}`} role="status">
            {status.text}
          </span>
        ) : null}
      </div>

      <section className="settings-group" aria-labelledby="settings-setup">
        <h3 id="settings-setup" className="title-medium">Setup check</h3>
        <Setup />
      </section>

      <section className="settings-group" aria-labelledby="settings-cli">
        <h3 id="settings-cli" className="title-medium">CLI configuration</h3>
        <CliConfigEditor onSaved={() => void refreshCliConfig()} />
        {loaded.phase === "ready" && loaded.configProblem ? (
          <p className="body-medium settings-problem">{loaded.configProblem}</p>
        ) : null}
        {config ? (
          <details className="details">
            <summary>Show all {configRows(config).length} settings</summary>
            <table className="config-table" aria-label="CLI configuration">
              <thead>
                <tr>
                  <th scope="col">Setting</th>
                  <th scope="col">Value</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {configRows(config).map((row) => (
                  <tr key={row.key}>
                    <td>
                      <code>{row.key}</code>
                    </td>
                    <td>{row.value}</td>
                    <td>{row.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        ) : null}
      </section>

      <section className="settings-group" aria-labelledby="settings-about">
        <h3 id="settings-about" className="title-medium">About</h3>
        <About />
      </section>
    </div>
  );
}
