import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AsrModels, AudioFile, AudioReport, InspectManifest, Request } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(),
  bookAudio: vi.fn(),
}));

import * as api from "../engine/api";
import { AudioCheck, LEAD_IN, chaptersToShow, clock, heardBy, isReport, size } from "./AudioCheck";
import type { CloneForm } from "./bookOptions";

/** Real CLI output from a three-model check of the Harbour demo with an insertion planted in chapter 3. */
function fixture<T>(name: string): T {
  return JSON.parse(readFileSync(resolve(process.cwd(), "src-tauri/tests/fixtures", name), "utf8")) as T;
}

const REPORT = fixture<AudioReport>("audio-report.json");
const MODELS = fixture<AsrModels>("asr-models.json");
const WORKSPACE = "/home/user/books/audiobooks/harbour-f428cec392";
const MANIFEST = `${WORKSPACE}/manifest.json`;

function file(number: number, title: string): AudioFile {
  const name = `${String(number).padStart(3, "0")} - ${title}.mp3`;
  return { path: `${WORKSPACE}/audio/${name}`, name, bytes: 1000 };
}

const FILES = Array.from({ length: 13 }, (_, index) => file(index + 1, `Chapter ${index + 1}`));
const INSPECT: InspectManifest = {
  title: "A Year of Harbour Weather",
  source_path: "/books/harbour.pdf",
  review_required: [],
  review_acknowledged: [],
  approved: true,
  chapters: FILES.map((_, index) => ({ number: index + 1, title: `Chapter ${index + 1}`, confidence: 1, manually_approved: false })),
};

let report: AudioReport;
let models: AsrModels;
const requests: Request[] = [];

beforeEach(() => {
  report = structuredClone(REPORT);
  models = structuredClone(MODELS);
  requests.length = 0;
  vi.mocked(api.bookAudio).mockResolvedValue(FILES);
  vi.mocked(api.run).mockImplementation(async (request: Request) => {
    requests.push(request);
    if (request.command === "asr_list") return { outcome: "success", result: models };
    if (request.command === "audio_report") return { outcome: "success", result: report };
    if (request.command === "audio_dismiss") {
      const chapter = report.report?.chapters.find((item) => item.number === request.chapter);
      if (chapter) chapter.flags[request.flag].reviewed = !request.undo;
      return { outcome: "success", result: { chapter: request.chapter, flag: request.flag, reviewed: !request.undo, warnings: [] } };
    }
    if (request.command === "asr_fetch") {
      models = { models: models.models.map((model) => ({ ...model, ready: true, weights_present: true, reason: null })) };
      return { outcome: "success", result: models };
    }
    return { outcome: "failed", error: { type: "InputError", code: 3, message: "unexpected" }, warnings: [] };
  });
});

function setup(cloneForm?: CloneForm, temperature = 0.2) {
  const onStart = vi.fn();
  const onPlay = vi.fn();
  const onEditNarration = vi.fn();
  render(
    <AudioCheck
      cloneForm={cloneForm}
      manifest={MANIFEST}
      workspace={WORKSPACE}
      inspect={INSPECT}
      voices={{ voices: ["Jasper", "Luna"], listable: true } as never}
      voice="Jasper"
      speed={1}
      temperature={temperature}
      onStart={onStart}
      onPlay={onPlay}
      onEditNarration={onEditNarration}
    />,
  );
  return { onStart, onPlay, onEditNarration };
}

function button(text: string, root: ParentNode = document): HTMLElement {
  const found = Array.from(root.querySelectorAll("md-filled-button, md-filled-tonal-button, md-outlined-button, md-text-button")).find(
    (element) => element.textContent?.includes(text),
  );
  if (!found) throw new Error(`no button labelled ${text}`);
  return found as HTMLElement;
}

function click(element: Element) {
  act(() => {
    element.dispatchEvent(new Event("click", { bubbles: true }));
  });
}

function chapter(number: number): HTMLElement {
  return screen.getByRole("listitem", { name: new RegExp(`^Chapter ${number}:`) });
}

describe("helpers", () => {
  it("format times, sizes and voters", () => {
    expect([clock(19.92), clock(75.4), clock(null)]).toEqual(["0:19", "1:15", "?"]);
    expect([size(1528006491), size(130557655)]).toEqual(["1.5 GB", "131 MB"]);
    expect([heardBy(["vosk"]), heardBy(["wav2vec2", "vosk"])]).toEqual(["Vosk only", "Wav2Vec2 and Vosk"]);
  });

  it("show only chapters that need attention or are out of date", () => {
    expect(chaptersToShow(REPORT).map((item) => item.number)).toEqual([3, 9, 10]);
    expect(chaptersToShow({ ...REPORT, stale: [1] }).map((item) => item.number)).toEqual([1, 3, 9, 10]);
  });

  it("accept only a report the panel can read", () => {
    expect(isReport(REPORT)).toBe(true);
    expect(isReport({ schema_version: 1, report: null, stale: [], warnings: [] })).toBe(true);
    expect(isReport({ report: { chapters: [{ number: 1 }] }, stale: [] })).toBe(false);
    expect(isReport({ report: null })).toBe(false);
  });
});

