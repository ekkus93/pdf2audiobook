import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InspectManifest, LibraryBook, Request } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(),
  describe: vi.fn(),
  openReview: vi.fn(),
  bookAudio: vi.fn(),
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
  vi.mocked(api.bookAudio).mockResolvedValue([]);
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
    // Pending edits and the audio check report the same engine failure in their own sections.
    expect(await screen.findAllByText("Invalid configuration")).toHaveLength(3);
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

  it("checks the new audio only when that option is switched on", async () => {
    const onStart = await renderPage();
    const check = screen.getByText("Check the new audio with speech recognition").closest("label")?.querySelector("md-switch") as HTMLElement & {
      selected: boolean;
    };
    expect(check.selected).toBeFalsy();
    click(button("Convert to audio"));
    expect(onStart).toHaveBeenLastCalledWith(
      expect.objectContaining({ command: "convert", convert: expect.objectContaining({ verify_audio: false }) }),
      "/out/lighthouse-1",
    );
    act(() => {
      check.selected = true;
      check.dispatchEvent(new Event("change", { bubbles: true }));
    });
    click(button("Convert to audio"));
    expect(onStart).toHaveBeenLastCalledWith(
      expect.objectContaining({ command: "convert", convert: expect.objectContaining({ verify_audio: true }) }),
      "/out/lighthouse-1",
    );
    // Analysis never checks audio.
    click(button("Analyze again"));
    expect(onStart.mock.lastCall?.[0]).not.toHaveProperty("convert");
  });

  it("a book analyzed without the LLM starts with it off and converts with --no-llm", async () => {
    expect(CONFIG.llm.enabled).toBe(true);
    const book = { ...BOOK, inspect: { ...(BOOK.inspect as InspectManifest), analyzed_with_llm: false } };
    const onStart = await renderPage(vi.fn(), book);
    const llm = document.querySelector("md-switch") as HTMLElement & { selected: boolean };
    expect(llm.selected).toBeFalsy();
    click(button("Convert to audio"));
    expect(onStart).toHaveBeenLastCalledWith(
      expect.objectContaining({ command: "convert", options: expect.objectContaining({ llm: false }) }),
      "/out/lighthouse-1",
    );
  });

  it("a book analyzed with the LLM keeps it on", async () => {
    const book = { ...BOOK, inspect: { ...(BOOK.inspect as InspectManifest), analyzed_with_llm: true } };
    const onStart = await renderPage(vi.fn(), book);
    click(button("Convert to audio"));
    expect(onStart).toHaveBeenLastCalledWith(
      expect.objectContaining({ options: expect.objectContaining({ llm: true }) }),
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

  it("lists the chapters' audio and passes a chosen chapter to the player", async () => {
    const files = [{ path: "/out/lighthouse-1/audio/001 - One.mp3", name: "001 - One.mp3", bytes: 10 }];
    vi.mocked(api.bookAudio).mockResolvedValue(files);
    const onPlay = vi.fn();
    render(<BookPage book={BOOK} outputDir="/out" minConfidence={0.75} onBack={vi.fn()} onStart={vi.fn()} onPlay={onPlay} />);
    expect(await screen.findByText("1 of 2 chapters converted")).toBeInTheDocument();
    expect(api.bookAudio).toHaveBeenCalledWith(BOOK.workspace);
    await act(async () => {
      screen.getByLabelText("Play chapter 1").dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(onPlay).toHaveBeenCalledWith(files, 0);
  });

  it("has no chapters and audio section before analysis", async () => {
    await renderPage(vi.fn(), { ...BOOK, analyzed: false, inspect: null, source: "/books/new.pdf" });
    expect(screen.queryByRole("heading", { name: "Chapters and audio" })).not.toBeInTheDocument();
    expect(api.bookAudio).not.toHaveBeenCalled();
  });
});

it("restores transient clone drafts and clears paired text when picking a new recording", async () => {
  const change = vi.fn();
  const onStart = vi.fn();
  const { defaults } = await import("./bookOptions");
  vi.mocked(api.run).mockImplementation(async (request: Request) => {
    if (request.command === "config_show") return { outcome: "success", result: CONFIG };
    if (request.command === "tts_models") return { outcome: "success", result: { models: [] } };
    if (request.command === "edits_list") return { outcome: "success", result: { edits: [] } };
    return { outcome: "success", result: { voices: ["Jasper"], listable: true } };
  });
  const draft = { ...defaults(CONFIG, 2), llm: false, voiceMode: "clone" as const, referenceAudio: "/clips/old.wav", referenceText: "PRIVATE DRAFT" };
  const rendered = render(<BookPage book={BOOK} outputDir="/out" minConfidence={0.75} onBack={vi.fn()} onStart={onStart} draft={draft} onDraftChange={change} />);
  expect(await screen.findByLabelText("Reference transcript (optional)")).toHaveValue("PRIVATE DRAFT");
  // A failed start keeps the mounted form and its transient draft.
  click(button("Convert to audio"));
  expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ convert: expect.objectContaining({ reference_text: "PRIVATE DRAFT", voice: null }) }), BOOK.workspace);
  expect(screen.getByLabelText("Reference transcript (optional)")).toHaveValue("PRIVATE DRAFT");
  rendered.unmount();
  render(<BookPage book={BOOK} outputDir="/out" minConfidence={0.75} onBack={vi.fn()} onStart={onStart} draft={draft} onDraftChange={change} />);
  expect(await screen.findByLabelText("Reference transcript (optional)")).toHaveValue("PRIVATE DRAFT");
  vi.mocked(open).mockResolvedValue("/clips/new.wav");
  await act(async () => button("Choose recording").dispatchEvent(new Event("click", { bubbles: true })));
  expect(change).toHaveBeenCalledWith(expect.objectContaining({ referenceAudio: "/clips/new.wav", referenceText: "", referenceTextFile: "" }));
});

