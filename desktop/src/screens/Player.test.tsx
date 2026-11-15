import { act, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AudioFile } from "../engine/types";

vi.mock("@tauri-apps/api/core", async (original) => ({
  ...(await original<typeof import("@tauri-apps/api/core")>()),
  convertFileSrc: (path: string, protocol = "asset") => `${protocol}://localhost/${encodeURIComponent(path)}`,
}));

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  playBookAudio: vi.fn(),
}));

import * as api from "../engine/api";
import { Player, chapterName, type Queue } from "./Player";

const BOOK = "/out/b";

const FILES: AudioFile[] = [
  { path: "/out/b/audio/001 - The Keeper.mp3", name: "001 - The Keeper.mp3", bytes: 1 },
  { path: "/out/b/audio/002 - The Storm.mp3", name: "002 - The Storm.mp3", bytes: 1 },
];

const fetched: string[] = [];
const revoked: string[] = [];
/** The book whose folder the bridge serves, as play_book_audio sets it. */
let selected: string | null = null;

beforeEach(() => {
  fetched.length = 0;
  revoked.length = 0;
  selected = null;
  vi.mocked(api.playBookAudio).mockImplementation(async (workspace: string) => {
    selected = workspace;
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  // Like the bridge (audio::serve): only MP3s of the selected book are served.
  vi.stubGlobal("fetch", async (url: string) => {
    fetched.push(url);
    const allowed = selected === BOOK && /^chapter:\/\/localhost\/[^/]+\.mp3$/.test(decodeURIComponent(url));
    // A string body: Node 22's Response can't read jsdom's Blob.
    return new Response(allowed ? "mp3" : null, { status: allowed ? 200 : 403, headers: { "Content-Type": "audio/mpeg" } });
  });
  let next = 0;
  URL.createObjectURL = () => `blob:chapter-${++next}`;
  URL.revokeObjectURL = (url: string) => void revoked.push(url);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function Harness({ start }: { start: Queue | null }) {
  const [queue, setQueue] = useState(start);
  return <Player queue={queue} onChange={setQueue} />;
}

async function press(label: string) {
  await act(async () => {
    screen.getByLabelText(label).dispatchEvent(new Event("click", { bubbles: true }));
  });
}

function audio(): HTMLAudioElement {
  return screen.getByTestId("player-audio") as HTMLAudioElement;
}

describe("Player", () => {
  it("names a chapter from its file", () => {
    expect(chapterName(FILES[1])).toBe("The Storm");
  });

  it("shows nothing without a queue", () => {
    render(<Harness start={null} />);
    expect(screen.queryByRole("region", { name: "Player" })).not.toBeInTheDocument();
  });

  it("reads the chosen chapter through the chapter protocol, plays it, and moves between chapters", async () => {
    render(<Harness start={{ book: "Lighthouse", workspace: BOOK, files: FILES, index: 0 }} />);
    expect(screen.getByRole("region", { name: "Player" })).toHaveTextContent("The Keeper");
    await waitFor(() => expect(audio().src).toBe("blob:chapter-1"));
    // By file name only: the bridge decides which folder that is.
    expect(fetched).toEqual([`chapter://localhost/${encodeURIComponent(FILES[0].name)}`]);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    expect(screen.getByLabelText("Previous chapter")).toHaveAttribute("disabled");
    await press("Next chapter");
    expect(screen.getByRole("region", { name: "Player" })).toHaveTextContent("The Storm");
    await waitFor(() => expect(audio().src).toBe("blob:chapter-2"));
    expect(revoked).toEqual(["blob:chapter-1"]);
    expect(screen.getByLabelText("Next chapter")).toHaveAttribute("disabled");
    await press("Previous chapter");
    expect(screen.getByRole("region", { name: "Player" })).toHaveTextContent("The Keeper");
  });

  it("says so when the bridge refuses a file that isn't a chapter", async () => {
    const outside = { path: "/out/b/manifest.json", name: "manifest.json", bytes: 1 };
    render(<Harness start={{ book: "Lighthouse", workspace: BOOK, files: [outside], index: 0 }} />);
    expect(await screen.findByText("This chapter couldn't be loaded")).toBeInTheDocument();
    expect(audio().getAttribute("src")).toBeNull();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("keeps reading its own book's chapters after another book's folder is selected", async () => {
    render(<Harness start={{ book: "Lighthouse", workspace: BOOK, files: FILES, index: 0 }} />);
    await waitFor(() => expect(audio().src).toBe("blob:chapter-1"));
    expect(api.playBookAudio).toHaveBeenLastCalledWith(BOOK);
    // Another book takes the bridge's folder, as playing it from elsewhere would.
    selected = "/out/other";
    await press("Next chapter");
    await waitFor(() => expect(audio().src).toBe("blob:chapter-2"));
    expect(api.playBookAudio).toHaveBeenLastCalledWith(BOOK);
    expect(screen.queryByText("This chapter couldn't be loaded")).not.toBeInTheDocument();
  });

  it("goes on to the next chapter when one ends", async () => {
    render(<Harness start={{ book: "Lighthouse", workspace: BOOK, files: FILES, index: 0 }} />);
    await act(async () => {
      audio().dispatchEvent(new Event("ended"));
    });
    expect(screen.getByRole("region", { name: "Player" })).toHaveTextContent("The Storm");
  });

  it("starts a chapter at a flagged passage once its audio is loaded, and again on each request", async () => {
    const queue: Queue = { book: "Lighthouse", workspace: BOOK, files: FILES, index: 1, start: 42, seek: 1 };
    const { rerender } = render(<Player queue={queue} onChange={vi.fn()} />);
    await waitFor(() => expect(audio().src).toBe("blob:chapter-1"));
    const element = audio();
    let time = 0;
    let ready = 0;
    Object.defineProperty(element, "currentTime", { configurable: true, get: () => time, set: (value: number) => void (time = value) });
    Object.defineProperty(element, "readyState", { configurable: true, get: () => ready });
    // Not before the metadata: the element can't seek yet.
    expect(time).toBe(0);
    await act(async () => {
      ready = 1;
      element.dispatchEvent(new Event("loadedmetadata"));
    });
    expect(time).toBe(42);
    // The same chapter and place again: seeks at once, without reloading the chapter.
    time = 80;
    rerender(<Player queue={{ ...queue, seek: 2 }} onChange={vi.fn()} />);
    expect(time).toBe(42);
    expect(fetched).toHaveLength(1);
    // Another place in the same chapter.
    rerender(<Player queue={{ ...queue, start: 7, seek: 3 }} onChange={vi.fn()} />);
    expect(time).toBe(7);
  });

  it("doesn't carry a passage's start into the next chapter", async () => {
    render(<Harness start={{ book: "Lighthouse", workspace: BOOK, files: FILES, index: 0, start: 30, seek: 1 }} />);
    await waitFor(() => expect(audio().src).toBe("blob:chapter-1"));
    await press("Next chapter");
    await waitFor(() => expect(audio().src).toBe("blob:chapter-2"));
    const element = audio();
    let time = 0;
    Object.defineProperty(element, "currentTime", { configurable: true, get: () => time, set: (value: number) => void (time = value) });
    await act(async () => {
      element.dispatchEvent(new Event("loadedmetadata"));
    });
    expect(time).toBe(0);
  });

  it("shows play or pause from the element's state, and closes", async () => {
    render(<Harness start={{ book: "Lighthouse", workspace: BOOK, files: FILES, index: 0 }} />);
    await act(async () => {
      audio().dispatchEvent(new Event("play"));
    });
    expect(screen.getByLabelText("Pause")).toBeInTheDocument();
    await act(async () => {
      audio().dispatchEvent(new Event("pause"));
    });
    expect(screen.getByLabelText("Play")).toBeInTheDocument();
    await press("Close player");
    expect(screen.queryByRole("region", { name: "Player" })).not.toBeInTheDocument();
  });
});
