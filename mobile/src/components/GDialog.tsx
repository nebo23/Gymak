/**
 * §9.2 GDialog — `visible`/`onClose`/`titleKey`/`bodyKey`/`actions`. The in-app
 * replacement for `Alert.alert`.
 *
 * Why this component exists at all: `Alert.alert` does not render a React
 * component. It calls the platform's own dialog, which is styled by the OS —
 * it ignores `tokens.ts`, ignores the Cairo font, ignores the app's own
 * light/dark choice, and lays its buttons out LTR regardless of the app's RTL
 * direction. No amount of styling reaches it, so the only fix is to stop
 * calling it. Everything below is ordinary RN, themed like every other
 * primitive.
 *
 * Modelled on `GSheet`, which already solves the overlay, the focus trap and
 * dismissal: RN's `Modal` renders in its own native presentation layer on both
 * platforms, which is what traps focus and hides the background from screen
 * readers; `accessibilityViewIsModal` covers VoiceOver.
 *
 * Two deliberate departures from the sketch this was specced from:
 *
 * 1. `actions` accepts up to THREE, not two. The unsent-sets dialog in
 *    `workout/active.tsx` has always offered cancel / retry-all / discard, and
 *    the conversion was required to preserve "same actions, same consequences".
 *    A two-action cap would have meant silently dropping a destructive choice,
 *    so the cap yields to behaviour preservation. Three always stacks.
 * 2. Buttons are built here rather than reusing `GButton`, which pins
 *    `numberOfLines={1}` and a fixed `controlHeight`. That clips a long Arabic
 *    label — one of the things being fixed — so these labels wrap and the row
 *    stacks when they do.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
  findNodeHandle,
  type NativeSyntheticEvent,
  type TextLayoutEventData,
} from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import type { Theme } from "../theme/tokens";
import { textStyle } from "../theme/typography";
import { minTouchTarget, radius, screenPadding, space } from "../theme/tokens";

export type GDialogActionVariant = "primary" | "secondary" | "destructive";

export interface GDialogAction {
  labelKey: string;
  onPress: () => void;
  variant?: GDialogActionVariant;
  testID?: string;
}

export interface GDialogProps {
  visible: boolean;
  onClose: () => void;
  titleKey: string;
  bodyKey?: string;
  /** Interpolation values for `bodyKey` (e.g. `{ count }`). Never display text. */
  bodyParams?: Record<string, unknown>;
  /** One to three. Three always stacks vertically. */
  actions: readonly GDialogAction[];
  /**
   * Scrim tap and Android back dismiss the dialog. Set `false` where dismissal
   * would lose data, so the caller must make an explicit choice.
   */
  dismissible?: boolean;
  testID?: string;
}

interface ActionColors {
  backgroundColor: string;
  borderColor: string;
  borderWidth: number;
  textColor: string;
}

function colorsFor(theme: Theme, variant: GDialogActionVariant): ActionColors {
  switch (variant) {
    case "primary":
      return {
        backgroundColor: theme.primary,
        borderColor: theme.primary,
        borderWidth: 0,
        textColor: theme.onPrimary,
      };
    case "destructive":
      // §10.5's "never opacity alone" applies to tone too: a destructive action
      // reads as destructive through the `error` token, not through a dimmed
      // primary. Outlined rather than filled so it never out-weighs the safe
      // choice next to it.
      return {
        backgroundColor: "transparent",
        borderColor: theme.error,
        borderWidth: 1,
        textColor: theme.error,
      };
    case "secondary":
    default:
      return {
        backgroundColor: "transparent",
        borderColor: theme.border,
        borderWidth: 1,
        textColor: theme.textPrimary,
      };
  }
}

