import { describe, expect, it } from "vitest";

import {
  arabicPluralCategory,
  englishPluralCategory,
  pluralCandidates,
  PLURAL_CATEGORIES,
} from "./plural";

describe("arabicPluralCategory", () => {
  it("resolves the six CLDR ar categories at their boundaries", () => {
    expect(arabicPluralCategory(0)).toBe("zero");
    expect(arabicPluralCategory(1)).toBe("one");
    expect(arabicPluralCategory(2)).toBe("two");

    // few: n % 100 = 3..10
    expect(arabicPluralCategory(3)).toBe("few");
    expect(arabicPluralCategory(10)).toBe("few");

    // many: n % 100 = 11..99 -- the noun reverts to its singular form here,
    // which is the case an English-shaped one/other fix gets wrong.
    expect(arabicPluralCategory(11)).toBe("many");
    expect(arabicPluralCategory(99)).toBe("many");

    expect(arabicPluralCategory(100)).toBe("other");
  });

  it("takes the modulo on 100, not 10", () => {
    // 103 is few and 111 is many: the two ranges repeat every hundred, so a
    // simple `count > 10` threshold would misclassify both.
    expect(arabicPluralCategory(103)).toBe("few");
    expect(arabicPluralCategory(110)).toBe("few");
    expect(arabicPluralCategory(111)).toBe("many");
    expect(arabicPluralCategory(199)).toBe("many");
    expect(arabicPluralCategory(200)).toBe("other");
    expect(arabicPluralCategory(201)).toBe("other");
    expect(arabicPluralCategory(202)).toBe("other");
  });

  it("never disagrees with Intl.PluralRules where the runtime provides it", () => {
    // Hermes ships Intl conditionally, which is why the rule is hand-written --
    // but where Intl *is* available (Node, and Hermes builds that include it)
    // it is the reference implementation, so any divergence is a bug here.
    const rules = new Intl.PluralRules("ar");
    for (let n = 0; n <= 250; n += 1) {
      expect(arabicPluralCategory(n)).toBe(rules.select(n));
    }
  });

  it("resolves non-integer and negative counts to other", () => {
    expect(arabicPluralCategory(1.5)).toBe("other");
    expect(arabicPluralCategory(-1)).toBe("other");
    expect(arabicPluralCategory(Number.NaN)).toBe("other");
  });
});

describe("englishPluralCategory", () => {
  it("resolves zero, one, and other", () => {
    expect(englishPluralCategory(0)).toBe("zero");
    expect(englishPluralCategory(1)).toBe("one");
    expect(englishPluralCategory(2)).toBe("other");
    expect(englishPluralCategory(11)).toBe("other");
    expect(englishPluralCategory(100)).toBe("other");
  });

  it("agrees with Intl.PluralRules once zero is folded into other", () => {
    const rules = new Intl.PluralRules("en");
    for (let n = 1; n <= 250; n += 1) {
      expect(englishPluralCategory(n)).toBe(rules.select(n));
    }
  });
});

describe("pluralCandidates", () => {
  it("puts the exact category first and falls back to other", () => {
    expect(pluralCandidates("ar", 2)).toEqual(["two", "other"]);
    expect(pluralCandidates("ar", 5)).toEqual(["few", "other"]);
    expect(pluralCandidates("en", 1)).toEqual(["one", "other"]);
  });

  it("does not repeat other when it is already the category", () => {
    expect(pluralCandidates("ar", 100)).toEqual(["other"]);
    expect(pluralCandidates("en", 7)).toEqual(["other"]);
  });

  it("only ever emits known CLDR categories", () => {
    for (const locale of ["ar", "en"] as const) {
      for (let n = 0; n <= 250; n += 1) {
        for (const candidate of pluralCandidates(locale, n)) {
          expect(PLURAL_CATEGORIES).toContain(candidate);
        }
      }
    }
  });
});
