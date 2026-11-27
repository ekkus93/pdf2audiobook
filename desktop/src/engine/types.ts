// Types for the bridge's Tauri commands; they mirror src-tauri/src/{commands,engine}.rs.

export type LlmProvider = "ollama" | "openai" | "llama-server";

/** The editable shared TOML file, separate from effective environment overrides. */
export interface CliConfigFile {
  path: string;
  text: string;
}

/** Options shared by analyze and convert; mirrors `BookOptions` in request.rs. */
export interface BookOptions {
  output?: string | null;
  ocr?: "auto" | "always" | "never" | null;
  pdf_password_env?: string | null;
  llm?: boolean | null;
  llm_provider?: LlmProvider | null;
  llm_model?: string | null;
  llm_url?: string | null;
  llm_context_tokens?: number | null;
  llm_output_tokens?: number | null;
  process_citations?: boolean | null;
  process_equations?: boolean | null;
  allow_remote_content?: boolean | null;
  vision?: boolean | null;
  allow_single_chapter?: boolean | null;
  resume?: boolean | null;
}

/** Private local reference options, shared by conversion and selective repair. */
export interface VoiceCloneOptions {
  clone_voice?: boolean | null;
  reference_audio?: string | null;
  reference_text_file?: string | null;
  /** Transient draft. Rust writes a private file; this text never enters argv. */
  reference_text?: string | null;
}
export interface TtsReadiness {
  name: string; model_id: string; revision: string; cloning: boolean;
  ready: boolean; package_installed: boolean; weights_present: boolean;
  size_bytes: number; download_bytes: number; directory: string;
  transcription_ready: boolean; detected_device: string; reason: string | null;
  files: Array<{ name: string; source: string; size_bytes: number; sha256: string; cached: boolean }>;
}
export interface TtsModels { models: Array<Partial<TtsReadiness> & { name: string }> }

/** Options only convert takes; mirrors `ConvertOptions` in request.rs. */
export interface ConvertOptions extends VoiceCloneOptions {
  tts_provider?: "kitten" | "piper" | null;
  tts_model?: string | null;
  voice?: string | null;
  bitrate?: string | null;
  chapters?: { kind: "one"; chapter: number } | { kind: "range"; first: number; last: number } | null;
  dry_run?: boolean;
  speed?: number | null;
  /** The Kitten 2 sampling temperature; omitted leaves it to the CLI's configuration. */
  temperature?: number | null;
  sample_rate?: number | null;
  cover?: string | null;
  accept_review?: Array<"damaged_source" | "ambiguous_page_numbers">;
  force?: boolean;
  /** Check the converted chapters with the speech recognizers afterwards (opt-in). */
  verify_audio?: boolean;
}

export type AsrModel = "whisper" | "wav2vec2" | "vosk";

/** An optional feature the built-in engine installs on demand (contracts/addons-list.schema.json). */
export type AddonName = "kitten2" | "audio-check";
export interface AddonState {
  name: AddonName;
  title: string;
  installed: boolean;
  components: Array<{ name: string; installed: boolean; packages: number }>;
  /** Add-ons for an older engine version are present; they are not used. */
  older_version_installed: boolean;
}
/** `addons list --json`; outside the built-in engine `available` is false. */
export interface AddonsList {
  available: boolean;
  addons: AddonState[];
}
/** `addons languages --json` (contracts/addon-languages.schema.json). */
/** A component inside the built-in engine and its licence (self-contained app spec C9). */
export interface Notice {
  name: string;
  version: string;
  license: string;
  source: string;
  files: string[];
}

export interface AddonLanguages {
  available: string[];
  installed: string[];
  bundled: string[];
}

