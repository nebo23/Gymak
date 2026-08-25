/**
 * §8.3.7: "state lives in src/workout/activeSession.ts and the server, never
 * only in a component." Built with plain Zustand `create` (matching
 * auth/session.ts's own precedent) so the module-level store -- not any
 * screen's component tree -- is the thing that survives rotation and
 * backgrounding; a remount of active.tsx just re-reads this store instead of
 * re-deriving anything.
 *
 * P2-ADR-08: the unsent-set queue is in-memory and dies with the process --
 * deliberately not persisted (no `zustand/middleware` `persist`, no
 * SecureStore). Confirmed sets are never actually lost, though: they are the
 * server's own truth, and `ensureFresh` below re-reads them from
 * `GET /workouts/active` + `GET /workouts/{id}` on any cold mount that finds
 * no session already in memory.
 *
 * The pure state-transition functions this store's actions delegate to live
 * in ./activeSessionLogic.ts, not here, and are re-exported below so nothing
 * outside this pair of files needs to know the split exists. That module has
 * zero value-level dependency on `api/*` (type-only imports, erased at
 * compile time); this one imports the real `api/workouts.ts` / `api/program.ts`
 * to do actual network I/O, which is exactly what pulls in `expo-router` and
 * therefore `react-native` -- fine for the app, fatal for vitest, whose plain
 * transform cannot parse `react-native`'s Flow-syntax source. Every RN-runtime
 * side effect (AccessibilityInfo, AppState, BackHandler) also stays out of
 * both files on purpose; the screen owns those.
 */
import { create, type StoreApi } from "zustand";

import {
  abandonWorkout,
  createSet,
  finishWorkout,
  getActiveWorkout,
  getWorkout,
  type SetRecordData,
  type WorkoutAbandonResponse,
  type WorkoutFinishResponse,
} from "../api/workouts";
import { getProgramDay, type ProgramDayExerciseDetail } from "../api/program";
import type { ExerciseListItem } from "../api/exercises";
import { parseApiError, resolveErrorCode, type ResolvedErrorCode } from "../api/errors";
import {
  computeRemainingSeconds,
  computeSessionTotals,
  discardUnsentSets,
  exerciseTargetFromLibraryItem,
  exerciseTargetFromProgramDay,
  exerciseTargetFromSessionGroup,
  findMostRecentExerciseIndex,
  generateLocalId,
  resolveConfirmedSet,
  resolveFailedSet,
  selectExerciseTarget,
  type ExerciseTarget,
  type SessionSetRow,
  type SessionTotals,
  type SetInput,
} from "./activeSessionLogic";

export * from "./activeSessionLogic";

export type ActiveSessionStatus = "idle" | "loading" | "ready" | "noSession" | "error";

interface ActiveSessionState {
  status: ActiveSessionStatus;
  loadErrorCode: ResolvedErrorCode | null;

  sessionId: string | null;
  programDayId: string | null;
  dayLabelKey: string | null;
  startedAt: string | null;
  exercises: ExerciseTarget[];
  currentExerciseIndex: number;
  sets: SessionSetRow[];
  sessionTotals: SessionTotals | null;

  restEndsAt: number | null;
  restPausedRemainingSeconds: number | null;

  lastSetRecord: SetRecordData | null;
  lastSetRecordNonce: number;

  finishing: boolean;
  abandoning: boolean;

  /** Rehydrates from the server if nothing is in memory yet; a no-op if a
   * session is already loaded (the rotation/remount fast path). */
  ensureFresh: () => Promise<void>;
  setCurrentExerciseIndex: (index: number) => void;
  /** T-30 gap 1: the hand-back from the §5.2 library sheet opened mid-session
   * (`/(app)/exercises?picker=1`). Adds the exercise to this session if it is
   * not already in the list and makes it current, so the next Log Set targets
   * it. Local only -- §5.7 needs no announcement of an exercise ahead of a set,
   * and a picked exercise the user never logs against must leave no trace. */
  selectAdHocExercise: (item: ExerciseListItem) => void;
  logSet: (input: SetInput) => Promise<void>;
  retrySet: (localId: string) => Promise<void>;
  retryAllUnsent: () => Promise<void>;
  discardUnsent: () => void;
  pauseRest: () => void;
  resumeRest: () => void;
  skipRest: () => void;
  completeRest: () => void;
  finish: (notes?: string) => Promise<WorkoutFinishResponse>;
  abandon: () => Promise<WorkoutAbandonResponse>;
  reset: () => void;
}

