/**
 * Placeholder for the (auth) stack. The real welcome screen (§9.3 #1) is
 * T-13's job — this exists only so the route group has something to render
 * and the three-stack boot requirement is checkable now.
 */
import { StyleSheet, Text, View } from "react-native";

import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { space } from "../../src/theme/tokens";

export default function WelcomePlaceholder() {
  const theme = useTheme();
  const { t, locale } = useI18n();

  return (
    <View style={[styles.container, { backgroundColor: theme.bg }]}>
      <Text style={[textStyle("h1", locale), { color: theme.textPrimary }]}>
        {t("placeholder.auth.title")}
      </Text>
      <Text
        style={[
          textStyle("body", locale),
          { color: theme.textSecondary, marginTop: space[2] },
        ]}
      >
        {t("placeholder.auth.body")}
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
