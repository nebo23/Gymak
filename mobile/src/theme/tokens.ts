/**
 * The complete Gymak palette and scales.
 *
 * DELIBERATE OVERRIDE OF §10 — the owner asked for true black-and-white themes.
 * The §10.2 `sand` scale was a WARM neutral (#FFFDF8 cream to #17130F warm
 * near-black) and every ground, border and shadow carried that brown cast.
 * `sand` is now a TRUE NEUTRAL greyscale (R==G==B at every step, pure white to
 * pure black) and the warm rgba overlays/shadows are neutralised. The §10.1
 * `rust` accent is KEPT unchanged and on purpose: selected states, the FAB, the
 * streak and the PR badge need a hue to read as "selected" rather than "a
 * slightly different grey". Key names and structure are untouched — values only.
 * docs/PHASE-2-SPEC.md §10 is intentionally NOT edited, so this file and §10.2
 * now differ; this docblock is the record of why.
 *
 * Values that changed beyond the scale swap did so to satisfy WCAG 2.1 AA,
 * which is a hard requirement: 4.5:1 body text, 3:1 large text and UI bounds.
 * `border` moved sand[300] to sand[500] because a 1.45:1 hairline cannot
 * identify an input; success/warningText/info were darkened a step (they failed
 * 4.5:1 on their own *Bg tints before this change as well as after it). No component may hold a hex literal;
 * everything visual reads from `LightTheme` / `DarkTheme` via `useTheme()`.
 */

// §10.1 — Rust scale: accent and strength.
export const rust = {
  50: "#FBEDE6",
  100: "#F6D3C3",
  200: "#EDA98A",
  300: "#E2835A",
  400: "#D5642F",
  500: "#C4491F", // core
  600: "#A63C18",
  700: "#832E12",
  800: "#5E210D",
  900: "#3B1508",
} as const;

// Sand scale: TRUE NEUTRAL greyscale (see the override note above). Every step
// has equal R, G and B, so no step can reintroduce a hue cast. Pure white at
// sand[50], pure black at sand[950]; the steps between are spaced by relative
// luminance rather than by evenly-stepped hex, so the light end has the fine
// gradations that surfaces need and the dark end keeps usable separation.
export const sand = {
  50: "#FFFFFF",
  100: "#F7F7F7",
  200: "#E8E8E8",
  300: "#D1D1D1",
  400: "#B0B0B0",
  500: "#8E8E8E",
  600: "#6E6E6E",
  700: "#4A4A4A",
  800: "#2B2B2B",
  900: "#171717",
  950: "#000000",
} as const;

// §10.4 — space / radius / control / motion scales. Theme-independent.
export const space = [4, 8, 12, 16, 20, 24, 32, 40, 48] as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  pill: 999,
} as const;

export const screenPadding = 20;
export const controlHeight = 52;
export const minTouchTarget = 48;

/**
 * Icon/glyph sizes. Before this existed, components hardcoded eighteen
 * different literals (36, 22, 20, 18, 16, 14, 12, 8, 6, 4, 2) with no system
 * behind them. Four deliberate steps, each anchored to something that already
 * exists rather than invented, all multiples of 4 to match `space`'s base:
 *
 *   sm 16 — small affordance (chevron, inline meta glyph). Equal to `body`
 *           (16) so it matches the text it sits beside, and the smallest that
 *           stays legible at the 130% font scale of device check 15.
 *   md 24 — the standard inline icon, and the tab bar. body x 1.5, and the
 *           platform-conventional 24dp; centred in a 48dp target it leaves an
 *           even 12dp all round. The tab bar takes md rather than lg because a
 *           tab item also carries a label, and at the 130% font scale of device
 *           check 15 a 28dp glyph plus a scaled label overflows the bar.
 *   lg 28 — prominent glyph: screen headers and anything that has to read as
 *           primary. Equal to `h1` (28) so it optically matches a screen title.
 *   xl 48 — empty-state / large illustrative glyph. Equal to `minTouchTarget`
 *           and body x 3, big enough to anchor an empty state on its own.
 */
export const iconSize = {
  sm: 16,
  md: 24,
  lg: 28,
  xl: 48,
} as const;

export const motion = {
  fast: 120,
  base: 200,
  slow: 320,
  easing: "ease-out",
} as const;

interface ShadowToken {
  offsetY: number;
  blurRadius: number;
  color: string;
}

interface SemanticTokens {
  bg: string;
  surface: string;
  surfaceVariant: string;
  card: string;
  input: string;
  border: string;
  divider: string;
  overlay: string;
  skeleton: string;
  primary: string;
  primaryPressed: string;
  primaryDisabled: string;
  primaryContainer: string;
  onPrimary: string;
  secondary: string;
  secondaryContainer: string;
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  textDisabled: string;
  textInverse: string;
  textLink: string;
  success: string;
  successBg: string;
  warning: string;
  warningText: string;
  warningBg: string;
  error: string;
  errorBg: string;
  info: string;
  infoBg: string;
  shadowColor: string;
  shadowSm: ShadowToken;
  shadowMd: ShadowToken;
  // §10.3's trailing paragraph — carried forward for later phases, defined
  // now so nothing gets improvised later.
  chart1: string;
  chart2: string;
  chart3: string;
  chart4: string;
  chart5: string;
  ringWorkout: string;
  ringCalories: string;
  ringWeight: string;
  streak: string;
  prBadge: string;
  navBg: string;
  fab: string;
  aiCoachBg: string;
  premiumBg: string;
}

