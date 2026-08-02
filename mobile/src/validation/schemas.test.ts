/**
 * §7.1's imperial-input round trip: "a user who enters 5'10" does not see
 * 177.7 cm come back as 5'9.9"." These pure functions have no React Native
 * dependency, so they run under plain Node via vitest.
 */
import { describe, expect, it } from "vitest";

import { cmToFeetInches, feetInchesToCm, kgToLbs, lbsToKg } from "./schemas";

describe("feetInchesToCm / cmToFeetInches round trip", () => {
  const cases: Array<{ feet: number; inches: number }> = [
    { feet: 5, inches: 0 },
    { feet: 5, inches: 10 },
    { feet: 5, inches: 11 },
    { feet: 6, inches: 0 },
    { feet: 6, inches: 2 },
    { feet: 4, inches: 8 },
  ];

  it.each(cases)("round-trips $feet'$inches\"", ({ feet, inches }) => {
    const cm = feetInchesToCm(feet, inches);
    expect(cmToFeetInches(cm)).toEqual({ feet, inches });
  });

  it("matches the spec's own example", () => {
    // §7.1: "a user who enters 5'10" does not see 177.7 cm come back as 5'9.9"."
    const cm = feetInchesToCm(5, 10);
    expect(cmToFeetInches(cm)).toEqual({ feet: 5, inches: 10 });
  });
});

describe("lbsToKg / kgToLbs round trip", () => {
  const cases = [120, 132.5, 150, 180.2, 220];

  it.each(cases)("round-trips %s lbs within display rounding", (lbs) => {
    const kg = lbsToKg(lbs);
    const roundTripped = kgToLbs(kg);
    expect(Math.abs(roundTripped - lbs)).toBeLessThanOrEqual(0.1);
  });
});