export type Request =
  | { command: "analyze"; book: string; options: BookOptions }
  | { command: "convert"; book: string; options: BookOptions; convert: ConvertOptions }
  | { command: "doctor"; check_llm?: boolean }
  | { command: "recover"; manifest: string; back_up_changed: boolean }
  | { command: "pack_m4b"; manifest: string; output: string; bitrate?: string | null; cover?: string | null }
  | {
      command: "regenerate_chapter";
      manifest: string;
      which: { kind: "chapter"; chapter: number } | { kind: "all_conflicts" };
      footnotes?: "warn" | "inline" | "end" | "omit" | null;
    }
  | { command: "budget_show"; workspace: string }
  | { command: "edits_list"; manifest: string; status: "pending" | "accepted" | "rejected" | "all"; with_text?: boolean }
  | { command: "edits_accept"; manifest: string; which: { kind: "all" } | { kind: "blocks"; ids: string[] } }
  | { command: "edits_reject"; manifest: string; which: { kind: "all" } | { kind: "blocks"; ids: string[] } }
  | { command: "config_show" }
  | { command: "inspect"; source: string; pdf_password_env?: string | null }
  | { command: "workspace"; book: string; output?: string | null }
  | { command: "voices"; tts_provider?: "kitten" | "piper" | null; tts_model?: string | null }
  | { command: "tts_models" }
  | { command: "tts_fetch" }
  | { command: "addons_list" }
  | { command: "addons_install"; addon: AddonName }
  | { command: "addons_remove"; addon: AddonName }
  | { command: "addon_languages" }
  | { command: "addon_add_languages"; languages: string[] }
  | { command: "addon_remove_language"; language: string }
  | { command: "asr_list" }
  | { command: "asr_fetch"; models: AsrModel[] }
  | { command: "verify_audio"; manifest: string; chapters?: number[]; models?: AsrModel[] }
  | { command: "audio_report"; manifest: string }
  | { command: "audio_dismiss"; manifest: string; chapter: number; flag: number; undo?: boolean }
  | (VoiceCloneOptions & { tts_provider?: "kitten" | "piper" | null; tts_model?: string | null; command: "resynthesize"; manifest: string; chapters: number[]; voice: string | null; speed: number | null; temperature?: number | null; verify_audio: boolean | null });

/** One speech recognizer's readiness (`asr list --json`, contracts/asr-models.schema.json). */
export interface AsrReadiness {
  model: AsrModel;
  family: string;
  model_id: string;
  revision: string;
  package: string;
  package_version: string | null;
  weights_present: boolean;
  size_bytes: number;
  location: string;
  ready: boolean;
  reason: string | null;
}

export interface AsrModels {
  models: AsrReadiness[];
}

export type ChapterVerdict = "no_mismatch_detected" | "possible_mismatch" | "model_disagreement" | "verification_unavailable";

/** A passage the models heard differently from the narration. */
export interface VerificationFlag {
  kind: "insertion" | "omission" | "substitution";
  confirmed: boolean;
  models: AsrModel[];
  ref_start: number;
  ref_end: number;
  expected: string;
  heard: Partial<Record<AsrModel, string>>;
  before: string;
  after: string;
  start: number | null;
  end: number | null;
  reviewed: boolean;
}

export interface ChapterVerification {
  number: number;
  status: ChapterVerdict;
  reason: string | null;
  partial: boolean;
  audio_sha256: string | null;
  duration_seconds: number | null;
  models: Array<{ model: AsrModel; outcome: "ok" | "unavailable" | "failed"; reason: string | null; seconds: number | null; word_count: number | null }>;
  flags: VerificationFlag[];
}

/** `reports/audio_verification.json` (contracts/audio-verification.schema.json). */
export interface VerificationReport {
  schema_version: 1;
  created_at: string;
  completed_at: string | null;
  models: Array<{ model: AsrModel; model_id: string; revision: string; package_version: string | null }>;
  chapters: ChapterVerification[];
  warnings: string[];
}

/** `audio-report show --json` (contracts/audio-report.schema.json). */
export interface AudioReport {
  schema_version: 1;
  report: VerificationReport | null;
  stale: number[];
  warnings: string[];
}

export interface EngineError {
  type: string;
  code: number;
  message: string;
  reason?: string;
}

export type Outcome<T = Record<string, unknown>> =
  | { outcome: "success"; result: T }
  | { outcome: "failed"; error: EngineError; warnings: string[] }
  | { outcome: "unreadable"; exit_code: number | null };

export type LocateError =
  | { kind: "not_found" }
  | { kind: "unresponsive" }
  | { kind: "bundled_broken" }
  | { kind: "version_mismatch"; cli: string; app: string; app_series: string };

export type BridgeError =
  | { kind: "locate"; error: LocateError; message: string }
  | { kind: "request"; message: string }
  | { kind: "busy"; message: string }
  | { kind: "start" };

export interface EngineInfo {
  version: string;
  source: "bundled" | "configured" | "on_path" | "uv_project";
  command: string;
}

export interface LlmCheck {
  provider: "ollama" | "openai" | "llama-server" | "disabled";
  checked: boolean;
  model?: string;
  configured_context?: number;
  output_tokens?: number;
  chunk_tokens?: number;
  estimated_tokens_needed?: number;
  reachable?: boolean;
  served_context?: number | null;
  enough?: boolean;
}

/** `doctor --json` (desktop/contracts/doctor.schema.json). */
export interface Doctor {
  version: string;
  ffmpeg: boolean;
  tesseract: boolean;
  ocr_requested_languages: string;
  ocr_installed_languages: string[];
  ocr_missing_languages: string[];
  kitten_installed: boolean;
  piper_installed: boolean;
  llm_provider: "ollama" | "openai" | "llama-server" | "disabled";
  process_citations: boolean;
  process_equations: boolean;
  llm_timeout_seconds: number | null;
  llm_check?: LlmCheck;
  warnings: string[];
}

