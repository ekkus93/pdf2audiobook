import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InspectManifest, LibraryBook, Request } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(),
  describe: vi.fn(),
  openReview: vi.fn(),
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
  live: false,
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
    if (request.command === "edits_list") return { outcome: "success", result: { edits: [] } };
    return {
      outcome: "success",
      result: { provider: "kitten", voices: ["Jasper", "Luna"], listable: true, default_voice: "Jasper" },
    };
  });
  vi.mocked(api.describe).mockImplementation(async (request: Request) => `pdf2audiobook ${request.command} …`);
}

beforeEach(respond);

/** The Material button whose label contains `text`. */
function button(text: string): HTMLElement {
  const found = Array.from(
    document.querySelectorAll("md-filled-button, md-filled-tonal-button, md-outlined-button, md-text-button"),
  ).find((element) => element.textContent?.includes(text));
  if (!found) throw new Error(`no button labelled ${text}`);
  return found as HTMLElement;
}

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
    // Pending edits report the same engine failure in their own section.
    expect(screen.getAllByText("Invalid configuration")).toHaveLength(2);
  });

  it("starts analysis and conversion with the chosen options", async () => {
    const onStart = await renderPage();
    const [analyze, convert] = [button("Analyze again"), button("Convert to audio")];
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
    expect(button("Analyze")).not.toHaveTextContent("again");
    expect(screen.queryByText("Review chapters")).not.toBeInTheDocument();
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
    click(button("Convert to audio"));
    expect(onStart).not.toHaveBeenCalled();
  });

  it("chooses a cover image", async () => {
    vi.mocked(open).mockResolvedValue("/art/cover.png");
    await renderPage();
    await act(async () => {
      button("Choose image").dispatchEvent(new Event("click", { bubbles: true }));
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

  it("opens chapter review for an analyzed book", async () => {
    vi.mocked(api.openReview).mockResolvedValue(undefined);
    const onReviewOpened = vi.fn();
    render(
      <BookPage book={BOOK} outputDir="/out" minConfidence={0.75} onBack={vi.fn()} onStart={vi.fn()} onReviewOpened={onReviewOpened} />,
    );
    expect(screen.getByRole("heading", { name: "Chapter review" })).toBeInTheDocument();
    await act(async () => {
      button("Review chapters").dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(api.openReview).toHaveBeenCalledWith(BOOK.manifest, BOOK.workspace, "The Lighthouse at Gull Point");
    expect(onReviewOpened).toHaveBeenCalledOnce();
    await screen.findByRole("heading", { name: "Analysis" });
  });

  it("asks for review when chapters need it, and says when the window is open", async () => {
    const uncertain = {
      ...BOOK,
      inspect: {
        ...(BOOK.inspect as InspectManifest),
        chapters: [{ number: 1, title: "One", confidence: 0.5, manually_approved: false }],
      },
    };
    const { rerender } = render(
      <BookPage book={uncertain} outputDir="/out" minConfidence={0.75} onBack={vi.fn()} onStart={vi.fn()} />,
    );
    expect(screen.getByRole("heading", { name: "Chapters need your review" })).toBeInTheDocument();
    expect(button("Review chapters").tagName).toBe("MD-FILLED-BUTTON");
    rerender(<BookPage book={uncertain} reviewing outputDir="/out" minConfidence={0.75} onBack={vi.fn()} onStart={vi.fn()} />);
    expect(screen.getByText(/The review page is open in its own window/)).toBeInTheDocument();
    expect(button("Review chapters")).toHaveAttribute("disabled");
    await screen.findByRole("heading", { name: "Analysis" });
  });

  it("shows why review couldn't open", async () => {
    vi.mocked(api.openReview).mockRejectedValue({ kind: "busy", message: "Another task is already changing this book; wait for it to finish" });
    await renderPage();
    await act(async () => {
      button("Review chapters").dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(screen.getByText("Another task is already changing this book; wait for it to finish")).toBeInTheDocument();
  });

  it("explains merging and splitting without editing the manifest", async () => {
    await renderPage();
    const details = screen.getByText("Merging or splitting chapters").closest("details") as HTMLDetailsElement;
    expect(details).toHaveTextContent("can't add or remove chapters");
    expect(details).toHaveTextContent("Protecting manual edits");
    expect(details).toHaveTextContent("The app never edits the manifest itself.");
    expect(within(details).getByText(BOOK.manifest)).toBeInTheDocument();
  });
});
