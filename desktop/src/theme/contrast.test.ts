// @vitest-environment node
import { describe, expect, it } from "vitest";
import { scheme, type Role } from "./scheme";

/** WCAG 2.x relative luminance of a #rrggbb colour. */
function luminance(hex: string): number {
  const channel = (offset: number) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

export function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

const SURFACES: Role[] = [
  "surface",
  "surfaceContainerLowest",
  "surfaceContainerLow",
  "surfaceContainer",
  "surfaceContainerHigh",
  "surfaceContainerHighest",
];

/** Text pairings: 4.5:1 (WCAG AA for normal text). */
const TEXT: Array<[Role, Role]> = [
  ["onPrimary", "primary"],
  ["onPrimaryContainer", "primaryContainer"],
  ["onSecondary", "secondary"],
  ["onSecondaryContainer", "secondaryContainer"],
  ["onTertiary", "tertiary"],
  ["onTertiaryContainer", "tertiaryContainer"],
  ["onError", "error"],
  ["onErrorContainer", "errorContainer"],
  ["inverseOnSurface", "inverseSurface"],
  ["onBackground", "background"],
  ...SURFACES.flatMap((surface): Array<[Role, Role]> => [
    ["onSurface", surface],
    ["onSurfaceVariant", surface],
    ["primary", surface],
  ]),
];

/** Icons and component boundaries: 3:1 (WCAG AA for graphics and large text). */
const GRAPHICS: Array<[Role, Role]> = [
  ...SURFACES.map((surface): [Role, Role] => ["outline", surface]),
  ...SURFACES.map((surface): [Role, Role] => ["tertiary", surface]),
  ...SURFACES.map((surface): [Role, Role] => ["error", surface]),
  ["inversePrimary", "inverseSurface"],
];

describe.each([
  ["dark", true],
  ["light", false],
])("%s theme contrast", (_name, isDark) => {
  const colors = scheme(isDark);

  it.each(TEXT)("text %s on %s is at least 4.5:1", (fg, bg) => {
    expect(contrast(colors[fg], colors[bg])).toBeGreaterThanOrEqual(4.5);
  });

  it.each(GRAPHICS)("graphic %s on %s is at least 3:1", (fg, bg) => {
    expect(contrast(colors[fg], colors[bg])).toBeGreaterThanOrEqual(3);
  });
});

describe("contrast()", () => {
  it("matches WCAG reference values", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
  });
});