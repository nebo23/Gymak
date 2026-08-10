/**
 * §10.5 GErrorBanner — localised message from an error `code`, optional
 * retry, dismissible. Announced on appearance (§10.6: errors are announced,
 * not only coloured — the start-side accent border carries the same meaning
 * structurally, so colour is never the only signal).
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
      style={[styles.container, { backgroundColor: theme.errorBg, borderStartColor: theme.error }]}
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
    >
      <Text style={[textStyle("label", locale), styles.message, { color: theme.error }]}>
        {resolved}
      </Text>
      {onRetry || onDismiss ? (
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
              <Text style={[styles.dismissGlyph, { color: theme.error }]}>✕</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

// The retry/dismiss controls are visually compact; hit-slop brings each
// one's effective touch area up to the §10.6 floor — the same pattern
// GTextInput's toggleHitSlop uses.
const actionVisualSize = 20;
const actionHitSlopPad = Math.max(0, (minTouchTarget - actionVisualSize) / 2);
const actionHitSlop = {
  top: actionHitSlopPad,
  bottom: actionHitSlopPad,
  left: actionHitSlopPad,
  right: actionHitSlopPad,
};

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    gap: space[3],
    borderRadius: radius.sm,
    borderStartWidth: 3,
    paddingVertical: space[2],
    paddingHorizontal: space[3],
  },
  message: {
    flex: 1,
  },
  actions: {
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
  },
  action: {
    paddingVertical: space[1],
  },
  dismissGlyph: {
    fontSize: 16,
    lineHeight: 20,
  },
});
