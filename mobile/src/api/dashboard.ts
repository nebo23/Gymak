/**
 * §5.12 GET /dashboard, P2-FR-012/P2-ADR-07. One round trip for every block
 * screen 16 renders.
 *
 * Types come from `schema.d.ts`, generated from backend/openapi.json, with
 * two documented exceptions below. `weight.change_30d_kg` stays typed
 * optional rather than nullable because P2-SAF-002 makes the backend omit the
 * key entirely for a minor rather than send it as `null` — `"change_30d_kg"
 * in weight` is how the client tells "omitted for a minor" apart from "no
 * entries yet to compare".
 */
import { client } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type DashboardActiveSession = Schemas["WorkoutSessionSummary"];
export type DashboardNextWorkout = Schemas["NextWorkoutData"];
export type DashboardStreak = Schemas["StreakData"];
export type DashboardThisWeek = Schemas["ThisWeekData"];
export type DashboardWeightPoint = Schemas["BodyWeightPoint"];
export type DashboardRecentRecord = Schemas["RecentRecordData"];

/**
 * THE TWO FIELDS THAT CANNOT COME FROM THE SCHEMA, AND WHY
 *
 * `DashboardResponse.weight` and `.program_stale` are declared on the backend
 * response model as bare dicts, so openapi.json carries them as
 * `{additionalProperties: true}` and `{additionalProperties: {type: string}}`
 * respectively — i.e. the generated types are `{[key: string]: unknown}` and
 * `{[key: string]: string} | null`. Aliasing those would DELETE type
 * information the screens depend on (`data.weight.latest_kg` would be
 * `unknown`), which is the opposite of the point of this change.
 *
 * They are therefore still written out here, and anchored below: the
 * `Extends` assertions fail to compile if the backend ever gives these two
 * fields a real model, or changes them to something these shapes no longer
 * fit. That is the signal to delete these shapes and alias them like every
 * other type in this file.
 *
 * Written as `type` aliases rather than `interface`s on purpose: only an
 * alias gets TypeScript's implicit index signature, and without one it
 * cannot be checked against an `additionalProperties` schema at all — the
 * anchor below would not compile.
 */
export type DashboardWeight = {
  latest_kg: number | null;
  measured_on: string | null;
  sparkline: DashboardWeightPoint[];
  change_30d_kg?: number | null;
};

export type DashboardProgramStale = {
  reason: string;
  from: string;
  to: string;
};

type Extends<Narrow extends Wide, Wide> = Narrow;
type _WeightFitsSchema = Extends<DashboardWeight, Schemas["DashboardResponse"]["weight"]>;
type _StaleFitsSchema = Extends<
  DashboardProgramStale,
  NonNullable<Schemas["DashboardResponse"]["program_stale"]>
>;

/**
 * Every key but those two is taken straight from the generated schema, so a
 * renamed or dropped field is a compile error here rather than a blank screen
 * on a phone. The `Omit` keys are themselves checked: if the backend renames
 * `program_stale`, `Omit` silently succeeds but the intersection then adds a
 * key the response no longer has AND the schema's own new key goes untyped —
 * which `getDashboard`'s return type surfaces at the call sites.
 */
export type DashboardData = Omit<
  Schemas["DashboardResponse"],
  "weight" | "program_stale"
> & {
  weight: DashboardWeight;
  program_stale: DashboardProgramStale | null;
};

export async function getDashboard(): Promise<DashboardData> {
  const response = await client.get<DashboardData>("/dashboard");
  return response.data;
}
