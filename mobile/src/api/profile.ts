/**
 * §5.8/§5.9: the one-time onboarding capture and the Settings PATCH surface.
 * Every field is SI on the wire (§5's conventions) — the imperial ↔ SI
 * conversion happens client-side in src/validation/schemas.ts before a
 * request is ever built here.
 */
import { client } from "./client";

export type Gender = "male" | "female";
export type Goal = "lose" | "gain" | "maintain";
export type ExperienceLevel = "beginner" | "intermediate" | "advanced";
export type ActivityLevel = "sedentary" | "light" | "moderate" | "high" | "very_high";
export type UnitSystem = "metric" | "imperial";
export type Language = "ar" | "en";

export interface ProfileData {
  name: string;
  gender: Gender;
  birth_date: string;
  height_cm: number;
  weight_kg: number | null;
  goal: Goal;
  experience_level: ExperienceLevel;
  activity_level: ActivityLevel | null;
  unit_system: UnitSystem;
  language: Language;
  /** IANA name (Phase 2 §4.2). Defaults server-side to "Africa/Cairo" until
   * a client writes a real one. */
  timezone: string;
  onboarding_completed: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProfileCreateInput {
  name: string;
  gender: Gender;
  birth_date: string;
  height_cm: number;
  weight_kg?: number;
  goal: Goal;
  experience_level: ExperienceLevel;
  activity_level?: ActivityLevel;
  unit_system?: UnitSystem;
  language?: Language;
}

export interface ProfileCreateResponse {
  profile: ProfileData;
  derived: { age: number };
}

/** Every key is optional: only the keys present in the body are touched (§5.9). */
export type ProfileUpdateInput = Partial<
  Pick<
    ProfileData,
    | "name"
    | "gender"
    | "birth_date"
    | "height_cm"
    | "weight_kg"
    | "goal"
    | "experience_level"
    | "activity_level"
    | "unit_system"
    | "language"
    | "timezone"
  >
>;

export async function getProfile(): Promise<ProfileData> {
  const response = await client.get<{ profile: ProfileData }>("/profile");
  return response.data.profile;
}

export async function createProfile(input: ProfileCreateInput): Promise<ProfileCreateResponse> {
  const response = await client.post<ProfileCreateResponse>("/profile", input);
  return response.data;
}

export async function updateProfile(input: ProfileUpdateInput): Promise<ProfileData> {
  const response = await client.patch<{ profile: ProfileData }>("/profile", input);
  return response.data.profile;
}
