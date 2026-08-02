/**
 * §10.5 GErrorBanner — localised message from an error `code`, optional
 * retry, dismissible. Announced on appearance (§10.6: errors are announced,
 * not only coloured).
 */
import { useEffect } from "react";
import { AccessibilityInfo, Pressable, StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { minTouchTarget, radius, space } from "../theme/tokens";

export interface GErrorBannerProps {
  /** Looked up as `errors.<code>` (§7.2/§9.6). */
  code?: string;
  /** Pre-resolved message, for the rare case the caller already built one
   * (e.g. a live rate-limit countdown) rather than a static error code. */
  message?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  testID?: string;
}

export function GErrorBanner({ code, message, onRetry, onDismiss, testID }: GErrorBannerProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const resolved = message ?? (code ? t(`errors.${code}`) : t("errors.GENERIC"));

  useEffect(() => {
    AccessibilityInfo.announceForAccessibility(resolved);
  }, [resolved]);

  return (
    <View
      testID={testID}
      style={[styles.container, { backgroundColor: theme.errorBg }]}
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
    >
      <Text style={[textStyle("body", locale), styles.message, { color: theme.error }]}>
        {resolved}
      </Text>
      <View style={styles.actions}>
        {onRetry ? (
          <Pressable
            onPress={onRetry}
            accessibilityRole="button"
            accessibilityLabel={t("common.retry")}
            style={styles.action}
            hitSlop={actionHitSlop}
          >
            <Text style={[textStyle("label", locale), { color: theme.error }]}>
              {t("common.retry")}
            </Text>
          </Pressable>
        ) : null}
        {onDismiss ? (
          <Pressable
            onPress={onDismiss}
            accessibilityRole="button"
            accessibilityLabel={t("common.dismiss")}
            style={styles.action}
            hitSlop={actionHitSlop}
          >
            <Text style={[textStyle("label", locale), { color: theme.error }]}>
              {t("common.dismiss")}
            </Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const actionHitSlopPad = Math.max(0, (minTouchTarget - 20) / 2);
const actionHitSlop = {
  top: actionHitSlopPad,
  bottom: actionHitSlopPad,
  left: actionHitSlopPad,
  right: actionHitSlopPad,
};

const styles = StyleSheet.create({
  container: {
    borderRadius: radius.md,
    padding: space[3],
  },
  message: {
    marginBottom: space[1],
  },
  actions: {
    flexDirection: "row",
    justifyContent: "flex-end",
  },
  action: {
    marginStart: space[3],
    minHeight: minTouchTarget,
    justifyContent: "center",
  },
});
