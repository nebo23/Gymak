/**
 * Resolves the active theme from the user's three-way preference (§10.3's
 * light/dark split), falling back to the OS colour scheme in `system` mode and
 * re-deriving on every OS-level change — but only in that mode; `light` and
 * `dark` are forced and ignore the OS.
 *
 * FIRST PAINT
 * The stored preference is read SYNCHRONOUSLY, in the `useState` initialiser
 * below, so it is known before the provider's first render and therefore
 * before anything paints. `expo-secure-store` 57 exposes a synchronous
 * `getItem`/`setItem` alongside the async pair, which is what makes this
 * possible without holding the splash for a tick or flashing the wrong theme
 * while an async read settles.
 *
 * STORAGE: WHY SECURESTORE FOR A NON-SECRET
 * A theme preference is NOT a secret and SecureStore is nominally for secrets.
 * It is used here anyway because §A.2 forbids adding a dependency and
 * `expo-secure-store` is the only key-value store installed — AsyncStorage and
 * friends are not, and adding one is not permitted. This is the honest choice
 * available rather than the ideal one; if a plain key-value store is ever added
 * to the dependency list, this should move to it. Note that `src/auth/storage.ts`
 * remains the only module allowed to touch SecureStore *for tokens* — this key
 * is not a token and is namespaced away from them.
 *
 * Named `useTheme.ts`, not `.tsx`, per the T-10 file list — the providers are
 * therefore built with `React.createElement` rather than JSX syntax, which
 * `.ts` cannot parse.
 */
import { createContext, createElement, useContext, useMemo, useState, type ReactNode } from "react";
import { useColorScheme } from "react-native";
import * as SecureStore from "expo-secure-store";

import { DarkTheme, LightTheme, type Theme } from "./tokens";
import {
  DEFAULT_THEME_PREFERENCE,
  THEME_PREFERENCE_KEY,
  parseThemePreference,
  resolveScheme,
  type ThemePreference,
} from "./themePreference";

/**
 * A SecureStore read can throw if the native module is unavailable (a bare web
 * bundle, a test runner). The preference is a convenience, never a
 * correctness-critical value, so a failure falls back to `system` — the exact
 * behaviour the app had before the preference existed — rather than breaking
 * the render.
 */
function readStoredPreference(): ThemePreference {
  try {
    return parseThemePreference(SecureStore.getItem(THEME_PREFERENCE_KEY));
  } catch {
    return DEFAULT_THEME_PREFERENCE;
  }
}

function writeStoredPreference(preference: ThemePreference): void {
  try {
    SecureStore.setItem(THEME_PREFERENCE_KEY, preference);
  } catch {
    // Persisting failed; the in-memory choice below still applies for this
    // run, so the user's tap is not silently ignored.
  }
}

export interface ThemePreferenceValue {
  preference: ThemePreference;
  setPreference: (next: ThemePreference) => void;
}

const ThemeContext = createContext<Theme>(LightTheme);

const ThemePreferenceContext = createContext<ThemePreferenceValue>({
  preference: DEFAULT_THEME_PREFERENCE,
  setPreference: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const osScheme = useColorScheme();
  // Lazy initialiser: runs once, during the first render, before first paint.
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference);

  const theme = useMemo(
    () => (resolveScheme(preference, osScheme) === "dark" ? DarkTheme : LightTheme),
    [preference, osScheme],
  );

  const preferenceValue = useMemo<ThemePreferenceValue>(
    () => ({
      preference,
      // State first, so the new theme is on screen this frame — no restart, no
      // reload. The language selector needs a reload because flipping RTL/LTR
      // genuinely requires one; swapping a palette does not, so nothing here
      // prompts for one.
      setPreference: (next: ThemePreference) => {
        setPreferenceState(next);
        writeStoredPreference(next);
      },
    }),
    [preference],
  );

  return createElement(
    ThemePreferenceContext.Provider,
    { value: preferenceValue },
    createElement(ThemeContext.Provider, { value: theme }, children),
  );
}

export function useTheme(): Theme {
  return useContext(ThemeContext);
}

export function useThemePreference(): ThemePreferenceValue {
  return useContext(ThemePreferenceContext);
}
