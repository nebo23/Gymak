/**
 * §5.3 (POST /program/generate), §5.4 (GET /program), §5.5 (GET /program/days/{day_id}).
 * Types are generated from backend/openapi.json (see `schema.d.ts`); the one
 * hand-written shape below says why it has to be. `estimated_minutes` and
 * `last_performance` are real as of T-24b, not placeholders.
 */
import { client } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ProgramDaySummary = Schemas["ProgramDaySummary"];
export type ProgramSummary = Schemas["ProgramSummary"];
export type ProgramGenerateResponse = Schemas["ProgramGenerateResponse"];
export type ProgramDayExerciseRef = Schemas["ProgramDayExerciseRef"];
export type ProgramDayExerciseBestSet = Schemas["ProgramDayExerciseBestSet"];
export type ProgramDayExerciseLastPerformance =
  Schemas["ProgramDayExerciseLastPerformance"];
export type ProgramDayExerciseDetail = Schemas["ProgramDayExerciseDetail"];
export type ProgramDayDetail = Schemas["ProgramDayDetail"];
export type ProgramDayDetailResponse = Schemas["ProgramDayDetailResponse"];

/**
 * The one shape that cannot be aliased. `ProgramResponse.stale` is a bare
 * dict on the backend response model, so the generated type is
 * `{[key: string]: string} | null` and screen 12 reading `stale.reason`
 * would lose its type entirely. Same situation, same reasoning, and same
 * anchor as `DashboardProgramStale` in dashboard.ts -- see the long note
 * there. The `Extends` line below fails to compile if the backend ever
 * models this field properly, which is when both copies should be deleted.
 */
export type ProgramStale = {
  reason: string;
  from: string;
  to: string;
};

type Extends<Narrow extends Wide, Wide> = Narrow;
type _StaleFitsSchema = Extends<
  ProgramStale,
  NonNullable<Schemas["ProgramResponse"]["stale"]>
>;

export type ProgramResponse = Omit<Schemas["ProgramResponse"], "stale"> & {
  stale: ProgramStale | null;
};

export async function getProgram(): Promise<ProgramResponse> {
  const response = await client.get<ProgramResponse>("/program");
  return response.data;
}

export async function generateProgram(daysPerWeek: number): Promise<ProgramGenerateResponse> {
  const response = await client.post<ProgramGenerateResponse>("/program/generate", {
    days_per_week: daysPerWeek,
  });
  return response.data;
}

export async function getProgramDay(dayId: string): Promise<ProgramDayDetailResponse> {
  const response = await client.get<ProgramDayDetailResponse>(`/program/days/${dayId}`);
  return response.data;
}