// §10.3 "Light (default)".
export const LightTheme: SemanticTokens = {
  bg: sand[100],
  surface: sand[50],
  surfaceVariant: sand[200],
  card: sand[50],
  input: sand[50],
  // sand[300] is a 1.45:1 hairline on a pure-white surface, which cannot
  // identify an input's bounds; sand[500] is 3.28:1 and meets WCAG 1.4.11.
  border: sand[500],
  divider: sand[200],
  overlay: "rgba(0,0,0,.45)",
  skeleton: sand[200],
  primary: rust[500],
  primaryPressed: rust[700],
  primaryDisabled: rust[200],
  primaryContainer: rust[50],
  onPrimary: "#FFFFFF",
  secondary: sand[700],
  secondaryContainer: sand[200],
  textPrimary: sand[900],
  textSecondary: sand[700],
  textMuted: sand[600],
  textDisabled: sand[500],
  textInverse: sand[50],
  textLink: rust[600],
  // Darkened one notch each: on their own *Bg tints these were 4.16, 4.16 and
  // 3.96:1 — under 4.5:1 before this change as well as after it.
  success: "#387349",
  successBg: "#DCEBDF",
  warning: "#BE832B",
  warningText: "#915E0F",
  warningBg: "#F7E9CE",
  error: "#B23A2E",
  errorBg: "#F5DCD8",
  info: "#396C84",
  infoBg: "#DAE7EE",
  // A warm shadow on a neutral ground is exactly the "off" look being fixed.
  shadowColor: "rgba(0,0,0,.10)",
  shadowSm: { offsetY: 1, blurRadius: 2, color: "rgba(0,0,0,.10)" },
  shadowMd: { offsetY: 6, blurRadius: 20, color: "rgba(0,0,0,.10)" },
  // §9.3: each >=3:1 on a white ground and separated from the others. chart5 is
  // the neutral series, so it comes from `sand`; it sits two luminance steps off
  // chart4 because grey has no hue to fall back on when luminance matches.
  chart1: "#C4491F",
  chart2: "#BE832B",
  chart3: "#2E5F7A",
  chart4: "#4E9A64",
  chart5: sand[600],
  // "ringWorkout rust" / "streak/prBadge rust": the fixed rust-500 core swatch,
  // not `primary` — §10.3's trailing paragraph gives ringCalories and
  // ringWeight as single hex values used unchanged in both themes, and groups
  // ringWorkout/streak/prBadge with them the same way, unlike `fab`, which it
  // explicitly ties to `primary` instead.
  ringWorkout: rust[500],
  ringCalories: "#BE832B",
  ringWeight: "#396C84",
  streak: rust[500],
  prBadge: rust[500],
  navBg: sand[50],
  fab: rust[500],
  aiCoachBg: "#EDE7F0",
  premiumBg: "#F3E9D4",
};

// Dark — neutral charcoal. `bg` stays sand[900] (#171717) rather than pure
// black: the elevation model needs headroom for `surface` to sit above the
// ground, and sand[950] pure black is in the scale when a surface needs it.
export const DarkTheme: SemanticTokens = {
  bg: sand[900],
  surface: sand[800],
  surfaceVariant: "#333333",
  card: sand[800],
  input: "#333333",
  // 3.03:1 on `surface`; the old #403A35 was 2.12:1 and failed WCAG 1.4.11.
  border: "#747474",
  divider: "#3A3A3A",
  overlay: "rgba(0,0,0,.55)",
  skeleton: "#333333",
  primary: rust[400],
  primaryPressed: "#EA8A5C",
  primaryDisabled: "#6E463A",
  primaryContainer: "#4A2418",
  onPrimary: "#171717",
  secondary: sand[400],
  secondaryContainer: "#333333",
  textPrimary: "#EDEDED",
  textSecondary: "#B0B0B0",
  textMuted: "#949494",
  textDisabled: "#757575",
  textInverse: sand[900],
  textLink: "#E8703F",
  success: "#6FBF87",
  successBg: "#24361F",
  warning: "#E0A94B",
  warningText: "#E8B968",
  warningBg: "#3A2E17",
  error: "#E88579",
  errorBg: "#3A1F1A",
  info: "#79A8BE",
  infoBg: "#1E2E36",
  shadowColor: "rgba(0,0,0,.35)",
  shadowSm: { offsetY: 1, blurRadius: 2, color: "rgba(0,0,0,.35)" },
  shadowMd: { offsetY: 6, blurRadius: 20, color: "rgba(0,0,0,.35)" },
  chart1: "#E8703F",
  chart2: "#E0A94B",
  chart3: "#79A8BE",
  chart4: "#6FBF87",
  chart5: sand[500],
  ringWorkout: rust[500],
  ringCalories: "#C98A2E",
  ringWeight: "#3E7691",
  streak: rust[500],
  prBadge: rust[500],
  navBg: sand[800],
  fab: rust[400],
  aiCoachBg: "#2C2635",
  premiumBg: "#352C1B",
};

export type Theme = SemanticTokens;
