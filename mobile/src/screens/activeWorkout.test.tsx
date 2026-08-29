/**
 * Screen test for `app/(app)/workout/active.tsx` — "the screen the phase lives
 * or dies on" (its own file header).
 *
 * WHAT IT LOCKS, AND WHY EACH ONE
 *
 *  1. Logging a set puts a row on screen carrying the reps and weight that
 *     were logged. This is the screen's whole job; §8.3.2 says Log Set is the
 *     only tap needed when the pre-fill is unchanged, so the test presses
 *     exactly that one button and reads the row that appears.
 *
 *  2. The "unsent sets" dialog at 1, 2, 3 and 11. Those four counts are the
 *     four Arabic CLDR categories this catalogue actually distinguishes —
 *     `one`, `two`, `few`, `many` — and the first two carry NO `{{count}}`
 *     placeholder at all («مجموعة واحدة», «مجموعتان»). That absence is what
 *     made the sibling defect «1 أيام» invisible to every static search for
 *     `{{count}}`: there is nothing to search for. Only rendering finds it.
 *
 *  3. Finish does not proceed while unsent rows exist. Note the real
 *     behaviour is INTERCEPTION, not a disabled button: `handleFinishPress`
 *     diverts to the unsent dialog and returns before `setDialog({kind:
 *     "finish"})`. The test asserts that observable behaviour — the finish
 *     confirm never appears and `finishWorkout` is never called — rather than
 *     asserting a `disabled` prop the screen does not set.
 *
 *  4. The "not sent" badge lands on the row that is actually unsent, with a
 *     confirmed row and an in-flight row on screen beside it to prove the
 *     badge is not simply rendered for every row.
 *
 * BOTH LOCALES, ALWAYS. See `src/test-utils/render.tsx` — Arabic is this
 * app's primary language and is where both device-found plural defects lived.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, waitFor } from "@testing-library/react-native";
import type { ReactElement } from "react";

import { renderWithProviders } from "../test-utils/render";
import type { Locale } from "../i18n";
import type {
  ExerciseTarget,
  SessionSetRow,
} from "../workout/activeSessionLogic";
import type { WorkoutSetData } from "../api/workouts";

/**
 * The HTTP transport. `api/client.ts` throws at import time when
 * `EXPO_PUBLIC_API_BASE_URL` is unset and jest loads no `.env`, so without
 * this the suite dies before its first test. Same category as jest.setup.js's
 * native doubles: it supplies a runtime, it does not change behaviour.
 */
jest.mock("../api/client", () => ({
  client: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() },
}));

jest.mock("../api/workouts", () => ({
  createSet: jest.fn(),
  finishWorkout: jest.fn(),
  abandonWorkout: jest.fn(),
  getActiveWorkout: jest.fn(),
  getWorkout: jest.fn(),
}));

jest.mock("../api/program", () => ({ getProgramDay: jest.fn() }));

import { createSet, finishWorkout } from "../api/workouts";
import { useActiveSessionStore } from "../workout/activeSession";
import ActiveWorkout from "../../app/(app)/workout/active";

const mockedCreateSet = createSet as jest.MockedFunction<typeof createSet>;
const mockedFinishWorkout = finishWorkout as jest.MockedFunction<typeof finishWorkout>;

const EXERCISE_ID = "ex-bench";

/**
 * `computePrefill` falls back to `lastPerformance` when no set for this
 * exercise has been logged yet, so these two numbers are what the reps and
 * weight fields hold on first render — and therefore what pressing Log Set
 * sends without the test typing anything. Driving the screen through its own
 * pre-fill rather than through synthetic field input is deliberate: §8.3.2's
 * one-tap path is the behaviour under test.
 */
const PREFILL_REPS = 8;
const PREFILL_WEIGHT = 60;

function exerciseTarget(): ExerciseTarget {
  return {
    exerciseId: EXERCISE_ID,
    slug: "barbell-bench-press",
    name: "Barbell Bench Press",
    primaryMuscle: "chest",
    targetSets: 3,
    targetRepsMin: 6,
    targetRepsMax: 10,
    restSeconds: 120,
    lastPerformance: { reps: PREFILL_REPS, weightKg: PREFILL_WEIGHT },
  };
}

