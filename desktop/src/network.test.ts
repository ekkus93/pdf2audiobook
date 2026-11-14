import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** Every source file of the app, tests left out. */
function sources(folder: string): string[] {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) && !path.includes("/test/") ? [path] : [];
  });
}

const SOURCES = sources(join(__dirname));

describe("the frontend makes no network requests of its own (spec D8.d)", () => {
  it("has no sockets, beacons or XHR", () => {
    for (const file of SOURCES) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(/\bnew WebSocket\b|\bEventSource\b|\bXMLHttpRequest\b|\bsendBeacon\b/);
    }
  });

  it("fetches only through the one helper that reads the app's own files", () => {
    const callers = SOURCES.filter((file) => /\bfetch\(/.test(readFileSync(file, "utf8")));
    expect(callers.map((file) => file.slice(__dirname.length + 1))).toEqual(["screens/Player.tsx"]);
    const player = readFileSync(join(__dirname, "screens/Player.tsx"), "utf8");
    // blobUrl's callers pass an asset-protocol URL (convertFileSrc) or a bundled sample.
    expect(player.match(/\bfetch\(/g)).toHaveLength(1);
    expect(player).toMatch(/return blobUrl\(convertFileSrc\(path\)\)/);
  });

  it("names no remote address", () => {
    for (const file of SOURCES) {
      const text = readFileSync(file, "utf8");
      expect(text.match(/https?:\/\/(?!127\.0\.0\.1|localhost)[\w.-]+/g) ?? [], file).toEqual([]);
    }
  });
});
