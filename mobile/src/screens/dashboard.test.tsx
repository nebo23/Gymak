/**
 * Screen test for `app/(app)/index.tsx` — the dashboard.
 *
 * WHY THIS FILE EXISTS
 * The runner was moved to jest-expo so screens could be rendered, but until
 * now the only thing that used that capability was `GStat.test.tsx`, and it
 * tests a *reconstruction* of this screen's streak stat — a local `StreakStat`
 * component that calls `t("dashboard.streak.unit", { count })` the same way
 * line 245 does. That proves the catalogue and the pluralizer agree. It does
 * NOT prove this screen still calls them: deleting the `unit` prop from the
 * real `GStat` here would leave that test green.
 *
 * So this file renders the actual default export, with the actual query layer
 * feeding it, and asserts on the text a user reads.
 *
 * WHAT IT LOCKS
 *  1. The «1 أيام» streak defect (657ab43), against the real screen this time.
 *  2. The next-workout line, which composes TWO independently-pluralised
 *     counts into one sentence — the shape most likely to be broken by a
 *     well-meaning "simplification" to a single `{{count}}`.
 *  3. That the empty state's call to action is wired to something.
 *
 * BOTH LOCALES, ALWAYS
 * Arabic is this app's primary language and the language both device-found
 * plural defects appeared in; English hid one of them. Every assertion below
 * therefore runs twice, and the two locales expect *different* strings at the
 * same count — which is what makes the pair meaningful rather than duplicated.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, waitFor } from "@testing-library/react-native";
import { router } from "expo-router";
import type { ReactElement } from "react";

import { renderWithProviders } from "../test-utils/render";
import type { Locale } from "../i18n";
import { useSessionStore } from "../auth/session";
import type { DashboardData } from "../api/dashboard";

/**
 * The HTTP transport, for the same reason jest.setup.js doubles the native
 * modules: it reaches for something a Node process does not have. `client.ts`
 * THROWS at import time when `EXPO_PUBLIC_API_BASE_URL` is unset, and jest
 * loads no `.env` — so merely importing the session store (which reaches
 * `api/auth.ts` -> `api/client.ts`) fails the suite before a single test runs.
 *
 * Only the transport is doubled. The session store, the query layer, the
 * providers and the screen itself are all real; `getDashboard` below is
 * stubbed at the API boundary, which is where a screen test should cut.
 */
jest.mock("../api/client", () => ({
  client: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() },
}));

jest.mock("../api/dashboard", () => ({ getDashboard: jest.fn() }));

import { getDashboard } from "../api/dashboard";
import Dashboard from "../../app/(app)/index";

const mockedGetDashboard = getDashboard as jest.MockedFunction<typeof getDashboard>;

/**
 * A complete, schema-shaped dashboard payload. Every field the response
 * declares is present with a realistic value rather than a cast: a fixture
 * that lies about the shape would let this suite keep passing after the
 * backend drops a field the screen reads.
 */
function dashboardData(overrides: Partial<DashboardData> = {}): DashboardData {
  return {
    greeting_name: "Nabil",
    // The literal the backend sends (`dashboard_service.py`'s _DISCLAIMER_KEY),
    // not an invented one: the screen renders `t(data.disclaimer_key)`, so a
    // made-up key here logs an "[i18n] missing key" warning on every render and
    // trains the reader to ignore exactly the warning that would matter.
    disclaimer_key: "common.medicalDisclaimer",
    active_session: null,
    next_workout: {
      program_day_id: "day-1",
      day_index: 0,
      label_key: "plan.day.fullBody",
      exercise_count: 5,
      estimated_minutes: 45,
    },
    streak: { current_days: 3, longest_days: 3, last_workout_local_date: "2026-08-28" },
    this_week: { completed: 2, target: 3, local_week_start: "2026-08-24" },
    weight: { latest_kg: null, measured_on: null, sparkline: [], change_30d_kg: null },
    recent_records: [],
    program_stale: null,
    ...overrides,
  };
}

