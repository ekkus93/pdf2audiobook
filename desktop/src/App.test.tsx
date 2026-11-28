import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./engine/api", async (original) => ({
  ...(await original<typeof import("./engine/api")>()),
  getSettings: vi.fn(),
  library: vi.fn(),
  locateEngine: vi.fn(),
  run: vi.fn(),
  describe: vi.fn(),
  onCloseRequested: vi.fn(),
  onReviewClosed: vi.fn(),
  quitApp: vi.fn(),
  startRun: vi.fn(),
  runProgress: vi.fn(),
  bookAudio: vi.fn(),
}));

import * as api from "./engine/api";
import type { LibraryBook, Request } from "./engine/types";
import App from "./App";
import { CONFIG } from "./screens/bookOptions.test";

beforeEach(() => {
  vi.mocked(api.getSettings).mockResolvedValue({
    cli_path: null,
    uv_project: null,
    developer_engine: false,
    output_dir: null,
    theme: "light",
    added_books: [],
    default_voice: null,
    llm_provider: null,
    llm_model: null,
  });
  vi.mocked(api.library).mockResolvedValue({ output_dir: "/out", min_boundary_confidence: 0.75, books: [], commands: [] });
  vi.mocked(api.locateEngine).mockReturnValue(new Promise(() => {}));
  // Requests a test does not answer stay pending, as an engine that has not replied yet.
  vi.mocked(api.run).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.onCloseRequested).mockImplementation(async (handler) => {
    closeRequested = handler;
    return () => undefined;
  });
  vi.mocked(api.quitApp).mockResolvedValue(undefined);
  vi.mocked(api.onReviewClosed).mockImplementation(async (handler) => {
    reviewClosed = handler;
    return () => undefined;
  });
});

let reviewClosed: () => void = () => undefined;

let closeRequested: () => void = () => undefined;

describe("App shell", () => {
  it("opens on the library with the rail's three destinations", async () => {
    render(<App />);
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Library" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Run" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("heading", { level: 1, name: "Library" })).toBeInTheDocument();
    expect(await screen.findByText("No books yet")).toBeInTheDocument();
  });

  it("applies the saved theme", async () => {
    render(<App />);
    await screen.findByText("No books yet");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("moves between destinations with the keyboard", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.tab();
    expect(screen.getByRole("button", { name: "Library" })).toHaveFocus();
    await user.tab();
    await user.tab();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("main", { name: "Settings" })).toBeInTheDocument();
  });

  it("re-reads the library when the review window closes", async () => {
    render(<App />);
    await screen.findByText("No books yet");
    expect(api.library).toHaveBeenCalledTimes(1);
    await act(async () => reviewClosed());
    expect(api.library).toHaveBeenCalledTimes(2);
  });

  it("asks before quitting while a run is going, then stops it and quits", async () => {
    render(<App />);
    await screen.findByText("No books yet");
    act(() => closeRequested());
    const dialog = document.querySelector("md-dialog") as HTMLElement & { open: boolean };
    expect(dialog.open).toBe(true);
    expect(dialog).toHaveTextContent("Stop the running task and quit?");
    const [keep, quit] = Array.from(dialog.querySelectorAll("md-text-button, md-filled-button"));
    expect(keep).toHaveTextContent("Keep running");
    await act(async () => {
      quit.dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(api.quitApp).toHaveBeenCalledOnce();
  });

  it("shows the book as the run left it when going back from the run", async () => {
    const before: LibraryBook = {
      workspace: "/out/lighthouse-1",
      manifest: "/out/lighthouse-1/manifest.json",
      analyzed: false,
      live: false,
      source: "/books/lighthouse.pdf",
      inspect: null,
      error: null,
      run_status: null,
      thumbnail: null,
    };
    const after: LibraryBook = {
      ...before,
      analyzed: true,
      source: null,
      inspect: {
        title: "The Lighthouse at Gull Point",
        source_path: "/books/lighthouse.pdf",
        review_required: [],
        review_acknowledged: [],
        approved: false,
        chapters: [{ number: 1, title: "One", confidence: 1, manually_approved: false }],
      },
    };
    const shelf = (book: LibraryBook) => ({ output_dir: "/out", min_boundary_confidence: 0.75, books: [book], commands: [] });
    vi.mocked(api.library).mockResolvedValueOnce(shelf(before)).mockResolvedValue(shelf(after));
    vi.mocked(api.run).mockImplementation(async (request: Request) => {
      if (request.command === "config_show") return { outcome: "success", result: CONFIG };
      if (request.command === "edits_list") return { outcome: "success", result: { edits: [] } };
      return { outcome: "success", result: { provider: "kitten", voices: ["Jasper"], listable: true, default_voice: "Jasper" } };
    });
    vi.mocked(api.describe).mockResolvedValue("pdf2audiobook …");
    vi.mocked(api.bookAudio).mockResolvedValue([]);
    vi.mocked(api.startRun).mockResolvedValue(7);
    vi.mocked(api.runProgress).mockResolvedValue({
      state: "finished",
      status: null,
      outcome: { outcome: "success", result: {} },
      cancelled: false,
    });
    const press = async (element: Element) => {
      await act(async () => {
        element.dispatchEvent(new Event("click", { bubbles: true }));
      });
    };
    const material = (text: string) =>
      Array.from(document.querySelectorAll("md-filled-button, md-filled-tonal-button")).find((element) =>
        element.textContent?.includes(text),
      ) as Element;

    render(<App />);
    await press(await screen.findByRole("button", { name: /^Open / }));
    await screen.findByRole("heading", { name: "Analysis" });
    await press(material("Analyze"));
    expect(api.startRun).toHaveBeenCalledWith(expect.objectContaining({ command: "analyze" }), "/out/lighthouse-1");
    expect(await screen.findByText(/Analysis finished/)).toBeInTheDocument();
    await press(material("Back to the book"));
    expect(await screen.findByRole("heading", { name: "The Lighthouse at Gull Point" })).toBeInTheDocument();
    expect(api.library).toHaveBeenCalledTimes(2);
  });
});
