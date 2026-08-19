/**
 * The pure half of GLineChart (§9.2/§9.3), split out for the same reason
 * activeSessionLogic.ts is split from activeSession.ts: zero runtime
 * dependency on `react-native` or `react-native-svg`, so vitest's plain
 * transform -- scoped to `src/**\/*.test.ts`, never `.tsx` (vitest.config.ts's
 * own comment: "component/screen code needs React Native's runtime ...
 * verified on-device, not here") -- can import this file directly and prove
 * the two rules §9.3 calls out as easiest to get wrong and hardest to notice:
 * gaps stay gaps, and the axis range is honest. GLineChart.tsx imports this
 * module for its geometry and adds nothing of its own beyond SVG drawing.
 */

export interface DateValue {
  /** ISO calendar date, "YYYY-MM-DD". No time-of-day, no timezone -- these
   * are already resolved server-side (§4.2/§5.10) into the caller's own
   * local calendar day before they ever reach this module. */
  date: string;
  value: number;
}

/** UTC-midnight epoch ms for a "YYYY-MM-DD" string -- the same anchor
 * history.tsx's own formatDay/formatMonthTitle use, so calendar-day
 * arithmetic here can never drift a day from a device's own local zone. */
function epochMsUTC(isoDate: string): number {
  return Date.parse(`${isoDate}T00:00:00Z`);
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/** Whole calendar days from `a` to `b` (positive when `b` is later). */
export function daysBetweenIso(a: string, b: string): number {
  return Math.round((epochMsUTC(b) - epochMsUTC(a)) / MS_PER_DAY);
}

export function addDaysIso(isoDate: string, days: number): string {
  return new Date(epochMsUTC(isoDate) + days * MS_PER_DAY).toISOString().slice(0, 10);
}

/**
 * §9.3: "Gaps are gaps... a straight line through a two-week hole is a claim
 * about weight the user never made." The mechanism: sort ascending, then
 * start a new segment every time consecutive points are more than exactly
 * one calendar day apart. Two points on genuinely adjacent calendar days
 * share a segment (there is no missing day between them to misrepresent);
 * anything wider starts a new one, and the caller draws each segment as its
 * own disconnected path -- never one path spanning every point. A
 * single-point segment is a real logged day with no adjacent neighbour on
 * either side; it is returned as a segment of length 1 rather than dropped,
 * so the caller can still mark it (a dot), never silently discarding a
 * value the user actually logged.
 */
export function buildContinuousSegments<T extends DateValue>(points: readonly T[]): T[][] {
  const sorted = [...points].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const segments: T[][] = [];
  for (const point of sorted) {
    const current = segments[segments.length - 1];
    const previous = current?.[current.length - 1];
    if (previous && daysBetweenIso(previous.date, point.date) === 1) {
      current.push(point);
    } else {
      segments.push([point]);
    }
  }
  return segments;
}

export interface ValueRange {
  min: number;
  max: number;
}

const MIN_PAD_KG = 0.5;
const PAD_RATIO = 0.1;

/**
 * §9.3: "The y-axis does not start at zero... the visible range is labelled
 * at both ends." The padded min/max computed here IS that visible range --
 * both a real point and its own axis label sit strictly inside it, never
 * exactly on the drawn edge. A flat series (every value identical, span 0)
 * still gets a non-zero band via MIN_PAD_KG, so a single repeated weight
 * never collapses the chart to a zero-height line.
 */
export function computeValueRange(values: readonly number[]): ValueRange {
  if (values.length === 0) return { min: 0, max: 1 };
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const pad = Math.max((rawMax - rawMin) * PAD_RATIO, MIN_PAD_KG);
  return { min: rawMin - pad, max: rawMax + pad };
}

export interface PlottedPoint<T> {
  item: T;
  /** 0 at the domain's start date, 1 at its end date. */
  xRatio: number;
  /** 0 at `range.min`, 1 at `range.max`. */
  yRatio: number;
}

/**
 * Places each point by its actual calendar distance from `domainStartIso`,
 * not by its index in the array -- a two-week hole must occupy two weeks'
 * width of empty space, exactly as wide as it would be if every day in it
 * had been logged and connected. Placing points evenly by index instead
 * would make a two-week gap look identical to a one-day one, which is the
 * same dishonesty §9.3 rules out for the path itself, just moved into the
 * axis instead of the line.
 */
export function plotPoints<T extends DateValue>(
  points: readonly T[],
  domainStartIso: string,
  domainDays: number,
  range: ValueRange,
): PlottedPoint<T>[] {
  const span = range.max - range.min;
  const lastDayIndex = Math.max(domainDays - 1, 1);
  return points.map((item) => ({
    item,
    xRatio: daysBetweenIso(domainStartIso, item.date) / lastDayIndex,
    yRatio: span > 0 ? (item.value - range.min) / span : 0.5,
  }));
}

export function buildPathD(plotted: readonly PlottedPoint<unknown>[], width: number, height: number): string {
  return plotted
    .map((point, index) => {
      const x = point.xRatio * width;
      const y = (1 - point.yRatio) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}
