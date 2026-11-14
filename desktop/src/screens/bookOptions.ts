import type { BookOptions, CliConfig, ConvertOptions, LlmProvider, Request } from "../engine/types";

/** What the Book options form edits (spec D4.3). Nothing here is stored per book. */
export interface OptionsForm {
  llm: boolean;
  provider: LlmProvider;
  model: string;
  contextTokens: string;
  outputTokens: string;
  remoteConsent: boolean;
  voice: string;
  speed: number;
  allChapters: boolean;
  firstChapter: string;
  lastChapter: string;
  cover: string | null;
}

export type OptionsErrors = Partial<Record<keyof OptionsForm, string>>;

const MODEL_KEY: Record<LlmProvider, "ollama" | "openai" | "llama_server"> = {
  ollama: "ollama",
  openai: "openai",
  "llama-server": "llama_server",
};

/** The form as the CLI's own configuration would run the book. */
export function defaults(config: CliConfig, chapters: number | null): OptionsForm {
  const tts = config.tts.provider === "piper" ? config.tts.piper : config.tts.kitten;
  return {
    llm: config.llm.enabled,
    provider: config.llm.provider,
    model: config.llm[MODEL_KEY[config.llm.provider]].model,
    contextTokens: String(config.llm.max_context_tokens),
    outputTokens: String(config.llm.max_output_tokens),
    remoteConsent: config.llm.allow_remote_content,
    voice: tts.voice,
    speed: tts.speed,
    allChapters: true,
    firstChapter: "1",
    lastChapter: chapters ? String(chapters) : "1",
    cover: null,
  };
}

/** The model the configuration names for a provider, used when the user switches provider. */
export function modelFor(config: CliConfig, provider: LlmProvider): string {
  return config.llm[MODEL_KEY[provider]].model;
}

function integer(value: string): number | null {
  return /^\d+$/.test(value.trim()) ? Number(value.trim()) : null;
}

/** The CLI's own limits, checked before anything runs. */
export function validate(form: OptionsForm, chapters: number | null): OptionsErrors {
  const errors: OptionsErrors = {};
  if (form.llm) {
    if (!form.model.trim()) errors.model = "Enter a model name";
    const context = integer(form.contextTokens);
    const output = integer(form.outputTokens);
    if (context === null || context < 512) errors.contextTokens = "At least 512 tokens";
    if (output === null || output < 1) errors.outputTokens = "At least 1 token";
    else if (context !== null && output + 128 >= context) {
      errors.outputTokens = "Must leave room in the context; lower it or raise the context";
    }
    if (form.provider === "openai" && !form.remoteConsent) {
      errors.remoteConsent = "OpenAI needs your consent to send book text";
    }
  }
  if (!Number.isFinite(form.speed) || form.speed < 0.1 || form.speed > 3) {
    errors.speed = "Between 0.1 and 3";
  }
  if (!form.allChapters) {
    const first = integer(form.firstChapter);
    const last = integer(form.lastChapter);
    const max = chapters ?? Number.MAX_SAFE_INTEGER;
    if (first === null || first < 1 || first > max) errors.firstChapter = `From 1 to ${chapters ?? "the last chapter"}`;
    if (last === null || last < 1 || last > max) errors.lastChapter = `From 1 to ${chapters ?? "the last chapter"}`;
    else if (first !== null && last < first) errors.lastChapter = "Can't be before the first chapter";
  }
  return errors;
}

function bookOptions(form: OptionsForm, output: string | null): BookOptions {
  if (!form.llm) return { output, llm: false };
  return {
    output,
    llm: true,
    llm_provider: form.provider,
    llm_model: form.model.trim(),
    llm_context_tokens: Number(form.contextTokens),
    llm_output_tokens: Number(form.outputTokens),
    allow_remote_content: form.provider === "openai" ? form.remoteConsent : null,
  };
}

/** The `analyze` and `convert` requests the form describes. */
export function requests(book: string, form: OptionsForm, output: string | null): { analyze: Request; convert: Request } {
  const options = bookOptions(form, output);
  const convert: ConvertOptions = {
    voice: form.voice || null,
    speed: form.speed,
    cover: form.cover,
    chapters: form.allChapters
      ? null
      : Number(form.firstChapter) === Number(form.lastChapter)
        ? { kind: "one", chapter: Number(form.firstChapter) }
        : { kind: "range", first: Number(form.firstChapter), last: Number(form.lastChapter) },
  };
  return {
    analyze: { command: "analyze", book, options },
    convert: { command: "convert", book, options, convert },
  };
}
