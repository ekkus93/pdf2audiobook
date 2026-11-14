import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useMemo, useState } from "react";
import { describe, errorMessage, run } from "../engine/api";
import type { CliConfig, LibraryBook, LlmProvider, Request, Voices } from "../engine/types";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { IconButton } from "../ui/IconButton";
import { CircularProgress } from "../ui/Progress";
import { Select } from "../ui/Select";
import { Slider } from "../ui/Slider";
import { Switch } from "../ui/Switch";
import { TextField } from "../ui/TextField";
import { defaults, modelFor, requests, validate, type OptionsForm } from "./bookOptions";
import { summarize } from "./bookState";
import "./screens.css";
import "./book.css";

interface BookPageProps {
  book: LibraryBook;
  outputDir: string;
  minConfidence: number;
  onBack: () => void;
  /** Starts a write-capable run for this book's workspace (spec D4.4). */
  onStart: (request: Request, workspace: string) => void;
}

type Loaded = { phase: "loading" } | { phase: "failed"; message: string } | { phase: "ready"; config: CliConfig; voices: Voices | null };

/** Loads the CLI's configuration and the voice list; never rejects. */
export async function loadOptions(): Promise<Loaded> {
  try {
    const config = await run<CliConfig>({ command: "config_show" });
    if (config.outcome !== "success") {
      const message = config.outcome === "failed" ? config.error.message : "The engine returned an unreadable result";
      return { phase: "failed", message };
    }
    const voices = await run<Voices>({ command: "voices" }).catch(() => null);
    return { phase: "ready", config: config.result, voices: voices?.outcome === "success" ? voices.result : null };
  } catch (error) {
    return { phase: "failed", message: errorMessage(error) };
  }
}

const PROVIDERS: ReadonlyArray<{ value: LlmProvider; label: string }> = [
  { value: "ollama", label: "Ollama (on this computer)" },
  { value: "llama-server", label: "llama-server (on this computer)" },
  { value: "openai", label: "OpenAI (sends book text to OpenAI)" },
];

/** One book: its options (spec D4.3) and the actions that start analysis or conversion. */
export function BookPage({ book, outputDir, minConfidence, onBack, onStart }: BookPageProps) {
  const summary = summarize(book, minConfidence);
  const source = book.inspect?.source_path ?? book.source ?? "";
  const [loaded, setLoaded] = useState<Loaded>({ phase: "loading" });
  const [form, setForm] = useState<OptionsForm | null>(null);

  useEffect(() => {
    let current = true;
    void loadOptions().then((next) => {
      if (!current) return;
      setLoaded(next);
      if (next.phase === "ready") setForm(defaults(next.config, summary.chapters));
    });
    return () => {
      current = false;
    };
  }, [summary.chapters]);

  return (
    <div className="screen book-page">
      <div className="book-header">
        <IconButton icon="arrow_back" label="Back to the library" onClick={onBack} />
        {book.thumbnail ? <img className="book-header-cover" src={book.thumbnail} alt="" /> : null}
        <div>
          <h2 className="headline-small book-header-title">{summary.title}</h2>
          <p className="body-medium on-surface-variant">
            {summary.chapters !== null ? `${summary.chapters} chapters · ` : ""}
            {source.split(/[\\/]/).pop()}
          </p>
        </div>
      </div>
      {loaded.phase === "loading" ? (
        <div className="screen-loading">
          <CircularProgress label="Loading the options" />
          <span className="body-medium on-surface-variant">Loading the options…</span>
        </div>
      ) : null}
      {loaded.phase === "failed" ? (
        <div className="notice notice-error">
          <Icon name="error" />
          <div>
            <div className="title-medium">The options couldn't be loaded</div>
            <p className="body-medium">{loaded.message}</p>
          </div>
        </div>
      ) : null}
      {loaded.phase === "ready" && form ? (
        <OptionsEditor
          form={form}
          onChange={setForm}
          config={loaded.config}
          voices={loaded.voices}
          chapters={summary.chapters}
          analyzed={book.analyzed}
          book={source}
          outputDir={outputDir}
          onStart={(request) => onStart(request, book.workspace)}
        />
      ) : null}
    </div>
  );
}

interface EditorProps {
  form: OptionsForm;
  onChange: (form: OptionsForm) => void;
  config: CliConfig;
  voices: Voices | null;
  chapters: number | null;
  analyzed: boolean;
  book: string;
  outputDir: string;
  onStart: (request: Request) => void;
}

