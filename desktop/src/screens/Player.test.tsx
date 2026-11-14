import { act, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AudioFile } from "../engine/types";

vi.mock("@tauri-apps/api/core", async (original) => ({
  ...(await original<typeof import("@tauri-apps/api/core")>()),
  convertFileSrc: (path: string) => `asset://localhost/${encodeURIComponent(path)}`,
}));

import { Player, chapterName, type Queue } from "./Player";

const FILES: AudioFile[] = [
  { path: "/out/b/audio/001 - The Keeper.mp3", name: "001 - The Keeper.mp3", bytes: 1 },
  { path: "/out/b/audio/002 - The Storm.mp3", name: "002 - The Storm.mp3", bytes: 1 },
];

const fetched: string[] = [];
const revoked: string[] = [];

beforeEach(() => {
  fetched.length = 0;
  revoked.length = 0;
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  // Like the bridge's asset scope: only the book's audio folder is served.
  vi.stubGlobal("fetch", async (url: string) => {
    fetched.push(url);
    const allowed = decodeURIComponent(url).startsWith("asset://localhost//out/b/audio/");
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

  it("reads the chosen chapter through the asset protocol, plays it, and moves between chapters", async () => {
    render(<Harness start={{ book: "Lighthouse", files: FILES, index: 0 }} />);
    expect(screen.getByRole("region", { name: "Player" })).toHaveTextContent("The Keeper");
    await waitFor(() => expect(audio().src).toBe("blob:chapter-1"));
    expect(fetched).toEqual([`asset://localhost/${encodeURIComponent(FILES[0].path)}`]);
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

  it("says so when the asset protocol refuses a chapter outside the audio folder", async () => {
    const outside = { path: "/out/b/manifest.json", name: "manifest.json", bytes: 1 };
    render(<Harness start={{ book: "Lighthouse", files: [outside], index: 0 }} />);
    expect(await screen.findByText("This chapter couldn't be loaded")).toBeInTheDocument();
    expect(audio().getAttribute("src")).toBeNull();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("goes on to the next chapter when one ends", async () => {
    render(<Harness start={{ book: "Lighthouse", files: FILES, index: 0 }} />);
    await act(async () => {
      audio().dispatchEvent(new Event("ended"));
    });
    expect(screen.getByRole("region", { name: "Player" })).toHaveTextContent("The Storm");
  });

  it("shows play or pause from the element's state, and closes", async () => {
    render(<Harness start={{ book: "Lighthouse", files: FILES, index: 0 }} />);
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
