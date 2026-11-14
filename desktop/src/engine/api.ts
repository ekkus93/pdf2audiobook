import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { AppSettings, EngineInfo, Library, Outcome, Progress, Request } from "./types";

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
