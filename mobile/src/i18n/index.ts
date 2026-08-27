/**
 * §9.6: Arabic default, English second, identical keys in both catalogues,
 * RTL via I18nManager, and a loud development-mode failure on any gap
 * between them or any request for a key that doesn't exist — never a
 * silently-rendered key name in production (§9.6's own words).
 *
 * i18n-js does the actual interpolation/pluralisation; the missing-key and
 * catalogue-symmetry checks below are ours, not i18n-js's built-in
 * `missingBehavior` — that only fires per lookup, so it cannot catch a key
 * that exists in `en.json` but was simply never added to `ar.json`, which is
 * the more common way this drifts.
 */
import { createContext, createElement, useContext, useMemo, useState, type ReactNode } from "react";
import { getLocales } from "expo-localization";
import { I18nManager } from "react-native";
import { I18n } from "i18n-js";
import * as SecureStore from "expo-secure-store";

import ar from "./ar.json";
import en from "./en.json";
import { PLURAL_CATEGORIES, pluralCandidates } from "./plural";

export type Locale = "ar" | "en";

const catalogs = { ar, en } as const;

const PLURAL_CATEGORY_SET: ReadonlySet<string> = new Set(PLURAL_CATEGORIES);

/**
 * A plural catalogue entry: an object whose keys are *all* CLDR categories,
 * e.g. `{ one: "1 set", other: "{{count}} sets" }`.
 *
 * These must be flattened as one logical key, not one key per category. Arabic
 * legitimately carries up to six categories where English carries two, so a
 * naive leaf walk reports `units.set.two`, `.few` and `.many` as "only in ar"
 * and turns the correct catalogue into a warning — the symmetry check would
 * then cry wolf on every plural string in the app, which is how a useful check
 * gets ignored and then deleted.
 *
 * The `every` is deliberate rather than `some`: a real content object that
 * happened to contain a key named `one` or `other` alongside ordinary keys is
 * not a plural entry and must keep being walked normally.
 */
function isPluralEntry(obj: Record<string, unknown>): boolean {
  const keys = Object.keys(obj);
  return (
    keys.length > 0 &&
    keys.every((k) => PLURAL_CATEGORY_SET.has(k)) &&
    Object.values(obj).every((v) => typeof v === "string")
  );
}

