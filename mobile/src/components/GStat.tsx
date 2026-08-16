/**
 * §9.2 GStat — label/value/unit/delta/tone. `value` uses the `stat` type
 * role (34/700, tabular figures). Tone colours the delta but never carries
 * meaning alone (§10.6): the sign is always spelled out in the text too, so
 * a colour-blind reader or a greyscale screenshot still gets the direction.
 */
import { StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { space } from "../theme/tokens";

export type GStatTone = "neutral" | "positive" | "negative";

export interface GStatProps {
  label: string;
  value: string | number;
  unit?: string;
  delta?: number;
  tone: GStatTone;
  testID?: string;
}

function formatDelta(delta: number): string {
  return delta > 0 ? `+${delta}` : `${delta}`;
}

export function GStat({ label, value, unit, delta, tone, testID }: GStatProps) {
  const theme = useTheme();
  const { locale } = useI18n();

  const toneColor =
    tone === "positive" ? theme.success : tone === "negative" ? theme.error : theme.textSecondary;

  return (
    <View testID={testID}>
      <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>{label}</Text>
      <View style={styles.valueRow}>
        <Text style={[textStyle("stat", locale), { color: theme.textPrimary }]}>{value}</Text>
        {unit ? (
          <Text style={[textStyle("label", locale), styles.unit, { color: theme.textMuted }]}>
            {unit}
          </Text>
        ) : null}
      </View>
      {delta !== undefined ? (
        <Text style={[textStyle("label", locale), { color: toneColor }]}>{formatDelta(delta)}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  valueRow: {
    flexDirection: "row",
    alignItems: "baseline",
  },
  unit: {
    marginStart: space[1],
  },
});
