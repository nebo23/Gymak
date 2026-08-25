/**
 * §5.2 (GET /exercises, GET /exercises/{id}), P2-FR-001. See
 * backend/app/schemas/exercise.py for the authoritative shapes. `name` (and, on the
 * detail response, `instructions`) arrive already resolved to the caller's profile
 * language (§5.2's own exception to "the server never sends display text") -- never
 * re-translated on the device.
 */
import { client } from "./client";

export interface ExerciseListItem {
  id: string;
  slug: string;
  name: string;
  primary_muscle: string;
  secondary_muscles: string[];
  equipment: string;
  movement_pattern: string;
  is_compound: boolean;
  difficulty: string;
  /** True for a row this user created. The server derives it from `user_id` and never
   * sends the owner id itself. Drives the list badge and whether edit/delete show. */
  is_custom: boolean;
}

export interface ExerciseDetailData extends ExerciseListItem {
  instructions: string;
}

export interface ExerciseListResponse {
  items: ExerciseListItem[];
  /** Opaque; pass back verbatim as `cursor` for the next page. Null on the last page. */
  next_cursor: string | null;
}

export interface ExerciseDetailResponse {
  exercise: ExerciseDetailData;
}

export interface ExerciseListParams {
  q?: string;
  muscle?: string;
  equipment?: string;
  cursor?: string;
}

/** §5.2. Filters combine with AND. `q` must be the user's untouched raw text --
 * T-16b's Arabic-aware normalisation (alef/yeh/teh-marbuta folding, harakat/tatweel
 * stripping) runs server-side only; doing any of that here would double-normalise
 * and break matches the server would otherwise find. */
export async function listExercises(params: ExerciseListParams = {}): Promise<ExerciseListResponse> {
  const response = await client.get<ExerciseListResponse>("/exercises", {
    params: {
      ...(params.q ? { q: params.q } : {}),
      ...(params.muscle ? { muscle: params.muscle } : {}),
      ...(params.equipment ? { equipment: params.equipment } : {}),
      ...(params.cursor ? { cursor: params.cursor } : {}),
    },
  });
  return response.data;
}

/** §5.2. A malformed or unknown id both resolve to the same 404
 * (`EXERCISE_NOT_FOUND`) -- see routers/exercises.py's own note on why. */
export async function getExercise(exerciseId: string): Promise<ExerciseDetailResponse> {
  const response = await client.get<ExerciseDetailResponse>(`/exercises/${exerciseId}`);
  return response.data;
}

// --- §5.11 GET /records, scoped to a single exercise -----------------------------
//
// Wrapped here rather than in a new api/records.ts: the exercise-detail screen is
// the only caller anywhere in the app so far (T-21's dashboard reads a different,
// pre-aggregated slice via schemas/metrics.py's RecentRecordData, not this
// endpoint), and this task's file list has no room to introduce a whole new api
// module for one scoped GET. Shapes mirror backend/app/schemas/metrics.py's
// RecordEntryData exactly.

export interface RecordExerciseRef {
  id: string;
  slug: string;
  name: string;
}

export interface HeaviestSetData {
  weight_kg: number;
  reps: number;
  session_id: string;
  local_date: string;
}

export interface BestE1rmData {
  value_kg: number;
  weight_kg: number;
  reps: number;
  local_date: string;
}

export interface BestSessionVolumeData {
  volume_kg: number;
  session_id: string;
  local_date: string;
}

export interface ExerciseRecordData {
  exercise: RecordExerciseRef;
  heaviest_set: HeaviestSetData;
  best_e1rm: BestE1rmData;
  best_session_volume: BestSessionVolumeData;
  total_sets: number;
}

interface RecordsResponse {
  records: ExerciseRecordData[];
}

/** §5.11: "Exercises the user has never performed are omitted entirely rather than
 * returned with nulls." `exercise_id` narrows the response to at most one entry, so
 * this resolves straight to that entry, or `null` when the user has never logged it
 * -- absence, not zeros, matching the spec's own wording exactly. */
export async function getExerciseRecord(exerciseId: string): Promise<ExerciseRecordData | null> {
  const response = await client.get<RecordsResponse>("/records", {
    params: { exercise_id: exerciseId },
  });
  return response.data.records[0] ?? null;
}


// --- Custom exercises -------------------------------------------------------------
//
// The owner-authorised departure from spec §1.2 ("Custom user-created exercises ...
// do not build"). Shapes mirror backend/app/schemas/exercise.py.
//
// One `name`, in whichever language the user typed: the server writes it to BOTH
// name columns, so a custom exercise never renders blank after a language switch.
// The four vocabulary fields are closed sets validated server-side against the same
// tuples the CHECK constraints are built from -- the picker UI offers exactly those
// values, so a rejection here means the two lists have drifted, not that the user
// did something unusual.

/** The closed vocabularies, mirroring backend/app/models/exercise.py. Kept here so
 * the create form can offer them; each value has an i18n key under
 * `exercises.vocab.*`, so nothing user-visible is derived from these strings. */
export const PRIMARY_MUSCLES = [
  "chest",
  "back",
  "lats",
  "traps",
  "front_delts",
  "side_delts",
  "rear_delts",
  "biceps",
  "triceps",
  "forearms",
  "quads",
  "hamstrings",
  "glutes",
  "calves",
  "abs",
  "obliques",
  "lower_back",
] as const;

export const EQUIPMENT = [
  "barbell",
  "dumbbell",
  "machine",
  "cable",
  "bodyweight",
  "kettlebell",
  "band",
] as const;

export const MOVEMENT_PATTERNS = [
  "squat",
  "hinge",
  "horizontal_push",
  "vertical_push",
  "horizontal_pull",
  "vertical_pull",
  "lunge",
  "carry",
  "isolation",
] as const;

export const DIFFICULTIES = ["beginner", "intermediate", "advanced"] as const;

export interface ExerciseCreateInput {
  name: string;
  primary_muscle: string;
  equipment: string;
  movement_pattern: string;
  difficulty: string;
  is_compound?: boolean;
  secondary_muscles?: string[];
  instructions?: string;
}

export type ExerciseUpdateInput = Partial<ExerciseCreateInput>;

export interface ExerciseDeleteResponse {
  id: string;
  is_active: boolean;
}

/** POST /exercises. 201 with the created row, already language-resolved. */
export async function createExercise(
  input: ExerciseCreateInput,
): Promise<ExerciseDetailResponse> {
  const response = await client.post<ExerciseDetailResponse>("/exercises", input);
  return response.data;
}

/** PATCH /exercises/{id}. Own rows only -- a seeded row is a 404, not a 403. */
export async function updateExercise(
  exerciseId: string,
  input: ExerciseUpdateInput,
): Promise<ExerciseDetailResponse> {
  const response = await client.patch<ExerciseDetailResponse>(
    `/exercises/${exerciseId}`,
    input,
  );
  return response.data;
}

/** DELETE /exercises/{id}. A SOFT delete: the row leaves the library but still
 * resolves by id, so a session that already logged it keeps its name. */
export async function deleteExercise(exerciseId: string): Promise<ExerciseDeleteResponse> {
  const response = await client.delete<ExerciseDeleteResponse>(`/exercises/${exerciseId}`);
  return response.data;
}
