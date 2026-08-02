/**
 * §10.5 GProgressBar — `step` of `total`, animated, with an accessible
 * "step 3 of 6" label.
 */
import { useEffect, useRef } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { motion, radius, space } from "../theme/tokens";

export interface GProgressBarProps {
  step: number;
  total: number;
  showLabel?: boolean;
  testID?: string;
}

export function GProgressBar({ step, total, showLabel = true, testID }: GProgressBarProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const ratio = total > 0 ? Math.min(Math.max(step / total, 0), 1) : 0;
  const progress = useRef(new Animated.Value(ratio)).current;

  useEffect(() => {
    Animated.timing(progress, {
      toValue: ratio,
      duration: motion.base,
      useNativeDriver: false,
    }).start();
  }, [ratio, progress]);

  const label = t("components.progressBar.stepLabel", { step, total });

  return (
    <View testID={testID}>
      <View
        style={[styles.track, { backgroundColor: theme.divider }]}
        accessibilityRole="progressbar"
        accessibilityLabel={label}
        accessibilityValue={{ min: 0, max: total, now: step, text: label }}
      >
        <Animated.View
          style={[
            styles.fill,
            {
              backgroundColor: theme.primary,
              width: progress.interpolate({
                inputRange: [0, 1],
                outputRange: ["0%", "100%"],
              }),
            },
          ]}
        />
      </View>
      {showLabel ? (
        <Text style={[textStyle("caption", locale), styles.label, { color: theme.textMuted }]}>
          {label}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    height: space[1],
    borderRadius: radius.pill,
    overflow: "hidden",
  },
  fill: {
    height: "100%",
    borderRadius: radius.pill,
  },
  label: {
    marginTop: space[1],
  },
});
