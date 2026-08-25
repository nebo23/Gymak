/**
 * Pure-function coverage for the active-workout session state (§8.3). The
 * Zustand store and the screen itself are exercised on-device per §10.2 --
 * vitest.config.ts scopes this project's suite to `src/**\/*.test.ts` for
 * exactly that reason (see its own comment). These are the functions
 * activeSession.ts's store actions delegate to for every state transition
 * that matters: pre-fill, the unsent-set gate, wall-clock rest arithmetic,
 * and resuming on the right exercise.
 */
import { describe, expect, it } from "vitest";

import {
  FALLBACK_REST_SECONDS,
  computePrefill,
  computeRemainingSeconds,
  discardUnsentSets,
  exerciseTargetFromLibraryItem,
  findMostRecentExerciseIndex,
  hasUnsentSets,
  resolveConfirmedSet,
  resolveFailedSet,
  selectExerciseTarget,
  type ExerciseTarget,
  type SessionSetRow,
} from "./activeSessionLogic";
import type { ExerciseListItem } from "../api/exercises";
import type { WorkoutSetData } from "../api/workouts";

const squat: ExerciseTarget = {
  exerciseId: "ex-squat",
  slug: "barbell-back-squat",
  name: "Barbell back squat",
  primaryMuscle: "quads",
  targetSets: 4,
  targetRepsMin: 6,
  targetRepsMax: 8,
  restSeconds: 150,
  lastPerformance: { reps: 8, weightKg: 60 },
};

const bench: ExerciseTarget = {
  exerciseId: "ex-bench",
  slug: "barbell-bench-press",
  name: "Barbell bench press",
  primaryMuscle: "chest",
  targetSets: 3,
  targetRepsMin: 8,
  targetRepsMax: 10,
  restSeconds: 120,
  lastPerformance: null,
};

function confirmedRow(
  exerciseId: string,
  overrides: Partial<WorkoutSetData> & { loggedAt?: string } = {},
): SessionSetRow {
  const { loggedAt, ...dataOverrides } = overrides;
  const data: WorkoutSetData = {
    id: `set-${Math.random()}`,
    exercise_id: exerciseId,
    set_index: 1,
    reps: 8,
    weight_kg: 60,
    rpe: null,
    is_warmup: false,
    logged_at: loggedAt ?? "2026-08-13T17:00:00Z",
    derived: { volume_kg: 480, e1rm_kg: 76 },
    ...dataOverrides,
  };
  return { kind: "confirmed", localId: `server-${data.id}`, exerciseId, data };
}

function pendingRow(
  exerciseId: string,
  overrides: Partial<{ localId: string; sending: boolean; errorCode: string | null }> = {},
): SessionSetRow {
  return {
    kind: "pending",
    localId: overrides.localId ?? "local-1",
    exerciseId,
    input: { reps: 5, weightKg: 40, rpe: null, isWarmup: false },
    sending: overrides.sending ?? false,
    errorCode: (overrides.errorCode as never) ?? null,
  };
}

describe("computePrefill", () => {
  it("uses the previous set of the same exercise in this session when one exists", () => {
    const sets = [confirmedRow("ex-squat", { reps: 6, weight_kg: 65 })];
    expect(computePrefill(squat, sets)).toEqual({ reps: 6, weightKg: 65 });
  });

  it("only looks at the most recent set for that exercise, not the first", () => {
    const sets = [
      confirmedRow("ex-squat", { reps: 8, weight_kg: 60 }),
      confirmedRow("ex-bench", { reps: 10, weight_kg: 40 }),
      confirmedRow("ex-squat", { reps: 6, weight_kg: 70 }),
    ];
    expect(computePrefill(squat, sets)).toEqual({ reps: 6, weightKg: 70 });
  });

  it("reads a still-unsent set's own input, not stale server data", () => {
    const sets = [pendingRow("ex-squat")];
    expect(computePrefill(squat, sets)).toEqual({ reps: 5, weightKg: 40 });
  });

  it("falls back to last_performance for the first set of the session", () => {
    expect(computePrefill(squat, [])).toEqual({ reps: 8, weightKg: 60 });
  });

  it("falls back to the target's minimum reps at zero weight with no history at all", () => {
    expect(computePrefill(bench, [])).toEqual({ reps: 8, weightKg: 0 });
  });

  it("falls back to a generic default when there is no exercise selected", () => {
    expect(computePrefill(undefined, [])).toEqual({ reps: 8, weightKg: 0 });
  });
});

describe("hasUnsentSets", () => {
  it("is false when every set is confirmed", () => {
    expect(hasUnsentSets([confirmedRow("ex-squat")])).toBe(false);
  });

  it("is true for a set still sending", () => {
    expect(hasUnsentSets([pendingRow("ex-squat", { sending: true })])).toBe(true);
  });

  it("is true for a set that failed and is waiting on retry", () => {
    expect(hasUnsentSets([pendingRow("ex-squat", { sending: false })])).toBe(true);
  });
});

describe("computeRemainingSeconds", () => {
  it("is the full duration right when the timer starts", () => {
    const now = 1_000_000;
    expect(computeRemainingSeconds(now + 150_000, now)).toBe(150);
  });

  it("counts down as time passes", () => {
    const now = 1_000_000;
    expect(computeRemainingSeconds(now + 150_000, now + 90_000)).toBe(60);
  });

  it("never goes negative once the timer has elapsed", () => {
    const now = 1_000_000;
    expect(computeRemainingSeconds(now - 5_000, now)).toBe(0);
  });

  it("is zero when there is no running timer", () => {
    expect(computeRemainingSeconds(null, Date.now())).toBe(0);
  });
});

