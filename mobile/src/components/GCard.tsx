/**
 * §9.2 GCard — title/subtitle/footer, optionally pressable. Surface
 * background, `radius.lg`, `shadowSm`; the pressable variant gets a real
 * pressed-state background swap, not opacity — §10.5's "never opacity
 * alone" rule, carried into every Phase 2 primitive too.
 */
import type { ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import type { Theme } from "../theme/tokens";
import { textStyle } from "../theme/typography";
import { radius, space } from "../theme/tokens";

export interface GCardProps {
  title?: string;
  subtitle?: string;
  onPress?: () => void;
  footer?: ReactNode;
  children?: ReactNode;
  accessibilityLabel?: string;
  testID?: string;
}

// RN's shadow properties are iOS-only (elevation carries Android); the
// token's colour already bakes in its own alpha, so shadowOpacity is 1 and
// the colour alone controls how strong the shadow reads.
function shadowStyle(token: Theme["shadowSm"]) {
  return {
    shadowColor: token.color,
    shadowOffset: { width: 0, height: token.offsetY },
    shadowOpacity: 1,
    shadowRadius: token.blurRadius,
    elevation: token.offsetY + Math.round(token.blurRadius / 4),
  };
}

export function GCard({
  title,
  subtitle,
  onPress,
  footer,
  children,
  accessibilityLabel,
  testID,
}: GCardProps) {
  const theme = useTheme();
  const { locale } = useI18n();
  const hasHeading = Boolean(title || subtitle);

  const body = (
    <>
      {title ? (
        <Text style={[textStyle("h3", locale), { color: theme.textPrimary }]}>{title}</Text>
      ) : null}
      {subtitle ? (
        <Text style={[textStyle("body", locale), styles.subtitle, { color: theme.textSecondary }]}>
          {subtitle}
        </Text>
      ) : null}
      {children ? <View style={hasHeading ? styles.body : undefined}>{children}</View> : null}
      {footer ? <View style={styles.footer}>{footer}</View> : null}
    </>
  );

  if (onPress) {
    return (
      <Pressable
        testID={testID}
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel ?? title}
        style={({ pressed }) => [
          styles.card,
          { backgroundColor: pressed ? theme.surfaceVariant : theme.card },
          shadowStyle(theme.shadowSm),
        ]}
      >
        {body}
      </Pressable>
    );
  }

  return (
    <View
      testID={testID}
      style={[styles.card, { backgroundColor: theme.card }, shadowStyle(theme.shadowSm)]}
    >
      {body}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    padding: space[4],
  },
  subtitle: {
    marginTop: space[0],
  },
  body: {
    marginTop: space[3],
  },
  footer: {
    marginTop: space[3],
  },
});
