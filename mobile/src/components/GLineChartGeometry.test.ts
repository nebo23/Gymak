/**
 * §9.3's two rules "easiest to get wrong and least likely to be noticed"
 * (T-28's own instructions): gaps stay gaps, and the y-axis range is honest
 * (non-zero-based, both ends inside it). These cases are what "proves it"
 * rather than asserts it.
 */
import { describe, expect, it } from "vitest";

import {
  addDaysIso,
  buildContinuousSegments,
  buildPathD,
  computeValueRange,
  daysBetweenIso,
  plotPoints,
  type DateValue,
} from "./GLineChartGeometry";

describe("daysBetweenIso / addDaysIso", () => {
  it("counts whole calendar days regardless of device-local time", () => {
    expect(daysBetweenIso("2026-01-01", "2026-01-02")).toBe(1);
    expect(daysBetweenIso("2026-01-01", "2026-01-31")).toBe(30);
    expect(daysBetweenIso("2026-01-31", "2026-01-01")).toBe(-30);
    expect(daysBetweenIso("2026-02-01", "2026-03-01")).toBe(28); // 2026 is not a leap year
  });

  it("round-trips with addDaysIso", () => {
    expect(addDaysIso("2026-01-01", 30)).toBe("2026-01-31");
    expect(addDaysIso("2026-03-01", -28)).toBe("2026-02-01");
  });
});

describe("buildContinuousSegments -- §9.3 'gaps are gaps'", () => {
  it("keeps a run of consecutive days in one segment", () => {
    const points: DateValue[] = [
      { date: "2026-01-01", value: 80 },
      { date: "2026-01-02", value: 79.5 },
      { date: "2026-01-03", value: 79 },
    ];
    expect(buildContinuousSegments(points)).toEqual([points]);
  });

  it("breaks into a new segment across a gap of missing days, however short", () => {
    // Monday and Wednesday logged, Tuesday not -- a one-day hole must still
    // split the path. Connecting these would draw a line implying a Tuesday
    // reading that was never taken.
    const monday: DateValue = { date: "2026-01-05", value: 80 };
    const wednesday: DateValue = { date: "2026-01-07", value: 78 };
    expect(buildContinuousSegments([monday, wednesday])).toEqual([[monday], [wednesday]]);
  });

  it("breaks across a two-week hole, exactly the case the done-when names", () => {
    const before: DateValue = { date: "2026-05-01", value: 82 };
    const after: DateValue = { date: "2026-05-15", value: 79 };
    const segments = buildContinuousSegments([before, after]);
    expect(segments).toHaveLength(2);
    expect(segments[0]).toEqual([before]);
    expect(segments[1]).toEqual([after]);
  });

  it("sorts out-of-order input before segmenting, so caller order never matters", () => {
    const jan2: DateValue = { date: "2026-01-02", value: 79 };
    const jan1: DateValue = { date: "2026-01-01", value: 80 };
    expect(buildContinuousSegments([jan2, jan1])).toEqual([[jan1, jan2]]);
  });

  it("returns a length-1 segment for an isolated day rather than dropping it", () => {
    const isolated: DateValue = { date: "2026-06-15", value: 77 };
    const segments = buildContinuousSegments([isolated]);
    expect(segments).toEqual([[isolated]]);
  });

  it("reproduces the done-when's 41-entry/90-day shape with real gaps visible", () => {
    // 90-day domain, one entry every other day except a genuine 10-day hole
    // in the middle -- 41 entries total (30 in two 15-entry alternating runs
    // either side of the hole, ... constructed directly below instead of by
    // formula, so the test's own intent stays legible).
    const points: DateValue[] = [];
    for (let i = 0; i < 30; i += 2) {
      points.push({ date: addDaysIso("2026-01-01", i), value: 80 - i * 0.05 });
    }
    // days 30..39 inclusive (10 days) are the hole: no entries at all.
    for (let i = 40; i <= 90; i += 2) {
      points.push({ date: addDaysIso("2026-01-01", i), value: 77 - (i - 40) * 0.05 });
    }
    expect(points).toHaveLength(41);

    const segments = buildContinuousSegments(points);
    // Every entry here is two days apart from its neighbour on the same
    // side of the hole, so none of them are calendar-adjacent -- each one
    // is its own segment (41 single-point segments), and none crosses the
    // 10-day hole. The hole is visible as "no segment has 2+ points," which
    // is the strongest possible proof nothing was interpolated across it.
    expect(segments).toHaveLength(41);
    expect(segments.every((segment) => segment.length === 1)).toBe(true);

    const lastBeforeHole = segments[14]![0]!;
    const firstAfterHole = segments[15]![0]!;
    expect(daysBetweenIso(lastBeforeHole.date, firstAfterHole.date)).toBeGreaterThan(1);
  });
});

describe("computeValueRange -- §9.3 'the y-axis does not start at zero'", () => {
  it("pads both ends so real points never sit exactly on the drawn edge", () => {
    const range = computeValueRange([76.1, 78.4, 73.4]);
    expect(range.min).toBeLessThan(73.4);
    expect(range.max).toBeGreaterThan(78.4);
  });

  it("never anchors at zero even when every value is far from it", () => {
    const range = computeValueRange([180, 182, 179]);
    expect(range.min).toBeGreaterThan(0);
    expect(range.min).toBeGreaterThan(170); // nowhere near flattening to zero
  });

  it("still returns a non-zero-height band when every value is identical", () => {
    const range = computeValueRange([75, 75, 75]);
    expect(range.max).toBeGreaterThan(range.min);
  });
});

describe("plotPoints -- calendar-distance x placement, not index placement", () => {
  it("spaces two points proportionally to their real day gap, not their array position", () => {
    const points: DateValue[] = [
      { date: "2026-01-01", value: 80 },
      { date: "2026-01-10", value: 80 }, // 9 days later, inside a 10-day domain
    ];
    const range = computeValueRange(points.map((p) => p.value));
    const plotted = plotPoints(points, "2026-01-01", 10, range);
    expect(plotted[0]!.xRatio).toBe(0);
    // 9 days elapsed out of 9 possible (domainDays=10 -> lastDayIndex=9) -> 1.0
    expect(plotted[1]!.xRatio).toBeCloseTo(1, 5);
  });

  it("a point exactly halfway through the domain lands at xRatio 0.5", () => {
    const points: DateValue[] = [
      { date: "2026-01-01", value: 80 },
      { date: "2026-01-16", value: 79 }, // day 15 of a 0-30 (31-day) domain
      { date: "2026-01-31", value: 78 },
    ];
    const range = computeValueRange(points.map((p) => p.value));
    const plotted = plotPoints(points, "2026-01-01", 31, range);
    expect(plotted[1]!.xRatio).toBeCloseTo(0.5, 5);
  });
});

describe("buildPathD", () => {
  it("emits one M (moveto) and only L (lineto) after it", () => {
    const points: DateValue[] = [
      { date: "2026-01-01", value: 80 },
      { date: "2026-01-02", value: 79 },
      { date: "2026-01-03", value: 78 },
    ];
    const range = computeValueRange(points.map((p) => p.value));
    const plotted = plotPoints(points, "2026-01-01", 3, range);
    const d = buildPathD(plotted, 300, 100);
    const commands = d.split(" ");
    expect(commands).toHaveLength(3);
    expect(commands[0]!.startsWith("M")).toBe(true);
    expect(commands[1]!.startsWith("L")).toBe(true);
    expect(commands[2]!.startsWith("L")).toBe(true);
  });
});
