/**
 * §10.5 GSelectCard — title, optional description, `selected`, `disabled`
 * with a reason line. Selected state is a rust border plus `primaryContainer`
 * fill, never a small radio dot (§10.5's own words).
 */
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { minTouchTarget, radius, space } from "../theme/tokens";

export interface GSelectCardProps {
  title: string;
  description?: string;
  selected: boolean;
  onPress: () => void;
  disabled?: boolean;
  disabledReason?: string;
  accessibilityLabel?: string;
  testID?: string;
}

export function GSelectCard({
  title,
  description,
  selected,
  onPress,
  disabled = false,
  disabledReason,
  accessibilityLabel,
  testID,
}: GSelectCardProps) {
  const theme = useTheme();
  const { locale } = useI18n();

  const borderColor = disabled ? theme.border : selected ? theme.primary : theme.border;
  const backgroundColor = disabled
    ? theme.surfaceVariant
    : selected
      ? theme.primaryContainer
      : theme.card;
  const titleColor = disabled ? theme.textDisabled : theme.textPrimary;

  return (
    <Pressable
      testID={testID}
      onPress={disabled ? undefined : onPress}
      disabled={disabled}
      accessibilityRole="radio"
      accessibilityLabel={accessibilityLabel ?? title}
      accessibilityState={{ selected, disabled }}
      style={[
        styles.card,
        {
          borderColor,
          backgroundColor,
          borderWidth: selected ? 2 : 1,
        },
      ]}
    >
      <Text style={[textStyle("bodyStrong", locale), { color: titleColor }]}>{title}</Text>
      {description ? (
        <Text
          style={[
            textStyle("body", locale),
            styles.description,
            { color: disabled ? theme.textDisabled : theme.textSecondary },
          ]}
        >
          {description}
        </Text>
      ) : null}
      {disabled && disabledReason ? (
        <Text style={[textStyle("caption", locale), styles.description, { color: theme.textMuted }]}>
          {disabledReason}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    minHeight: minTouchTarget,
    borderRadius: radius.lg,
    padding: space[3],
    justifyContent: "center",
  },
  description: {
    marginTop: space[0],
  },
});
