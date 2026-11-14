import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Library as LibraryData } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  library: vi.fn(),
  addBook: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import { open } from "@tauri-apps/plugin-dialog";
import * as api from "../engine/api";
import { Library } from "./Library";

const DATA: LibraryData = {
  output_dir: "/home/user/audiobooks",
  min_boundary_confidence: 0.75,
  books: [
    {
      workspace: "/home/user/audiobooks/lighthouse-1",
      manifest: "/home/user/audiobooks/lighthouse-1/manifest.json",
      analyzed: true,
      source: null,
      inspect: {
        title: "The Lighthouse at Gull Point",
        source_path: "/books/lighthouse.pdf",
        review_required: [],
        review_acknowledged: [],
        approved: false,
        chapters: [{ number: 1, title: "Front Matter", confidence: 0.7, manually_approved: false }],
      },
      error: null,
      run_status: null,
      thumbnail: "data:image/png;base64,UE5H",
    },
    {
      workspace: "/home/user/audiobooks/new-2",
      manifest: "/home/user/audiobooks/new-2/manifest.json",
      analyzed: false,
      source: "/books/Spring Snow.epub",
      inspect: null,
      error: null,
      run_status: null,
      thumbnail: null,
    },
  ],
};

beforeEach(() => {
  vi.mocked(api.library).mockResolvedValue(DATA);
  vi.mocked(api.addBook).mockResolvedValue(undefined);
});

function click(element: Element) {
  act(() => {
    element.dispatchEvent(new Event("click", { bubbles: true }));
  });
}

describe("Library", () => {
  it("shows a loading state, then a card per book with its state", async () => {
    render(<Library />);
    expect(screen.getByRole("progressbar", { name: "Loading your books" })).toBeInTheDocument();
    const grid = await screen.findByRole("list", { name: "Books" });
    const cards = within(grid).getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByRole("heading", { name: "The Lighthouse at Gull Point" })).toBeInTheDocument();
    expect(cards[0]).toHaveTextContent("Needs review");
    expect(cards[0]).toHaveTextContent("1 chapters");
    expect(cards[0].querySelector("img")).toHaveAttribute("src", "data:image/png;base64,UE5H");
    expect(cards[0].querySelector("img")).toHaveAttribute("alt", "");
    expect(cards[1]).toHaveTextContent("Spring Snow");
    expect(cards[1]).toHaveTextContent("Not analyzed");
  });

  it("shows an empty state that names the output folder", async () => {
    vi.mocked(api.library).mockResolvedValue({ ...DATA, books: [] });
    render(<Library />);
    expect(await screen.findByText("No books yet")).toBeInTheDocument();
    expect(screen.getByText(/\/home\/user\/audiobooks/)).toBeInTheDocument();
  });

  it("sends the user to setup when the engine isn't found", async () => {
    vi.mocked(api.library).mockRejectedValue({
      kind: "locate",
      error: { kind: "not_found" },
      message: "The pdf2audiobook command-line tool was not found",
    });
    const onOpenSettings = vi.fn();
    render(<Library onOpenSettings={onOpenSettings} />);
    expect(await screen.findByText("pdf2audiobook isn't set up yet")).toBeInTheDocument();
    click(document.querySelector("md-filled-tonal-button") as Element);
    expect(onOpenSettings).toHaveBeenCalledOnce();
  });

  it("offers to try again after a failure", async () => {
    vi.mocked(api.library).mockRejectedValueOnce({ kind: "request", message: "The engine reported no output folder" });
    render(<Library />);
    expect(await screen.findByText("The engine reported no output folder")).toBeInTheDocument();
    click(document.querySelector("md-filled-tonal-button") as Element);
    expect(await screen.findByRole("list", { name: "Books" })).toBeInTheDocument();
  });

  it("adds a book picked in the file dialog and reloads", async () => {
    vi.mocked(open).mockResolvedValue("/books/New Book.pdf");
    render(<Library />);
    await screen.findByRole("list", { name: "Books" });
    await act(async () => {
      (document.querySelector("md-fab") as Element).dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(open).toHaveBeenCalledWith({
      multiple: false,
      directory: false,
      filters: [{ name: "Books", extensions: ["pdf", "epub"] }],
    });
    expect(api.addBook).toHaveBeenCalledWith("/books/New Book.pdf");
    expect(await screen.findByText("Added New Book.pdf")).toBeInTheDocument();
    expect(api.library).toHaveBeenCalledTimes(2);
  });

  it("does nothing when the file dialog is cancelled", async () => {
    vi.mocked(open).mockResolvedValue(null);
    render(<Library />);
    await screen.findByRole("list", { name: "Books" });
    await act(async () => {
      (document.querySelector("md-fab") as Element).dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(api.addBook).not.toHaveBeenCalled();
  });

  it("the add button is a labelled Material FAB", async () => {
    render(<Library />);
    await screen.findByRole("list", { name: "Books" });
    expect(document.querySelector("md-fab")).toHaveAttribute("aria-label", "Add book");
  });
});
