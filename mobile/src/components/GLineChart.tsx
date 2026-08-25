/**
 * §9.2 GLineChart -- `series`/`xAccessor`/`yAccessor`/`range`, per §9.3. One
 * chart type in Phase 2: a line, weight over time, with the moving average
 * as a second line. Built from `react-native-svg` alone (§9.3/§A.2) -- no
 * charting library, so this file draws exactly what §9.3 asks for and
 * nothing a generic chart library would bring along uninvited.
 *
 * All the geometry -- gap segmentation, the non-zero-based axis range,
 * calendar-distance point placement -- lives in the RN/SVG-free
 * GLineChartGeometry.ts, unit-tested there. This file is deliberately thin:
 * it measures its own width, calls that module, and draws the result.
 *
 * RTL: the whole chart (canvas and its four corner labels) sits inside a
 * `direction: "ltr"` container -- a real RN `ViewStyle` property (Yoga's own
 * layout-direction concept, not a manual `start`/`end` swap) that forces
 * this entire subtree to lay out left-to-right regardless of
 * `I18nManager.isRTL`, so a plain `flexDirection: "row"` inside it never
 * needs its own RTL branch. This is a deliberate, narrow exception to
 * "start/end, never left/right" (§9.6/CLAUDE.md) -- the same exception
 * Phase 1 §9.6 already carves out for numbers, dates, and weights ("stay
 * left-to-right ... even in Arabic"). A time-series chart is exactly that
 * kind of content: mirroring it would reverse which side "earlier" sits on,
 * which no reader benefits from and every reader would find confusing
 * regardless of script direction. The axis labels keep Western digits and that
 * LTR order in both locales, which is what §9.6 actually constrains.
 *
 * AMENDED by device check 14 ("RTL throughout, INCLUDING THE CHART'S AXIS
 * LABELS"): the month NAME is now localised, so an Arabic Progress screen reads
 * "28 مايو" rather than "May 28". This paragraph previously claimed the labels
 * were "never Arabic script" and pinned them to the Latin face; that went
 * further than §9.6, which carves out digits and direction, not month names --
 * and it left visible English inside an otherwise fully-Arabic screen. The
 * weight labels are still formatted on the Latin face, which is what the
 * numerals argument (Inter's digits vs Cairo's) was actually about; the date
 * labels follow `locale` so Arabic script gets Cairo instead of falling back to
 * a system font Inter cannot supply. Colours are read from `useTheme()` only -- never a hex literal --
 * but which token each series uses is the caller's choice (progress.tsx),
 * not hardcoded here, matching every other primitive's separation between
 * "generic component" and "this app's specific usage of it."
 */
import { useState } from "react";
import { StyleSheet, Text, View, type LayoutChangeEvent } from "react-native";
import Svg, { Circle, G, Path } from "react-native-svg";

import { useI18n, type Locale } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { space } from "../theme/tokens";
import {
  buildContinuousSegments,
  buildPathD,
  computeValueRange,
  daysBetweenIso,
  plotPoints,
  type DateValue,
} from "./GLineChartGeometry";

export interface GLineChartSeries<T> {
  data: T[];
  color: string;
  strokeWidth?: number;
  /** Draws a small dot at every point in this series -- reserved for the
   * raw log (§9.3's "chart3" series), never the moving average, so a real
   * logged day is always visible as a mark even when it has no adjacent
   * neighbour to draw a line to. */
  showDots?: boolean;
}

export interface GLineChartRange {
  /** ISO date, inclusive. */
  start: string;
  /** ISO date, inclusive. */
  end: string;
}

export interface GLineChartProps<T> {
  series: GLineChartSeries<T>[];
  xAccessor: (item: T) => string;
  yAccessor: (item: T) => number;
  range: GLineChartRange;
  /** §9.3: "summarising the trend in words" -- built by the caller, which
   * knows the units and the caller's own locale-aware number formatting. */
  accessibilityLabel: string;
  testID?: string;
}

const CHART_HEIGHT = 160;
const Y_LABEL_COLUMN_WIDTH = 36;
const DOT_RADIUS = 3;

/** Deliberately Western digits regardless of the app's own locale -- see this
 * file's module docstring. A number has no language, so "en" and
 * "ar-u-nu-latn" render this identically; "en" is kept for the plain case. */
function formatAxisWeight(value: number): string {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 0 }).format(Math.round(value));
}

