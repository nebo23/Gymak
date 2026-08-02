/**
 * §9.3's note under the screen inventory: onboarding progress is held on the
 * device, not the server. Steps 1-6 write to this local Zustand draft, and
 * exactly one network call — POST /profile — happens, on Finish (review.tsx).
 * Deliberately not persisted to SecureStore/AsyncStorage: if the app process
 * dies mid-flow the user restarts onboarding, which is §9.3's own accepted
 * tradeoff ("far simpler than six partial-write endpoints"), not a bug to
 * route around. Killing and reopening the app while the process survives
 * (manual check 2) works because this module-level store isn't torn down.
 *
 * activity_level has no onboarding step (§9.3 screens 7-12 name six fields
 * across six steps and activity_level isn't one of them — it's nullable in
 * §4.3 and only editable later, from Settings), so it's absent here on
 * purpose, not an oversight.
 */
import { create } from "zustand";

import type {
  ExperienceLevel,
  Gender,
  Goal,
  Language,
  ProfileCreateInput,
  UnitSystem,
} from "../api/profile";

export interface OnboardingDraftFields {
  name: string;
  gender: Gender | null;
  birthDate: string | null;
  unitSystem: UnitSystem;
  heightCm: number | null;
  weightKg: number | null;
  goal: Goal | null;
  experienceLevel: ExperienceLevel | null;
  language: Language;
}

interface OnboardingDraftState extends OnboardingDraftFields {
  setName: (name: string) => void;
  setGender: (gender: Gender) => void;
  setBirthDate: (birthDate: string) => void;
  setUnitSystem: (unitSystem: UnitSystem) => void;
  setHeightWeight: (heightCm: number, weightKg: number) => void;
  setGoal: (goal: Goal | null) => void;
  setExperienceLevel: (experienceLevel: ExperienceLevel) => void;
  setLanguage: (language: Language) => void;
  reset: () => void;
}

// §4.3's own server defaults ('metric', 'ar') — not a guess.
const initialFields: OnboardingDraftFields = {
  name: "",
  gender: null,
  birthDate: null,
  unitSystem: "metric",
  heightCm: null,
  weightKg: null,
  goal: null,
  experienceLevel: null,
  language: "ar",
};

export const useOnboardingDraft = create<OnboardingDraftState>((set) => ({
  ...initialFields,
  setName: (name) => set({ name }),
  setGender: (gender) => set({ gender }),
  setBirthDate: (birthDate) => set({ birthDate }),
  setUnitSystem: (unitSystem) => set({ unitSystem }),
  setHeightWeight: (heightCm, weightKg) => set({ heightCm, weightKg }),
  setGoal: (goal) => set({ goal }),
  setExperienceLevel: (experienceLevel) => set({ experienceLevel }),
  setLanguage: (language) => set({ language }),
  reset: () => set({ ...initialFields }),
}));

/**
 * Builds the §5.8 POST /profile body. Returns null if any of the six steps
 * hasn't been completed yet — review.tsx's Finish button is the only caller,
 * and it never should be able to press Finish with a null result, but a
 * direct deep-link into /review is a real enough path (Fast Refresh during
 * development, a resumed dev build) that silently sending a half-filled
 * payload would be worse than refusing.
 */
export function draftToProfileInput(draft: OnboardingDraftFields): ProfileCreateInput | null {
  if (
    draft.name.length === 0 ||
    !draft.gender ||
    !draft.birthDate ||
    draft.heightCm === null ||
    draft.weightKg === null ||
    !draft.goal ||
    !draft.experienceLevel
  ) {
    return null;
  }
  return {
    name: draft.name,
    gender: draft.gender,
    birth_date: draft.birthDate,
    height_cm: draft.heightCm,
    weight_kg: draft.weightKg,
    goal: draft.goal,
    experience_level: draft.experienceLevel,
    unit_system: draft.unitSystem,
    language: draft.language,
  };
}