function OptionsEditor({ form, onChange, config, voices, chapters, analyzed, book, outputDir, onStart }: EditorProps) {
  const errors = validate(form, chapters);
  const valid = Object.keys(errors).length === 0;
  const built = useMemo(() => requests(book, form, outputDir), [book, form, outputDir]);
  const [shown, setShown] = useState<string[]>([]);
  const set = <K extends keyof OptionsForm>(key: K, value: OptionsForm[K]) => onChange({ ...form, [key]: value });

  useEffect(() => {
    if (!valid) return;
    let current = true;
    void Promise.all([describe(built.analyze), describe(built.convert)])
      .then((lines) => current && setShown(lines))
      .catch(() => current && setShown([]));
    return () => {
      current = false;
    };
  }, [built, valid]);

  const chooseCover = async () => {
    const picked = await open({ multiple: false, directory: false, filters: [{ name: "Images", extensions: ["jpg", "jpeg", "png"] }] });
    if (typeof picked === "string") set("cover", picked);
  };

  const voiceOptions = (voices?.listable ? voices.voices : [form.voice]).filter(Boolean).map((voice) => ({ value: voice, label: voice }));

  return (
    <>
      <div className="options-grid">
        <section className="options-group" aria-labelledby="options-analysis">
          <h3 id="options-analysis" className="title-medium">Analysis</h3>
          <Switch label="Use an LLM to find chapters and clean the text" selected={form.llm} onChange={(value) => set("llm", value)} />
          {form.llm ? (
            <>
              <Select
                label="Provider"
                value={form.provider}
                options={PROVIDERS}
                onChange={(value) => onChange({ ...form, provider: value as LlmProvider, model: modelFor(config, value as LlmProvider) })}
              />
              <TextField label="Model" value={form.model} onChange={(value) => set("model", value)} errorText={errors.model} />
              <div className="field-pair">
                <TextField
                  label="Context (tokens)"
                  type="number"
                  value={form.contextTokens}
                  onChange={(value) => set("contextTokens", value)}
                  errorText={errors.contextTokens}
                  min={512}
                />
                <TextField
                  label="Output cap (tokens)"
                  type="number"
                  value={form.outputTokens}
                  onChange={(value) => set("outputTokens", value)}
                  errorText={errors.outputTokens}
                  supportingText="Reasoning models need about 32768"
                  min={1}
                />
              </div>
              {form.provider === "openai" ? (
                <div className={`consent ${errors.remoteConsent ? "consent-missing" : ""}`}>
                  <Switch
                    label="Send this book's text to OpenAI for analysis"
                    selected={form.remoteConsent}
                    onChange={(value) => set("remoteConsent", value)}
                  />
                  <p className="body-medium on-surface-variant">
                    Book text leaves this computer only with this consent. {errors.remoteConsent ?? ""}
                  </p>
                </div>
              ) : null}
            </>
          ) : (
            <p className="body-medium on-surface-variant">Chapters are found from the book's layout alone.</p>
          )}
        </section>
        <section className="options-group" aria-labelledby="options-voice">
          <h3 id="options-voice" className="title-medium">Voice</h3>
          {voiceOptions.length > 0 ? (
            <Select label="Voice" value={form.voice} options={voiceOptions} onChange={(value) => set("voice", value)} />
          ) : (
            <p className="body-medium on-surface-variant">This voice engine has no voice list; the configured voice is used.</p>
          )}
          <div className="slider-row">
            <span className="label-large">Speed</span>
            <Slider label="Speed" value={form.speed} min={0.5} max={2} step={0.05} onChange={(value) => set("speed", value)} />
            <span className="body-medium slider-value">{form.speed.toFixed(2)}×</span>
          </div>
        </section>
        <section className="options-group" aria-labelledby="options-chapters">
          <h3 id="options-chapters" className="title-medium">Chapters</h3>
          <Switch label="Convert every chapter" selected={form.allChapters} onChange={(value) => set("allChapters", value)} />
          {!form.allChapters ? (
            <div className="field-pair">
              <TextField label="First" type="number" value={form.firstChapter} onChange={(value) => set("firstChapter", value)} errorText={errors.firstChapter} min={1} />
              <TextField label="Last" type="number" value={form.lastChapter} onChange={(value) => set("lastChapter", value)} errorText={errors.lastChapter} min={1} />
            </div>
          ) : null}
        </section>
        <section className="options-group" aria-labelledby="options-cover">
          <h3 id="options-cover" className="title-medium">Cover art</h3>
          <p className="body-medium on-surface-variant">
            {form.cover ? form.cover.split(/[\\/]/).pop() : "Optional: a JPEG or PNG embedded in every chapter file."}
          </p>
          <div className="button-row">
            <Button variant="outlined" icon="folder_open" onClick={() => void chooseCover()}>
              Choose image
            </Button>
            {form.cover ? (
              <Button variant="text" onClick={() => set("cover", null)}>
                Remove
              </Button>
            ) : null}
          </div>
        </section>
      </div>
      <div className="book-actions">
        <Button variant="tonal" icon="sync" disabled={!valid} onClick={() => onStart(built.analyze)}>
          {analyzed ? "Analyze again" : "Analyze"}
        </Button>
        <Button icon="headphones" disabled={!valid} onClick={() => onStart(built.convert)}>
          Convert to audio
        </Button>
        {!valid ? <span className="body-medium book-actions-hint">Fix the highlighted options first.</span> : null}
      </div>
      {shown.length > 0 ? (
        <details className="details">
          <summary>Details</summary>
          <p className="body-medium on-surface-variant">The commands these buttons run:</p>
          {shown.map((command) => (
            <pre key={command} className="command">
              {command}
            </pre>
          ))}
        </details>
      ) : null}
    </>
  );
}
