import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { AppSettings, AudioFile, CliConfigFile, EngineInfo, Library, Notice, Outcome, Progress, Request } from "./types";

/** Finds and confirms the CLI (spec D3.a). Rejects with a `BridgeError`. */
export function locateEngine(): Promise<EngineInfo> {
  return invoke<EngineInfo>("locate_engine");
}

/** Runs one request; write-capable requests must name their workspace. */
export function run<T = Record<string, unknown>>(request: Request, workspace?: string): Promise<Outcome<T>> {
  return invoke<Outcome<T>>("run_engine", { request, workspace: workspace ?? null });
}

/** The command line a request runs, for "Details". */
export function describe(request: Request): Promise<string> {
  return invoke<string>("describe_request", { request });
}

export function library(): Promise<Library> {
  return invoke<Library>("library");
}

/** Remembers a book picked in the file dialog so the library shows it before analysis. */
export async function addBook(book: string): Promise<void> {
  await invoke("add_book", { book });
}

export function getSettings(): Promise<AppSettings> {
  return invoke<AppSettings>("get_settings");
}

export async function saveSettings(settings: AppSettings): Promise<void> {
  await invoke("save_settings", { settings });
}

export function readCliConfig(): Promise<CliConfigFile> {
  return invoke<CliConfigFile>("read_cli_config");
}

/** The backend validates TOML and rejects changes to a file edited since it was loaded. */
export function saveCliConfig(text: string, expected: string): Promise<CliConfigFile> {
  return invoke<CliConfigFile>("save_cli_config", { text, expected });
}

/** The built-in engine's components and licences; null in a build without one. */
export function engineNotices(): Promise<Notice[] | null> {
  return invoke<Notice[] | null>("engine_notices");
}

/** One component's licence texts, by its place in `engineNotices`. */
export function engineNoticeText(index: number): Promise<string> {
  return invoke<string>("engine_notice_text", { index });
}

/** A user-facing sentence for anything `invoke` rejects with. */
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error && typeof error.message === "string") {
    return error.message;
  }
  return "The engine could not be started";
}

/** Starts analyze or convert for a book's workspace; resolves with the run's ID at once. */
export function startRun(request: Request, workspace: string): Promise<number> {
  return invoke<number>("start_run", { request, workspace });
}

export function runProgress(id: number): Promise<Progress> {
  return invoke<Progress>("run_progress", { id });
}

/** Asks a run to stop; the bridge kills it if it hasn't stopped after 30 seconds. */
export async function cancelRun(id: number): Promise<void> {
  await invoke("cancel_run", { id });
}

/** Stops every run, then quits the app. */
export async function quitApp(): Promise<void> {
  await invoke("quit_app");
}

/** Called when the window is closed while a run is going; returns an unsubscribe function. */
export function onCloseRequested(handler: () => void): Promise<() => void> {
  return listen("close-requested", handler);
}

/** Opens the chapter review page for a book in its own window (spec D6). */
export async function openReview(manifest: string, workspace: string, title: string): Promise<void> {
  await invoke("open_review", { manifest, workspace, title });
}

/** Called when the review window has closed and its server has stopped. */
export function onReviewClosed(handler: () => void): Promise<() => void> {
  return listen("review-closed", handler);
}

/** A book's chapter MP3s. */
export function bookAudio(workspace: string): Promise<AudioFile[]> {
  return invoke<AudioFile[]>("book_audio", { workspace });
}

/** Lets the player read this book's chapters (and no other book's) through `chapter:`. */
export async function playBookAudio(workspace: string): Promise<void> {
  await invoke("play_book_audio", { workspace });
}

export async function openAudioFolder(workspace: string): Promise<void> {
  await invoke("open_audio_folder", { workspace });
}

/** Writes a zip of the chapter MP3s (and the book, if `source` is given); resolves with the file count. */
export function exportZip(workspace: string, destination: string, title: string, source: string | null): Promise<number> {
  return invoke<number>("export_zip", { workspace, destination, title, source });
}
