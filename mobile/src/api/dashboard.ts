/**
 * §5.12 GET /dashboard, P2-FR-012/P2-ADR-07. One round trip for every block
 * screen 16 renders — see backend/app/schemas/metrics.py's `DashboardResponse`
 * for the authoritative shape. `weight.change_30d_kg` is typed optional, not
 * nullable, because P2-SAF-002 makes the backend omit the key entirely for a
 * minor rather than send it as `null` (schemas/metrics.py's own documented
 * reasoning) — `"change_30d_kg" in weight` is how the client tells "omitted
 * for a minor" apart from "no entries yet to compare".
 */
import { client } from "./client";

export interface DashboardActiveSession {
  id: string;
  status: string;
  started_at: string;
  local_date: string;
  program_day_id: string | null;
}

export interface DashboardNextWorkout {
  program_day_id: string;
  day_index: number;
  label_key: string;
  exercise_count: number;
  estimated_minutes: number;
}

export interface DashboardStreak {
  current_days: number;
  longest_days: number;
  last_workout_local_date: string | null;
}

export interface DashboardThisWeek {
  completed: number;
  target: number;
  local_week_start: string;
}

export interface DashboardWeightPoint {
  measured_on: string;
  weight_kg: number;
}

export interface DashboardWeight {
  latest_kg: number | null;
  measured_on: string | null;
  sparkline: DashboardWeightPoint[];
  change_30d_kg?: number | null;
}

export interface DashboardRecentRecord {
  exercise_name: string;
  kind: string;
  value: number;
  local_date: string;
}

export interface DashboardProgramStale {
  reason: string;
  from: string;
  to: string;
}

export interface DashboardData {
  greeting_name: string;
  active_session: DashboardActiveSession | null;
  next_workout: DashboardNextWorkout | null;
  streak: DashboardStreak;
  this_week: DashboardThisWeek;
  weight: DashboardWeight;
  recent_records: DashboardRecentRecord[];
  program_stale: DashboardProgramStale | null;
  disclaimer_key: string;
}

export async function getDashboard(): Promise<DashboardData> {
  const response = await client.get<DashboardData>("/dashboard");
  return response.data;
}