describe("the Kitten 2 temperature", () => {
  const KITTEN2 = { ...CONFIG, tts: { ...CONFIG.tts, kitten: { ...CONFIG.tts.kitten, model: "kitten2", temperature: 0.4 } } };
  const slider = () => document.querySelector('md-slider[aria-label="Temperature"]') as (HTMLElement & { value: number }) | null;
  const serve = (config: typeof CONFIG) =>
    vi.mocked(api.run).mockImplementation(async (request: Request) => {
      if (request.command === "config_show") return { outcome: "success", result: config };
      if (request.command === "tts_models") return { outcome: "success", result: { models: [] } };
      if (request.command === "edits_list") return { outcome: "success", result: { edits: [] } };
      return { outcome: "success", result: { provider: "kitten", voices: ["Jasper"], listable: true, default_voice: "Jasper" } };
    });
  const converted = (onStart: ReturnType<typeof vi.fn>) => {
    click(button("Convert to audio"));
    return (onStart.mock.lastCall?.[0] as Extract<Request, { command: "convert" }>).convert;
  };

  it("is hidden and not sent when another model speaks the book", async () => {
    const onStart = await renderPage();
    expect(slider()).toBeNull();
    expect(converted(onStart)).not.toHaveProperty("temperature");
  });

  it("starts from the configuration and sends the chosen value for Kitten 2", async () => {
    serve(KITTEN2);
    const onStart = await renderPage();
    const control = slider();
    expect(control?.value).toBe(0.4);
    expect(screen.getByText("0.40")).toBeInTheDocument();
    expect(screen.getByText(/Lower keeps the narration closer to the text/)).toBeInTheDocument();
    expect(converted(onStart).temperature).toBe(0.4);
    act(() => {
      Object.defineProperty(control, "value", { value: 0.6, writable: true, configurable: true });
      control?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(converted(onStart).temperature).toBe(0.6);
  });

  it("appears when a voice is cloned, since cloning uses Kitten 2", async () => {
    serve(CONFIG);
    const onStart = await renderPage();
    const mode = Array.from(document.querySelectorAll("md-outlined-select")).find((element) => (element as HTMLElement & { label: string }).label === "Voice source");
    act(() => {
      Object.defineProperty(mode, "value", { value: "clone", writable: true, configurable: true });
      mode?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(slider()?.value).toBe(0.2);
    const field = Array.from(document.querySelectorAll("md-outlined-text-field")).find((element) => (element as HTMLElement & { label: string }).label === "Reference recording");
    act(() => {
      Object.defineProperty(field, "value", { value: "/clips/a.wav", writable: true, configurable: true });
      field?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(converted(onStart).temperature).toBe(0.2);
  });
});
