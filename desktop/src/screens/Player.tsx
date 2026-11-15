import { convertFileSrc } from "@tauri-apps/api/core";
import { useEffect, useRef, useState } from "react";
import { playBookAudio } from "../engine/api";
import type { AudioFile } from "../engine/types";
import { PlayerBar } from "../ui/PlayerBar";

export interface Queue {
  /** The book's title, shown under the chapter. */
  book: string;
  /** The book's workspace: the player reads chapters from its `audio/` folder. */
  workspace: string;
  files: AudioFile[];
  index: number;
  /** Seconds into the chapter to start from (a flagged passage); applied once per `seek`. */
  start?: number;
  /** Changes for every new "listen here" request, so the same place can be played again. */
  seek?: number;
}

/** "001 - The Keeper.mp3" → "The Keeper". */
export function chapterName(file: AudioFile): string {
  return file.name.replace(/\.mp3$/i, "").replace(/^\d+\s*-\s*/, "");
}

/**
 * Reads a chapter of the book in `workspace` by file name through the app's `chapter:` protocol
 * and returns a `blob:` URL to play. The bridge serves only MP3s from one book's `audio/`
 * folder (audio::serve), so the player first makes it this book's: browsing to another book
 * meanwhile doesn't stop playback. WebKitGTK's media element can't stream from a custom scheme
 * (it reports "source not supported"), but `fetch` can.
 */
export async function loadChapter(workspace: string, name: string): Promise<string> {
  await playBookAudio(workspace);
  return blobUrl(convertFileSrc(name, "chapter"));
}

/** Fetches `url` into a `blob:` URL that WebKitGTK can play; the caller revokes it. */
export async function blobUrl(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`fetch ${response.status}`);
  return URL.createObjectURL(await response.blob());
}

/** Plays chapter MP3s with an `<audio>` element (spec D7.a). */
export function Player({ queue, onChange }: { queue: Queue | null; onChange: (queue: Queue | null) => void }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [failed, setFailed] = useState(false);
  const file = queue ? queue.files[queue.index] : undefined;
  const workspace = queue?.workspace;
  // Where to start once the chapter's metadata is loaded; cleared once applied.
  const pending = useRef<number | null>(null);
  // The chapter whose audio the element holds, so a seek never lands in the previous chapter.
  const loadedName = useRef<string | null>(null);
  const start = queue?.start;
  const seek = queue?.seek;

  useEffect(() => {
    if (start === undefined) {
      pending.current = null;
      return;
    }
    const element = audio.current;
    if (element && element.readyState >= 1 && loadedName.current === file?.name) {
      element.currentTime = start;
      void element.play()?.catch(() => setPlaying(false));
    } else {
      pending.current = start;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a new seek request, not a new file
  }, [start, seek]);

  useEffect(() => {
    const element = audio.current;
    if (!element || !file || !workspace) return;
    let current = true;
    let url: string | null = null;
    setPosition(0);
    setFailed(false);
    void loadChapter(workspace, file.name)
      .then((loaded) => {
        url = loaded;
        if (!current) return URL.revokeObjectURL(loaded);
        element.src = loaded;
        loadedName.current = file.name;
        return element.play()?.catch(() => setPlaying(false));
      })
      .catch(() => current && setFailed(true));
    return () => {
      current = false;
      loadedName.current = null;
      element.pause();
      if (url) URL.revokeObjectURL(url);
    };
  }, [file, workspace]);

  if (!queue || !file) return null;
  const go = (index: number) => onChange({ ...queue, index, start: undefined });
  return (
    <>
      <audio
        ref={audio}
        data-testid="player-audio"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onLoadedMetadata={(event) => {
          if (pending.current === null) return;
          event.currentTarget.currentTime = pending.current;
          pending.current = null;
        }}
        onTimeUpdate={(event) => {
          const element = event.currentTarget;
          setPosition(element.duration ? element.currentTime / element.duration : 0);
        }}
        onEnded={() => (queue.index + 1 < queue.files.length ? go(queue.index + 1) : setPlaying(false))}
      />
      <PlayerBar
        title={chapterName(file)}
        subtitle={failed ? "This chapter couldn't be loaded" : queue.book}
        playing={playing}
        position={position}
        onTogglePlay={() => {
          const element = audio.current;
          if (!element) return;
          if (element.paused) void element.play()?.catch(() => setPlaying(false));
          else element.pause();
        }}
        onPrevious={queue.index > 0 ? () => go(queue.index - 1) : undefined}
        onNext={queue.index + 1 < queue.files.length ? () => go(queue.index + 1) : undefined}
        onClose={() => {
          audio.current?.pause();
          onChange(null);
        }}
      />
    </>
  );
}
