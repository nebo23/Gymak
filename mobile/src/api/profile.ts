/**
 * §5.8/§5.9: the one-time onboarding capture and the Settings PATCH surface.
 * Every field is SI on the wire (§5's conventions) — the imperial ↔ SI
 * conversion happens client-side in src/validation/schemas.ts before a
 * request is ever built here.
 *
 * Types are generated from backend/openapi.json via `schema.d.ts`, except the
 * six vocabulary fields the schema types as bare strings — see the note below
 * for why narrowing those by hand is the correct answer rather than a
 * shortcut.
 */
import { client } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/**
 * THE SIX NARROWED FIELDS
 *
 * The backend declares gender/goal/experience_level/activity_level/
 * unit_system/language as plain `str` with a CHECK constraint, not as an
 * enum, so openapi.json carries them as `"type": "string"` and the generated
 * types are just `string`. These unions are therefore NARROWER than the
 * schema, deliberately: the Settings pickers, the onboarding radio groups and
 * the `profile.*` i18n key lookups all rely on exhaustiveness, and widening
 * them to `string` would silently delete that. Aliasing here would be
 * "generated from the schema" in letter and a regression in fact.
 *
 * The `Extends` anchors below keep them honest: each fails to compile if the
 * schema's own type for that field stops being a string it can narrow — the
 * signal that the backend finally modelled these as enums and that these
 * unions should be replaced by the generated ones.
 */
export type Gender = "male" | "female";
export type Goal = "lose" | "gain" | "maintain";
export type ExperienceLevel = "beginner" | "intermediate" | "advanced";
export type ActivityLevel = "sedentary" | "light" | "moderate" | "high" | "very_high";
export type UnitSystem = "metric" | "imperial";
export type Language = "ar" | "en";

type Extends<Narrow extends Wide, Wide> = Narrow;
type _SchemaProfile = Schemas["ProfileData"];
type _GenderFits = Extends<Gender, _SchemaProfile["gender"]>;
type _GoalFits = Extends<Goal, _SchemaProfile["goal"]>;
type _ExperienceFits = Extends<ExperienceLevel, _SchemaProfile["experience_level"]>;
type _ActivityFits = Extends<ActivityLevel, NonNullable<_SchemaProfile["activity_level"]>>;
type _UnitSystemFits = Extends<UnitSystem, _SchemaProfile["unit_system"]>;
type _LanguageFits = Extends<Language, _SchemaProfile["language"]>;

/**
 * Every other key — including `timezone`, `created_at` and the two Decimal
 * fields — comes straight from the schema, so a rename upstream is a compile
 * error here. `timezone` keeps its Phase 2 §4.2 note: IANA name, defaulting
 * server-side to "Africa/Cairo" until a client writes a real one.
 */
export type ProfileData = Omit<
  Schemas["ProfileData"],
  "gender" | "goal" | "experience_level" | "activity_level" | "unit_system" | "language"
> & {
  gender: Gender;
  goal: Goal;
  experience_level: ExperienceLevel;
  activity_level: ActivityLevel | null;
  unit_system: UnitSystem;
  language: Language;
};

/**
 * `language` and `unit_system` are optional on the wire (the server defaults
 * them to "ar" and "metric"), but openapi-typescript marks any property
 * carrying a `default` as required — it generates ONE type per schema and
 * cannot tell a request the client sends from a response the server fills in.
 * They are restored to optional here rather than by turning the generator's
 * `--default-non-nullable` off, which would make every DEFAULTED RESPONSE
 * field optional too and push a wave of null checks into the screens.
 */
export type ProfileCreateInput = Omit<
  Schemas["ProfileCreateRequest"],
  "gender" | "goal" | "experience_level" | "activity_level" | "unit_system" | "language"
> & {
  gender: Gender;
  goal: Goal;
  experience_level: ExperienceLevel;
  activity_level?: ActivityLevel;
  unit_system?: UnitSystem;
  language?: Language;
};

export type ProfileCreateResponse = Omit<Schemas["ProfileCreateResponse"], "profile"> & {
  profile: ProfileData;
};

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

/**
 * PATCH /profile accepts a strict subset of what the schema allows: the
 * schema's `ProfileUpdateRequest` also carries `onboarding_completed`, which
 * no screen may set (§5.9 — it is server-derived from POST /profile). The
 * anchor keeps the subset a real subset instead of a stale one.
 */
type _UpdateIsSubsetOfSchema = Extends<
  ProfileUpdateInput,
  Partial<Schemas["ProfileUpdateRequest"]>
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
