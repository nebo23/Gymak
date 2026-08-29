/**
 * CLDR plural categories, and the Arabic rule `i18n-js` does not ship.
 *
 * `i18n-js`'s built-in pluralizer resolves `one` for 1, `zero` for 0, and
 * `other` for everything else — an English rule applied to every locale. Under
 * `ar` that is wrong for two whole ranges, and wrong in *both* directions:
 *
 *   2       مجموعتان   dual, a category English does not have at all
 *   3–10    ٣ مجموعات  the noun takes its PLURAL form
 *   11–99   ١١ مجموعة  the noun goes back to its SINGULAR form
 *
 * That reversal at eleven is why a one/other split — the fix an English-shaped
 * reading of this bug suggests — still renders Arabic incorrectly for every
 * count from 2 to 10. The rule below is the CLDR `ar` rule in full, written out
 * rather than taken from `Intl.PluralRules`: Hermes ships Intl conditionally by
 * platform and build flags, and a plural rule that silently degrades to English
 * on one platform is the exact defect this module exists to remove. The rule is
 * also fixed for all time — Arabic grammar is not going to be revised — so
 * there is nothing to keep in sync.
 *
 * Pure and I/O-free: no `I18n` instance, no catalogue, no clock. `index.ts`
 * registers `arabicPluralCategory` with `i18n.pluralization`; this module never
 * imports `i18n-js` itself, which is what lets `plural.test.ts` assert the rule
 * directly under the `src/**` vitest scope.
 */

/** The six CLDR plural categories. Arabic uses all of them; English uses three. */
export type PluralCategory = "zero" | "one" | "two" | "few" | "many" | "other";

/** Every category, in CLDR order. The catalogue-symmetry check in `index.ts` uses this. */
export const PLURAL_CATEGORIES: readonly PluralCategory[] = [
  "zero",
  "one",
  "two",
  "few",
  "many",
  "other",
] as const;

/**
 * The CLDR `ar` plural rule.
 *
 * ```
 * zero  n = 0                 لا مجموعات
 * one   n = 1                 مجموعة واحدة
 * two   n = 2                 مجموعتان
 * few   n % 100 = 3..10       ٣ مجموعات   ١٠٣ مجموعات
 * many  n % 100 = 11..99      ١١ مجموعة   ٩٩ مجموعة
 * other everything else       ١٠٠ مجموعة  ١٠١ مجموعة
 * ```
 *
 * The modulo is on 100, not 10: 103 is `few` and 111 is `many`, which is why
 * the two ranges cannot be collapsed into a simple threshold.
 *
 * Non-integers and negatives cannot reach any caller here — every count in this
 * app is a length or a tally — but both resolve to `other`, which is the
 * category CLDR itself assigns to fractional counts.
 */
export function arabicPluralCategory(count: number): PluralCategory {
  if (!Number.isInteger(count) || count < 0) return "other";
  if (count === 0) return "zero";
  if (count === 1) return "one";
  if (count === 2) return "two";
  const mod100 = count % 100;
  if (mod100 >= 3 && mod100 <= 10) return "few";
  if (mod100 >= 11 && mod100 <= 99) return "many";
  return "other";
}

/**
 * The CLDR `en` plural rule, plus `zero` when the catalogue offers it.
 *
 * `i18n-js`'s default pluralizer already implements exactly this, so registering
 * it changes no behaviour. It is written out anyway so both locales resolve
 * through the same tested path — the alternative leaves English depending on a
 * library default that a future `i18n-js` release could redefine underneath a
 * catalogue whose `zero` keys nothing in this repo asserts.
 */
export function englishPluralCategory(count: number): PluralCategory {
  if (!Number.isInteger(count) || count < 0) return "other";
  if (count === 0) return "zero";
  if (count === 1) return "one";
  return "other";
}

/**
 * The candidate-key list `i18n.pluralization.register` expects: the exact
 * category first, then `other` as the fallback for a catalogue that does not
 * define every category. English catalogues legitimately define only
 * `one`/`other`, so the fallback is load-bearing, not defensive padding.
 */
export function pluralCandidates(locale: "ar" | "en", count: number): PluralCategory[] {
  const category = locale === "ar" ? arabicPluralCategory(count) : englishPluralCategory(count);
  return category === "other" ? ["other"] : [category, "other"];
}
