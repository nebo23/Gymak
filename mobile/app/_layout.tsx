/**
 * Root layout: wires QueryClient, i18n and theme (§9.2's provider stack,
 * minus `SessionProvider` — the session gate is T-12's job, not this one).
 *
 * Renders nothing until the two locked-in fonts (Inter, Cairo — see the T-10
 * report) have loaded, so no screen ever flashes an OS-substituted fallback
 * face before swapping to the real one.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Slot } from "expo-router";
import { View } from "react-native";

import { I18nProvider } from "../src/i18n";
import { ThemeProvider, useTheme } from "../src/theme/useTheme";
import { useAppFonts } from "../src/theme/typography";

const queryClient = new QueryClient();

function AppShell() {
  const theme = useTheme();
  const fontsLoaded = useAppFonts();

  if (!fontsLoaded) {
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
