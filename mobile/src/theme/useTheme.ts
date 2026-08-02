/**
 * Follows the OS colour scheme (§10.3's light/dark split), re-deriving on
 * every OS-level change rather than reading it once at startup.
 *
 * Named `useTheme.ts`, not `.tsx`, per the T-10 file list — `ThemeProvider`
 * is therefore built with `React.createElement` rather than JSX syntax,
 * which `.ts` cannot parse.
 */
import { createContext, createElement, useContext, useMemo, type ReactNode } from "react";
import { useColorScheme } from "react-native";

import { DarkTheme, LightTheme, type Theme } from "./tokens";

const ThemeContext = createContext<Theme>(LightTheme);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const scheme = useColorScheme();
  const theme = useMemo(() => (scheme === "dark" ? DarkTheme : LightTheme), [scheme]);
  return createElement(ThemeContext.Provider, { value: theme }, children);
}

export function useTheme(): Theme {
  return useContext(ThemeContext);
}
