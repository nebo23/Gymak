/**
 * GMetric — a number and its unit, with nothing else attached.
 *
 * `GStat` already owns the labelled hero figure (label above, 34pt value,
 * optional delta). What had no home was the number that appears INSIDE
 * something else: a record's e1RM at the end of a list row, a session's volume
 * beside its date, the current value under a chart. Those were being written
 * as `bodyStrong` text with the unit glued into the same string --
 * `${value.toFixed(1)} ${unit}` -- which is why a column of them never lined
 * up and why the unit competed with the number for weight.
 *
 * Two things this fixes, both of them the brief's "numbers are not treated as
 * data" rule:
 *   - tabular figures, so digits are the same width and a column of values
 *     aligns on the decimal instead of drifting;
 *   - the unit is a separate, smaller, muted element on the baseline, so the
 *     number reads first and the unit qualifies it. One units treatment,
 *     everywhere, instead of a per-call-site string template.
 */
import { StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { space } from "../theme/tokens";

/** `sm` -> metricSm (18), `md` -> metric (22), `lg` -> stat (34). */
export type GMetricSize = "sm" | "md" | "lg";

const ROLE: Record<GMetricSize, "metricSm" | "metric" | "stat"> = {
  sm: "metricSm",
  md: "metric",
  lg: "stat",
};

export interface GMetricProps {
  value: string | number;
  /** Already translated. Rendered separately from the value, never concatenated. */
  unit?: string;
  size?: GMetricSize;
  /**
   * `true` colours the value with the accent — for a personal record. Uses
   * `textAccent`, not `primary`: `primary` is the fill step and is 3.84:1 on a
   * dark surface, under AA for text.
   */
  accent?: boolean;
  testID?: string;
}

export function GMetric({ value, unit, size = "md", accent = false, testID }: GMetricProps) {
  const theme = useTheme();
  const { locale } = useI18n();

  return (
    <View style={styles.row} testID={testID}>
      <Text style={[textStyle(ROLE[size], locale), { color: accent ? theme.textAccent : theme.textPrimary }]}>
        {value}
      </Text>
      {unit ? (
        <Text style={[textStyle("label", locale), styles.unit, { color: theme.textMuted }]}>
          {unit}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    // Baseline, not centre: the unit has to sit ON the number's baseline or it
    // floats in the middle of the digits' height and reads as a separate word.
    alignItems: "baseline",
  },
  unit: {
    marginStart: space[0],
  },
});
