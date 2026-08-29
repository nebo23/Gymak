/**
 * Screen test for `app/(app)/plan/index.tsx` — the plan overview.
 *
 * WHAT IT LOCKS
 *
 *  1. The day row's summary line, which composes TWO independently-pluralised
 *     counts into one sentence: «5 تمارين · حوالي 45 دقيقة». Exercises and
 *     minutes land in DIFFERENT Arabic CLDR categories at those values (`few`
 *     and `many`), so a regression that pluralises the sentence on a single
 *     `count` — the obvious "simplification" — cannot satisfy both halves.
 *     This is the same composition the dashboard's next-workout line uses, and
 *     it is asserted in both places on purpose: they are separate call sites
 *     with separate catalogue keys (`plan.overview.footer` vs
 *     `dashboard.nextWorkout.footer`) and one can rot without the other.
 *
 *  2. The regenerate confirmation names the right number of days, in the right
 *     grammatical form. `days_per_week` is the count, and 1/2/3 are three
 *     distinct Arabic forms — `one` and `two` are spelled out in words and
 *     contain no `{{count}}` placeholder at all, so a one/other regression
 *     produces «1 يوم»-shaped text that no `{{count}}` search can find.
 *
 * BOTH LOCALES, ALWAYS — see `src/test-utils/render.tsx`.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, waitFor } from "@testing-library/react-native";
import type { ReactElement } from "react";

import { renderWithProviders } from "../test-utils/render";
import type { Locale } from "../i18n";
import { useSessionStore } from "../auth/session";
import type { ProgramDaySummary, ProgramResponse } from "../api/program";

/** See the note in activeWorkout.test.tsx — the transport, nothing more. */
jest.mock("../api/client", () => ({
  client: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() },
}));

jest.mock("../api/program", () => ({
  getProgram: jest.fn(),
  generateProgram: jest.fn(),
  getProgramDay: jest.fn(),
}));

import { getProgram } from "../api/program";
import PlanOverview from "../../app/(app)/plan/index";

const mockedGetProgram = getProgram as jest.MockedFunction<typeof getProgram>;

function day(overrides: Partial<ProgramDaySummary> = {}): ProgramDaySummary {
  return {
    id: "day-1",
    day_index: 0,
    label_key: "plan.day.fullBody",
    exercise_count: 5,
    estimated_minutes: 45,
    // Real catalogue keys: the card renders `t("muscles." + muscle)` for each,
    // and an invented one would log a missing-key warning on every render.
    focus_muscles: ["chest", "back"],
    ...overrides,
  };
}

function programResponse(daysPerWeek: number, days: ProgramDaySummary[]): ProgramResponse {
  return {
    program: {
      id: "prog-1",
      created_at: "2026-08-01T00:00:00Z",
      days_per_week: daysPerWeek,
      experience_level: "beginner",
      generator_version: 1,
      goal: "hypertrophy",
      split_type: "full_body",
      days,
    },
    stale: null,
  };
}

function withQuery(ui: ReactElement): ReactElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

async function renderPlan(locale: Locale, response: ProgramResponse) {
  mockedGetProgram.mockResolvedValue(response);
  const result = await renderWithProviders(withQuery(<PlanOverview />), { locale });
  await waitFor(() => expect(result.getByTestId("plan-day-0")).toBeTruthy());
  return result;
}

beforeEach(() => {
  jest.clearAllMocks();
  // `useQuery` is `enabled: user !== null`; without this the screen sits in
  // its loading state forever and every assertion times out unexplained.
  useSessionStore.setState({
    status: "active",
    user: { id: "u1", email: "a@b.c", emailVerified: true, authMethods: ["password"] },
    onboardingCompleted: true,
  });
});

