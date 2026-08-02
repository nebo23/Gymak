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

import ar from "./ar.json";
import en from "./en.json";

export type Locale = "ar" | "en";

const catalogs = { ar, en } as const;

function flattenKeys(obj: unknown, prefix = ""): Set<string> {
  const keys = new Set<string>();
  if (obj === null || typeof obj !== "object") {
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

// §13.2 item 7: Arabic by default, but the device locale is respected on
// first launch if it is English. There is no persisted user override yet —
// that lands with the Settings screen (T-14) — so this runs fresh every
// cold start.
function detectInitialLocale(): Locale {
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
