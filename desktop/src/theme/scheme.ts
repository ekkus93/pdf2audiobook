// The Material 3 colour scheme, generated from the two seeds in spec D11.b.
//
// Vite runs this at build time (see the `m3-theme` plugin in vite.config.ts) to produce the
// `--md-sys-color-*` CSS variables; no colour value is typed in by hand.

import {
  argbFromHex,
  DynamicScheme,
  Hct,
  hexFromArgb,
  MaterialDynamicColors,
  SchemeTonalSpot,
  TonalPalette,
  Variant,
} from "@material/material-color-utilities";

export const SEEDS = { primary: "#6D5BD0", tertiary: "#E8A25C" } as const;

export const ROLES = [
  "primary",
  "onPrimary",
  "primaryContainer",
  "onPrimaryContainer",
  "inversePrimary",
  "secondary",
  "onSecondary",
  "secondaryContainer",
  "onSecondaryContainer",
  "tertiary",
  "onTertiary",
  "tertiaryContainer",
  "onTertiaryContainer",
  "error",
  "onError",
  "errorContainer",
  "onErrorContainer",
  "background",
  "onBackground",
  "surface",
  "onSurface",
  "surfaceVariant",
  "onSurfaceVariant",
  "surfaceDim",
  "surfaceBright",
  "surfaceContainerLowest",
  "surfaceContainerLow",
  "surfaceContainer",
  "surfaceContainerHigh",
  "surfaceContainerHighest",
  "inverseSurface",
  "inverseOnSurface",
  "outline",
  "outlineVariant",
  "shadow",
  "scrim",
  "surfaceTint",
] as const;

export type Role = (typeof ROLES)[number];
export type Scheme = Record<Role, string>;

/** Midnight Iris with Amber: tonal-spot scheme, iris primary, amber tertiary, iris-tinted neutrals. */
export function scheme(isDark: boolean): Scheme {
  const primary = Hct.fromInt(argbFromHex(SEEDS.primary));
  const base = new SchemeTonalSpot(primary, isDark, 0);
  const dynamic = new DynamicScheme({
    sourceColorHct: primary,
    variant: Variant.TONAL_SPOT,
    contrastLevel: 0,
    isDark,
    primaryPalette: TonalPalette.fromHueAndChroma(primary.hue, 48),
    secondaryPalette: base.secondaryPalette,
    tertiaryPalette: TonalPalette.fromInt(argbFromHex(SEEDS.tertiary)),
    neutralPalette: TonalPalette.fromHueAndChroma(primary.hue, 6),
    neutralVariantPalette: TonalPalette.fromHueAndChroma(primary.hue, 10),
  });
  const colors = MaterialDynamicColors as unknown as Record<
    Role,
    { getArgb(scheme: DynamicScheme): number }
  >;
  return Object.fromEntries(
    ROLES.map((role) => [role, hexFromArgb(colors[role].getArgb(dynamic))]),
  ) as Scheme;
}

/** `onPrimaryContainer` becomes `on-primary-container`. */
export function kebab(role: Role): string {
  return role.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

function block(values: Scheme): string {
  return ROLES.map((role) => `  --md-sys-color-${kebab(role)}: ${values[role]};`).join("\n");
}

/**
 * CSS for both themes. Dark is the default (spec D11.c); `data-theme="light"` and
 * `data-theme="system"` on the root element select light, or follow the system.
 */
export function themeCss(): string {
  const dark = block(scheme(true));
  const light = block(scheme(false));
  return [
    `:root,\n:root[data-theme="dark"] {\n  color-scheme: dark;\n${dark}\n}`,
    `:root[data-theme="light"] {\n  color-scheme: light;\n${light}\n}`,
    `@media (prefers-color-scheme: light) {\n  :root[data-theme="system"] {\n    color-scheme: light;\n${light.replace(/^/gm, "  ")}\n  }\n}`,
    "",
  ].join("\n\n");
}