function flattenKeys(obj: unknown, prefix = ""): Set<string> {
  const keys = new Set<string>();
  if (obj === null || typeof obj !== "object") {
    keys.add(prefix);
    return keys;
  }
  if (isPluralEntry(obj as Record<string, unknown>)) {
    keys.add(prefix);
    return keys;
  }
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${k}` : k;
    for (const leaf of flattenKeys(v, path)) keys.add(leaf);
  }
  return keys;
}

if (__DEV__) {
  const arKeys = flattenKeys(ar);
  const enKeys = flattenKeys(en);
  const onlyInAr = [...arKeys].filter((k) => !enKeys.has(k));
  const onlyInEn = [...enKeys].filter((k) => !arKeys.has(k));
  if (onlyInAr.length > 0 || onlyInEn.length > 0) {
    console.warn(
      "[i18n] ar.json and en.json have mismatched keys.",
      onlyInAr.length > 0 ? { onlyInAr } : {},
      onlyInEn.length > 0 ? { onlyInEn } : {},
    );
  }
}

/**
 * §13.2 item 7: Arabic by default, but the device locale is respected on first
 * launch if it is English.
 *
 * The user's own choice wins over both, and is cached on the device so it is
 * known *before first render*. It has to be: `applyRTLFor` below runs at module
 * scope, and `I18nManager.forceRTL` only takes effect for the next mount — so a
 * locale that arrived later (from the profile, over the network) could not flip
 * direction without a second reload. Device check 14 is what this is for: before
 * this cache existed, choosing العربية updated the profile, told the user to
 * restart, and then came back in English, because the restart re-derived the
 * locale from the *device* and discarded the choice.
 *
 * The profile's `language` remains the account-level source of truth (it is what
 * the Settings form edits and what the server localises exercise names by); this
 * is only a device-local bootstrap copy, written whenever the user picks a
 * language. Same honest-compromise storage note as `src/theme/useTheme.ts`:
 * SecureStore is nominally for secrets and this is not one, but §A.2 forbids
 * adding a dependency and it is the only key-value store installed. Namespaced
 * `gymak.locale.*`, not `gymak.session.*`, so signing out does not clear it.
 */
const LOCALE_PREFERENCE_KEY = "gymak.locale.preference";

function readStoredLocale(): Locale | null {
  try {
    const raw = SecureStore.getItem(LOCALE_PREFERENCE_KEY);
    return raw === "ar" || raw === "en" ? raw : null;
  } catch {
    return null;
  }
}

function writeStoredLocale(locale: Locale): void {
  try {
    SecureStore.setItem(LOCALE_PREFERENCE_KEY, locale);
  } catch {
    // Persisting failed; the in-memory switch below still applies for this run.
  }
}

function detectInitialLocale(): Locale {
  const stored = readStoredLocale();
  if (stored) return stored;
  const device = getLocales()[0]?.languageCode;
  return device === "en" ? "en" : "ar";
}

function applyRTLFor(locale: Locale): void {
  I18nManager.allowRTL(true);
  const shouldBeRTL = locale === "ar";
  if (I18nManager.isRTL !== shouldBeRTL) {
    I18nManager.forceRTL(shouldBeRTL);
  }
}

const initialLocale = detectInitialLocale();
applyRTLFor(initialLocale);

const i18n = new I18n(catalogs);
i18n.defaultLocale = "ar";
i18n.locale = initialLocale;
i18n.enableFallback = true;

/**
 * `i18n-js` ships one pluralizer for every locale, and it implements the
 * English rule: `one` for 1, `zero` for 0, `other` for the rest. Left alone it
 * renders «٢ مجموعة» for two and «٣ مجموعة» for three — wrong in the language
 * this app defaults to. `src/i18n/plural.ts` carries the real CLDR rules and
 * the reasoning; registering both locales keeps English on the same tested path
 * rather than on a library default.
 */
i18n.pluralization.register("ar", (_i18n, count) => pluralCandidates("ar", count));
i18n.pluralization.register("en", (_i18n, count) => pluralCandidates("en", count));

function translate(locale: Locale, key: string, options?: Record<string, unknown>): string {
  i18n.locale = locale;
  const result = i18n.t(key, options);
  if (__DEV__ && result.startsWith("[missing")) {
    console.warn(`[i18n] missing key "${key}" for locale "${locale}"`);
  }
  return result;
}

interface I18nContextValue {
  locale: Locale;
  t: (key: string, options?: Record<string, unknown>) => string;
  /**
   * Switches the in-memory catalogue immediately. Does **not** by itself fix
   * layout direction if the language change also flips RTL/LTR — per §9.6,
   * that requires `I18nManager.forceRTL` (called here) *and* a full app
   * reload, which has no UI trigger yet (T-13 owns that; it should call this
   * then prompt/perform the reload — e.g. `expo-updates`' `reloadAsync`,
   * not yet an Appendix A.2 dependency).
   */
  setLocale: (locale: Locale) => void;
}

const I18nContext = createContext<I18nContextValue>({
  locale: initialLocale,
  t: (key, options) => translate(initialLocale, key, options),
  setLocale: () => {},
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      t: (key, options) => translate(locale, key, options),
      setLocale: (next: Locale) => {
        applyRTLFor(next);
        // Cached before the state update so the choice survives even if the
        // user force-quits at the "restart to apply" prompt rather than after it.
        writeStoredLocale(next);
        setLocaleState(next);
      },
    }),
    [locale],
  );

  return createElement(I18nContext.Provider, { value }, children);
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext);
}