/** The server's representation of an acknowledged set. */
function setData(localId: string, reps: number, weightKg: number): WorkoutSetData {
  return {
    id: `srv-${localId}`,
    exercise_id: EXERCISE_ID,
    set_index: 1,
    reps,
    weight_kg: weightKg,
    rpe: null,
    is_warmup: false,
    logged_at: "2026-08-29T10:00:00Z",
    derived: { volume_kg: reps * weightKg, e1rm_kg: weightKg * 1.2 },
  };
}

/** A row the server has acknowledged. */
function confirmedRow(localId: string, reps: number, weightKg: number): SessionSetRow {
  return { kind: "confirmed", localId, exerciseId: EXERCISE_ID, data: setData(localId, reps, weightKg) };
}

/** A row that failed to send and is sitting there waiting for a retry. */
function pendingRow(localId: string, sending = false): SessionSetRow {
  return {
    kind: "pending",
    localId,
    exerciseId: EXERCISE_ID,
    input: { reps: PREFILL_REPS, weightKg: PREFILL_WEIGHT, rpe: null, isWarmup: false },
    sending,
    errorCode: sending ? null : "GENERIC",
  };
}

function withQuery(ui: ReactElement): ReactElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

/**
 * Seeds the real store and renders the real screen.
 *
 * `sessionId` is set, which is what makes the screen's `useFocusEffect` ->
 * `ensureFresh()` a genuine no-op: `ensureFresh` returns immediately when
 * `sessionId !== null` (activeSession.ts:132). Nothing is stubbed to achieve
 * that — the production guard does it — so the hydration path stays honest.
 */
