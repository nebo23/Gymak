/**
 * Placeholder for the (app) stack. Real home (§9.3 #14) is T-14's job.
 */
import { StyleSheet, Text, View } from "react-native";

import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { space } from "../../src/theme/tokens";

export default function HomePlaceholder() {
  const theme = useTheme();
  const { t, locale } = useI18n();

  return (
    <View style={[styles.container, { backgroundColor: theme.bg }]}>
      <Text style={[textStyle("h1", locale), { color: theme.textPrimary }]}>
        {t("placeholder.app.title")}
      </Text>
      <Text
        style={[
          textStyle("body", locale),
          { color: theme.textSecondary, marginTop: space[2] },
        ]}
      >
        {t("placeholder.app.body")}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: space[4],
  },
});
