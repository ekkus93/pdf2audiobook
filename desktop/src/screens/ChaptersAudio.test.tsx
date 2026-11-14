import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AudioFile, InspectManifest } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(),
  bookAudio: vi.fn(),
  exportZip: vi.fn(),
  openAudioFolder: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ save: vi.fn() }));

import { save } from "@tauri-apps/plugin-dialog";
import * as api from "../engine/api";
import { ChaptersAudio, chapterRows } from "./ChaptersAudio";

const WORKSPACE = "/out/book-1";
const MANIFEST = `${WORKSPACE}/manifest.json`;
const SOURCE = "/books/lighthouse.pdf";

function file(number: number, title: string): AudioFile {
  const name = `${String(number).padStart(3, "0")} - ${title}.mp3`;
  return { path: `${WORKSPACE}/audio/${name}`, name, bytes: 1000 };
}

const FILES = [file(1, "The Keeper"), file(2, "The Storm")];
const INSPECT: InspectManifest = {
  title: "The Lighthouse at Gull Point",
  source_path: SOURCE,
  review_required: [],
  review_acknowledged: [],
  approved: false,
  chapters: [
    { number: 1, title: "The Keeper", confidence: 1, manually_approved: false },
    { number: 2, title: "The Storm", confidence: 1, manually_approved: false },
    { number: 3, title: "The Wreck", confidence: 1, manually_approved: false },
    { number: 4, title: "Morning", confidence: 1, manually_approved: false },
  ],
  conversion_status: {
    chapters: [
      { number: 1, status: "complete" },
      { number: 2, status: "complete" },
      { number: 3, status: "failed" },
    ],
  },
};

beforeEach(() => {
  vi.mocked(api.bookAudio).mockResolvedValue(FILES);
  vi.mocked(api.openAudioFolder).mockResolvedValue(undefined);
});

function setup(changes: { cover?: string | null } = {}) {
  const onPlay = vi.fn();
  const onContinueConverting = vi.fn();
  render(
    <ChaptersAudio
      title={INSPECT.title}
      workspace={WORKSPACE}
      manifest={MANIFEST}
      source={SOURCE}
      inspect={INSPECT}
      cover={changes.cover ?? null}
      onPlay={onPlay}
      onContinueConverting={onContinueConverting}
    />,
  );
  return { onPlay, onContinueConverting };
}

function button(text: string): HTMLElement {
  const found = Array.from(document.querySelectorAll("md-filled-button, md-filled-tonal-button")).find((element) =>
    element.textContent?.includes(text),
  );
  if (!found) throw new Error(`no button labelled ${text}`);
  return found as HTMLElement;
}

async function press(element: Element) {
  await act(async () => {
    element.dispatchEvent(new Event("click", { bubbles: true }));
  });
}

describe("chapterRows", () => {
  it("joins chapters with their files and conversion status", () => {
    expect(chapterRows(INSPECT, FILES).map((row) => [row.number, row.status, row.file?.name ?? null])).toEqual([
      [1, "converted", "001 - The Keeper.mp3"],
      [2, "converted", "002 - The Storm.mp3"],
      [3, "failed", null],
      [4, "not_converted", null],
    ]);
  });

  it("counts a file without a status as converted, and a status without a file as not", () => {
    const bare = { ...INSPECT, conversion_status: undefined };
    expect(chapterRows(bare, [FILES[0]]).map((row) => row.status)).toEqual([
      "converted",
      "not_converted",
      "not_converted",
      "not_converted",
    ]);
  });
});