describe("a day row summarises its exercises and duration", () => {
  /**
   * Western digits: nothing in `src/i18n` transliterates numerals (no
   * `Intl.NumberFormat`, no numbering-system option), so «5» renders as "5"
   * even in Arabic. `GStat.test.tsx` asserts `"3"` for the same reason.
   */
  it.each<[Locale, string]>([
    ["ar", "5 تمارين · حوالي 45 دقيقة"],
    ["en", "5 exercises · about 45 minutes"],
  ])("%s: five exercises, about forty-five minutes", async (locale, expected) => {
    const { getByText } = await renderPlan(locale, programResponse(3, [day()]));
    expect(getByText(expected)).toBeTruthy();
  });

  /**
   * One of each. Arabic spells both out («تمرين واحد», «دقيقة واحدة») and
   * neither string carries a digit — the shape that hid the original defect
   * from every static search.
   */
  it.each<[Locale, string]>([
    ["ar", "تمرين واحد · حوالي دقيقة واحدة"],
    ["en", "1 exercise · about 1 minute"],
  ])("%s: the singular forms", async (locale, expected) => {
    const { getByText } = await renderPlan(
      locale,
      programResponse(3, [day({ exercise_count: 1, estimated_minutes: 1 })]),
    );
    expect(getByText(expected)).toBeTruthy();
  });

  it("renders one card per day, each with its own summary", async () => {
    const { getByTestId, getByText } = await renderPlan(
      "ar",
      programResponse(2, [
        day({ id: "d1", day_index: 0, exercise_count: 5, estimated_minutes: 45 }),
        day({
          id: "d2",
          day_index: 1,
          label_key: "plan.day.upper",
          exercise_count: 2,
          estimated_minutes: 30,
        }),
      ]),
    );

    expect(getByTestId("plan-day-0")).toBeTruthy();
    expect(getByTestId("plan-day-1")).toBeTruthy();
    expect(getByText("5 تمارين · حوالي 45 دقيقة")).toBeTruthy();
    // Two exercises is Arabic's `two` — a dual form, spelled out, no digit.
    expect(getByText("تمرينان · حوالي 30 دقيقة")).toBeTruthy();
  });
});

describe("the regenerate confirmation names the day count", () => {
  /**
   * 1, 2 and 3 are the three Arabic categories reachable by a real
   * `days_per_week`, and all three read differently: «يوم واحد» (one),
   * «يومين» (two, spelled out), «{{count}} أيام» (few). The `many` form
   * (11+) is deliberately not asserted here — this screen's count is a
   * days-per-week value and cannot reach it, and a test that fabricated an
   * 11-day week would be asserting a state the product cannot produce.
   * `activeWorkout.test.tsx` covers `many` on a count that genuinely reaches
   * it (unsent sets).
   */
  it.each<[number, string]>([
    [
      1,
      "سيستبدل هذا خطتك الحالية بخطة جديدة من يوم واحد. سجل تدريباتك السابقة يبقى كما هو تمامًا.",
    ],
    [
      2,
      "سيستبدل هذا خطتك الحالية بخطة جديدة من يومين. سجل تدريباتك السابقة يبقى كما هو تمامًا.",
    ],
    [
      3,
      "سيستبدل هذا خطتك الحالية بخطة جديدة من 3 أيام. سجل تدريباتك السابقة يبقى كما هو تمامًا.",
    ],
  ])("Arabic: a %i-day plan", async (daysPerWeek, expected) => {
    const { getByTestId, getByText } = await renderPlan(
      "ar",
      programResponse(daysPerWeek, [day()]),
    );

    fireEvent.press(getByTestId("plan-regenerate"));

    // React 19 commits this asynchronously; the dialog is not up the instant
    // press returns.
    await waitFor(() => expect(getByText("إعادة إنشاء خطتك؟")).toBeTruthy());
    expect(getByText(expected)).toBeTruthy();
  });

  it.each<[number, string]>([
    [
      1,
      "This replaces your current plan with a new 1-day plan. Your training history stays exactly as it is.",
    ],
    [
      3,
      "This replaces your current plan with a new 3-day plan. Your training history stays exactly as it is.",
    ],
  ])("English: a %i-day plan", async (daysPerWeek, expected) => {
    const { getByTestId, getByText } = await renderPlan(
      "en",
      programResponse(daysPerWeek, [day()]),
    );

    fireEvent.press(getByTestId("plan-regenerate"));

    await waitFor(() => expect(getByText("Regenerate your plan?")).toBeTruthy());
    expect(getByText(expected)).toBeTruthy();
  });

  it("does not regenerate anything merely by opening the confirm", async () => {
    // The count is only correct if the dialog is genuinely a CONFIRM step.
    // A screen that regenerated on the first press would still show the right
    // sentence, so the guarantee is asserted rather than assumed.
    const { generateProgram } = jest.requireMock("../api/program") as {
      generateProgram: jest.Mock;
    };
    const { getByTestId, getByText } = await renderPlan("ar", programResponse(3, [day()]));

    fireEvent.press(getByTestId("plan-regenerate"));
    await waitFor(() => expect(getByText("إعادة إنشاء خطتك؟")).toBeTruthy());

    expect(generateProgram).not.toHaveBeenCalled();
  });
});
