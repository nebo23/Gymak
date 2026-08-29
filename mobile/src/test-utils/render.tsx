/**
 * The component-test entry point: renders a component inside the same two
 * providers `app/_layout.tsx` wraps the real app in — `I18nProvider` then
 * `ThemeProvider`, in that order — and lets a test pick the locale.
 *
 * WHY A LOCALE ARGUMENT IS NOT OPTIONAL SUGAR
 * This app ships Arabic first and English second, and its whole class of
 * i18n defects (the «1 أيام» streak label among them) only appears in one of
 * the two. A harness that could render just the default locale would give a
 * green suite that never looks at the language most of the users read. Every
 * component test can therefore be written twice over, once per locale, and
 * assert different text each time.
 *
 * HOW THE LOCALE IS SET
 * `I18nProvider` takes no locale prop: it derives its initial value once, at
 * module scope, from the stored preference or the device (`detectInitialLocale`),
 * because `I18nManager.forceRTL` has to run before first mount. That is
 * correct for the app and is not changed here — this file is test
 * infrastructure and does not touch application logic. Instead `LocaleBridge`
 * below drives the provider's own public `setLocale`, i.e. exactly the path a
 * user takes in Settings, and withholds children until the switch has landed
 * so no assertion can ever read a half-switched tree.
 */
import { useEffect, type ReactElement, type ReactNode } from "react";
import { render as rntlRender, type RenderResult } from "@testing-library/react-native";

import { I18nProvider, useI18n, type Locale } from "../i18n";
import { ThemeProvider } from "../theme/useTheme";

function LocaleBridge({ locale, children }: { locale: Locale; children: ReactNode }) {
  const { locale: current, setLocale } = useI18n();

  useEffect(() => {
    if (current !== locale) setLocale(locale);
  }, [current, locale, setLocale]);

  // Held back for exactly one render when the requested locale differs from
  // the provider's initial one. Returning the children early would let a test
  // assert against Arabic text in an "en" case and pass for the wrong reason.
  return current === locale ? <>{children}</> : null;
}

export interface RenderOptions {
  /** Which catalogue to render under. Required — see the note above. */
  locale: Locale;
}

/**
 * Renders `ui` under the app's providers at `options.locale`.
 *
 * ASYNC because @testing-library/react-native 14's own `render` is: it awaits
 * React 19's concurrent commit before handing back queries, which is also what
 * flushes `LocaleBridge`'s effect. Callers must `await` it — a forgotten await
 * yields a Promise whose `getByText` is undefined, which is a loud failure
 * rather than a silent wrong-locale pass, and that is the safer direction.
 *
 * Returns @testing-library/react-native's own `RenderResult` unchanged, so
 * every query (`getByText`, `getByTestId`, …) works as documented upstream
 * with nothing to re-learn here.
 */
export async function renderWithProviders(
  ui: ReactElement,
  options: RenderOptions,
): Promise<RenderResult> {
  return rntlRender(
    <I18nProvider>
      <LocaleBridge locale={options.locale}>
        <ThemeProvider>{ui}</ThemeProvider>
      </LocaleBridge>
    </I18nProvider>,
  );
}

/**
 * The translator for the locale under test, for assertions that must compare
 * rendered output against the catalogue rather than against a hardcoded
 * string. Use a literal (`"يوم"`) when the point of the test IS the exact
 * wording; use this when the point is that the right *key* was chosen.
 */
export { useI18n } from "../i18n";
export type { Locale } from "../i18n";