/** Western digits and LTR order in both locales (Phase 1 §9.6: "numbers, dates,
 * weights ... stay left-to-right and use Western digits even in Arabic"), but
 * the month NAME follows the app locale -- `ar-u-nu-latn` is the Arabic
 * calendar with Latin numerals, the same pairing progress.tsx and settings.tsx
 * already use for user-facing dates. §9.6 constrains digits and direction; it
 * does not ask for an English month name inside an Arabic UI, and device check
 * 14 ("RTL throughout, including the chart's axis labels") is what catches the
 * difference -- before this, an Arabic Progress screen still read "May 28". */
function formatAxisDate(isoDate: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-u-nu-latn" : "en", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${isoDate}T00:00:00Z`));
}

export function GLineChart<T>({
  series,
  xAccessor,
  yAccessor,
  range,
  accessibilityLabel,
  testID,
}: GLineChartProps<T>) {
  const theme = useTheme();
  const { locale } = useI18n();
  const [width, setWidth] = useState(0);

  const domainDays = Math.max(1, daysBetweenIso(range.start, range.end) + 1);

  const seriesPoints: DateValue[][] = series.map((oneSeries) =>
    oneSeries.data.map((item) => ({ date: xAccessor(item), value: yAccessor(item) })),
  );
  const allValues = seriesPoints.flat().map((point) => point.value);
  const valueRange = computeValueRange(allValues);

  const handleLayout = (event: LayoutChangeEvent) => {
    setWidth(event.nativeEvent.layout.width);
  };

  return (
    <View
      testID={testID}
      style={styles.ltrRoot}
      accessible
      accessibilityRole="image"
      accessibilityLabel={accessibilityLabel}
    >
      <View
        style={styles.canvasRow}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
      >
        <View style={styles.yLabelColumn}>
          <Text style={[textStyle("caption", "en"), { color: theme.textMuted }]}>
            {formatAxisWeight(valueRange.max)}
          </Text>
          <Text style={[textStyle("caption", "en"), { color: theme.textMuted }]}>
            {formatAxisWeight(valueRange.min)}
          </Text>
        </View>

        <View onLayout={handleLayout} style={styles.canvas}>
          {width > 0 ? (
            <Svg width={width} height={CHART_HEIGHT}>
              {series.map((oneSeries, seriesIndex) => {
                const points = seriesPoints[seriesIndex]!;
                const segments = buildContinuousSegments(points);
                return (
                  <G key={seriesIndex}>
                    {segments.map((segment, segmentIndex) => {
                      if (segment.length < 2) return null;
                      const plotted = plotPoints(segment, range.start, domainDays, valueRange);
                      const d = buildPathD(plotted, width, CHART_HEIGHT);
                      return (
                        <Path
                          key={segmentIndex}
                          d={d}
                          stroke={oneSeries.color}
                          strokeWidth={oneSeries.strokeWidth ?? 2}
                          fill="none"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      );
                    })}
                    {oneSeries.showDots
                      ? plotPoints(points, range.start, domainDays, valueRange).map((plotted, i) => (
                          <Circle
                            key={i}
                            cx={plotted.xRatio * width}
                            cy={(1 - plotted.yRatio) * CHART_HEIGHT}
                            r={DOT_RADIUS}
                            fill={oneSeries.color}
                          />
                        ))
                      : null}
                  </G>
                );
              })}
            </Svg>
          ) : null}
        </View>
      </View>

      <View
        style={styles.xLabelRow}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
      >
        {/* `locale`, not a hardcoded "en": an Arabic month name needs the Cairo
            face -- Inter has no Arabic glyphs and would fall back to a system
            font. The weight labels above stay on the Latin face, which is what
            the module docstring's numerals argument is actually about. */}
        <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
          {formatAxisDate(range.start, locale)}
        </Text>
        <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
          {formatAxisDate(range.end, locale)}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  // §9.6's "numbers/dates/weights stay left-to-right" extended to this
  // whole chart -- see the module docstring above.
  ltrRoot: {
    direction: "ltr",
  },
  canvasRow: {
    flexDirection: "row",
  },
  yLabelColumn: {
    width: Y_LABEL_COLUMN_WIDTH,
    height: CHART_HEIGHT,
    justifyContent: "space-between",
  },
  canvas: {
    flex: 1,
    height: CHART_HEIGHT,
  },
  xLabelRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: space[1],
    // Inset past the y-label column so the two date labels line up with the
    // canvas, not with the axis numbers. `marginStart`, not `marginLeft`,
    // even though `ltrRoot` above forces this subtree left-to-right and the
    // two therefore resolve identically here -- the codebase-wide "start/end,
    // never left/right" rule stays mechanically greppable that way, and the
    // forced direction is what makes the choice a no-op rather than a risk.
    marginStart: Y_LABEL_COLUMN_WIDTH,
  },
});
