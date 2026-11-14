import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Doctor } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  locateEngine: vi.fn(),
  run: vi.fn(),
  describe: vi.fn(),
}));

import * as api from "../engine/api";
import { Setup } from "./Setup";

const DOCTOR: Doctor = {
  version: "0.1.0",
  ffmpeg: false,
  tesseract: true,
  ocr_requested_languages: "eng",
  ocr_installed_languages: ["eng"],
  ocr_missing_languages: [],
  kitten_installed: true,
  piper_installed: false,
  llm_provider: "ollama",
  process_citations: true,
  process_equations: true,
  llm_timeout_seconds: 300,
  warnings: [],
};

const engine = { version: "0.1.0", source: "on_path" as const, command: "pdf2audiobook" };

beforeEach(() => {
  vi.mocked(api.locateEngine).mockResolvedValue(engine);
  vi.mocked(api.run).mockResolvedValue({ outcome: "success", result: DOCTOR });
  vi.mocked(api.describe).mockResolvedValue("pdf2audiobook --no-progress doctor --json");
});

describe("Setup", () => {
  it("shows a loading state, then every check", async () => {
    render(<Setup />);
    expect(screen.getByRole("progressbar", { name: "Checking your setup" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Setup checks" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getByRole("status")).toHaveTextContent("1 thing needs attention");
    expect(within(list).getByText("sudo apt install ffmpeg")).toBeInTheDocument();
    expect(api.run).toHaveBeenCalledWith({ command: "doctor" });
  });

  it("says everything is ready when nothing is missing", async () => {
    vi.mocked(api.run).mockResolvedValue({ outcome: "success", result: { ...DOCTOR, ffmpeg: true } });
    render(<Setup />);
    expect(await screen.findByText("Everything is ready")).toBeInTheDocument();
  });

  it("explains how to install the CLI when it isn't found", async () => {
    vi.mocked(api.locateEngine).mockRejectedValue({
      kind: "locate",
      error: { kind: "not_found" },
      message: "The pdf2audiobook command-line tool was not found",
    });
    render(<Setup />);
    expect(await screen.findByText("pdf2audiobook isn't installed")).toBeInTheDocument();
    expect(screen.getByText("The pdf2audiobook command-line tool was not found")).toBeInTheDocument();
    expect(screen.getByText('uv tool install ".[kitten]"')).toBeInTheDocument();
    expect(api.run).not.toHaveBeenCalled();
  });

  it("names a version mismatch", async () => {
    vi.mocked(api.locateEngine).mockRejectedValue({
      kind: "locate",
      error: { kind: "version_mismatch", cli: "0.2.0", app: "0.1.0", app_series: "0.1" },
      message: "pdf2audiobook 0.2.0 can't be used with this app (0.1.0); install a 0.1.x version",
    });
    render(<Setup />);
    expect(await screen.findByText("This pdf2audiobook version can't be used")).toBeInTheDocument();
  });

  it("shows the engine's error when doctor fails", async () => {
    vi.mocked(api.run).mockResolvedValue({
      outcome: "failed",
      error: { type: "ConfigError", code: 2, message: "Invalid configuration" },
      warnings: [],
    });
    render(<Setup />);
    expect(await screen.findByText("The setup check failed")).toBeInTheDocument();
    expect(screen.getByText("Invalid configuration")).toBeInTheDocument();
  });

  it("shows a fixed message for an unreadable result", async () => {
    vi.mocked(api.run).mockResolvedValue({ outcome: "unreadable", exit_code: 1 });
    render(<Setup />);
    expect(await screen.findByText("The engine returned an unreadable result")).toBeInTheDocument();
  });

  it("checks the Ollama context only when asked", async () => {
    render(<Setup />);
    await screen.findByRole("list", { name: "Setup checks" });
    const button = document.querySelector("md-filled-tonal-button") as HTMLElement;
    expect(button).toHaveTextContent("Check context");
    vi.mocked(api.run).mockResolvedValue({
      outcome: "success",
      result: {
        ...DOCTOR,
        llm_check: {
          provider: "ollama",
          checked: true,
          model: "qwen3.5:9b",
          configured_context: 16384,
          output_tokens: 1024,
          chunk_tokens: 4000,
          estimated_tokens_needed: 9248,
          reachable: true,
          served_context: 4096,
          enough: false,
        },
      },
    });
    act(() => {
      button.dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(await screen.findByText(/only 4,096 tokens/)).toBeInTheDocument();
    expect(api.run).toHaveBeenLastCalledWith({ command: "doctor", check_llm: true });
  });

  it("lists the commands it ran under a native Details disclosure", async () => {
    render(<Setup />);
    await screen.findByRole("list", { name: "Setup checks" });
    const summary = screen.getByText("Details");
    // A <summary> is focusable and toggles with Enter or Space in every browser.
    expect(summary.tagName).toBe("SUMMARY");
    const details = summary.closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    details.open = true;
    expect(within(details).getByText("pdf2audiobook --no-progress doctor --json")).toBeInTheDocument();
    expect(within(details).getByText("pdf2audiobook")).toBeInTheDocument();
  });

  it("uses only keyboard-operable controls, each with a name", async () => {
    // jsdom can't move focus into Lit shadow roots; real keyboard use is covered end to end.
    const { container } = render(<Setup />);
    await screen.findByRole("list", { name: "Setup checks" });
    const controls = container.querySelectorAll(
      "button, summary, md-icon-button, md-filled-button, md-filled-tonal-button, md-outlined-button, md-text-button",
    );
    expect(controls.length).toBeGreaterThan(3);
    for (const control of controls) {
      const name = control.getAttribute("aria-label") ?? control.textContent?.trim();
      expect(name, control.outerHTML).toBeTruthy();
    }
    expect(container.querySelectorAll("[onclick], div[tabindex], span[tabindex]")).toHaveLength(0);
  });

  it("copies a fix command", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<Setup />);
    await screen.findByRole("list", { name: "Setup checks" });
    const copy = document.querySelector('[aria-label="Copy command"]') as HTMLElement;
    await act(async () => {
      copy.dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(writeText).toHaveBeenCalledWith("sudo apt install ffmpeg");
    expect(document.querySelector('[aria-label="Copied"]')).not.toBeNull();
  });
});
