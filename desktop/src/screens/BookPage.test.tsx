import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LibraryBook, Request } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(),
  describe: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import { open } from "@tauri-apps/plugin-dialog";
import * as api from "../engine/api";
import { BookPage } from "./BookPage";
import { CONFIG } from "./bookOptions.test";

const BOOK: LibraryBook = {
  workspace: "/out/lighthouse-1",
  manifest: "/out/lighthouse-1/manifest.json",
  analyzed: true,
  source: null,
  inspect: {
    title: "The Lighthouse at Gull Point",
    source_path: "/books/lighthouse.pdf",
    review_required: [],
    review_acknowledged: [],
    approved: false,
    chapters: [
      { number: 1, title: "One", confidence: 0.9, manually_approved: false },
      { number: 2, title: "Two", confidence: 0.9, manually_approved: false },
    ],
  },
  error: null,
  run_status: null,
  thumbnail: "data:image/png;base64,UE5H",
};

function respond() {
  vi.mocked(api.run).mockImplementation(async (request: Request) => {
    if (request.command === "config_show") return { outcome: "success", result: CONFIG };
    return {
      outcome: "success",
      result: { provider: "kitten", voices: ["Jasper", "Luna"], listable: true, default_voice: "Jasper" },
    };
  });
  vi.mocked(api.describe).mockImplementation(async (request: Request) => `pdf2audiobook ${request.command} …`);
}

beforeEach(respond);

function click(element: Element | null) {
  act(() => {
    element?.dispatchEvent(new Event("click", { bubbles: true }));
  });
}

async function renderPage(onStart = vi.fn(), book: LibraryBook = BOOK) {
  render(<BookPage book={book} outputDir="/out" minConfidence={0.75} onBack={vi.fn()} onStart={onStart} />);
  await screen.findByRole("heading", { name: "Analysis" });
  return onStart;
}

describe("BookPage", () => {
  it("shows the book and loads the options from the CLI's configuration", async () => {
    render(<BookPage book={BOOK} outputDir="/out" minConfidence={0.75} onBack={vi.fn()} onStart={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "The Lighthouse at Gull Point" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Loading the options" })).toBeInTheDocument();
    for (const name of ["Analysis", "Voice", "Chapters", "Cover art"]) {
      expect(await screen.findByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("2 chapters · lighthouse.pdf")).toBeInTheDocument();
    const model = document.querySelector("md-outlined-text-field") as HTMLElement & { value: string };
    expect(model.value).toBe("qwen3.5:9b");
    expect(api.run).toHaveBeenCalledWith({ command: "config_show" });
    expect(api.run).toHaveBeenCalledWith({ command: "voices" });
  });

  it("shows why the options couldn't load", async () => {
    vi.mocked(api.run).mockResolvedValue({
      outcome: "failed",
      error: { type: "ConfigError", code: 2, message: "Invalid configuration" },
      warnings: [],
    });
    render(<BookPage book={BOOK} outputDir="/out" minConfidence={0.75} onBack={vi.fn()} onStart={vi.fn()} />);
    expect(await screen.findByText("The options couldn't be loaded")).toBeInTheDocument();
    expect(screen.getByText("Invalid configuration")).toBeInTheDocument();
  });

  it("starts analysis and conversion with the chosen options", async () => {
    const onStart = await renderPage();
    const [analyze, convert] = [
      document.querySelector("md-filled-tonal-button"),
      document.querySelector("md-filled-button"),
    ];
    expect(analyze).toHaveTextContent("Analyze again");
    click(analyze);
    expect(onStart).toHaveBeenLastCalledWith(
      expect.objectContaining({ command: "analyze", book: "/books/lighthouse.pdf" }),
      "/out/lighthouse-1",
    );
    click(convert);
    expect(onStart).toHaveBeenLastCalledWith(
      expect.objectContaining({ command: "convert", convert: expect.objectContaining({ voice: "Jasper", speed: 1 }) }),
      "/out/lighthouse-1",
    );
  });

  it("an unanalyzed book offers Analyze", async () => {
    await renderPage(vi.fn(), { ...BOOK, analyzed: false, inspect: null, source: "/books/new.pdf" });
    const button = document.querySelector("md-filled-tonal-button");
    expect(button).toHaveTextContent("Analyze");
    expect(button).not.toHaveTextContent("again");
  });

  it("asks for consent before OpenAI and blocks the buttons until given", async () => {
    const onStart = await renderPage();
    const provider = document.querySelector("md-outlined-select") as HTMLElement;
    vi.spyOn(Object.getPrototypeOf(provider), "value", "get").mockReturnValue("openai");
    act(() => {
      provider.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(await screen.findByText("Send this book's text to OpenAI for analysis")).toBeInTheDocument();
    expect(screen.getByText("Fix the highlighted options first.")).toBeInTheDocument();
    click(document.querySelector("md-filled-button"));
    expect(onStart).not.toHaveBeenCalled();
  });

  it("chooses a cover image", async () => {
    vi.mocked(open).mockResolvedValue("/art/cover.png");
    await renderPage();
    await act(async () => {
      document.querySelector("md-outlined-button")?.dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(open).toHaveBeenCalledWith(expect.objectContaining({ filters: [{ name: "Images", extensions: ["jpg", "jpeg", "png"] }] }));
    expect(screen.getByText("cover.png")).toBeInTheDocument();
  });

  it("lists the commands the buttons run under Details", async () => {
    await renderPage();
    const details = (await screen.findByText("Details")).closest("details") as HTMLDetailsElement;
    expect(within(details).getByText("pdf2audiobook analyze …")).toBeInTheDocument();
    expect(within(details).getByText("pdf2audiobook convert …")).toBeInTheDocument();
  });

  it("goes back with the labelled back button", async () => {
    const onBack = vi.fn();
    render(<BookPage book={BOOK} outputDir="/out" minConfidence={0.75} onBack={onBack} onStart={vi.fn()} />);
    click(document.querySelector('[aria-label="Back to the library"]'));
    expect(onBack).toHaveBeenCalledOnce();
    await screen.findByRole("heading", { name: "Analysis" });
  });

  it("opens from the library card, which is a single named control", async () => {
    const user = userEvent.setup();
    const { Library } = await import("./Library");
    vi.mocked(api.run).mockReset();
    const onOpenBook = vi.fn();
    const library = vi.spyOn(api, "library").mockResolvedValue({
      output_dir: "/out",
      min_boundary_confidence: 0.75,
      books: [BOOK],
      commands: [],
    });
    render(<Library onOpenBook={onOpenBook} />);
    await user.click(await screen.findByRole("button", { name: "Open The Lighthouse at Gull Point" }));
    expect(onOpenBook).toHaveBeenCalledWith(BOOK, expect.objectContaining({ output_dir: "/out" }));
    library.mockRestore();
  });
});
