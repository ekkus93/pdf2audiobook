import type { BookOptions, CliConfig, ConvertOptions, LlmProvider, Request, VoiceCloneOptions } from "../engine/types";

/** What the Book options form edits (spec D4.3). Nothing here is stored per book. */
export interface CloneForm {
  voiceMode?: "inherit" | "builtin" | "clone";
  referenceAudio?: string;
  referenceTextFile?: string;
  referenceText?: string;
  inheritedClone?: boolean;
  inheritedReference?: boolean;
  inheritedTranscript?: boolean;
  /** Whether the configuration (or the book's profile) already selects Kitten 2. */
  inheritedKitten2?: boolean;
}
export const isCloning = (form: CloneForm) => form.voiceMode === "clone" || (form.voiceMode !== "builtin" && !!form.inheritedClone);
/** The CLI's `--tts-temperature` range and default (config.py `KITTEN2_TEMPERATURE_RANGE`). */
export const TEMPERATURE = { min: 0.05, max: 1.5, step: 0.05, fallback: 0.2 } as const;
const KITTEN2_MODELS = new Set(["kitten2", "KittenML/kitten-tts-2"]);
/** Whether Kitten 2 will speak: a clone always uses it, built-in voices only when it is configured. */
export const usesKitten2 = (form: CloneForm) => isCloning(form) || !!form.inheritedKitten2;
/** The temperature to send: only when Kitten 2 speaks, since other models ignore it. */
export const temperatureRequest = (form: CloneForm, temperature: number) => (usesKitten2(form) ? { temperature } : {});
export function temperatureError(temperature: number): string | undefined {
  return Number.isFinite(temperature) && temperature >= TEMPERATURE.min && temperature <= TEMPERATURE.max
    ? undefined
    : `Between ${TEMPERATURE.min} and ${TEMPERATURE.max}`;
}
export function cloneRequest(form: CloneForm): VoiceCloneOptions & { tts_provider?: "kitten"; tts_model?: string } {
  if (form.voiceMode === "builtin") return { clone_voice: false };
  if (!isCloning(form)) return {};
  return {
    ...(form.voiceMode === "clone" ? { clone_voice: true, tts_provider: "kitten" as const, tts_model: "kitten2" } : {}),
    ...(form.referenceAudio?.trim() ? { reference_audio: form.referenceAudio } : {}),
    ...(form.referenceTextFile?.trim() ? { reference_text_file: form.referenceTextFile } : {}),
    ...(form.referenceText?.trim() ? { reference_text: form.referenceText } : {}),
  };
}
export function cloneErrors(form: CloneForm): Partial<Record<keyof CloneForm, string>> {
  if (!isCloning(form)) return {};
  const errors: Partial<Record<keyof CloneForm, string>> = {};
  if (!form.referenceAudio?.trim() && !form.inheritedReference) errors.referenceAudio = "Choose a 5–30 second recording";
  if (form.referenceText && new TextEncoder().encode(form.referenceText).length > 65536) errors.referenceText = "At most 64 KiB of UTF-8 text";
  if (form.referenceText?.includes("\0")) errors.referenceText = "Remove NUL characters";
  if (form.referenceText?.trim() && form.referenceTextFile?.trim()) errors.referenceText = "Use typed text or a transcript file";
  return errors;
}
export interface OptionsForm extends CloneForm {
  llm: boolean;
  provider: LlmProvider;
  model: string;
  contextTokens: string;
  outputTokens: string;
  remoteConsent: boolean;
  voice: string;
  speed: number;
  /** The Kitten 2 sampling temperature; used only when Kitten 2 speaks the book. */
  temperature: number;
  allChapters: boolean;
  firstChapter: string;
  lastChapter: string;
  cover: string | null;
  /** Check the new audio with the speech recognizers afterwards; off unless chosen. */
  verifyAudio: boolean;
}

export type OptionsErrors = Partial<Record<keyof OptionsForm, string>>;

const MODEL_KEY: Record<LlmProvider, "ollama" | "openai" | "llama_server"> = {
  ollama: "ollama",
  openai: "openai",
  "llama-server": "llama_server",
};

/** The form as the CLI's own configuration would run the book. */
/** What the app's Settings say new books start with (spec D4.8); unset values use the CLI's. */
export interface Preferences {
  default_voice?: string | null;
  llm_provider?: LlmProvider | null;
  llm_model?: string | null;
}

/**
 * The options a book starts with: the CLI's configuration, then the app's Settings, then how the
 * book itself was last analyzed. A book analyzed without the LLM keeps it off, so Convert doesn't
 * re-analyze it (and the CLI doesn't refuse over approved chapters).
 */
export function defaults(
  config: CliConfig,
  chapters: number | null,
  preferences: Preferences = {},
  analyzedWithLlm: boolean | null = null,
  source: string = "",
): OptionsForm {
  const name = source.split(/[\\/]/).pop() ?? "";
  const dot = name.lastIndexOf(".");
  const profile = config.tts.profiles?.[dot > 0 ? name.slice(0, dot) : name];
  const ttsProvider = profile?.provider ?? config.tts.provider;
  const tts = ttsProvider === "piper" ? config.tts.piper : config.tts.kitten;
  const provider = preferences.llm_provider ?? config.llm.provider;
  const kittenModel = profile?.kitten_model ?? config.tts.kitten.model;
  return {
    voiceMode: "inherit",
    inheritedClone: profile?.clone_voice ?? config.tts.voice_clone?.enabled ?? false,
    inheritedKitten2: ttsProvider === "kitten" && KITTEN2_MODELS.has(kittenModel),
    inheritedReference: !!(profile?.reference_audio ?? config.tts.voice_clone?.reference_audio),
    inheritedTranscript: profile?.reference_audio != null ? !!profile.reference_text_file : !!(profile?.reference_text_file ?? config.tts.voice_clone?.reference_text_file),
    referenceAudio: "", referenceText: "", referenceTextFile: "",
    llm: analyzedWithLlm ?? config.llm.enabled,
    provider,
    model: preferences.llm_model || config.llm[MODEL_KEY[provider]].model,
    contextTokens: String(config.llm.max_context_tokens),
    outputTokens: String(config.llm.max_output_tokens),
    remoteConsent: config.llm.allow_remote_content,
    voice: preferences.default_voice || profile?.voice || tts.voice,
    speed: profile?.speed ?? tts.speed,
    temperature: profile?.temperature ?? config.tts.kitten.temperature ?? TEMPERATURE.fallback,
    allChapters: true,
    firstChapter: "1",
    lastChapter: chapters ? String(chapters) : "1",
    cover: null,
    verifyAudio: false,
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
  const errors: OptionsErrors = cloneErrors(form);
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
  const temperature = temperatureError(form.temperature);
  if (temperature) errors.temperature = temperature;
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
    ...cloneRequest(form),
    voice: isCloning(form) ? null : form.voice || null,
    speed: form.speed,
    ...temperatureRequest(form, form.temperature),
    cover: form.cover,
    verify_audio: form.verifyAudio,
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
