/**
 * §10.4's type scale, plus the two-decision font wiring T-10 owns.
 *
 * Latin face: Inter. Arabic face: Cairo (see the T-10 report for why, over
 * IBM Plex Sans Arabic). Both are loaded once via `useAppFonts()` below —
 * never left to the OS to substitute a per-platform fallback.
 *
 * Expo Google Fonts ships one font *family name per weight*
 * (`Cairo_700Bold`, not `Cairo` + `fontWeight: "700"`). Setting `fontWeight`
 * alongside one of these family names makes RN attempt to synthesize a
 * further-bolded fake weight on top of an already-bold glyph outline, which
 * is exactly the inconsistent-per-platform rendering "never let the OS pick
 * a fallback" is guarding against. `textStyle()` below therefore emits
 * `fontFamily` only, weight baked in, and no `fontWeight` key at all.
 */
import {
  Cairo_400Regular,
  Cairo_500Medium,
  Cairo_600SemiBold,
  Cairo_700Bold,
} from "@expo-google-fonts/cairo";
import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
} from "@expo-google-fonts/inter";
import { useFonts } from "expo-font";

export type FontWeight = 400 | 500 | 600 | 700;
export type Locale = "ar" | "en";

/** Every Expo Google Fonts constant `useFonts` needs to load, for both faces. */
export const fontsToLoad = {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  Cairo_400Regular,
  Cairo_500Medium,
  Cairo_600SemiBold,
  Cairo_700Bold,
} as const;

/** `_layout.tsx` calls this once; screens must not render text until it resolves. */
export function useAppFonts(): boolean {
  const [loaded] = useFonts(fontsToLoad);
  return loaded;
}

const latinFamily: Record<FontWeight, string> = {
  400: "Inter_400Regular",
  500: "Inter_500Medium",
  600: "Inter_600SemiBold",
  700: "Inter_700Bold",
};

const arabicFamily: Record<FontWeight, string> = {
  400: "Cairo_400Regular",
  500: "Cairo_500Medium",
  600: "Cairo_600SemiBold",
  700: "Cairo_700Bold",
};

export function fontFamilyFor(locale: Locale, weight: FontWeight): string {
  return locale === "ar" ? arabicFamily[weight] : latinFamily[weight];
}

interface TypeRole {
  fontSize: number;
  weight: FontWeight;
  lineHeight?: number;
  letterSpacing?: number;
  tabularNums?: boolean;
}

// §10.4's role table. `caption`'s colour (textMuted) is a theme concern, not
// a typography one — callers pair `typeScale.caption` with `theme.textMuted`.
export const typeScale: Record<
  | "display"
  | "h1"
  | "h2"
  | "h3"
  | "body"
  | "bodyStrong"
  | "label"
  | "caption"
  | "stat"
  | "metric"
  | "metricSm",
  TypeRole
> = {
  display: { fontSize: 34, weight: 700, letterSpacing: -0.02 * 34 },
  h1: { fontSize: 28, weight: 700 },
  h2: { fontSize: 22, weight: 600 },
  h3: { fontSize: 18, weight: 600 },
  body: { fontSize: 16, weight: 400, lineHeight: 16 * 1.5 },
  bodyStrong: { fontSize: 16, weight: 600 },
  label: { fontSize: 14, weight: 500 },
  caption: { fontSize: 12, weight: 400 },
  stat: { fontSize: 34, weight: 700, tabularNums: true },
  // Weights, reps, volumes, e1RMs and streaks are the CONTENT of this app, and
  // they were being set in `body` and `bodyStrong` -- the same type as the
  // sentence next to them, with proportional figures, so a column of numbers
  // did not line up and a number the user is proud of read as prose.
  //
  // `stat` (34) is right for a hero and far too big for a list row, which is
  // why those two roles kept reaching for body text instead. These fill that
  // gap: both carry tabular figures, and both sit a deliberate step above the
  // `label` (14) they are captioned by rather than level with it.
  //
  //   metric   22  a row's value, a card's secondary figure. Equal to `h2`, so
  //                a number can head a row the way a title heads a card.
  //   metricSm 18  an inline figure inside a dense row. Equal to `h3`, and one
  //                clear step above the 16 of the body text beside it.
  metric: { fontSize: 22, weight: 700, tabularNums: true },
  metricSm: { fontSize: 18, weight: 600, tabularNums: true },
};

export interface ResolvedTextStyle {
  fontFamily: string;
  fontSize: number;
  lineHeight?: number;
  letterSpacing?: number;
  fontVariant?: ["tabular-nums"];
}

export function textStyle(
  role: keyof typeof typeScale,
  locale: Locale,
): ResolvedTextStyle {
  const spec = typeScale[role];
  return {
    fontFamily: fontFamilyFor(locale, spec.weight),
    fontSize: spec.fontSize,
    ...(spec.lineHeight !== undefined ? { lineHeight: spec.lineHeight } : {}),
    ...(spec.letterSpacing !== undefined ? { letterSpacing: spec.letterSpacing } : {}),
    ...(spec.tabularNums ? { fontVariant: ["tabular-nums"] as const } : {}),
  };
}
