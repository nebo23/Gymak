/**
 * §7.1 field rules, mirrored client-side. The server is authoritative — these
 * exist so a screen can show a field error before a round trip, not to
 * replace server validation. The password denylist (§6.2/A-07) is
 * deliberately not duplicated here: it is a vendored 1000-entry list that is
 * a server concern, and the server's 422 VALIDATION_ERROR / TOO_COMMON is
 * what surfaces that case.
 */
import { z } from "zod";

// ---------------------------------------------------------------------------
// Primitive field schemas (§7.1)
// ---------------------------------------------------------------------------

const EMAIL_MAX_LENGTH = 254;
// RFC-shaped, not a full RFC 5322 parser — MX is never checked (§7.1).
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const emailSchema = z
  .string()
  .trim()
  .toLowerCase()
  .max(EMAIL_MAX_LENGTH)
  .regex(EMAIL_REGEX);

export const passwordSchema = z.string().min(8).max(128);

// Arabic + Latin letters, spaces, hyphens, apostrophes — no digits, no emoji.
const NAME_REGEX = /^[\p{Script=Arabic}a-zA-Z\s'-]+$/u;

export const nameSchema = z
  .string()
  .trim()
  .min(2)
  .max(60)
  .regex(NAME_REGEX);

export const genderSchema = z.enum(["male", "female"]);

const ISO_DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;

/** Whole years between `birthDate` and `asOf` (defaults to now), UTC-based. */
export function computeAge(birthDate: string, asOf: Date = new Date()): number | null {
  if (!ISO_DATE_REGEX.test(birthDate)) return null;
  const birth = new Date(`${birthDate}T00:00:00Z`);
  if (Number.isNaN(birth.getTime())) return null;
  if (birth.getTime() > asOf.getTime()) return null; // not in the future

  let age = asOf.getUTCFullYear() - birth.getUTCFullYear();
  const hadBirthdayThisYear =
    asOf.getUTCMonth() > birth.getUTCMonth() ||
    (asOf.getUTCMonth() === birth.getUTCMonth() && asOf.getUTCDate() >= birth.getUTCDate());
  if (!hadBirthdayThisYear) age -= 1;
  return age;
}

export const birthDateSchema = z.string().refine((value) => {
  const age = computeAge(value);
  return age !== null && age >= 13 && age <= 100;
}, "birth_date:OUT_OF_RANGE");

function roundTo(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

function hasAtMostDecimals(value: number, decimals: number): boolean {
  return Math.abs(value - roundTo(value, decimals)) < 1e-9;
}

export const heightCmSchema = z
  .number()
  .min(100)
  .max(250)
  .refine((v) => hasAtMostDecimals(v, 1), "height_cm:OUT_OF_RANGE");

export const weightKgSchema = z
  .number()
  .min(30)
  .max(300)
  .refine((v) => hasAtMostDecimals(v, 2), "weight_kg:OUT_OF_RANGE");

export const goalSchema = z.enum(["lose", "gain", "maintain"]);
export const experienceLevelSchema = z.enum(["beginner", "intermediate", "advanced"]);
export const activityLevelSchema = z.enum(["sedentary", "light", "moderate", "high", "very_high"]);
export const unitSystemSchema = z.enum(["metric", "imperial"]);
export const languageSchema = z.enum(["ar", "en"]);

// P1-ADR-07: RFC 4648 Base32 minus the visually ambiguous `I` and `O` — same
// alphabet GOtpInput.tsx sanitises against (kept independent here so this
// module has no React Native dependency and can run under plain Node/vitest).
const RESET_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ234567";
const RESET_CODE_LENGTH = 8;
const RESET_CODE_REGEX = new RegExp(`^[${RESET_CODE_ALPHABET}]{${RESET_CODE_LENGTH}}$`);

export const resetCodeSchema = z
  .string()
  .transform((value) => value.toUpperCase())
  .pipe(z.string().regex(RESET_CODE_REGEX, "code:INVALID"));

// ---------------------------------------------------------------------------
// P1-SAF-001, mirrored for immediate UI feedback — the server re-checks this
// on every POST and PATCH regardless of what the client sends.
// ---------------------------------------------------------------------------

export function isGoalPermitted(goal: z.infer<typeof goalSchema>, birthDate: string): boolean {
  if (goal !== "lose") return true;
  const age = computeAge(birthDate);
  return age !== null && age >= 18;
}

// ---------------------------------------------------------------------------
// Composite screen schemas
// ---------------------------------------------------------------------------

export const registerSchema = z
  .object({
    email: emailSchema,
    password: passwordSchema,
    confirmPassword: z.string(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "password:MISMATCH",
    path: ["confirmPassword"],
  });

export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1),
});

export const onboardingProfileSchema = z
  .object({
    name: nameSchema,
    gender: genderSchema,
    birth_date: birthDateSchema,
    height_cm: heightCmSchema,
    weight_kg: weightKgSchema,
    goal: goalSchema,
    experience_level: experienceLevelSchema,
    activity_level: activityLevelSchema,
    unit_system: unitSystemSchema,
    language: languageSchema,
  })
  .refine((data) => isGoalPermitted(data.goal, data.birth_date), {
    message: "GOAL_NOT_PERMITTED_FOR_MINOR",
    path: ["goal"],
  });

// ---------------------------------------------------------------------------
// §7.1 "Imperial input, SI storage" — the API never accepts imperial values.
// ---------------------------------------------------------------------------

const CM_PER_INCH = 2.54;
const KG_PER_LB = 0.45359237;

/** Rounded to 1 decimal place, matching height_cm's numeric(5,1) storage. */
export function feetInchesToCm(feet: number, inches: number): number {
  const totalInches = feet * 12 + inches;
  return roundTo(totalInches * CM_PER_INCH, 1);
}

export function cmToFeetInches(cm: number): { feet: number; inches: number } {
  const totalInches = cm / CM_PER_INCH;
  let feet = Math.floor(totalInches / 12);
  let inches = Math.round(totalInches - feet * 12);
  if (inches === 12) {
    feet += 1;
    inches = 0;
  }
  return { feet, inches };
}

/** Rounded to 2 decimal places, matching weight_kg's numeric(5,2) storage. */
export function lbsToKg(lbs: number): number {
  return roundTo(lbs * KG_PER_LB, 2);
}

export function kgToLbs(kg: number): number {
  return roundTo(kg / KG_PER_LB, 1);
}
