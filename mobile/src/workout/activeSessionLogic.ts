/**
 * The pure half of the active-workout session state, split out of
 * activeSession.ts so it has zero runtime dependency on `react-native` or
 * `expo-router` -- every import below is `import type`, which TypeScript
 * erases entirely at compile time. That is not a style preference: the
 * Zustand store in activeSession.ts imports the *real* `api/workouts.ts` /
 * `api/program.ts` at the value level, which pull in `expo-router`'s
 * `client.ts` dependency, whose transitive `react-native` source uses Flow
 * type syntax vitest's plain transform cannot parse (`SyntaxError: Unexpected
 * token 'typeof'`) -- confirmed by running the suite before this split
 * existed. `timezoneSync.ts` avoids the problem by having no external
 * imports at all; this module does the same by construction, so
 * `activeSession.test.ts` can import straight from here.
 *
 * activeSession.ts re-exports everything below, so nothing outside this
 * pair of files needs to know the split exists.
 */
import type { ProgramDayExerciseDetail } from "../api/program";
import type { SessionDetailExerciseGroup, WorkoutSetData } from "../api/workouts";
import type { ResolvedErrorCode } from "../api/errors";

// §5.4's day fetch has no target/rest data for an empty session's exercises,
// and §4.5's own rest_seconds CHECK floor is 30 -- this is only ever used on
// the unreachable-today empty-session path (no exercise picker exists until
// T-29), so it is a documented, honest fallback, not a real prescription.
export const FALLBACK_REST_SECONDS = 90;

export interface ExerciseTarget {
  exerciseId: string;
  slug: string;
  name: string;
  primaryMuscle: string;
  targetSets: number | null;
  targetRepsMin: number | null;
  targetRepsMax: number | null;
  restSeconds: number;
  lastPerformance: { reps: number; weightKg: number } | null;
}

export interface SetInput {
  reps: number;
  weightKg: number;
  rpe: number | null;
  isWarmup: boolean;
}

export type SessionSetRow =
  | { kind: "confirmed"; localId: string; exerciseId: string; data: WorkoutSetData }
  | {
      kind: "pending";
      localId: string;
      exerciseId: string;
      input: SetInput;
      sending: boolean;
      errorCode: ResolvedErrorCode | null;
    };

export interface PrefillValues {
  reps: number;
  weightKg: number;
}

export interface SessionTotals {
  sets: number;
  volumeKg: number;
}

export function exerciseTargetFromProgramDay(item: ProgramDayExerciseDetail): ExerciseTarget {
  return {
    exerciseId: item.exercise.id,
    slug: item.exercise.slug,
    name: item.exercise.name,
    primaryMuscle: item.exercise.primary_muscle,
    targetSets: item.target_sets,
    targetRepsMin: item.target_reps_min,
    targetRepsMax: item.target_reps_max,
    restSeconds: item.rest_seconds,
    lastPerformance: item.last_performance
      ? {
          reps: item.last_performance.best_set.reps,
          weightKg: item.last_performance.best_set.weight_kg,
        }
      : null,
  };
}

export function exerciseTargetFromSessionGroup(group: SessionDetailExerciseGroup): ExerciseTarget {
  return {
    exerciseId: group.exercise.id,
    slug: group.exercise.slug,
    name: group.exercise.name,
    primaryMuscle: group.exercise.primary_muscle,
    targetSets: null,
    targetRepsMin: null,
    targetRepsMax: null,
    restSeconds: FALLBACK_REST_SECONDS,
    lastPerformance: null,
  };
}

/** §8.3.2: "pre-fill from the user's previous set of that exercise in this
 * session, or from `last_performance` for the first set." `sets` is searched
 * from the end -- it is always append-ordered, so the last match is always
 * the most recent regardless of which exercise was "current" in between. */
export function computePrefill(
  exercise: ExerciseTarget | undefined,
  sets: SessionSetRow[],
): PrefillValues {
  if (exercise) {
    for (let i = sets.length - 1; i >= 0; i -= 1) {
      const row = sets[i];
      if (row.exerciseId !== exercise.exerciseId) continue;
      return row.kind === "confirmed"
        ? { reps: row.data.reps, weightKg: row.data.weight_kg }
        : { reps: row.input.reps, weightKg: row.input.weightKg };
    }
    if (exercise.lastPerformance) {
      return { reps: exercise.lastPerformance.reps, weightKg: exercise.lastPerformance.weightKg };
    }
    if (exercise.targetRepsMin !== null) {
      return { reps: exercise.targetRepsMin, weightKg: 0 };
    }
  }
  return { reps: 8, weightKg: 0 };
}

/** §8.5 "Unsent set": blocks Finish while true. A set still `sending` counts
 * too -- Finish must wait for the in-flight request to actually resolve. */
export function hasUnsentSets(sets: SessionSetRow[]): boolean {
  return sets.some((row) => row.kind === "pending");
}

/** §8.3.4's wall-clock arithmetic, isolated so it is testable without a clock
 * mock: given the stored end timestamp and "now", how many seconds remain. */
export function computeRemainingSeconds(endsAt: number | null, now: number): number {
  if (endsAt === null) return 0;
  return Math.max(0, Math.round((endsAt - now) / 1000));
}

export function resolveConfirmedSet(
  sets: SessionSetRow[],
  localId: string,
  data: WorkoutSetData,
): SessionSetRow[] {
  return sets.map((row) =>
    row.localId === localId
      ? { kind: "confirmed" as const, localId, exerciseId: row.exerciseId, data }
      : row,
  );
}

export function resolveFailedSet(
  sets: SessionSetRow[],
  localId: string,
  errorCode: ResolvedErrorCode,
): SessionSetRow[] {
  return sets.map((row) =>
    row.kind === "pending" && row.localId === localId ? { ...row, sending: false, errorCode } : row,
  );
}

/** P2-ADR-08's "discard unsent": these sets were never accepted by the server
 * (that is what "unsent" means), so there is nothing to delete server-side --
 * this only ever drops local rows. A row still `sending` is left alone; its
 * own response handler resolves it (or leaves it retryable) when it lands. */
export function discardUnsentSets(sets: SessionSetRow[]): SessionSetRow[] {
  return sets.filter((row) => row.kind !== "pending" || row.sending);
}

export function computeSessionTotals(sets: SessionSetRow[]): SessionTotals {
  let count = 0;
  let volumeKg = 0;
  for (const row of sets) {
    if (row.kind !== "confirmed" || row.data.is_warmup) continue;
    count += 1;
    volumeKg += row.data.derived.volume_kg;
  }
  return { sets: count, volumeKg: Math.round(volumeKg * 100) / 100 };
}

/** Resume lands on the exercise of the most recently logged set, not
 * necessarily the first in the day -- "continue where you left off." */
export function findMostRecentExerciseIndex(
  exercises: ExerciseTarget[],
  sets: SessionSetRow[],
): number {
  let latestTime = -Infinity;
  let latestExerciseId: string | null = null;
  for (const row of sets) {
    if (row.kind !== "confirmed") continue;
    const loggedAt = Date.parse(row.data.logged_at);
    if (loggedAt > latestTime) {
      latestTime = loggedAt;
      latestExerciseId = row.exerciseId;
    }
  }
  if (latestExerciseId !== null) {
    const index = exercises.findIndex((exercise) => exercise.exerciseId === latestExerciseId);
    if (index >= 0) return index;
  }
  return 0;
}

export function generateLocalId(): string {
  return `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
