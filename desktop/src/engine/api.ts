import { invoke } from "@tauri-apps/api/core";
import type { AppSettings, EngineInfo, Library, Outcome, Request } from "./types";

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
