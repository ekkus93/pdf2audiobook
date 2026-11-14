// @vitest-environment node
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ICONS } from "./icons.generated";
import { themeCss } from "./scheme";

const DESKTOP = fileURLToPath(new URL("../..", import.meta.url));
const REMOTE = /(?:url\(\s*["']?|@import\s+["']?|(?:href|src)\s*=\s*["'])\s*(?:https?:)?\/\//i;

function files(folder: string, suffix: string): string[] {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name);
    if (statSync(path).isDirectory()) return files(path, suffix);
    return path.endsWith(suffix) ? [path] : [];
  });
}

/** Follows the CSS @imports the app makes, including those into node_modules. */
function cssWithImports(path: string, seen = new Set<string>()): Array<[string, string]> {
  if (seen.has(path)) return [];
  seen.add(path);
  const text = readFileSync(path, "utf8");
  const found: Array<[string, string]> = [[path, text]];
  for (const match of text.matchAll(/@import\s+["']([^"']+)["']/g)) {
    const target = match[1].startsWith(".")
      ? resolve(dirname(path), match[1])
      : join(DESKTOP, "node_modules", match[1]);
    found.push(...cssWithImports(target, seen));
  }
  return found;
}

describe("nothing is fetched at run time", () => {
  it("the HTML loads only local files", () => {
    const html = readFileSync(join(DESKTOP, "index.html"), "utf8");
    expect(html).not.toMatch(REMOTE);
  });

  it("the generated theme and every stylesheet, with its imports, reference only local files", () => {
    expect(themeCss()).not.toMatch(REMOTE);
    const sheets = files(join(DESKTOP, "src"), ".css").flatMap((path) => cssWithImports(path));
    expect(sheets.length).toBeGreaterThan(4);
    for (const [path, text] of sheets) {
      expect(text, path).not.toMatch(REMOTE);
      for (const match of text.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)) {
        if (match[1].startsWith("data:")) continue;
        expect(existsSync(resolve(dirname(path), match[1])), `${path}: ${match[1]}`).toBe(true);
      }
    }
  });

  it("bundles Instrument Serif, Figtree, Roboto Mono and the icon subset", () => {
    const base = readFileSync(join(DESKTOP, "src/theme/base.css"), "utf8");
    expect(base).toContain('@import "@fontsource/instrument-serif/400.css"');
    expect(base).toContain('@import "@fontsource-variable/figtree/index.css"');
    expect(base).toContain('@import "@fontsource-variable/roboto-mono/index.css"');
    const subset = join(DESKTOP, "src/assets/fonts/material-symbols-rounded-subset.woff2");
    expect(statSync(subset).size).toBeLessThan(200_000);
  });

  it("the icon map matches icons.json", () => {
    const names = JSON.parse(readFileSync(join(DESKTOP, "src/theme/icons.json"), "utf8"));
    expect(Object.keys(ICONS)).toEqual(names);
    for (const code of Object.values(ICONS)) {
      expect(code >= 0xe000 && code <= 0xf8ff).toBe(true);
    }
  });
});