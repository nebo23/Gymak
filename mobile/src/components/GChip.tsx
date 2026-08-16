/**
 * §9.2 GChip — filter and range chips. `label`, `selected`, `onPress`,
 * `disabled`. Selected = rust border + `primaryContainer`, matching
 * `GSelectCard`'s selected treatment exactly, just in a compact pill.
 */
import { Pressable, StyleSheet, Text } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { minTouchTarget, radius, space } from "../theme/tokens";

export interface GChipProps {
  label: string;
  selected: boolean;
  onPress: () => void;
  disabled?: boolean;
  accessibilityLabel?: string;
  testID?: string;
}

export function GChip({
  label,
  selected,
  onPress,
  disabled = false,
  accessibilityLabel,
  testID,
}: GChipProps) {
  const theme = useTheme();
  const { locale } = useI18n();

  const borderColor = disabled ? theme.border : selected ? theme.primary : theme.border;
  const backgroundColor = disabled
    ? theme.surfaceVariant
    : selected
      ? theme.primaryContainer
      : theme.surface;
  const textColor = disabled ? theme.textDisabled : selected ? theme.primary : theme.textSecondary;

  return (
    <Pressable
      testID={testID}
      onPress={disabled ? undefined : onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ selected, disabled }}
      style={[styles.chip, { borderColor, backgroundColor, borderWidth: selected ? 2 : 1 }]}
    >
      <Text style={[textStyle("label", locale), { color: textColor }]} numberOfLines={1}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    minHeight: minTouchTarget,
    borderRadius: radius.pill,
    paddingHorizontal: space[3],
    alignItems: "center",
    justifyContent: "center",
  },
});
