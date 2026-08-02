/**
 * The complete Gymak palette and scales, transcribed verbatim from spec §10.
 * Every hex value below is copied character-for-character from §10.1–§10.4 —
 * none invented, adjusted, or rounded. No component may hold a hex literal;
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

// §10.2 — Sand scale: warm neutral.
export const sand = {
  50: "#FFFDF8",
  100: "#FAF6EF",
  200: "#F3ECE0",
  300: "#E7DDCC",
  400: "#D3C7B4",
  500: "#B4A896",
  600: "#8A8175",
  700: "#5A5249",
  800: "#35302B",
  900: "#211D1B",
  950: "#17130F",
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
  border: sand[300],
  divider: sand[200],
  overlay: "rgba(33,29,27,.45)",
  skeleton: sand[200],
  primary: rust[500],
  primaryPressed: rust[700],
  primaryDisabled: rust[200],
  primaryContainer: rust[50],
  onPrimary: "#FFF6EF",
  secondary: sand[700],
  secondaryContainer: sand[200],
  textPrimary: sand[900],
  textSecondary: sand[700],
  textMuted: sand[600],
  textDisabled: sand[500],
  textInverse: sand[50],
  textLink: rust[600],
  success: "#3B7A4E",
  successBg: "#DCEBDF",
  warning: "#C98A2E",
  warningText: "#9A6410",
  warningBg: "#F7E9CE",
  error: "#B23A2E",
  errorBg: "#F5DCD8",
  info: "#3E7691",
  infoBg: "#DAE7EE",
  shadowColor: "rgba(53,41,30,.10)",
  shadowSm: { offsetY: 1, blurRadius: 2, color: "rgba(53,41,30,.10)" },
  shadowMd: { offsetY: 6, blurRadius: 20, color: "rgba(53,41,30,.10)" },
  chart1: "#C4491F",
  chart2: "#C98A2E",
  chart3: "#3E7691",
  chart4: "#3B7A4E",
  chart5: "#B4A896",
  // "ringWorkout rust" / "streak/prBadge rust": the fixed rust-500 core swatch,
  // not `primary` — §10.3's trailing paragraph gives ringCalories and
  // ringWeight as single hex values used unchanged in both themes, and groups
  // ringWorkout/streak/prBadge with them the same way, unlike `fab`, which it
  // explicitly ties to `primary` instead.
  ringWorkout: rust[500],
  ringCalories: "#C98A2E",
  ringWeight: "#3E7691",
  streak: rust[500],
  prBadge: rust[500],
  navBg: sand[50],
  fab: rust[500],
  aiCoachBg: "#EDE7F0",
  premiumBg: "#F3E9D4",
};

// §10.3 "Dark — warm charcoal, never #000".
export const DarkTheme: SemanticTokens = {
  bg: sand[900],
  surface: "#2A2523",
  surfaceVariant: "#332D2A",
  card: "#2A2523",
  input: "#332D2A",
  border: "#403A35",
  divider: "#35302B",
  overlay: "rgba(0,0,0,.55)",
  skeleton: "#332D2A",
  primary: rust[400],
  primaryPressed: "#EA8A5C",
  primaryDisabled: "#6E463A",
  primaryContainer: "#4A2418",
  onPrimary: "#1A1310",
  secondary: sand[400],
  secondaryContainer: "#332D2A",
  textPrimary: "#EDE6DA",
  textSecondary: "#B5AB9E",
  textMuted: "#8A8175",
  textDisabled: "#6A625A",
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
  chart5: "#B4A896",
  ringWorkout: rust[500],
  ringCalories: "#C98A2E",
  ringWeight: "#3E7691",
  streak: rust[500],
  prBadge: rust[500],
  navBg: "#2A2523",
  fab: rust[400],
  aiCoachBg: "#2C2635",
  premiumBg: "#352C1B",
};

export type Theme = SemanticTokens;