/** A fresh client per render: retries off so a rejected query surfaces at once. */
function withQuery(ui: ReactElement): ReactElement {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

async function renderDashboard(locale: Locale, overrides: Partial<DashboardData> = {}) {
  mockedGetDashboard.mockResolvedValue(dashboardData(overrides));
  const result = await renderWithProviders(withQuery(<Dashboard />), { locale });
  // The screen renders a skeleton until the query settles; every assertion
  // below is about loaded content, so wait for it here rather than in each test.
  await waitFor(() => expect(result.getByTestId("dashboard-streak")).toBeTruthy());
  return result;
}

beforeEach(() => {
  jest.clearAllMocks();
  // `useQuery` is `enabled: user !== null`; without a user the screen never
  // leaves its loading state and every assertion would time out unexplained.
  useSessionStore.setState({
    status: "active",
    user: { id: "u1", email: "a@b.c", emailVerified: true, authMethods: ["password"] },
    onboardingCompleted: true,
  });
});

describe("dashboard streak card agrees with its count", () => {
  /**
   * 1, 3 and 11 are not arbitrary. They are the three Arabic CLDR categories
   * whose nouns differ (`one`, `few`, `many`), and 11 is the one English has
   * no equivalent for — Arabic reverts to a singular-LOOKING form there while
   * English stays plural. A one/other fix, the intuitive misreading of the
   * original bug, passes 1 and 3 and fails 11.
   */
  it.each([
    [1, "يوم"],
    [3, "أيام"],
    [11, "يومًا"],
  ])("Arabic: %i days renders «%s»", async (days, expected) => {
    const { getByText } = await renderDashboard("ar", {
      streak: {
        current_days: days as number,
        longest_days: days as number,
        last_workout_local_date: "2026-08-28",
      },
    });
    expect(getByText(expected as string)).toBeTruthy();
  });

  it.each([
    [1, "day"],
    [3, "days"],
    [11, "days"],
  ])("English: %i days renders «%s»", async (days, expected) => {
    const { getByText } = await renderDashboard("en", {
      streak: {
        current_days: days as number,
        longest_days: days as number,
        last_workout_local_date: "2026-08-28",
      },
    });
    expect(getByText(expected as string)).toBeTruthy();
  });

  it("renders the number itself, not only the noun", async () => {
    const { getByText } = await renderDashboard("ar", {
      streak: { current_days: 11, longest_days: 11, last_workout_local_date: "2026-08-28" },
    });
    expect(getByText("11")).toBeTruthy();
  });
});

describe("next workout line composes both counts", () => {
  /**
   * Two counts, two DIFFERENT Arabic categories in one sentence: 5 exercises
   * is `few`, 45 minutes is `many`. If either number were ever routed through
   * the other's category — or if the sentence were collapsed to a single
   * `{{count}}` — this exact string stops matching.
   *
   * Digits are Western here because nothing in `src/i18n` transliterates them
   * (there is no `Intl.NumberFormat` call and no numbering-system option);
   * `GStat.test.tsx` asserts `"3"` for the same reason.
   */
  it("Arabic: 5 exercises and 45 minutes", async () => {
    const { getByText } = await renderDashboard("ar");
    expect(getByText("5 تمارين · حوالي 45 دقيقة")).toBeTruthy();
  });

  it("English: 5 exercises and 45 minutes", async () => {
    const { getByText } = await renderDashboard("en");
    expect(getByText("5 exercises · about 45 minutes")).toBeTruthy();
  });

  /**
   * One exercise and one minute: the count where Arabic uses a word («تمرين
   * واحد») and carries no `{{count}}` placeholder at all. That is the shape
   * that made the original defect invisible to every grep for `{{count}}`.
   */
  it("Arabic: the singular forms carry no digit", async () => {
    const { getByText } = await renderDashboard("ar", {
      next_workout: {
        program_day_id: "day-1",
        day_index: 0,
        label_key: "plan.day.upper",
        exercise_count: 1,
        estimated_minutes: 1,
      },
    });
    expect(getByText("تمرين واحد · حوالي دقيقة واحدة")).toBeTruthy();
  });

  it("English: the singular forms", async () => {
    const { getByText } = await renderDashboard("en", {
      next_workout: {
        program_day_id: "day-1",
        day_index: 0,
        label_key: "plan.day.upper",
        exercise_count: 1,
        estimated_minutes: 1,
      },
    });
    expect(getByText("1 exercise · about 1 minute")).toBeTruthy();
  });
});

describe("empty state offers a live action", () => {
  /**
   * "No dead CTA" is a behavioural claim, so it is asserted behaviourally:
   * the button exists, and PRESSING it routes. `GEmptyState` renders its
   * button only when BOTH `actionLabelKey` and `onAction` are passed, so a
   * regression that drops the handler makes the button vanish and the
   * getByTestId below fail — and one that keeps the button but breaks the
   * handler fails on the router assertion instead.
   */
  it.each<[Locale, string]>([
    ["ar", "إنشاء خطتي"],
    ["en", "Build my plan"],
  ])("%s: no-plan empty state routes to the plan tab", async (locale, label) => {
    const { getByTestId, getByText } = await renderDashboard(locale, { next_workout: null });

    expect(getByTestId("dashboard-no-program")).toBeTruthy();
    expect(getByText(label)).toBeTruthy();

    fireEvent.press(getByTestId("dashboard-no-program-action"));
    expect(router.push).toHaveBeenCalledWith("/(app)/plan");
  });

  it("does not render the next-workout card when there is no plan", async () => {
    const { queryByTestId } = await renderDashboard("ar", { next_workout: null });
    expect(queryByTestId("dashboard-next-workout")).toBeNull();
  });
});