export interface InspectChapter {
  number: number;
  title: string;
  confidence: number;
  manually_approved: boolean;
}

/** `inspect MANIFEST --json` (desktop/contracts/inspect-manifest.schema.json). */
export interface InspectManifest {
  title: string;
  source_path: string;
  review_required: string[];
  review_acknowledged: string[];
  approved: boolean;
  chapters: InspectChapter[];
  conversion_status?: { chapters: Array<{ number: number; status: string }> };
  /** Whether the last analysis used the LLM; null if the workspace doesn't record it. */
  analyzed_with_llm?: boolean | null;
}

export interface RunStage {
  name: string;
  detail: string | null;
  unit: string;
  done: number;
  total: number | null;
  elapsed_seconds: number;
  estimated_remaining_seconds: number | null;
}

/** `reports/run_status.json` (desktop/contracts/run-status.schema.json). */
export interface RunStatus {
  command: string;
  state: "running" | "completed" | "stopped";
  updated_at: string;
  elapsed_seconds: number;
  stage?: RunStage | null;
  completed_stages?: Array<{ name: string; seconds: number }>;
}

/** `run_progress`: a run still going, or its result (src-tauri/src/engine/live.rs). */
export type Progress =
  | { state: "running"; status: RunStatus | null; cancelling: boolean }
  | { state: "finished"; status: RunStatus | null; outcome: Outcome; cancelled: boolean };

export interface LibraryBook {
  workspace: string;
  manifest: string;
  /** False for a book added in the app that hasn't been analyzed yet. */
  analyzed: boolean;
  /** True while a run this app started is working on the book. */
  live: boolean;
  source: string | null;
  inspect: InspectManifest | null;
  error: string | null;
  run_status: RunStatus | null;
  thumbnail: string | null;
}

export interface Library {
  output_dir: string;
  min_boundary_confidence: number;
  books: LibraryBook[];
  /** The commands run to build the library, for "Details". */
  commands: string[];
}

export type Theme = "dark" | "light" | "system";

export interface AppSettings {
  cli_path: string | null;
  uv_project: string | null;
  /** Use `cli_path`, PATH or `uv_project` before the engine built into the app. */
  developer_engine: boolean;
  output_dir: string | null;
  theme: Theme;
  added_books: string[];
  /** The voice new books start with; null uses the CLI's voice. */
  default_voice: string | null;
  /** The LLM provider new books start with; null uses the CLI's provider. */
  llm_provider: LlmProvider | null;
  /** The LLM model new books start with; null uses the CLI's model for the provider. */
  llm_model: string | null;
}

/** The parts of `config show --json` the app reads. */
export interface CliConfig {
  general: { output_dir: string };
  llm: {
    enabled: boolean;
    provider: LlmProvider;
    max_context_tokens: number;
    max_output_tokens: number;
    allow_remote_content: boolean;
    /** Per-book LLM budgets; null means no limit. */
    max_requests?: number | null;
    max_reported_tokens?: number | null;
    max_estimated_cost_usd?: number | null;
    ollama: { model: string };
    openai: { model: string };
    llama_server: { model: string };
  };
  tts: {
    provider: "kitten" | "piper";
    profiles?: Record<string, { provider?: "kitten" | "piper" | null; kitten_model?: string | null; voice?: string | null; speed?: number | null; temperature?: number | null; clone_voice?: boolean | null; reference_audio?: string | null; reference_text_file?: string | null }>;
    voice_clone?: { enabled: boolean; reference_audio: string | null; reference_text_file: string | null };
    /** `temperature` is the Kitten 2 sampling temperature; older CLIs do not report it. */
    kitten: { model: string; voice: string; speed: number; temperature?: number };
    piper: { voice: string; speed: number };
  };
  chapters: { min_boundary_confidence: number };
}

/** `voices --json`. */
export interface Voices {
  provider: "kitten" | "piper";
  voices: string[];
  listable: boolean;
  default_voice: string;
}

/** One row of `edits list --json --with-text`. */
export interface PendingEdit {
  block_id: string;
  chapter: number | null;
  provider: string;
  status: "pending" | "accepted" | "rejected";
  reason?: string;
  original?: string;
  replacement?: string;
}

/** A chapter MP3 (src-tauri/src/audio.rs). */
export interface AudioFile {
  path: string;
  name: string;
  bytes: number;
}

/** `budget show --json` (desktop/contracts/budget-show.schema.json). */
export interface BudgetReport {
  requests: Array<{
    id: number;
    status: string;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    total_tokens: number | null;
    estimated_cost_usd: number | null;
  }>;
  totals: {
    requests_started: number;
    unresolved_requests: number;
    reported_tokens: number;
    estimated_cost_usd: number;
    unpriced_requests?: number;
  };
}