async function renderActive(locale: Locale, sets: SessionSetRow[] = []) {
  useActiveSessionStore.setState({
    status: "ready",
    loadErrorCode: null,
    sessionId: "sess-1",
    programDayId: "day-1",
    dayLabelKey: "plan.day.fullBody",
    startedAt: "2026-08-29T09:30:00Z",
    exercises: [exerciseTarget()],
    currentExerciseIndex: 0,
    sets,
    sessionTotals: { sets: sets.length, volumeKg: 0 },
    restEndsAt: null,
    restPausedRemainingSeconds: null,
    lastSetRecord: null,
    lastSetRecordNonce: 0,
    finishing: false,
    abandoning: false,
  });
  return renderWithProviders(withQuery(<ActiveWorkout />), { locale });
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("logging a set puts it on screen", () => {
  /**
   * The row's text is built in one <Text> as
   * `setLabel · reps × weight weightUnit`, so the assertion is the whole
   * user-visible line rather than the numbers in isolation — a row that
   * rendered the reps where the weight belongs would still pass a
   * `getByText("60")`.
   *
   * The server's answer is held back deliberately, rather than pre-resolved,
   * so the two halves of §8.3.5's optimistic write can be asserted apart:
   *
   *   - the row is on screen, marked "sending", while the request is still in
   *     flight — the guarantee the whole optimistic design exists for;
   *   - and it is STILL there, with the same reps and weight and no badge,
   *     once the response lands. The optimistic row and the confirmed row are
   *     two different objects (`resolveConfirmedSet` swaps one for the other),
   *     so only checking after confirmation would miss the first and only
   *     checking before would miss the second.
   *
   * Resolving inside `act` is also what keeps the store's post-response
   * `set()` (activeSession.ts:319) inside React's render window; left to
   * settle on its own it lands after the assertion and React warns that the
   * update was not wrapped in `act(…)`.
   */
  it.each<[Locale, string, string]>([
    ["ar", `المجموعة 1 · ${PREFILL_REPS} × ${PREFILL_WEIGHT} كجم`, "جارٍ الإرسال…"],
    ["en", `Set 1 · ${PREFILL_REPS} × ${PREFILL_WEIGHT} kg`, "Sending…"],
  ])(
    "%s: one tap on Log Set adds a row carrying the reps and weight",
    async (locale, expected, sendingBadge) => {
      let answer: (() => void) | undefined;
      mockedCreateSet.mockReturnValue(
        new Promise((resolve) => {
          answer = () =>
            resolve({
              set: setData("local-1", PREFILL_REPS, PREFILL_WEIGHT),
              session_totals: { sets: 1, volume_kg: PREFILL_REPS * PREFILL_WEIGHT },
              is_record: null,
            });
        }),
      );

      const { getByTestId, getByText, queryByText } = await renderActive(locale);

      fireEvent.press(getByTestId("active-workout-log-set"));

      // Before the server has answered.
      await waitFor(() => expect(getByText(expected)).toBeTruthy());
      expect(getByText(sendingBadge)).toBeTruthy();

      // The values that reached the API are the pre-filled ones, un-mangled.
      expect(mockedCreateSet).toHaveBeenCalledWith(
        "sess-1",
        expect.objectContaining({ reps: PREFILL_REPS, weight_kg: PREFILL_WEIGHT }),
      );

      // After it answers.
      await act(async () => {
        answer?.();
      });
      expect(queryByText(sendingBadge)).toBeNull();
      expect(getByText(expected)).toBeTruthy();
    },
  );
});

describe("the unsent-sets dialog agrees with its count", () => {
  /**
   * Arabic. Four counts, four different sentences.
   *
   * 1 and 2 are the ones that matter most: their strings are written out in
   * words and contain no digit at all, so a regression to a one/other rule
   * renders «1 مجموعة» — grammatical-looking, wrong, and invisible to any
   * test that only checked that the number appeared.
   *
   * 11 (`many`) is the category English has no counterpart for. A fix that
   * only distinguishes singular from plural passes 3 and fails here.
   */
  it.each<[number, string]>([
    [1, "مجموعة واحدة لم تُرسل بعد. أعد المحاولة الآن، أو تجاهلها وأنهِ التمرين بدونها."],
    [2, "مجموعتان لم تُرسلا بعد. أعد المحاولة الآن، أو تجاهلهما وأنهِ التمرين بدونهما."],
    [3, "3 مجموعات لم تُرسل بعد. أعد المحاولة الآن، أو تجاهلها وأنهِ التمرين بدونها."],
    [11, "11 مجموعة لم تُرسل بعد. أعد المحاولة الآن، أو تجاهلها وأنهِ التمرين بدونها."],
  ])("Arabic: %i unsent sets", async (count, expected) => {
    const rows = Array.from({ length: count }, (_, i) => pendingRow(`local-${i}`));
    const { getByTestId, getByText } = await renderActive("ar", rows);

    fireEvent.press(getByTestId("active-workout-finish"));

    // `waitFor`, not a bare expect: React 19 commits this state change
    // asynchronously, so the dialog is not on screen the instant press returns.
    await waitFor(() => expect(getByText("لديك مجموعات لم تُرسل")).toBeTruthy());
    expect(getByText(expected)).toBeTruthy();
  });

  it.each<[number, string]>([
    [1, "1 set hasn't been sent yet. Retry now, or discard it and finish without it."],
    [2, "2 sets haven't been sent yet. Retry now, or discard them and finish without them."],
    [3, "3 sets haven't been sent yet. Retry now, or discard them and finish without them."],
    [11, "11 sets haven't been sent yet. Retry now, or discard them and finish without them."],
  ])("English: %i unsent sets", async (count, expected) => {
    const rows = Array.from({ length: count }, (_, i) => pendingRow(`local-${i}`));
    const { getByTestId, getByText } = await renderActive("en", rows);

    fireEvent.press(getByTestId("active-workout-finish"));

    await waitFor(() => expect(getByText("You have unsent sets")).toBeTruthy());
    expect(getByText(expected)).toBeTruthy();
  });
});

describe("finish does not proceed while sets are unsent", () => {
  it.each<[Locale, string]>([
    ["ar", "إنهاء هذا التمرين؟"],
    ["en", "Finish this workout?"],
  ])("%s: the finish confirm never opens and the session is not finished", async (locale, confirmTitle) => {
    const { getByTestId, getByText, queryByText } = await renderActive(locale, [
      pendingRow("local-1"),
    ]);

    fireEvent.press(getByTestId("active-workout-finish"));

    // Wait for the press to have DONE something first. Asserting the absence
    // of the confirm without this would also pass on a screen whose Finish
    // button did nothing at all — the failure mode this pair exists to rule
    // out (see the sibling test below).
    const unsentTitle = locale === "ar" ? "لديك مجموعات لم تُرسل" : "You have unsent sets";
    await waitFor(() => expect(getByText(unsentTitle)).toBeTruthy());

    // The unsent dialog took the press instead of the finish confirm.
    expect(queryByText(confirmTitle)).toBeNull();
    expect(mockedFinishWorkout).not.toHaveBeenCalled();
  });

  it.each<[Locale, string]>([
    ["ar", "إنهاء هذا التمرين؟"],
    ["en", "Finish this workout?"],
  ])("%s: with every row confirmed, the same press DOES open the confirm", async (locale, confirmTitle) => {
    // The other half of the claim. Without this, a screen whose Finish button
    // was simply broken would pass the test above for the wrong reason.
    const { getByTestId, getByText } = await renderActive(locale, [
      confirmedRow("local-1", PREFILL_REPS, PREFILL_WEIGHT),
    ]);

    fireEvent.press(getByTestId("active-workout-finish"));

    await waitFor(() => expect(getByText(confirmTitle)).toBeTruthy());
  });
});

describe("the unsent marker lands on the unsent row", () => {
  /**
   * Three rows at once, one of each kind. Asserting within each row's own
   * testID (`active-workout-set-<localId>`) is what makes this a test of
   * placement rather than of mere presence: a screen that stamped "not sent"
   * on every row would satisfy a bare `getByText("لم تُرسل")`.
   */
  it.each<[Locale, string, string]>([
    ["ar", "لم تُرسل", "جارٍ الإرسال…"],
    ["en", "Not sent", "Sending…"],
  ])("%s: only the failed row is marked", async (locale, unsentBadge, sendingBadge) => {
    const { getByTestId, getAllByText } = await renderActive(locale, [
      confirmedRow("row-confirmed", PREFILL_REPS, PREFILL_WEIGHT),
      pendingRow("row-unsent", false),
      pendingRow("row-sending", true),
    ]);

    const confirmed = getByTestId("active-workout-set-row-confirmed");
    const unsent = getByTestId("active-workout-set-row-unsent");
    const sending = getByTestId("active-workout-set-row-sending");

    // Exactly one row carries the unsent badge, and it is the failed one.
    expect(getAllByText(unsentBadge)).toHaveLength(1);
    expect(within(unsent, unsentBadge)).toBe(true);
    expect(within(confirmed, unsentBadge)).toBe(false);
    expect(within(sending, unsentBadge)).toBe(false);

    // The in-flight row says so instead of claiming it failed.
    expect(within(sending, sendingBadge)).toBe(true);
    expect(within(unsent, sendingBadge)).toBe(false);

    // And the confirmed row is marked neither way — it is simply a result.
    expect(within(confirmed, sendingBadge)).toBe(false);
  });
});

/**
 * True when `text` is rendered anywhere inside `node`'s subtree. Written here
 * rather than reached for from the library because RNTL's own `within()`
 * scopes queries by host element and these rows nest their badges a couple of
 * levels down; walking the tree is both simpler to read and immune to the
 * intermediate <View>s changing.
 */
function within(node: { children: unknown }, text: string): boolean {
  const visit = (child: unknown): boolean => {
    if (typeof child === "string") return child === text;
    if (Array.isArray(child)) return child.some(visit);
    if (child && typeof child === "object" && "children" in child) {
      return visit((child as { children: unknown }).children);
    }
    return false;
  };
  return visit(node.children);
}
