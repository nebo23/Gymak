/**
 * GIcon — every glyph in the app, drawn as a real SVG path on one grid.
 *
 * WHY THIS REPLACED THE HAND-BUILT VIEWS
 * Before this, each glyph was stacked `<View>`s with borders: the home tab was
 * a CSS triangle (`borderBottomColor`) sitting on a bordered square, the
 * progress tab was three bars of height 8, 14 and 20, the reveal toggle was an
 * ellipse ring plus a rotated bar, and the back affordance was the text
 * character "<". That construction cannot hold a consistent stroke weight, has
 * no optical sizing, and gives each shape its own accidental proportions — the
 * single biggest contributor to the amateur look the owner called out. It also
 * could not be fixed by tuning the numbers: a border-drawn triangle has no
 * stroke at all, so "one stroke weight across the set" was unreachable by
 * construction.
 *
 * `react-native-svg` is ALREADY a dependency (15.15.4, added by T-28 for
 * GLineChart), so this adds nothing to the dependency list — §A.2 and §8.1's
 * "add no new dependency either way" both hold.
 *
 * THE GRID
 * Every glyph is drawn on a 24x24 viewBox with 2 units of padding, so the live
 * area is a 20x20 box. Shapes differ but optical mass does not: a "home" and a
 * "settings" glyph fill the same box, which is what makes a row of them read as
 * one set rather than four drawings that happen to sit together.
 *
 * THE STROKE
 * Outline only — no fills — with round caps and round joins throughout, so
 * there is exactly one corner treatment in the system.
 *
 * Stroke width is OPTICALLY sized, not proportional. A constant width in
 * viewBox units renders proportionally to the box, which would put 3.5dp on a
 * 48dp empty-state glyph (a marker pen) and 1.17dp on a 16dp chevron (a
 * hairline). `iconStroke` instead names the width in RENDERED dp per step and
 * this component converts back to user units, so the numbers in the token are
 * what actually lands on glass.
 */
import { I18nManager, type ColorValue } from "react-native";
import Svg, { G, Path } from "react-native-svg";

import { iconSize, iconStroke } from "../theme/tokens";

/** The grid every glyph is drawn on. 24x24 with 2u padding => a 20x20 live area. */
const VIEWBOX = 24;

export type GIconName =
  | "home"
  | "plan"
  | "progress"
  | "settings"
  | "chevron"
  | "chevronBack"
  | "eye"
  | "eyeOff"
  | "minus"
  | "plus"
  | "check"
  | "search"
  | "close";

export type GIconSize = keyof typeof iconSize;

/**
 * Circles are expressed as two arc segments rather than <Circle> so that every
 * glyph is the same primitive — one array of `d` strings — and therefore gets
 * identical stroke, cap and join handling with no per-shape branch.
 */
function circle(cx: number, cy: number, r: number): string {
  return `M${cx + r} ${cy} A${r} ${r} 0 1 1 ${cx - r} ${cy} A${r} ${r} 0 1 1 ${cx + r} ${cy}`;
}

const GLYPHS: Record<GIconName, readonly string[]> = {
  // Roof apex on the vertical centre line, walls dropped to a common baseline,
  // door centred — so the mass sits where the other glyphs' mass sits.
  home: ["M3 10.2 L12 3.2 L21 10.2 V19.5 Q21 21 19.5 21 H4.5 Q3 21 3 19.5 Z", "M9.5 21 V14.5 H14.5 V21"],
  // A calendar, not the old clipboard: a training plan is read by week.
  plan: [
    "M4 6.5 Q4 5 5.5 5 H18.5 Q20 5 20 6.5 V19.5 Q20 21 18.5 21 H5.5 Q4 21 4 19.5 Z",
    "M8.5 3 V7",
    "M15.5 3 V7",
    "M4 10 H20",
    "M8 14 H16",
    "M8 17.5 H13",
  ],
  // Bars on a baseline. A trend polyline was the other candidate and was
  // rejected: it muddies at the 16dp step, where bars stay separable.
  progress: ["M3.5 20.5 H20.5", "M7 20.5 V14", "M12 20.5 V10", "M17 20.5 V6"],
  settings: [
    "M3.5 7 H20.5",
    "M3.5 12 H20.5",
    "M3.5 17 H20.5",
    circle(9, 7, 2),
    circle(15, 12, 2),
    circle(7.5, 17, 2),
  ],
  // `chevron` points toward `end` (a disclosure); `chevronBack` toward
  // `start`. Both are listed in MIRRORED below, so each flips under RTL and
  // keeps pointing at the direction it means rather than the side it sat on.
  chevron: ["M9.5 5 L16.5 12 L9.5 19"],
  chevronBack: ["M14.5 5 L7.5 12 L14.5 19"],
  eye: ["M2.5 12 C6 6.5 18 6.5 21.5 12 C18 17.5 6 17.5 2.5 12 Z", circle(12, 12, 3)],
  eyeOff: ["M2.5 12 C6 6.5 18 6.5 21.5 12 C18 17.5 6 17.5 2.5 12 Z", circle(12, 12, 3), "M4 4 L20 20"],
  minus: ["M5 12 H19"],
  plus: ["M12 5 V19", "M5 12 H19"],
  check: ["M4.5 12.5 L9.5 17.5 L19.5 7"],
  search: [circle(10.5, 10.5, 6.5), "M15.5 15.5 L21 21"],
  close: ["M6 6 L18 18", "M18 6 L6 18"],
};

/**
 * Glyphs that encode a direction and must therefore mirror under RTL (§9.6),
 * exactly as GScreen's back affordance already did when it was a text "<".
 * Everything else is direction-neutral and must NOT flip — a mirrored search
 * lens or calendar is just a wrong drawing.
 */
const MIRRORED: ReadonlySet<GIconName> = new Set<GIconName>(["chevron", "chevronBack"]);

export interface GIconProps {
  name: GIconName;
  /** A step on the `iconSize` scale — a name, not a number, so the scale holds. */
  size?: GIconSize;
  /**
   * `ColorValue`, not `string`, because that is what React Navigation hands
   * `tabBarIcon` and what `react-native-svg`'s `stroke` already accepts.
   * Callers still pass a `theme.*` token — never a literal.
   */
  color: ColorValue;
  /**
   * Omit for a decorative glyph (the default), which is then hidden from
   * assistive tech. Pass a TRANSLATED label only when this icon is the entire
   * content of a touchable and nothing else names it.
   */
  accessibilityLabel?: string;
  testID?: string;
}

export function GIcon({ name, size = "md", color, accessibilityLabel, testID }: GIconProps) {
  const px = iconSize[size];
  // Rendered dp -> user units. See "THE STROKE" above.
  const strokeWidth = (iconStroke[size] * VIEWBOX) / px;
  const mirrored = MIRRORED.has(name) && I18nManager.isRTL;
  const decorative = accessibilityLabel === undefined;

  return (
    <Svg
      width={px}
      height={px}
      viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`}
      testID={testID}
      accessibilityLabel={accessibilityLabel}
      accessibilityElementsHidden={decorative}
      importantForAccessibility={decorative ? "no-hide-descendants" : "yes"}
    >
      <G transform={mirrored ? `translate(${VIEWBOX} 0) scale(-1 1)` : undefined}>
        {GLYPHS[name].map((d) => (
          <Path
            key={d}
            d={d}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </G>
    </Svg>
  );
}
