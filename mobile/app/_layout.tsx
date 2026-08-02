/**
 * Root layout: wires QueryClient, i18n, theme and the session gate (§9.2's
 * provider stack).
 *
 * Renders nothing until the two locked-in fonts (Inter, Cairo — see the T-10
 * report) have loaded, and nothing routable until §9.2's boot sequence
 * resolves: SecureStore is read, and — if a session was found — GET
 * /auth/me is awaited. `<Slot />`, and therefore app/index.tsx's redirect,
 * only mounts once that is done, so a signed-in user never sees the login
 * screen flash.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Slot } from "expo-router";
import { useEffect } from "react";
import { View } from "react-native";

import { useSessionStore } from "../src/auth/session";
import { I18nProvider } from "../src/i18n";
import { ThemeProvider, useTheme } from "../src/theme/useTheme";
import { useAppFonts } from "../src/theme/typography";

const queryClient = new QueryClient();

function AppShell() {
  const theme = useTheme();
  const fontsLoaded = useAppFonts();
  const sessionStatus = useSessionStore((state) => state.status);

  useEffect(() => {
    void useSessionStore.getState().hydrate();
  }, []);

  if (!fontsLoaded || sessionStatus === "booting") {
    return <View style={{ flex: 1, backgroundColor: theme.bg }} />;
  }

  return <Slot />;
}

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ThemeProvider>
          <AppShell />
        </ThemeProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
