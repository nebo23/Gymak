/**
 * §10.5 GButton — variant: primary | secondary | ghost | social, loading,
 * disabled, fullWidth, icon. Height 52 / radius 12 (§10.4 control height).
 * Loading keeps the label and the button's width; disabled swaps in a real
 * disabled colour from the theme rather than dimming with opacity, per
 * §10.5's explicit "never opacity alone" rule.
 */
import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
  type GestureResponderEvent,
} from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import type { Theme } from "../theme/tokens";
import { textStyle } from "../theme/typography";
import { controlHeight, radius, space } from "../theme/tokens";

export type GButtonVariant = "primary" | "secondary" | "ghost" | "social";

export interface GButtonProps {
  label: string;
  onPress: (event: GestureResponderEvent) => void;
  variant?: GButtonVariant;
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  icon?: ReactNode;
  accessibilityLabel?: string;
  testID?: string;
}

interface VariantColors {
  backgroundColor: string;
  borderColor: string;
  borderWidth: number;
  textColor: string;
}

function colorsFor(theme: Theme, variant: GButtonVariant, disabled: boolean): VariantColors {
  if (disabled) {
    switch (variant) {
      case "primary":
        return {
          backgroundColor: theme.primaryDisabled,
          borderColor: theme.primaryDisabled,
          borderWidth: 0,
          textColor: theme.onPrimary,
        };
      case "secondary":
        return {
          backgroundColor: "transparent",
          borderColor: theme.border,
          borderWidth: 1,
          textColor: theme.textDisabled,
        };
      case "social":
        return {
          backgroundColor: theme.surfaceVariant,
          borderColor: theme.border,
          borderWidth: 1,
          textColor: theme.textDisabled,
        };
      case "ghost":
      default:
        return {
          backgroundColor: "transparent",
          borderColor: "transparent",
          borderWidth: 0,
          textColor: theme.textDisabled,
        };
    }
  }

  switch (variant) {
    case "primary":
      return {
        backgroundColor: theme.primary,
        borderColor: theme.primary,
        borderWidth: 0,
        textColor: theme.onPrimary,
      };
    case "secondary":
      return {
        backgroundColor: "transparent",
        borderColor: theme.border,
        borderWidth: 1,
        textColor: theme.textPrimary,
      };
    case "social":
      return {
        backgroundColor: theme.surface,
        borderColor: theme.border,
        borderWidth: 1,
        textColor: theme.textPrimary,
      };
    case "ghost":
    default:
      return {
        backgroundColor: "transparent",
        borderColor: "transparent",
        borderWidth: 0,
        textColor: theme.primary,
      };
  }
}

export function GButton({
  label,
  onPress,
  variant = "primary",
  loading = false,
  disabled = false,
  fullWidth = false,
  icon,
  accessibilityLabel,
  testID,
}: GButtonProps) {
  const theme = useTheme();
  const { locale } = useI18n();
  const isDisabled = disabled || loading;
  const colors = colorsFor(theme, variant, isDisabled);

  return (
    <Pressable
      testID={testID}
      onPress={isDisabled ? undefined : onPress}
      disabled={isDisabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      style={({ pressed }) => [
        styles.base,
        {
          backgroundColor: colors.backgroundColor,
          borderColor: colors.borderColor,
          borderWidth: colors.borderWidth,
          width: fullWidth ? "100%" : undefined,
          opacity: pressed && !isDisabled ? 0.9 : 1,
        },
      ]}
    >
      <View style={styles.content} pointerEvents="none">
        {icon != null ? <View style={styles.icon}>{icon}</View> : null}
        <Text
          style={[textStyle("bodyStrong", locale), { color: colors.textColor }]}
          numberOfLines={1}
        >
          {label}
        </Text>
        {loading ? (
          <ActivityIndicator style={styles.spinner} color={colors.textColor} size="small" />
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    height: controlHeight,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: space[4],
  },
  content: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
  },
  icon: {
    marginEnd: space[1],
  },
  spinner: {
    marginStart: space[1],
  },
});
