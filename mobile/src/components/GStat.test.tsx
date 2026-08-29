/**
 * The first component test in this repo, and the reason the runner changed.
 *
 * WHAT IT LOCKS
 * The «1 أيام» defect found on device (657ab43). Its shape is what made it
 * invisible: `GStat` draws the number from `value` and the noun from `unit`,
 * two separate <Text> elements, so the noun string carries no `{{count}}`
 * placeholder at all. Every static search for a plural bug in this codebase
 * had looked for `{{count}}` — by construction that search could not reach
 * this class of defect, and nothing but a human reading a phone screen could.
 *
 * Rendering the component with the real catalogue and the real pluralizer is
 * what closes that gap permanently: the assertion below fails if the Arabic
 * `few` form is ever dropped, if the pluralizer regresses to i18n-js's
 * English one/other default, or if GStat stops rendering `unit` at all.
 *
 * WHY BOTH LOCALES
 * Arabic is the default language of this app and English the second. A test
 * that ran only the default would still pass with an English-shaped rule
 * quietly applied to Arabic — which is precisely the bug. Running the same
 * assertions in both is what distinguishes "the plural rule works" from
 * "the string happened to be right for the number I picked."
 */
import { renderWithProviders } from "../test-utils/render";
import { useI18n, type Locale } from "../i18n";
import { GStat } from "./GStat";

/**
 * The unit label exactly as `app/(app)/index.tsx:245` builds it, via the same
 * `t(key, { count })` call. Resolving the string through a component that
 * consumes the provider — rather than importing `plural.ts` and asserting the
 * category — is deliberate: `plural.test.ts` already covers the rule in
 * isolation, and duplicating it here would prove nothing new. What this file
 * has to prove is that the rule is actually WIRED to what a user sees.
 */
function StreakStat({ days }: { days: number }) {
  const { t } = useI18n();
  return (
    <GStat
      testID="streak"
      label={t("dashboard.streak.label")}
      value={days}
      unit={t("dashboard.streak.unit", { count: days })}
      tone="neutral"
    />
  );
}

function renderStreak(days: number, locale: Locale) {
  return renderWithProviders(<StreakStat days={days} />, { locale });
}

/** @testing-library/react-native 14 renders asynchronously; see render.tsx. */

describe("GStat renders a count-agreeing unit label", () => {
  describe("Arabic", () => {
    it("uses the singular «يوم» at 1 — the reported bug rendered «أيام» here", async () => {
      const { getByText } = await renderStreak(1, "ar");
      expect(getByText("يوم")).toBeTruthy();
    });

    it("uses the plural «أيام» at 3, where CLDR ar is `few`", async () => {
      const { getByText } = await renderStreak(3, "ar");
      expect(getByText("أيام")).toBeTruthy();
    });

    /**
     * Eleven is the reversal English has no equivalent for: the noun goes
     * BACK to a singular-looking form (`many`). A one/other fix — the
     * intuitive reading of this bug — passes the two cases above and fails
     * here, which is the whole point of asserting it.
     */
    it("uses «يومًا» at 11, where the noun reverts under CLDR `many`", async () => {
      const { getByText } = await renderStreak(11, "ar");
      expect(getByText("يومًا")).toBeTruthy();
    });

    it("still renders the number itself beside the noun", async () => {
      const { getByText } = await renderStreak(3, "ar");
      expect(getByText("3")).toBeTruthy();
    });
  });

  describe("English", () => {
    it("uses the singular at 1", async () => {
      const { getByText } = await renderStreak(1, "en");
      expect(getByText("day")).toBeTruthy();
    });

    it("uses the plural at 3", async () => {
      const { getByText } = await renderStreak(3, "en");
      expect(getByText("days")).toBeTruthy();
    });

    /**
     * The count where the two languages disagree about which form to use.
     * If the locale switch in the harness ever silently stopped working,
     * this case and the Arabic `many` case above cannot both pass.
     */
    it("stays plural at 11, where Arabic reverts", async () => {
      const { getByText } = await renderStreak(11, "en");
      expect(getByText("days")).toBeTruthy();
    });
  });
});

/**
 * A guard on the harness itself rather than on GStat. `renderWithProviders`
 * withholds children until the requested locale has landed; if that ever
 * breaks, every English assertion above would read the Arabic catalogue and
 * fail with a confusing "unable to find text" instead of naming the cause.
 */
describe("the render harness", () => {
  it("reports the locale it was asked for", async () => {
    function LocaleProbe() {
      const { locale } = useI18n();
      return <GStat testID="probe" label="l" value={locale} tone="neutral" />;
    }
    const { getByText } = await renderWithProviders(<LocaleProbe />, { locale: "en" });
    expect(getByText("en")).toBeTruthy();
  });

  it("renders the app's default locale when asked for Arabic", async () => {
    function LocaleProbe() {
      const { locale } = useI18n();
      return <GStat testID="probe" label="l" value={locale} tone="neutral" />;
    }
    const { getByText } = await renderWithProviders(<LocaleProbe />, { locale: "ar" });
    expect(getByText("ar")).toBeTruthy();
  });
});
