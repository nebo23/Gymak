/**
 * §9.2 GSheet — `visible`/`onClose`/`children`. Bottom sheet for the
 * exercise picker and the log-weight form (later tasks). Built on RN's
 * `Modal`, which already renders in its own native presentation layer on
 * both platforms — the standard way a modal traps focus and hides the
 * background from screen readers, no extra wiring needed beyond
 * `accessibilityViewIsModal` for VoiceOver. Dismissible by backdrop tap and
 * by the hardware back button (`onRequestClose`); `overlay` token behind.
 */
import type { ReactNode } from "react";
import { Modal, Pressable, StyleSheet, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { radius, screenPadding, space } from "../theme/tokens";

export interface GSheetProps {
  visible: boolean;
  onClose: () => void;
  children: ReactNode;
  testID?: string;
}

export function GSheet({ visible, onClose, children, testID }: GSheetProps) {
  const theme = useTheme();
  const { t } = useI18n();

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent
      testID={testID}
    >
      <View style={styles.wrapper} accessibilityViewIsModal>
        <Pressable
          style={[styles.overlay, { backgroundColor: theme.overlay }]}
          onPress={onClose}
          accessibilityRole="button"
          accessibilityLabel={t("common.dismiss")}
        />
        <View style={[styles.sheet, { backgroundColor: theme.surface }]}>
          <View style={styles.handleRow}>
            <View style={[styles.handle, { backgroundColor: theme.border }]} />
          </View>
          {children}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    flex: 1,
    justifyContent: "flex-end",
  },
  overlay: {
    position: "absolute",
    top: 0,
    start: 0,
    end: 0,
    bottom: 0,
  },
  sheet: {
    borderTopStartRadius: radius.xl,
    borderTopEndRadius: radius.xl,
    paddingHorizontal: screenPadding,
    paddingTop: space[2],
    paddingBottom: space[6],
    maxHeight: "85%",
  },
  handleRow: {
    alignItems: "center",
    paddingVertical: space[2],
  },
  // The grabber is a drawn affordance, not an icon: 36x4 is the bar itself,
  // one-off geometry in the same sense as an SVG path. It carries no meaning at
  // another size and nothing else in the app reuses it, so it stays literal.
  handle: {
    width: 36,
    height: 4,
    borderRadius: radius.pill,
  },
});
