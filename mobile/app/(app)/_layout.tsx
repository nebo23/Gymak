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
 * Tab icons: real SVG paths via `GIcon`. They were four hand-built stacks of
 * bordered `<View>`s until the UI pass — a CSS-triangle roof on a bordered
 * square for home, three bars of height 8/14/20 for progress — drawn at four
 * different extents with no shared stroke. `@expo/vector-icons` still does not
 * resolve here and no dependency was added: `react-native-svg` was already
 * installed for GLineChart. See src/components/GIcon.tsx for the grid and the
 * stroke ramp.
 */
import { Tabs } from "expo-router";
import { useEffect, useRef } from "react";
import { StyleSheet } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getCalendars } from "expo-localization";

import { getProfile, updateProfile } from "../../src/api/profile";
import { shouldSyncDeviceTimezone } from "../../src/auth/timezoneSync";
import { useSession } from "../../src/auth/useSession";
import { GIcon } from "../../src/components";
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
          tabBarIcon: ({ color }) => <GIcon name="home" color={color} />,
        }}
      />
      <Tabs.Screen
        name="plan"
        options={{
          title: t("nav.plan"),
          tabBarAccessibilityLabel: t("nav.plan"),
          tabBarIcon: ({ color }) => <GIcon name="plan" color={color} />,
        }}
      />
      <Tabs.Screen
        name="progress"
        options={{
          title: t("nav.progress"),
          tabBarAccessibilityLabel: t("nav.progress"),
          tabBarIcon: ({ color }) => <GIcon name="progress" color={color} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: t("nav.settings"),
          tabBarAccessibilityLabel: t("nav.settings"),
          tabBarIcon: ({ color }) => <GIcon name="settings" color={color} />,
        }}
      />
      {/* T-26: §8.1 presents the active session "outside the tabs" -- not a
          tab button (`href: null`, same as _dev-gallery below) and, per
          device check 4, with the tab bar itself hidden while it's focused.
          `tabBarStyle` is read from the *focused* screen's own options, so
          setting it here -- rather than in the shared `screenOptions` above
          -- only hides the bar on this one screen, not every tab. */}
      <Tabs.Screen
        name="workout/active"
        options={{ href: null, tabBarStyle: { display: "none" } }}
      />
      {/* T-26 found this live: plan/[dayId] is a sibling route under plan/,
          not nested behind its own _layout.tsx, so Tabs auto-adds it as a
          fifth bar item labelled with the raw route name unless excluded
          here -- exactly like workout/active above. Latent since T-25 (which
          had no device/emulator available to catch it); fixed here because
          this task already touches this file and a stray untranslated tab
          on every single screen would fail device check 4 on its own. */}
      <Tabs.Screen name="plan/[dayId]" options={{ href: null }} />
      {/* T-27: same reason as plan/[dayId] above -- history.tsx is a sibling
          route directly under (app)/, so Tabs auto-adds it as a fifth bar
          item unless excluded. §8.1 names exactly four tabs, so it is
          excluded here; §8.2 never names where history is reached from, so
          this is deliberately *only* a tab-bar exclusion, not a claim that
          any screen links here yet -- see T-27's own report. */}
      <Tabs.Screen name="history" options={{ href: null }} />
      <Tabs.Screen name="workout/[id]" options={{ href: null }} />
      {/* T-29: same reason as plan/[dayId] and history above -- exercises/index.tsx
          and exercises/[id].tsx are sibling routes directly under (app)/exercises/,
          so Tabs auto-adds each as its own fifth/sixth bar item (labelled from the
          raw route name) unless excluded here. §8.1 lists the library as a
          full-screen route reached "from plan and from the active session", not a
          tab, so both are excluded the same way workout/active is. `index.tsx`
          collapses to its directory's own name for route-registration purposes --
          matching this file's own "plan" entry above, which is plan/index.tsx, not
          "plan/index" -- so the list screen is named "exercises" here, not
          "exercises/index". */}
      <Tabs.Screen name="exercises" options={{ href: null }} />
      <Tabs.Screen name="exercises/[id]" options={{ href: null }} />
      <Tabs.Screen name="_dev-gallery" options={{ href: null }} />
    </Tabs>
  );
}
