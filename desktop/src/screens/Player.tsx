import { convertFileSrc } from "@tauri-apps/api/core";
import { useEffect, useRef, useState } from "react";
import type { AudioFile } from "../engine/types";
import { PlayerBar } from "../ui/PlayerBar";

export interface Queue {
  /** The book's title, shown under the chapter. */
  book: string;
  files: AudioFile[];
  index: number;
}

/** "001 - The Keeper.mp3" → "The Keeper". */
export function chapterName(file: AudioFile): string {
  return file.name.replace(/\.mp3$/i, "").replace(/^\d+\s*-\s*/, "");
}

/**
 * Reads a chapter through Tauri's asset protocol and returns a `blob:` URL to play. WebKitGTK's
 * media loader can't stream from the custom `asset:` scheme (the element reports "source not
 * supported"), but `fetch` can, and still goes through the asset scope: the bridge allows only
 * the opened book's `audio/` folder, so any other path is refused (403).
 */
export async function loadChapter(path: string): Promise<string> {
  const response = await fetch(convertFileSrc(path));
  if (!response.ok) throw new Error(`asset ${response.status}`);
  return URL.createObjectURL(await response.blob());
}

/** Plays chapter MP3s with an `<audio>` element (spec D7.a). */
export function Player({ queue, onChange }: { queue: Queue | null; onChange: (queue: Queue | null) => void }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [failed, setFailed] = useState(false);
  const file = queue ? queue.files[queue.index] : undefined;

  useEffect(() => {
    const element = audio.current;
    if (!element || !file) return;
    let current = true;
    let url: string | null = null;
    setPosition(0);
    setFailed(false);
    void loadChapter(file.path)
      .then((loaded) => {
        url = loaded;
        if (!current) return URL.revokeObjectURL(loaded);
        element.src = loaded;
        return element.play()?.catch(() => setPlaying(false));
      })
      .catch(() => current && setFailed(true));
    return () => {
      current = false;
      element.pause();
      if (url) URL.revokeObjectURL(url);
    };
  }, [file]);

  if (!queue || !file) return null;
  const go = (index: number) => onChange({ ...queue, index });
  return (
    <>
      <audio
        ref={audio}
        data-testid="player-audio"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
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
