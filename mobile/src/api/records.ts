/**
 * §5.11 GET /records, P2-ADR-05. See backend/app/schemas/metrics.py's
 * `RecordsResponse`/`RecordEntryData` for the authoritative shape. The types
 * below are generated from it, via backend/openapi.json and `schema.d.ts` --
 * no longer transcribed by hand.
 *
 * Not named in T-28's own file list -- GET /records has no home in any of
 * the files that task does name (bodyWeight.ts is body weight, not personal
 * records; jamming a second, unrelated resource's types into it would break
 * this codebase's own one-resource-per-api-module convention, the same one
 * dashboard.ts/workouts.ts/program.ts already follow). Added as its own
 * module for that reason -- see this task's own report for the flag.
 */
import { client } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type RecordExerciseRef = Schemas["RecordExerciseRef"];
export type HeaviestSetData = Schemas["HeaviestSetData"];
export type BestE1rmData = Schemas["BestE1rmData"];
export type BestSessionVolumeData = Schemas["BestSessionVolumeData"];
export type RecordEntryData = Schemas["RecordEntryData"];
export type RecordsResponse = Schemas["RecordsResponse"];

/** §5.11. Exercises never performed are omitted entirely, never returned
 * with nulls -- an empty `records` array is a well-formed, common result,
 * not a failure. */
export async function getRecords(): Promise<RecordsResponse> {
  const response = await client.get<RecordsResponse>("/records");
  return response.data;
}