export function GDialog({
  visible,
  onClose,
  titleKey,
  bodyKey,
  bodyParams,
  actions,
  dismissible = true,
  testID,
}: GDialogProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const titleRef = useRef<Text>(null);
  const [stacked, setStacked] = useState(false);

  // Three actions never fit side by side legibly; stack without measuring.
  const forceStack = actions.length > 2;

  useEffect(() => {
    if (!visible) setStacked(false);
  }, [visible]);

  /**
   * Entry point of the focus trap. Focus lands on the TITLE, never on an
   * action — which is what keeps a destructive action from being the
   * default-focused control, as well as reading the question before the
   * answers.
   */
  useEffect(() => {
    if (!visible) return;
    const handle = findNodeHandle(titleRef.current);
    if (handle !== null) AccessibilityInfo.setAccessibilityFocus(handle);
  }, [visible]);

  /**
   * A label that wraps is the signal to stack: at that point a horizontal row
   * would clip or overlap, which is exactly what the OS dialog's fixed row did
   * to long Arabic labels. Latches on — it never unsets while open, so the
   * layout cannot oscillate between row and column.
   */
  const onLabelLayout = useCallback((e: NativeSyntheticEvent<TextLayoutEventData>) => {
    if (e.nativeEvent.lines.length > 1) setStacked(true);
  }, []);

  const handleScrim = dismissible ? onClose : undefined;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      // Android hardware back. RN requires the prop; when the dialog is not
      // dismissible it is a no-op so back cannot discard the pending choice.
      onRequestClose={dismissible ? onClose : () => {}}
      statusBarTranslucent
      testID={testID}
    >
      <View style={styles.wrapper} accessibilityViewIsModal>
        <Pressable
          style={[styles.overlay, { backgroundColor: theme.overlay }]}
          onPress={handleScrim}
          disabled={!dismissible}
          accessibilityRole="button"
          accessibilityLabel={t("common.dismiss")}
          importantForAccessibility={dismissible ? "yes" : "no-hide-descendants"}
        />
        <View
          style={[
            styles.panel,
            {
              backgroundColor: theme.surface,
              shadowColor: theme.shadowMd.color,
              shadowOffset: { width: 0, height: theme.shadowMd.offsetY },
              shadowRadius: theme.shadowMd.blurRadius,
            },
          ]}
        >
          <Text
            ref={titleRef}
            accessibilityRole="header"
            style={[textStyle("h3", locale), styles.title, { color: theme.textPrimary }]}
          >
            {t(titleKey)}
          </Text>
          {bodyKey !== undefined ? (
            <Text style={[textStyle("body", locale), styles.body, { color: theme.textSecondary }]}>
              {t(bodyKey, bodyParams)}
            </Text>
          ) : null}
          <View style={stacked || forceStack ? styles.actionsColumn : styles.actionsRow}>
            {actions.map((action) => {
              const variant = action.variant ?? "secondary";
              const colors = colorsFor(theme, variant);
              const label = t(action.labelKey);
              return (
                <Pressable
                  key={action.labelKey}
                  testID={action.testID}
                  onPress={action.onPress}
                  accessibilityRole="button"
                  accessibilityLabel={label}
                  style={({ pressed }) => [
                    styles.action,
                    stacked || forceStack ? styles.actionStacked : styles.actionInline,
                    {
                      backgroundColor: colors.backgroundColor,
                      borderColor: colors.borderColor,
                      borderWidth: colors.borderWidth,
                      opacity: pressed ? 0.9 : 1,
                    },
                  ]}
                >
                  <Text
                    onTextLayout={onLabelLayout}
                    style={[
                      textStyle("bodyStrong", locale),
                      styles.actionLabel,
                      { color: colors.textColor },
                    ]}
                  >
                    {label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: screenPadding,
  },
  overlay: {
    position: "absolute",
    top: 0,
    start: 0,
    end: 0,
    bottom: 0,
  },
  panel: {
    width: "100%",
    maxWidth: 420, // one-off geometry: a dialog wider than this on a tablet
    // reads as a page, not a dialog. Not a token because nothing else needs it.
    borderRadius: radius.lg,
    padding: space[4],
    // Android elevation has no token; it mirrors shadowMd's blur.
    elevation: 6,
    shadowOpacity: 1,
  },
  title: {
    marginBottom: space[1],
    // RN's textAlign has no "start"; "auto" is the RTL-correct value -- it
    // resolves to the reader's start edge. Never a hardcoded left/right.
    textAlign: "auto",
  },
  body: {
    marginBottom: space[4],
    textAlign: "auto",
  },
  actionsRow: {
    // Under `I18nManager.forceRTL` a plain row flips on its own, so the last
    // action sits at the reader's end -- the left in Arabic, which is where an
    // Arabic reader expects the confirming action and is not where the OS
    // dialog put it.
    flexDirection: "row",
    justifyContent: "flex-end",
  },
  actionsColumn: {
    flexDirection: "column",
  },
  action: {
    // minHeight, not height: a wrapped two-line label must grow the button
    // rather than clip inside it. Always >= the 48dp touch target.
    // Both dimensions, not just height: a short label ("OK") must still be a
    // 48dp target in the inline row.
    minHeight: minTouchTarget,
    minWidth: minTouchTarget,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: space[3],
    paddingVertical: space[1],
  },
  actionInline: {
    marginStart: space[2],
    flexShrink: 1,
  },
  actionStacked: {
    marginTop: space[2],
    alignSelf: "stretch",
  },
  actionLabel: {
    textAlign: "center",
  },
});
