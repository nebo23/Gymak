/**
 * The three-way theme preference: `system` (default), `light`, `dark`.
 *
 * WHY THIS IS LOCAL AND NOT ON THE PROFILE
 * `language` and `unit_system` live on the profile because they are genuinely
 * account-level — the same person wants the same language and the same units
 * on every device they sign in from. A theme is not that. The conventional
 * expectation is per-device: the same account on a phone at night and a tablet
 * in daylight legitimately wants different answers. A profile field would also
 * mean a migration plus a network round trip before the theme could resolve,
 * which shows up as a flash of the wrong theme on every cold start. So this is
 * stored on the device and never sent to the server.
 *
 * This module is deliberately free of React and of `expo-secure-store`, so the
 * resolution rules below are plain functions that vitest can import and check
 * without a native runtime (see `themePreference.test.ts`). The storage and
 * the hook live in `useTheme.ts`.
 */

export type ThemePreference = "system" | "light" | "dark";

/** The order the Settings control renders them in. */
export const THEME_PREFERENCES: readonly ThemePreference[] = ["system", "light", "dark"];

export const DEFAULT_THEME_PREFERENCE: ThemePreference = "system";

/**
 * SecureStore key. Namespaced like the token keys in `src/auth/storage.ts` so
 * the device's keystore stays legible, but deliberately under `gymak.theme.`
 * rather than `gymak.session.` — this is not session state and must survive a
 * log out, which clears everything under `gymak.session.`.
 */
export const THEME_PREFERENCE_KEY = "gymak.theme.preference";

/**
 * Anything that is not one of the three known values — a missing key on first
 * launch, a value written by a future version, a corrupted entry — resolves to
 * `system`, which is exactly the behaviour the app had before this preference
 * existed. There is no failure mode here that leaves the user without a theme.
 */
export function parseThemePreference(raw: string | null | undefined): ThemePreference {
  return raw === "light" || raw === "dark" || raw === "system" ? raw : DEFAULT_THEME_PREFERENCE;
}

/**
 * Mirrors React Native's `ColorSchemeName` without importing it, so this module
 * stays runtime-free and node-testable. `"unspecified"` and `null` are both
 * real values `useColorScheme()` returns when the OS has not reported a scheme.
 */
export type OsColorScheme = "light" | "dark" | "unspecified" | null | undefined;

/**
 * `system` defers to the OS scheme; anything the OS has not actually reported
 * as dark falls to light, as it did before this preference existed.
 * `light`/`dark` are forced and ignore the OS entirely, which is the property
 * that makes an OS-level change a no-op in those two modes.
 */
export function resolveScheme(
  preference: ThemePreference,
  osScheme: OsColorScheme,
): "light" | "dark" {
  if (preference === "light" || preference === "dark") return preference;
  return osScheme === "dark" ? "dark" : "light";
}