describe("AudioCheck", () => {
  it("shows the model votes, excerpts and what each model heard for a confirmed passage", async () => {
    setup();
    const row = await waitFor(() => chapter(3));
    expect(row).toHaveTextContent("Possible mismatch");
    expect(row).toHaveTextContent("Checked by Whisper, Wav2Vec2, Vosk");
    expect(row).toHaveTextContent("Different words heard");
    expect(row).toHaveTextContent("at 0:19 · heard by Wav2Vec2 and Vosk");
    expect(row).toHaveTextContent("light changed over the long breakwater.");
    expect(row).toHaveTextContent("Wav2Vec2 heard");
    // Whisper's own insertion is a disagreement, not a confirmed flag.
    expect(row).toHaveTextContent("Whisper only: the others disagree");
    expect(screen.getByText(/13 chapters checked · 10 with no mismatch detected/)).toBeInTheDocument();
    expect(screen.getByText(/A flag is a reason to listen, not proof/)).toBeInTheDocument();
  });

  it("listens from a little before the passage in the right chapter", async () => {
    const { onPlay } = setup();
    const row = await waitFor(() => chapter(3));
    click(button("Listen", row));
    expect(onPlay).toHaveBeenCalledWith(FILES, 2, 19.92 - LEAD_IN);
  });

  it("marks a passage reviewed and back without touching audio", async () => {
    setup();
    let row = await waitFor(() => chapter(3));
    click(button("Sounds right", row));
    await waitFor(() => expect(chapter(3)).toHaveTextContent("· reviewed"));
    expect(requests).toContainEqual({ command: "audio_dismiss", manifest: MANIFEST, chapter: 3, flag: 0, undo: false });
    row = chapter(3);
    click(button("Not reviewed", row));
    await waitFor(() => expect(chapter(3)).not.toHaveTextContent("· reviewed"));
    expect(requests.filter((request) => request.command === "resynthesize")).toEqual([]);
  });

  it("verifies existing audio as a run of its own", async () => {
    const { onStart } = setup();
    await waitFor(() => chapter(3));
    click(button("Verify existing audio"));
    expect(onStart).toHaveBeenCalledWith({ command: "verify_audio", manifest: MANIFEST });
  });

  it("speaks a chapter again with a chosen voice and speed, and checks it afterwards", async () => {
    const { onStart } = setup();
    const row = await waitFor(() => chapter(3));
    click(button("Speak again…", row));
    const dialog = document.querySelector("md-dialog[open]") as HTMLElement;
    expect(dialog).toHaveTextContent("Its current audio stays playable until the new audio is ready");
    click(button("Speak again", dialog));
    expect(onStart).toHaveBeenCalledWith({
      command: "resynthesize",
      manifest: MANIFEST,
      chapters: [3],
      voice: "Jasper",
      speed: 1,
      verify_audio: true,
    });
  });

  it("opens the review page to correct a chapter's text", async () => {
    const { onEditNarration } = setup();
    click(button("Correct the text", await waitFor(() => chapter(3))));
    expect(onEditNarration).toHaveBeenCalled();
  });

  it("marks out-of-date results", async () => {
    report.stale = [3];
    setup();
    await waitFor(() => expect(chapter(3)).toHaveTextContent("out of date"));
    expect(screen.getByRole("status")).toHaveTextContent("Out of date for chapter 3");
  });

  it("says when fewer than three models voted", async () => {
    const third = report.report?.chapters.find((item) => item.number === 9);
    if (!third) throw new Error("the fixture has chapter 9");
    third.partial = true;
    third.models = third.models.filter((model) => model.model !== "whisper");
    setup();
    await waitFor(() => expect(chapter(9)).toHaveTextContent("partial: fewer than three recognizers voted"));
    expect(chapter(9)).toHaveTextContent("Checked by Wav2Vec2, Vosk");
  });

  it("can't verify without a ready model, and offers the download through the engine", async () => {
    models.models = models.models.map((model) => ({ ...model, ready: false, weights_present: false, reason: "model_not_downloaded" }));
    const { onStart } = setup();
    await waitFor(() => expect(screen.getByLabelText("Speech recognizers")).toHaveTextContent("Whisper"));
    expect(screen.getByLabelText("Speech recognizers")).toHaveTextContent("not downloaded (1.5 GB)");
    expect(button("Verify existing audio")).toHaveAttribute("disabled");
    click(button("Download recognizers…"));
    const dialog = document.querySelector("md-dialog[open]") as HTMLElement;
    expect(dialog).toHaveTextContent("the app itself doesn't connect anywhere");
    expect(dialog).toHaveTextContent("/home/me/.cache/pdf2audiobook/asr/whisper");
    click(button("Download", dialog));
    await waitFor(() => expect(requests).toContainEqual({ command: "asr_fetch", models: ["whisper", "wav2vec2", "vosk"] }));
    await waitFor(() => expect(button("Verify existing audio")).not.toHaveAttribute("disabled"));
    expect(onStart).not.toHaveBeenCalled();
  });

  it("explains how to install recognizers that aren't installed", async () => {
    models.models = models.models.map((model) => ({ ...model, ready: false, package_version: null, reason: "model_not_installed" }));
    setup();
    await waitFor(() => expect(screen.getByText(/The speech recognizers aren't installed/)).toBeInTheDocument());
    expect(screen.queryByText("Download recognizers…")).toBeNull();
  });

  it("an unverified book says so", async () => {
    report = { schema_version: 1, report: null, stale: [], warnings: [] };
    setup();
    expect(await screen.findByText("Not checked yet.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Checked chapters" })).toBeNull();
  });

  it("shows an engine failure without any book text", async () => {
    vi.mocked(api.run).mockResolvedValue({
      outcome: "failed",
      error: { type: "WorkspaceError", code: 4, message: "The workspace manifest is missing" },
      warnings: [],
    });
    setup();
    expect(await screen.findByText("The workspace manifest is missing")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("breakwater");
  });

  it("explains a chapter that wasn't compared because its narration changed", async () => {
    const current = report.report;
    if (!current) throw new Error("the fixture has a report");
    report.report = {
      ...current,
      chapters: current.chapters.map((item) =>
        item.number === 9
          ? { ...item, status: "verification_unavailable", reason: "narration_not_spoken", flags: [], partial: true, models: [] }
          : item,
      ),
    };
    setup();
    await waitFor(() => expect(chapter(9)).toHaveTextContent("Not checked"));
    expect(chapter(9)).toHaveTextContent("wasn't compared");
    expect(chapter(9)).toHaveTextContent("speak it again first");
  });

  it("an unreadable result is reported, not shown half-parsed", async () => {
    report = { schema_version: 1, report: { chapters: [{ number: 3 }] }, stale: [] } as never;
    setup();
    expect(await screen.findByText("The engine returned an unreadable result")).toBeInTheDocument();
    expect(within(document.body).queryByText(/Possible mismatch/)).toBeNull();
  });
});

it("repairs a clone with the same private selection and no remembered built-in voice", async () => {
  const form = { voiceMode: "clone" as const, referenceAudio: "/clips/PRIVATE.wav", referenceText: "PRIVATE transcript" };
  const { onStart } = setup(form);
  click(button("Speak again…", await waitFor(() => chapter(3))));
  const dialog = document.querySelector("md-dialog[open]") as HTMLElement;
  expect(within(dialog).getByLabelText("Reference transcript (optional)")).toHaveValue("PRIVATE transcript");
  click(button("Speak again", dialog));
  expect(onStart).toHaveBeenCalledWith({
    command: "resynthesize", manifest: MANIFEST, chapters: [3],
    tts_provider: "kitten", tts_model: "kitten2", clone_voice: true,
    reference_audio: "/clips/PRIVATE.wav", reference_text: "PRIVATE transcript",
    voice: null, speed: 1, temperature: 0.2, verify_audio: true,
  });
});

it("speaks again with the book's Kitten 2 temperature, or none for another model", async () => {
  const slider = () => document.querySelector('md-dialog[open] md-slider[aria-label="Temperature"]') as (HTMLElement & { value: number }) | null;
  const first = setup({ voiceMode: "inherit", inheritedKitten2: true }, 0.45);
  click(button("Speak again…", await waitFor(() => chapter(3))));
  expect(slider()?.value).toBe(0.45);
  act(() => {
    const control = slider();
    if (control) control.value = 0.3;
    control?.dispatchEvent(new Event("change", { bubbles: true }));
  });
  click(button("Speak again", document.querySelector("md-dialog[open]") as HTMLElement));
  expect(first.onStart).toHaveBeenLastCalledWith(expect.objectContaining({ command: "resynthesize", temperature: 0.3 }));
  cleanup();
  const second = setup({ voiceMode: "inherit" }, 0.45);
  click(button("Speak again…", await waitFor(() => chapter(3))));
  expect(slider()).toBeNull();
  click(button("Speak again", document.querySelector("md-dialog[open]") as HTMLElement));
  expect(second.onStart.mock.lastCall?.[0]).not.toHaveProperty("temperature");
});
