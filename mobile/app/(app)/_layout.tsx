/**
 * (app) group layout — Phase 2's four-tab shell (§8.1, P2-FR-014).
 *
 * Before this task, `(app)/_layout.tsx` did not exist: the group ran on
 * Expo Router's implicit default Stack. `app/index.tsx`'s session gate
 * redirected an active session straight to `/(app)/home`, and settings.tsx
 * was reached with `router.push`/`router.back` on top of it — no tab bar
 * anywhere.
 *
 * `home.tsx` (Phase 1's placeholder) is gone — T-24 deleted it the same
 * commit it built the real `index.tsx`, so there is no `home` route left to
 * register here. `_dev-gallery` is a real, working route outside this
 * task's file list, so it stays exactly as it is — just hidden from the bar
 * (`href: null`) because §8.1 names exactly four tabs: index, plan,
 * progress, settings. `plan` and `progress` are this task's own
 * placeholders (T-25/T-26 replace them with the real screens).
 *
 * Tab icons: `@expo/vector-icons` does not resolve in this project (checked
 * mobile/node_modules/@expo/vector-icons and expo/node_modules/@expo/
 * vector-icons — neither exists), matching the precedent GTextInput's eye
 * icon already set, so these are hand-drawn from Views, not an icon font.
 */
import { Tabs } from "expo-router";
import { useEffect, useRef } from "react";
import { StyleSheet, View, type ColorValue } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getCalendars } from "expo-localization";

import { getProfile, updateProfile } from "../../src/api/profile";
import { shouldSyncDeviceTimezone } from "../../src/auth/timezoneSync";
import { useSession } from "../../src/auth/useSession";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { space } from "../../src/theme/tokens";

/**
 * Sends the device's real IANA zone the first time it's still the server
 * default (§4.2's ownership note). An account that already carries a real
 * zone — whether a previous run of this same sync, or a manual Settings
 * edit — never has it overwritten; `shouldSyncDeviceTimezone` (unit-tested
 * in src/auth/timezoneSync.test.ts) is what guarantees that.
 */
function useSyncDeviceTimezone(): void {
  const { user } = useSession();
  const queryClient = useQueryClient();
  const attempted = useRef(false);
  const profileQuery = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
    enabled: user !== null,
  });

  useEffect(() => {
    if (attempted.current || !profileQuery.data) return;

    const deviceTimezone = getCalendars()[0]?.timeZone;
    if (!deviceTimezone) return;
    if (!shouldSyncDeviceTimezone({ storedTimezone: profileQuery.data.timezone, deviceTimezone })) {
      return;
    }

    attempted.current = true;
    updateProfile({ timezone: deviceTimezone })
      .then((updated) => queryClient.setQueryData(["profile"], updated))
      .catch(() => {
        // Leave it eligible to retry on the next successful profile fetch —
        // a dropped connection here shouldn't cost the account its one shot
        // at a correct streak.
        attempted.current = false;
      });
  }, [profileQuery.data, queryClient]);
}

type TabIconName = "home" | "plan" | "progress" | "settings";

function TabIcon({ name, color }: { name: TabIconName; color: ColorValue }) {
  return (
    <View
      style={iconStyles.box}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      {name === "home" ? (
        <>
          <View style={[iconStyles.homeRoof, { borderBottomColor: color }]} />
          <View style={[iconStyles.homeBase, { borderColor: color }]} />
        </>
      ) : null}
      {name === "plan" ? (
        <View style={[iconStyles.planBoard, { borderColor: color }]}>
          <View style={[iconStyles.planLine, { backgroundColor: color, width: "100%" }]} />
          <View style={[iconStyles.planLine, { backgroundColor: color, width: "70%" }]} />
          <View style={[iconStyles.planLine, { backgroundColor: color, width: "85%" }]} />
        </View>
      ) : null}
      {name === "progress" ? (
        <View style={iconStyles.progressRow}>
          <View style={[iconStyles.progressBar, { height: 8, backgroundColor: color }]} />
          <View style={[iconStyles.progressBar, { height: 14, backgroundColor: color }]} />
          <View style={[iconStyles.progressBar, { height: 20, backgroundColor: color }]} />
        </View>
      ) : null}
      {name === "settings" ? (
        <View style={iconStyles.settingsColumn}>
          {[0.3, 0.65, 0.45].map((position, index) => (
            <View key={index} style={[iconStyles.sliderTrack, { backgroundColor: color }]}>
              <View
                style={[iconStyles.sliderKnob, { backgroundColor: color, start: `${position * 100}%` }]}
              />
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

export default function AppTabsLayout() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  useSyncDeviceTimezone();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.primary,
        tabBarInactiveTintColor: theme.textMuted,
        tabBarStyle: {
          backgroundColor: theme.navBg,
          borderTopColor: theme.border,
          borderTopWidth: StyleSheet.hairlineWidth,
        },
        tabBarLabelStyle: textStyle("caption", locale),
        tabBarItemStyle: { paddingVertical: space[1] },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: t("nav.home"),
          tabBarAccessibilityLabel: t("nav.home"),
          tabBarIcon: ({ color }) => <TabIcon name="home" color={color} />,
        }}
      />
      <Tabs.Screen
        name="plan"
        options={{
          title: t("nav.plan"),
          tabBarAccessibilityLabel: t("nav.plan"),
          tabBarIcon: ({ color }) => <TabIcon name="plan" color={color} />,
        }}
      />
      <Tabs.Screen
        name="progress"
        options={{
          title: t("nav.progress"),
          tabBarAccessibilityLabel: t("nav.progress"),
          tabBarIcon: ({ color }) => <TabIcon name="progress" color={color} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: t("nav.settings"),
          tabBarAccessibilityLabel: t("nav.settings"),
          tabBarIcon: ({ color }) => <TabIcon name="settings" color={color} />,
        }}
      />
      <Tabs.Screen name="_dev-gallery" options={{ href: null }} />
    </Tabs>
  );
}

const iconStyles = StyleSheet.create({
  box: { width: 22, height: 22, alignItems: "center", justifyContent: "center" },
  homeRoof: {
    width: 0,
    height: 0,
    borderLeftWidth: 11,
    borderRightWidth: 11,
    borderBottomWidth: 9,
    borderLeftColor: "transparent",
    borderRightColor: "transparent",
  },
  homeBase: {
    width: 16,
    height: 10,
    borderWidth: 2,
  },
  planBoard: {
    width: 18,
    height: 20,
    borderWidth: 2,
    borderRadius: 3,
    padding: 3,
    justifyContent: "center",
    gap: 3,
  },
  planLine: { height: 2, borderRadius: 1 },
  progressRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    width: 22,
    height: 20,
  },
  progressBar: { width: 4, borderRadius: 1 },
  settingsColumn: { width: 20, height: 20, justifyContent: "space-between" },
  sliderTrack: { height: 2, borderRadius: 1, justifyContent: "center" },
  sliderKnob: { position: "absolute", width: 6, height: 6, borderRadius: 3, top: -2 },
});