const initialState = {
  status: "idle" as ActiveSessionStatus,
  loadErrorCode: null as ResolvedErrorCode | null,
  sessionId: null as string | null,
  programDayId: null as string | null,
  dayLabelKey: null as string | null,
  startedAt: null as string | null,
  exercises: [] as ExerciseTarget[],
  currentExerciseIndex: 0,
  sets: [] as SessionSetRow[],
  sessionTotals: null as SessionTotals | null,
  restEndsAt: null as number | null,
  restPausedRemainingSeconds: null as number | null,
  lastSetRecord: null as SetRecordData | null,
  lastSetRecordNonce: 0,
  finishing: false,
  abandoning: false,
};

export const useActiveSessionStore = create<ActiveSessionState>((set, get) => ({
  ...initialState,

  ensureFresh: async () => {
    if (get().sessionId !== null) return;
    set({ status: "loading", loadErrorCode: null });
    try {
      const active = await getActiveWorkout();
      if (!active) {
        set({ status: "noSession" });
        return;
      }

      const detail = await getWorkout(active.session.id);
      const programDayId = detail.session.program_day_id;

      let dayExercises: ProgramDayExerciseDetail[] | null = null;
      let dayLabelKey: string | null = detail.session.label_key;
      let dayFetchFailed = false;
      if (programDayId) {
        try {
          const day = await getProgramDay(programDayId);
          dayExercises = day.day.exercises;
          dayLabelKey = day.day.label_key;
        } catch {
          dayFetchFailed = true;
        }
      }

      if (dayFetchFailed && detail.session.exercises.length === 0) {
        set({ status: "error", loadErrorCode: "GENERIC" });
        return;
      }

      const exercises: ExerciseTarget[] = dayExercises
        ? dayExercises.map(exerciseTargetFromProgramDay)
        : detail.session.exercises.map(exerciseTargetFromSessionGroup);

      const sets: SessionSetRow[] = detail.session.exercises.flatMap((group) =>
        group.sets.map(
          (data): SessionSetRow => ({
            kind: "confirmed",
            localId: `server-${data.id}`,
            exerciseId: group.exercise.id,
            data,
          }),
        ),
      );

      set({
        status: "ready",
        loadErrorCode: null,
        sessionId: active.session.id,
        programDayId,
        dayLabelKey,
        startedAt: active.session.started_at,
        exercises,
        sets,
        sessionTotals: computeSessionTotals(sets),
        currentExerciseIndex: findMostRecentExerciseIndex(exercises, sets),
      });
    } catch (err) {
      set({ status: "error", loadErrorCode: resolveErrorCode(err) });
    }
  },

  setCurrentExerciseIndex: (index) => set({ currentExerciseIndex: index }),

  selectAdHocExercise: (item) =>
    set((state) => {
      const next = selectExerciseTarget(state.exercises, exerciseTargetFromLibraryItem(item));
      return { exercises: next.exercises, currentExerciseIndex: next.index };
    }),

  logSet: async (input) => {
    const { sessionId, exercises, currentExerciseIndex } = get();
    const exercise = exercises[currentExerciseIndex];
    if (!sessionId || !exercise) return;

    const localId = generateLocalId();
    const pendingRow: SessionSetRow = {
      kind: "pending",
      localId,
      exerciseId: exercise.exerciseId,
      input,
      sending: true,
      errorCode: null,
    };
    set((state) => ({
      sets: [...state.sets, pendingRow],
      // §8.3.4: starts the instant the set is logged, optimistically -- the
      // user is resting physically regardless of what the network is doing.
      // GRestTimer re-seeds itself the moment the parent passes a changed
      // `seconds` value, so simply moving `restEndsAt` forward is enough --
      // no separate nonce is needed to force a remount.
      restEndsAt: Date.now() + exercise.restSeconds * 1000,
      restPausedRemainingSeconds: null,
    }));

    await sendPendingSet(sessionId, exercise.exerciseId, localId, input, set);
  },

  retrySet: async (localId) => {
    const { sessionId, sets } = get();
    const row = sets.find((candidate) => candidate.localId === localId);
    if (!sessionId || !row || row.kind !== "pending" || row.sending) return;

    set((state) => ({
      sets: state.sets.map((candidate) =>
        candidate.localId === localId ? { ...candidate, sending: true, errorCode: null } : candidate,
      ),
    }));
    await sendPendingSet(sessionId, row.exerciseId, localId, row.input, set);
  },

  retryAllUnsent: async () => {
    const unsent = get().sets.filter((row) => row.kind === "pending" && !row.sending);
    // Bounded by construction: a manual, human-paced batch of the currently
    // unsent rows (typically a handful), fired once -- never a polling loop
    // -- which is what keeps this nowhere near §7.3's 300/hour set limit.
    await Promise.allSettled(unsent.map((row) => get().retrySet(row.localId)));
  },

  discardUnsent: () => set((state) => ({ sets: discardUnsentSets(state.sets) })),

  pauseRest: () =>
    set((state) => {
      if (state.restEndsAt === null || state.restPausedRemainingSeconds !== null) return state;
      return {
        restPausedRemainingSeconds: computeRemainingSeconds(state.restEndsAt, Date.now()),
      };
    }),

  resumeRest: () =>
    set((state) => {
      if (state.restPausedRemainingSeconds === null) return state;
      return {
        restEndsAt: Date.now() + state.restPausedRemainingSeconds * 1000,
        restPausedRemainingSeconds: null,
      };
    }),

  skipRest: () => set({ restEndsAt: null, restPausedRemainingSeconds: null }),

  completeRest: () =>
    set((state) =>
      state.restEndsAt === null ? state : { restEndsAt: null, restPausedRemainingSeconds: null },
    ),

  finish: async (notes) => {
    const { sessionId } = get();
    if (!sessionId) throw new Error("No active session to finish.");
    set({ finishing: true });
    try {
      const response = await finishWorkout(sessionId, notes);
      return response;
    } finally {
      set({ finishing: false });
    }
  },

  abandon: async () => {
    const { sessionId } = get();
    if (!sessionId) throw new Error("No active session to abandon.");
    set({ abandoning: true });
    try {
      const response = await abandonWorkout(sessionId);
      return response;
    } finally {
      set({ abandoning: false });
    }
  },

  reset: () => set({ ...initialState }),
}));

async function sendPendingSet(
  sessionId: string,
  exerciseId: string,
  localId: string,
  input: SetInput,
  set: StoreApi<ActiveSessionState>["setState"],
): Promise<void> {
  try {
    const response = await createSet(sessionId, {
      exercise_id: exerciseId,
      reps: input.reps,
      weight_kg: input.weightKg,
      is_warmup: input.isWarmup,
      ...(input.rpe !== null ? { rpe: input.rpe } : {}),
    });
    set((state) => ({
      sets: resolveConfirmedSet(state.sets, localId, response.set),
      sessionTotals: { sets: response.session_totals.sets, volumeKg: response.session_totals.volume_kg },
      lastSetRecord: response.is_record,
      lastSetRecordNonce: state.lastSetRecordNonce + 1,
    }));
  } catch (err) {
    const problem = parseApiError(err);
    set((state) => ({ sets: resolveFailedSet(state.sets, localId, problem.code) }));
  }
}