describe("ChaptersAudio", () => {
  it("shows each chapter's state and plays a converted one", async () => {
    const { onPlay } = setup();
    const list = await screen.findByRole("list", { name: "Chapters" });
    expect(await screen.findByText("2 of 4 chapters converted")).toBeInTheDocument();
    expect(within(list).getByRole("listitem", { name: "Chapter 1: The Keeper" })).toHaveTextContent("Converted");
    expect(within(list).getByRole("listitem", { name: "Chapter 3: The Wreck" })).toHaveTextContent("Failed");
    expect(within(list).getByRole("listitem", { name: "Chapter 4: Morning" })).toHaveTextContent("Not converted");
    expect(screen.queryByLabelText("Play chapter 3")).not.toBeInTheDocument();
    await press(screen.getByLabelText("Play chapter 2"));
    expect(onPlay).toHaveBeenCalledWith(FILES, 1);
    expect(api.bookAudio).toHaveBeenCalledWith(WORKSPACE);
  });

  it("opens the book's audio folder", async () => {
    setup();
    await screen.findByText("2 of 4 chapters converted");
    await press(document.querySelector("md-assist-chip") as Element);
    expect(api.openAudioFolder).toHaveBeenCalledWith(WORKSPACE);
  });

  it("makes an M4B at the chosen path with the cover", async () => {
    vi.mocked(save).mockResolvedValue("/exports/Lighthouse.m4b");
    vi.mocked(api.run).mockResolvedValue({ outcome: "success", result: {} });
    setup({ cover: "/art/cover.png" });
    await screen.findByText("2 of 4 chapters converted");
    await press(button("Make M4B"));
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ defaultPath: `${INSPECT.title}.m4b` }));
    expect(api.run).toHaveBeenCalledWith(
      { command: "pack_m4b", manifest: MANIFEST, output: "/exports/Lighthouse.m4b", cover: "/art/cover.png" },
      WORKSPACE,
    );
    expect(await screen.findByText("Saved Lighthouse.m4b")).toBeInTheDocument();
  });

  it("does nothing when the save dialog is cancelled", async () => {
    vi.mocked(save).mockResolvedValue(null);
    setup();
    await screen.findByText("2 of 4 chapters converted");
    await press(button("Make M4B"));
    await press(button("Export zip"));
    expect(api.run).not.toHaveBeenCalled();
    expect(api.exportZip).not.toHaveBeenCalled();
  });

  it("shows the CLI's message for stale chapters and offers to continue converting", async () => {
    vi.mocked(save).mockResolvedValue("/exports/Lighthouse.m4b");
    vi.mocked(api.run).mockResolvedValue({
      outcome: "failed",
      error: { type: "AudioError", code: 6, message: "Chapter audio is stale or missing for chapter(s): 3, 4; run convert" },
      warnings: [],
    });
    const { onContinueConverting } = setup();
    await screen.findByText("2 of 4 chapters converted");
    await press(button("Make M4B"));
    expect(await screen.findByText("Chapter audio is stale or missing for chapter(s): 3, 4; run convert")).toBeInTheDocument();
    await press(button("Continue converting"));
    expect(onContinueConverting).toHaveBeenCalledOnce();
  });

  it("doesn't offer to continue converting for other M4B failures", async () => {
    vi.mocked(save).mockResolvedValue("/exports/Lighthouse.m4b");
    vi.mocked(api.run).mockResolvedValue({
      outcome: "failed",
      error: { type: "AudioError", code: 6, message: "ffmpeg is not installed" },
      warnings: [],
    });
    setup();
    await screen.findByText("2 of 4 chapters converted");
    await press(button("Make M4B"));
    expect(await screen.findByText("ffmpeg is not installed")).toBeInTheDocument();
    expect(() => button("Continue converting")).toThrow();
  });

  it("exports a zip with the book by default, or without it when unticked", async () => {
    vi.mocked(save).mockResolvedValue("/exports/Lighthouse.zip");
    vi.mocked(api.exportZip).mockResolvedValue(3);
    setup();
    await screen.findByText("2 of 4 chapters converted");
    await press(button("Export zip"));
    expect(api.exportZip).toHaveBeenLastCalledWith(WORKSPACE, "/exports/Lighthouse.zip", INSPECT.title, SOURCE);
    expect(await screen.findByText("Saved Lighthouse.zip with 3 files")).toBeInTheDocument();

    const checkbox = document.querySelector("md-checkbox") as HTMLElement & { checked: boolean };
    await act(async () => {
      checkbox.checked = false;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await press(button("Export zip"));
    expect(api.exportZip).toHaveBeenLastCalledWith(WORKSPACE, "/exports/Lighthouse.zip", INSPECT.title, null);
  });

  it("reports a refused export", async () => {
    vi.mocked(save).mockResolvedValue(`${WORKSPACE}/audio/x.zip`);
    vi.mocked(api.exportZip).mockRejectedValue({ kind: "request", message: "Choose a place outside the book's own folder" });
    setup();
    await screen.findByText("2 of 4 chapters converted");
    await press(button("Export zip"));
    expect(await screen.findByText("Choose a place outside the book's own folder")).toBeInTheDocument();
  });

  it("disables M4B and zip until a chapter is converted", async () => {
    vi.mocked(api.bookAudio).mockResolvedValue([]);
    setup();
    expect(await screen.findByText("0 of 4 chapters converted")).toBeInTheDocument();
    expect(button("Make M4B")).toHaveAttribute("disabled");
    expect(button("Export zip")).toHaveAttribute("disabled");
  });
});
