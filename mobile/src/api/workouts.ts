/**
 * §5.6 (POST /workouts, GET /workouts/active), §5.7 (POST .../sets), §5.8
 * (POST .../finish, .../abandon), §5.9 (GET /workouts, GET /workouts/{id}) --
 * P2-FR-005/006/007/008. Types are generated from backend/openapi.json (see
 * `schema.d.ts`); backend/app/schemas/workout.py remains the authoritative
 * source they are generated from. PATCH/DELETE on a set are still unwrapped
 * -- no screen calls them yet.
 */
import { client } from "./client";
import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type WorkoutSessionSummary = Schemas["WorkoutSessionSummary"];
export type WorkoutStartResponse = Schemas["WorkoutStartResponse"];
export type SetDerived = Schemas["SetDerived"];
export type WorkoutSetData = Schemas["WorkoutSetData"];
export type SessionTotalsData = Schemas["SessionTotalsData"];
export type SetRecordData = Schemas["SetRecordData"];
export type WorkoutSetActionResponse = Schemas["WorkoutSetActionResponse"];
export type WorkoutFinishedSummary = Schemas["WorkoutFinishedSummary"];
export type RecordSetItem = Schemas["RecordSetItem"];
export type WorkoutFinishResponse = Schemas["WorkoutFinishResponse"];
export type WorkoutAbandonResponse = Schemas["WorkoutAbandonResponse"];
export type SessionDetailExerciseRef = Schemas["SessionDetailExerciseRef"];
export type SessionDetailExerciseGroup = Schemas["SessionDetailExerciseGroup"];
export type WorkoutDetailData = Schemas["WorkoutDetailData"];
export type WorkoutDetailResponse = Schemas["WorkoutDetailResponse"];

/** §5.9's seven summary fields -- no `sets`, no `notes`; `GET /workouts/{id}`
 * is what carries those. */
export type WorkoutHistoryItem = Schemas["WorkoutHistoryItem"];
export type WorkoutHistoryResponse = Schemas["WorkoutHistoryResponse"];

/**
 * `is_warmup` carries a server-side default (false) and openapi-typescript
 * therefore marks it required; the client has always sent it explicitly, so
 * it is left required here too rather than loosened. `rpe` stays optional —
 * §8.4's disclosure toggle hides the field client-side and the wire shape
 * mirrors that: a hidden field is one that was never asked about, so it is
 * omitted from the request entirely rather than sent as null.
 */
export type WorkoutSetCreateInput = Schemas["WorkoutSetCreateRequest"];

/**
 * §5.9 history filters. `from`/`to`/`status` exist on the endpoint but no
 * screen offers filter UI, so `listWorkouts` still wraps `cursor` only —
 * the type is taken whole so that the day a screen does offer them, the
 * names and shapes are already the server's, not a guess.
 */
export type WorkoutHistoryParams = NonNullable<
  paths["/api/v1/workouts"]["get"]["parameters"]["query"]
>;

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

/** §5.9 history, cursor-paginated newest first. `cursor` must be a page's own
 * `next_cursor` passed back verbatim, never constructed client-side.
 * `from`/`to`/`status` exist on the endpoint but no screen offers filter UI,
 * so they are not wrapped here. */
export async function listWorkouts(cursor?: string): Promise<WorkoutHistoryResponse> {
  const response = await client.get<WorkoutHistoryResponse>("/workouts", {
    params: cursor ? { cursor } : undefined,
  });
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
