/**
 * §9.2 GEmptyState — `titleKey`/`bodyKey`/`actionLabelKey?`. Never renders
 * raw text: unlike every other primitive, which takes pre-resolved strings,
 * this one takes i18n keys and resolves them itself (the same shape
 * `GErrorBanner` uses for `code`), because §8.5 says every empty state names
 * one concrete action, and that action is only ever a translated key, never
 * a caller-built string.
 */
import { StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { space } from "../theme/tokens";
import { GButton } from "./GButton";

export interface GEmptyStateProps {
  titleKey: string;
  bodyKey: string;
  actionLabelKey?: string;
  onAction?: () => void;
  testID?: string;
}

export function GEmptyState({
  titleKey,
  bodyKey,
  actionLabelKey,
  onAction,
  testID,
}: GEmptyStateProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();

  return (
    <View style={styles.container} testID={testID}>
      <Text style={[textStyle("h3", locale), styles.title, { color: theme.textPrimary }]}>
        {t(titleKey)}
      </Text>
      <Text style={[textStyle("body", locale), styles.body, { color: theme.textSecondary }]}>
        {t(bodyKey)}
      </Text>
      {actionLabelKey && onAction ? (
        <GButton
          label={t(actionLabelKey)}
          onPress={onAction}
          testID={testID ? `${testID}-action` : undefined}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    paddingVertical: space[6],
    paddingHorizontal: space[4],
  },
  title: {
    textAlign: "center",
  },
  body: {
    textAlign: "center",
    marginTop: space[1],
    marginBottom: space[4],
  },
});
