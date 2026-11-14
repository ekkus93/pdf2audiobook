// Types for the bridge's Tauri commands; they mirror src-tauri/src/{commands,engine}.rs.

export type Request =
  | { command: "doctor"; check_llm?: boolean }
  | { command: "config_show" }
  | { command: "inspect"; source: string; pdf_password_env?: string | null }
  | { command: "workspace"; book: string; output?: string | null }
  | { command: "voices"; tts_provider?: "kitten" | "piper" | null; tts_model?: string | null };

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
  | { kind: "version_mismatch"; cli: string; app: string; app_series: string };

export type BridgeError =
  | { kind: "locate"; error: LocateError; message: string }
  | { kind: "request"; message: string }
  | { kind: "busy"; message: string }
  | { kind: "start" };

export interface EngineInfo {
  version: string;
  source: "configured" | "on_path" | "uv_project";
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
}

/** `reports/run_status.json` (desktop/contracts/run-status.schema.json). */
export interface RunStatus {
  command: string;
  state: "running" | "completed" | "stopped";
  updated_at: string;
  elapsed_seconds: number;
}

export interface LibraryBook {
  workspace: string;
  manifest: string;
  /** False for a book added in the app that hasn't been analyzed yet. */
  analyzed: boolean;
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
  output_dir: string | null;
  theme: Theme;
  added_books: string[];
}
