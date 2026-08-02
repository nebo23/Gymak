/**
 * §9.3 screen 14 — home [placeholder]. A name greeting and an honest panel
 * stating the training plan arrives in a later phase — explicitly no fake
 * data, no placeholder charts, no dummy workout cards (§1.2 is unambiguous
 * that workouts/programmes are out of scope for Phase 1 entirely).
 */
import { useQuery } from "@tanstack/react-query";
import { router } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import { getProfile } from "../../src/api/profile";
import { resolveErrorCode } from "../../src/api/errors";
import { useSession } from "../../src/auth/useSession";
import { GButton, GErrorBanner, GScreen } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { radius, space } from "../../src/theme/tokens";

export default function Home() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const { user } = useSession();

  const profileQuery = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
    enabled: user !== null,
  });

  const name = profileQuery.data?.name;

  return (
    <GScreen>
      <View style={styles.topRow}>
        <GButton
          variant="ghost"
          label={t("home.settingsButton")}
          onPress={() => router.push("/(app)/settings")}
          testID="home-settings"
        />
      </View>

      {profileQuery.isError ? (
        <GErrorBanner
          code={resolveErrorCode(profileQuery.error)}
          onRetry={() => profileQuery.refetch()}
          testID="home-profile-error"
        />
      ) : null}

      <Text style={[textStyle("h1", locale), styles.greeting, { color: theme.textPrimary }]}>
        {name ? t("home.greeting", { name }) : t("home.greetingFallback")}
      </Text>

      <View style={[styles.panel, { backgroundColor: theme.card, borderColor: theme.border }]}>
        <Text style={[textStyle("h3", locale), { color: theme.textPrimary }]}>
          {t("home.planPanelTitle")}
        </Text>
        <Text
          style={[textStyle("body", locale), styles.panelBody, { color: theme.textSecondary }]}
        >
          {t("home.planPanelBody")}
        </Text>
      </View>
    </GScreen>
  );
}

const styles = StyleSheet.create({
  topRow: {
    flexDirection: "row",
    justifyContent: "flex-end",
  },
  greeting: {
    marginTop: space[4],
    marginBottom: space[5],
  },
  panel: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: space[4],
  },
  panelBody: {
    marginTop: space[2],
  },
});
