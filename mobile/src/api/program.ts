/**
 * §5.3 (POST /program/generate), §5.4 (GET /program), §5.5 (GET /program/days/{day_id}).
 * See backend/app/schemas/program.py for the authoritative shapes — `estimated_minutes`
 * and `last_performance` are real as of T-24b, not placeholders.
 */
import { client } from "./client";

export interface ProgramDaySummary {
  id: string;
  day_index: number;
  label_key: string;
  focus_muscles: string[];
  exercise_count: number;
  estimated_minutes: number;
}

export interface ProgramSummary {
  id: string;
  days_per_week: number;
  split_type: string;
  goal: string;
  experience_level: string;
  generator_version: number;
  created_at: string;
  days: ProgramDaySummary[];
}

export interface ProgramStale {
  reason: string;
  from: string;
  to: string;
}

export interface ProgramResponse {
  program: ProgramSummary;
  stale: ProgramStale | null;
}

export interface ProgramGenerateResponse {
  program: ProgramSummary;
  notes_key: string[];
}

export interface ProgramDayExerciseRef {
  id: string;
  slug: string;
  name: string;
  equipment: string;
  primary_muscle: string;
}

export interface ProgramDayExerciseBestSet {
  reps: number;
  weight_kg: number;
}

export interface ProgramDayExerciseLastPerformance {
  session_id: string;
  local_date: string;
  best_set: ProgramDayExerciseBestSet;
}

export interface ProgramDayExerciseDetail {
  id: string;
  position: number;
  exercise: ProgramDayExerciseRef;
  target_sets: number;
  target_reps_min: number;
  target_reps_max: number;
  rest_seconds: number;
  last_performance: ProgramDayExerciseLastPerformance | null;
}

export interface ProgramDayDetail {
  id: string;
  day_index: number;
  label_key: string;
  exercises: ProgramDayExerciseDetail[];
}

export interface ProgramDayDetailResponse {
  day: ProgramDayDetail;
}

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
