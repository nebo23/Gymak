/**
 * §10.5 GScreen — SafeArea, keyboard-avoiding, scroll-on-overflow, standard
 * padding, optional header with a back affordance.
 */
import type { ReactNode } from "react";
import {
  I18nManager,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { minTouchTarget, screenPadding, space } from "../theme/tokens";

export interface GScreenHeader {
  title: string;
  onBack?: () => void;
}

export interface GScreenProps {
  children: ReactNode;
  header?: GScreenHeader;
  footer?: ReactNode;
  scroll?: boolean;
  testID?: string;
}

export function GScreen({ children, header, footer, scroll = true, testID }: GScreenProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const Content = scroll ? ScrollView : View;
  const contentProps = scroll
    ? { contentContainerStyle: styles.scrollContent, keyboardShouldPersistTaps: "handled" as const }
    : { style: styles.plainContent };

  return (
    <SafeAreaView style={[styles.safeArea, { backgroundColor: theme.bg }]} testID={testID}>
      {header ? (
        <View style={styles.header}>
          {header.onBack ? (
            <Pressable
              onPress={header.onBack}
              accessibilityRole="button"
              accessibilityLabel={t("common.back")}
              style={styles.backButton}
            >
              {/* A back chevron implies direction, so — unlike the OTP boxes
                  or the logo — it must mirror under RTL (§9.6). */}
              <Text
                style={[
                  textStyle("h2", locale),
                  { color: theme.textPrimary },
                  I18nManager.isRTL ? styles.chevronRTL : null,
                ]}
              >
                {"‹"}
              </Text>
            </Pressable>
          ) : (
            <View style={styles.backButtonSpacer} />
          )}
          <Text
            style={[textStyle("h3", locale), styles.headerTitle, { color: theme.textPrimary }]}
            numberOfLines={1}
          >
            {header.title}
          </Text>
          <View style={styles.backButtonSpacer} />
        </View>
      ) : null}
      <KeyboardAvoidingView
        style={styles.flexContent}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <Content {...contentProps}>{children}</Content>
      </KeyboardAvoidingView>
      {footer ? <View style={styles.footer}>{footer}</View> : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  flexContent: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
    paddingHorizontal: screenPadding,
    paddingTop: space[3],
    paddingBottom: space[5],
  },
  plainContent: {
    flex: 1,
    paddingHorizontal: screenPadding,
    paddingTop: space[3],
    paddingBottom: space[5],
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: space[2],
    minHeight: minTouchTarget,
  },
  backButton: {
    minWidth: minTouchTarget,
    minHeight: minTouchTarget,
    alignItems: "center",
    justifyContent: "center",
  },
  backButtonSpacer: {
    minWidth: minTouchTarget,
  },
  chevronRTL: {
    transform: [{ scaleX: -1 }],
  },
  headerTitle: {
    flex: 1,
    textAlign: "center",
  },
  footer: {
    paddingHorizontal: screenPadding,
    paddingBottom: space[4],
  },
});
