// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ROLES, SEEDS, kebab, scheme, themeCss, type Role } from "./scheme";

/** The role table in spec D11.b: role -> [dark, light]. */
function specTable(): Map<string, [string, string]> {
  const spec = readFileSync(
    fileURLToPath(new URL("../../../docs/PDF2AUDIOBOOK_TAURI_SPEC.md", import.meta.url)),
    "utf8",
  );
  const rows = new Map<string, [string, string]>();
  for (const match of spec.matchAll(/^\s*\| `(\w+)` \| `(#[0-9a-f]{6})` \| `(#[0-9a-f]{6})` \|$/gm)) {
    rows.set(match[1], [match[2], match[3]]);
  }
  return rows;
}

describe("Material 3 scheme", () => {
  it("is generated from the seeds in the spec", () => {
    expect(SEEDS).toEqual({ primary: "#6D5BD0", tertiary: "#E8A25C" });
  });

  it("matches every role in the spec D11.b table, dark and light", () => {
    const table = specTable();
    expect(table.size).toBe(22);
    const dark = scheme(true);
    const light = scheme(false);
    for (const [role, [darkHex, lightHex]] of table) {
      expect(ROLES).toContain(role);
      expect(dark[role as Role], `${role} dark`).toBe(darkHex);
      expect(light[role as Role], `${role} light`).toBe(lightHex);
    }
  });

  it("emits a CSS variable for every role in both themes, dark by default", () => {
    const css = themeCss();
    for (const role of ROLES) {
      const name = `--md-sys-color-${kebab(role)}:`;
      expect(css.split(name).length - 1, role).toBe(3); // dark, light, system-light
    }
    expect(css).toMatch(/^:root,\n:root\[data-theme="dark"\] \{\n {2}color-scheme: dark;/);
    expect(css).toContain(':root[data-theme="light"]');
    expect(css).toContain('@media (prefers-color-scheme: light) {\n  :root[data-theme="system"]');
  });
});