/**
 * §5.6 (POST /workouts, GET /workouts/active), §5.7 (POST .../sets), §5.8
 * (POST .../finish, .../abandon), §5.9 (GET /workouts/{id}) -- P2-FR-005/006/007.
 * See backend/app/schemas/workout.py for the authoritative shapes. Only the
 * endpoints T-26's active-workout screen actually calls are wrapped here;
 * PATCH/DELETE on a set and the history list (§5.9's other half) are T-27's
 * own additions to this same file when it needs them.
 */
import { client } from "./client";

export interface WorkoutSessionSummary {
  id: string;
  status: string;
  started_at: string;
  local_date: string;
  program_day_id: string | null;
}

export interface WorkoutStartResponse {
  session: WorkoutSessionSummary;
}

export interface SetDerived {
  volume_kg: number;
  e1rm_kg: number;
}

export interface WorkoutSetData {
  id: string;
  exercise_id: string;
  set_index: number;
  reps: number;
  weight_kg: number;
  rpe: number | null;
  is_warmup: boolean;
  logged_at: string;
  derived: SetDerived;
}

export interface SessionTotalsData {
  sets: number;
  volume_kg: number;
}

export interface SetRecordData {
  kind: string;
  previous: number;
}

export interface WorkoutSetActionResponse {
  set: WorkoutSetData;
  session_totals: SessionTotalsData;
  is_record: SetRecordData | null;
}

export interface WorkoutSetCreateInput {
  exercise_id: string;
  reps: number;
  weight_kg: number;
  /** Omitted from the request entirely (not sent as null) when absent -- §8.4's
   * disclosure toggle hides the field client-side, and the wire shape mirrors that:
   * a hidden field is a field that was never asked about. */
  rpe?: number;
  is_warmup: boolean;
}

export interface WorkoutFinishedSummary {
  id: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  total_volume_kg: number | null;
  set_count: number;
  exercise_count: number;
}

export interface RecordSetItem {
  exercise_id: string;
  kind: string;
  value: number;
}

export interface WorkoutFinishResponse {
  session: WorkoutFinishedSummary;
  records_set: RecordSetItem[];
}

export interface WorkoutAbandonResponse {
  session: WorkoutFinishedSummary;
}

export interface SessionDetailExerciseRef {
  id: string;
  slug: string;
  name: string;
  primary_muscle: string;
}

export interface SessionDetailExerciseGroup {
  exercise: SessionDetailExerciseRef;
  sets: WorkoutSetData[];
}

export interface WorkoutDetailData {
  id: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  local_date: string;
  duration_seconds: number | null;
  total_volume_kg: number | null;
  notes: string | null;
  program_day_id: string | null;
  label_key: string | null;
  set_count: number;
  exercise_count: number;
  exercises: SessionDetailExerciseGroup[];
}

export interface WorkoutDetailResponse {
  session: WorkoutDetailData;
}

/** §5.6. Omit `programDayId` entirely for an empty session. Throws (axios) with
 * `code: "SESSION_ALREADY_ACTIVE"` and `detail: "<active session id>"` when one is
 * already open -- the caller offers Resume / Discard and start new from that. */
export async function startWorkout(programDayId?: string): Promise<WorkoutStartResponse> {
  const response = await client.post<WorkoutStartResponse>(
    "/workouts",
    programDayId ? { program_day_id: programDayId } : {},
  );
  return response.data;
}

/** §5.1: "the in-progress session, or 204." Returns `null` on 204 rather than
 * throwing -- no active session is a normal, common outcome, not a failure. */
export async function getActiveWorkout(): Promise<WorkoutStartResponse | null> {
  const response = await client.get<WorkoutStartResponse>("/workouts/active", {
    validateStatus: (status) => status === 200 || status === 204,
  });
  if (response.status === 204) return null;
  return response.data;
}

/** §5.9. The session with every set, grouped by exercise. */
export async function getWorkout(sessionId: string): Promise<WorkoutDetailResponse> {
  const response = await client.get<WorkoutDetailResponse>(`/workouts/${sessionId}`);
  return response.data;
}

/** §5.7 POST. `set_index` is server-assigned; never sent by the client. */
export async function createSet(
  sessionId: string,
  input: WorkoutSetCreateInput,
): Promise<WorkoutSetActionResponse> {
  const response = await client.post<WorkoutSetActionResponse>(
    `/workouts/${sessionId}/sets`,
    input,
  );
  return response.data;
}

/** §5.8. `notes` is optional and trimmed server-side. */
export async function finishWorkout(
  sessionId: string,
  notes?: string,
): Promise<WorkoutFinishResponse> {
  const response = await client.post<WorkoutFinishResponse>(`/workouts/${sessionId}/finish`, {
    notes: notes ?? null,
  });
  return response.data;
}

export async function abandonWorkout(sessionId: string): Promise<WorkoutAbandonResponse> {
  const response = await client.post<WorkoutAbandonResponse>(`/workouts/${sessionId}/abandon`, {});
  return response.data;
}
