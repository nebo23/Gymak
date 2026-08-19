/**
 * §5.11 GET /records, P2-ADR-05. See backend/app/schemas/metrics.py's
 * `RecordsResponse`/`RecordEntryData` for the authoritative shape -- read
 * directly from that file, not inferred.
 *
 * Not named in T-28's own file list -- GET /records has no home in any of
 * the files that task does name (bodyWeight.ts is body weight, not personal
 * records; jamming a second, unrelated resource's types into it would break
 * this codebase's own one-resource-per-api-module convention, the same one
 * dashboard.ts/workouts.ts/program.ts already follow). Added as its own
 * module for that reason -- see this task's own report for the flag.
 */
import { client } from "./client";

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

export interface RecordEntryData {
  exercise: RecordExerciseRef;
  heaviest_set: HeaviestSetData;
  best_e1rm: BestE1rmData;
  best_session_volume: BestSessionVolumeData;
  total_sets: number;
}

export interface RecordsResponse {
  records: RecordEntryData[];
}

/** §5.11. Exercises never performed are omitted entirely, never returned
 * with nulls -- an empty `records` array is a well-formed, common result,
 * not a failure. */
export async function getRecords(): Promise<RecordsResponse> {
  const response = await client.get<RecordsResponse>("/records");
  return response.data;
}