describe("resolveConfirmedSet / resolveFailedSet", () => {
  it("replaces a pending row with a confirmed one at the same position", () => {
    const sets = [confirmedRow("ex-squat"), pendingRow("ex-bench", { localId: "local-2" })];
    const serverData: WorkoutSetData = {
      id: "set-9",
      exercise_id: "ex-bench",
      set_index: 1,
      reps: 5,
      weight_kg: 40,
      rpe: null,
      is_warmup: false,
      logged_at: "2026-08-13T17:05:00Z",
      derived: { volume_kg: 200, e1rm_kg: 46.7 },
    };
    const result = resolveConfirmedSet(sets, "local-2", serverData);
    expect(result).toHaveLength(2);
    expect(result[1]).toEqual({
      kind: "confirmed",
      localId: "local-2",
      exerciseId: "ex-bench",
      data: serverData,
    });
    // The other row is untouched.
    expect(result[0]).toBe(sets[0]);
  });

  it("marks a pending row unsent with the resolved error code, leaving other rows alone", () => {
    const sets = [pendingRow("ex-squat", { localId: "local-3", sending: true })];
    const result = resolveFailedSet(sets, "local-3", "OFFLINE");
    expect(result[0]).toMatchObject({ kind: "pending", sending: false, errorCode: "OFFLINE" });
  });
});

describe("discardUnsentSets", () => {
  it("drops failed/unsent rows but keeps confirmed ones", () => {
    const sets = [
      confirmedRow("ex-squat"),
      pendingRow("ex-bench", { localId: "local-4", sending: false }),
    ];
    expect(discardUnsentSets(sets)).toEqual([sets[0]]);
  });

  it("does not drop a row that is still in flight", () => {
    const sets = [pendingRow("ex-squat", { localId: "local-5", sending: true })];
    expect(discardUnsentSets(sets)).toEqual(sets);
  });
});

describe("findMostRecentExerciseIndex", () => {
  const exercises = [squat, bench];

  it("returns 0 (the first exercise) when nothing has been logged yet", () => {
    expect(findMostRecentExerciseIndex(exercises, [])).toBe(0);
  });

  it("returns the index of the exercise whose set has the latest logged_at", () => {
    const sets = [
      confirmedRow("ex-squat", { loggedAt: "2026-08-13T17:00:00Z" }),
      confirmedRow("ex-bench", { loggedAt: "2026-08-13T17:10:00Z" }),
    ];
    expect(findMostRecentExerciseIndex(exercises, sets)).toBe(1);
  });

  it("ignores still-pending rows, which carry no server timestamp", () => {
    const sets = [
      confirmedRow("ex-squat", { loggedAt: "2026-08-13T17:00:00Z" }),
      pendingRow("ex-bench"),
    ];
    expect(findMostRecentExerciseIndex(exercises, sets)).toBe(0);
  });
});

// T-30 gap 1: the mid-session exercise picker's hand-back.
const curlLibraryItem: ExerciseListItem = {
  id: "ex-curl",
  slug: "dumbbell-biceps-curl",
  name: "Dumbbell biceps curl",
  primary_muscle: "biceps",
  secondary_muscles: ["forearms"],
  equipment: "dumbbell",
  movement_pattern: "elbow_flexion",
  is_custom: false,
  is_compound: false,
  difficulty: "beginner",
};

describe("exerciseTargetFromLibraryItem", () => {
  it("carries identity across and leaves every target field null", () => {
    const target = exerciseTargetFromLibraryItem(curlLibraryItem);
    expect(target).toEqual({
      exerciseId: "ex-curl",
      slug: "dumbbell-biceps-curl",
      name: "Dumbbell biceps curl",
      primaryMuscle: "biceps",
      targetSets: null,
      targetRepsMin: null,
      targetRepsMax: null,
      restSeconds: FALLBACK_REST_SECONDS,
      lastPerformance: null,
    });
  });
});

describe("selectExerciseTarget", () => {
  const dayExercises = [squat, bench];

  it("appends an exercise the day did not prescribe and makes it current", () => {
    const picked = exerciseTargetFromLibraryItem(curlLibraryItem);
    const result = selectExerciseTarget(dayExercises, picked);
    expect(result.index).toBe(dayExercises.length);
    expect(result.exercises).toHaveLength(dayExercises.length + 1);
    expect(result.exercises[result.index]).toBe(picked);
  });

  it("selects the existing entry instead of appending a duplicate", () => {
    const alreadyPresent = exerciseTargetFromLibraryItem({
      ...curlLibraryItem,
      id: "ex-bench",
      slug: "barbell-bench-press",
      name: "Barbell bench press",
    });
    const result = selectExerciseTarget(dayExercises, alreadyPresent);
    expect(result.index).toBe(1);
    expect(result.exercises).toBe(dayExercises);
    // The prescribed target survives -- the picked stand-in never overwrites it.
    expect(result.exercises[1]!.targetSets).toBe(bench.targetSets);
  });

  it("works from an empty session, which had no exercise to log against at all", () => {
    const picked = exerciseTargetFromLibraryItem(curlLibraryItem);
    const result = selectExerciseTarget([], picked);
    expect(result.index).toBe(0);
    expect(result.exercises).toEqual([picked]);
  });
});
