/**
 * §9.3 screen 15 — settings. Reads GET /profile, edits through PATCH (only
 * the fields that actually changed — §5.9: "only the keys present in the
 * body are touched"), plus the account actions: log out, log out of all
 * devices, and delete account behind a typed confirmation.
 *
 * The height/weight unit toggle and the birth-date picker reuse the same
 * approach as onboarding step-3/step-2 (live SI conversion, native picker) —
 * duplicated locally rather than extracted into a ninth shared component,
 * per "use only T-11 primitives, no new component."
 *
 * LAYOUT — REBUILT IN THE UI PASS
 * This screen used to render roughly seventeen `GSelectCard`s at once: gender
 * (2), goal (3), experience (3), activity (5), units (2), language (2) and
 * theme (3), every one the same size and weight and the same distance from
 * its neighbours. It is now a GROUPED LIST OF ROWS, each showing its label and
 * its CURRENT VALUE, with the choices living in a `GSheet` that only exists
 * while it is open — Material's "show the setting's status instead of
 * describing the setting".
 *
 * What deliberately did NOT move behind a disclosure: name, height, weight and
 * timezone. A free-text or numeric field has no "current value vs. choices"
 * split to collapse — the field already IS its current value — so hiding it
 * behind a tap would cost a tap and buy nothing.
 *
 * NOTHING about what this screen sends changed: `buildDiff` and the PATCH are
 * untouched, and the theme preference stays device-local and out of the diff.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Platform, StyleSheet, Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { router, useFocusEffect } from "expo-router";
import DateTimePicker, { type DateTimePickerEvent } from "@react-native-community/datetimepicker";
import { getCalendars } from "expo-localization";

import { deleteAccount, logout, logoutAll } from "../../src/api/auth";
import { parseApiError, resolveErrorCode, type ResolvedErrorCode } from "../../src/api/errors";
import {
  getProfile,
  updateProfile,
  type ActivityLevel,
  type ExperienceLevel,
  type Gender,
  type Goal,
  type Language,
  type ProfileData,
  type ProfileUpdateInput,
  type UnitSystem,
} from "../../src/api/profile";
import { useSessionStore } from "../../src/auth/session";
import { useSession } from "../../src/auth/useSession";
import {
  GButton,
  GDialog,
  GErrorBanner,
  GOptionSheet,
  GScreen,
  GSectionHeader,
  GSettingRow,
  GTextInput,
  type GOptionSheetOption,
} from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme, useThemePreference } from "../../src/theme/useTheme";
import { THEME_PREFERENCES, type ThemePreference } from "../../src/theme/themePreference";
import { textStyle } from "../../src/theme/typography";
import { layout, radius, space } from "../../src/theme/tokens";
import {
  cmToFeetInches,
  feetInchesToCm,
  heightCmSchema,
  isGoalPermitted,
  kgToLbs,
  lbsToKg,
  nameSchema,
  weightKgSchema,
} from "../../src/validation/schemas";

function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function fromIsoDate(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

interface FormState {
  name: string;
  gender: Gender;
  birthDate: string;
  unitSystem: UnitSystem;
  heightCm: number;
  weightKg: number;
  goal: Goal;
  experienceLevel: ExperienceLevel;
  activityLevel: ActivityLevel | null;
  language: Language;
  timezone: string;
}

function toFormState(profile: ProfileData): FormState {
  return {
    name: profile.name,
    gender: profile.gender,
    birthDate: profile.birth_date,
    unitSystem: profile.unit_system,
    heightCm: profile.height_cm,
    weightKg: profile.weight_kg ?? 0,
    goal: profile.goal,
    experienceLevel: profile.experience_level,
    activityLevel: profile.activity_level,
    language: profile.language,
    timezone: profile.timezone,
  };
}

function buildDiff(original: ProfileData, form: FormState): ProfileUpdateInput {
  const diff: ProfileUpdateInput = {};
  if (form.name !== original.name) diff.name = form.name;
  if (form.gender !== original.gender) diff.gender = form.gender;
  if (form.birthDate !== original.birth_date) diff.birth_date = form.birthDate;
  if (form.heightCm !== original.height_cm) diff.height_cm = form.heightCm;
  if (form.weightKg !== (original.weight_kg ?? 0)) diff.weight_kg = form.weightKg;
  if (form.goal !== original.goal) diff.goal = form.goal;
  if (form.experienceLevel !== original.experience_level) diff.experience_level = form.experienceLevel;
  if (form.activityLevel !== original.activity_level && form.activityLevel !== null) {
    diff.activity_level = form.activityLevel;
  }
  if (form.unitSystem !== original.unit_system) diff.unit_system = form.unitSystem;
  if (form.language !== original.language) diff.language = form.language;
  if (form.timezone !== original.timezone) diff.timezone = form.timezone;
  return diff;
}

const THEME_KEY: Record<ThemePreference, string> = {
  system: "settings.theme.system",
  light: "settings.theme.light",
  dark: "settings.theme.dark",
};

/**
 * Every row shows its CURRENT VALUE, so each setting needs a value -> i18n key
 * lookup. These are the same keys the old cards used as their titles; nothing
 * new is being said, it is just being said once per setting instead of once
 * per option.
 */
const GENDER_KEY: Record<Gender, string> = {
  male: "settings.fields.male",
  female: "settings.fields.female",
};

const GOAL_KEY: Record<Goal, string> = {
  lose: "settings.fields.goalLose",
  gain: "settings.fields.goalGain",
  maintain: "settings.fields.goalMaintain",
};

const EXPERIENCE_KEY: Record<ExperienceLevel, string> = {
  beginner: "settings.fields.experienceBeginner",
  intermediate: "settings.fields.experienceIntermediate",
  advanced: "settings.fields.experienceAdvanced",
};

// The row shows the SHORT form ("Metric"); the sheet shows the long one
// ("Metric (cm / kg)"), where there is room to say what the choice means.
const UNIT_KEY: Record<UnitSystem, string> = {
  metric: "settings.units.metricShort",
  imperial: "settings.units.imperialShort",
};

const UNIT_LONG_KEY: Record<UnitSystem, string> = {
  metric: "settings.units.metric",
  imperial: "settings.units.imperial",
};

const LANGUAGE_KEY: Record<Language, string> = {
  ar: "settings.language.arabic",
  en: "settings.language.english",
};

const GENDERS: Gender[] = ["male", "female"];
const GOALS: Goal[] = ["lose", "gain", "maintain"];
const EXPERIENCE_LEVELS: ExperienceLevel[] = ["beginner", "intermediate", "advanced"];
const UNIT_SYSTEMS: UnitSystem[] = ["metric", "imperial"];
const LANGUAGES: Language[] = ["ar", "en"];

const ACTIVITY_LEVELS: ActivityLevel[] = ["sedentary", "light", "moderate", "high", "very_high"];
const ACTIVITY_KEY: Record<ActivityLevel, string> = {
  sedentary: "settings.fields.activitySedentary",
  light: "settings.fields.activityLight",
  moderate: "settings.fields.activityModerate",
  high: "settings.fields.activityHigh",
  very_high: "settings.fields.activityVeryHigh",
};

export default function Settings() {
  const theme = useTheme();
  // Device-local, deliberately not part of `form`/`buildDiff` — the theme is
  // never sent to the server, so it has no place in the profile PATCH and no
  // dependence on Save.
  const { preference: themePreference, setPreference: setThemePreference } = useThemePreference();
  const { t, locale, setLocale } = useI18n();
  const { user } = useSession();
  const queryClient = useQueryClient();

  const profileQuery = useQuery({ queryKey: ["profile"], queryFn: getProfile });

  const [form, setForm] = useState<FormState | null>(null);
  const [unit, setUnit] = useState<UnitSystem>("metric");
  const [heightCmText, setHeightCmText] = useState("");
  const [weightKgText, setWeightKgText] = useState("");
  const [feetText, setFeetText] = useState("");
  const [inchesText, setInchesText] = useState("");
  const [weightLbText, setWeightLbText] = useState("");
  const [showDatePicker, setShowDatePicker] = useState(false);

  // Which setting's choices are open, if any. One value rather than seven
  // booleans: only one sheet can be open at a time, and encoding that in the
  // type means it cannot be violated by a missed setState.
  const [openSheet, setOpenSheet] = useState<
    "gender" | "goal" | "experience" | "activity" | "unit" | "language" | "theme" | null
  >(null);

  const [nameError, setNameError] = useState<string | undefined>(undefined);
  const [heightError, setHeightError] = useState<string | undefined>(undefined);
  const [weightError, setWeightError] = useState<string | undefined>(undefined);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ResolvedErrorCode | null>(null);
  const [savedNotice, setSavedNotice] = useState(false);

  const [accountBusy, setAccountBusy] = useState<"logout" | "logoutAll" | "delete" | null>(null);
  const [accountError, setAccountError] = useState<ResolvedErrorCode | null>(null);
  const [deletePanelOpen, setDeletePanelOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  // The profile object the form's current values were seeded from. T-30 needs
  // it to tell "the server has newer values" from "the user has typed
  // something" -- see the re-seed effect below.
  const seededFromRef = useRef<ProfileData | null>(null);

  const seedForm = useCallback((profile: ProfileData) => {
    const seeded = toFormState(profile);
    seededFromRef.current = profile;
    setForm(seeded);
    setUnit(seeded.unitSystem);
    setHeightCmText(String(seeded.heightCm));
    setWeightKgText(String(seeded.weightKg));
    const imperial = cmToFeetInches(seeded.heightCm);
    setFeetText(String(imperial.feet));
    setInchesText(String(imperial.inches));
    setWeightLbText(String(kgToLbs(seeded.weightKg)));
  }, []);

  // Seed the editable form once the profile loads. Only when `form` is still
  // null, so a save's own optimistic cache update doesn't clobber in-flight
  // edits with a refetch.
  useEffect(() => {
    if (profileQuery.data && form === null) seedForm(profileQuery.data);
  }, [profileQuery.data, form, seedForm]);

  // T-30, device check 12: logging a body weight on the Progress tab updates
  // `profiles.weight_kg` server-side (P2-ADR-06) and invalidates ["profile"],
  // but this screen is a tab that Expo Router keeps mounted, and the seeding
  // effect above deliberately fires only once -- so the weight field went on
  // showing the value it was first seeded with. Refetch on focus, then adopt
  // the newer profile only when the form still matches what it was seeded
  // from; a form the user has actually edited is never overwritten, which is
  // the property the once-only guard above was protecting.
  const refetchProfile = profileQuery.refetch;
  useFocusEffect(
    useCallback(() => {
      void refetchProfile();
    }, [refetchProfile]),
  );

  useEffect(() => {
    const latest = profileQuery.data;
    const seeded = seededFromRef.current;
    if (!latest || !seeded || latest === seeded || form === null) return;
    if (Object.keys(buildDiff(seeded, form)).length > 0) return;
    seedForm(latest);
  }, [profileQuery.data, form, seedForm]);

  const hasPassword = user?.authMethods.includes("password") ?? false;

  const [languageNoticeVisible, setLanguageNoticeVisible] = useState(false);
  const [deletedNoticeVisible, setDeletedNoticeVisible] = useState(false);

  const loseDisabled = form ? !isGoalPermitted("lose", form.birthDate) : false;

  const handleUnitChange = (next: UnitSystem) => {
    if (!form || next === unit) return;
    if (next === "imperial") {
      const cm = Number.parseFloat(heightCmText);
      const kg = Number.parseFloat(weightKgText);
      if (Number.isFinite(cm)) {
        const { feet, inches } = cmToFeetInches(cm);
        setFeetText(String(feet));
        setInchesText(String(inches));
      }
      if (Number.isFinite(kg)) setWeightLbText(String(kgToLbs(kg)));
    } else {
      const feet = Number.parseFloat(feetText);
      const inches = Number.parseFloat(inchesText);
      const lb = Number.parseFloat(weightLbText);
      if (Number.isFinite(feet) && Number.isFinite(inches)) {
        setHeightCmText(String(feetInchesToCm(feet, inches)));
      }
      if (Number.isFinite(lb)) setWeightKgText(String(lbsToKg(lb)));
    }
    setUnit(next);
    setForm({ ...form, unitSystem: next });
  };

  const handleLanguageChange = (next: Language) => {
    if (!form) return;
    setForm({ ...form, language: next });
    if (next !== locale) {
      setLocale(next);
      setLanguageNoticeVisible(true);
    }
  };

  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale === "ar" ? "ar-u-nu-latn" : "en", {
        year: "numeric",
        month: "long",
        day: "numeric",
      }),
    [locale],
  );

  const handleDateChange = (event: DateTimePickerEvent, selected?: Date) => {
    if (Platform.OS === "android") setShowDatePicker(false);
    if (event.type === "set" && selected && form) {
      setForm({ ...form, birthDate: toIsoDate(selected) });
    }
  };

  const handleSave = async () => {
    if (!form || !profileQuery.data) return;
    setSaveError(null);
    setSavedNotice(false);

    let heightCm: number;
    let weightKg: number;
    if (unit === "metric") {
      heightCm = Number.parseFloat(heightCmText);
      weightKg = Number.parseFloat(weightKgText);
    } else {
      heightCm = feetInchesToCm(Number.parseFloat(feetText), Number.parseFloat(inchesText));
      weightKg = lbsToKg(Number.parseFloat(weightLbText));
    }
    const nameResult = nameSchema.safeParse(form.name);
    const heightResult = heightCmSchema.safeParse(heightCm);
    const weightResult = weightKgSchema.safeParse(weightKg);
    setNameError(nameResult.success ? undefined : t("fieldErrors.name.INVALID"));
    setHeightError(heightResult.success ? undefined : t("fieldErrors.height.OUT_OF_RANGE"));
    setWeightError(weightResult.success ? undefined : t("fieldErrors.weight.OUT_OF_RANGE"));
    if (form.goal === "lose" && loseDisabled) {
      setSaveError("GOAL_NOT_PERMITTED_FOR_MINOR");
      return;
    }
    if (!nameResult.success || !heightResult.success || !weightResult.success) return;

    const finalForm: FormState = {
      ...form,
      name: nameResult.data,
      heightCm: heightResult.data,
      weightKg: weightResult.data,
    };
    const diff = buildDiff(profileQuery.data, finalForm);
    if (Object.keys(diff).length === 0) {
      setSavedNotice(true);
      return;
    }

    setSaving(true);
    try {
      const updated = await updateProfile(diff);
      queryClient.setQueryData(["profile"], updated);
      seededFromRef.current = updated;
      setForm(toFormState(updated));
      setSavedNotice(true);
    } catch (err) {
      const problem = parseApiError(err);
      setSaveError(problem.code);
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    setAccountError(null);
    setAccountBusy("logout");
    try {
      const { refreshToken } = useSessionStore.getState();
      if (refreshToken) await logout(refreshToken);
      await useSessionStore.getState().signOut();
      router.replace("/(auth)/welcome");
    } catch (err) {
      setAccountError(resolveErrorCode(err));
    } finally {
      setAccountBusy(null);
    }
  };

  const handleLogoutAll = async () => {
    setAccountError(null);
    setAccountBusy("logoutAll");
    try {
      await logoutAll();
      await useSessionStore.getState().signOut();
      router.replace("/(auth)/welcome");
    } catch (err) {
      setAccountError(resolveErrorCode(err));
    } finally {
      setAccountBusy(null);
    }
  };

  const handleDeleteAccount = async () => {
    if (deleteConfirmText.trim().toUpperCase() !== t("settings.account.deleteConfirmWord")) return;
    if (hasPassword && deletePassword.length === 0) return;
    setAccountError(null);
    setAccountBusy("delete");
    try {
      await deleteAccount(hasPassword ? deletePassword : undefined);
      await useSessionStore.getState().signOut();
      setDeletedNoticeVisible(true);
    } catch (err) {
      setAccountError(resolveErrorCode(err));
    } finally {
      setAccountBusy(null);
    }
  };

  if (profileQuery.isLoading || !form) {
    return (
      <GScreen header={{ title: t("settings.title"), onBack: () => router.back() }}>
        {profileQuery.isError ? (
          <GErrorBanner
            code={resolveErrorCode(profileQuery.error)}
            onRetry={() => profileQuery.refetch()}
            testID="settings-load-error"
          />
        ) : null}
      </GScreen>
    );
  }

  const deleteConfirmValid =
    deleteConfirmText.trim().toUpperCase() === t("settings.account.deleteConfirmWord") &&
    (!hasPassword || deletePassword.length > 0);

  // Built here rather than at module scope: every label is translated, and the
  // "lose" option's disabled state depends on the account's birth date.
  const genderOptions: GOptionSheetOption<Gender>[] = GENDERS.map((value) => ({
    value,
    label: t(GENDER_KEY[value]),
  }));
  const goalOptions: GOptionSheetOption<Goal>[] = GOALS.map((value) => ({
    value,
    label: t(GOAL_KEY[value]),
    disabled: value === "lose" && loseDisabled,
    disabledReason:
      value === "lose" && loseDisabled ? t("settings.fields.goalLoseDisabledReason") : undefined,
  }));
  const experienceOptions: GOptionSheetOption<ExperienceLevel>[] = EXPERIENCE_LEVELS.map(
    (value) => ({ value, label: t(EXPERIENCE_KEY[value]) }),
  );
  const activityOptions: GOptionSheetOption<ActivityLevel>[] = ACTIVITY_LEVELS.map((value) => ({
    value,
    label: t(ACTIVITY_KEY[value]),
  }));
  const unitOptions: GOptionSheetOption<UnitSystem>[] = UNIT_SYSTEMS.map((value) => ({
    value,
    label: t(UNIT_LONG_KEY[value]),
  }));
  const languageOptions: GOptionSheetOption<Language>[] = LANGUAGES.map((value) => ({
    value,
    label: t(LANGUAGE_KEY[value]),
  }));
  const themeOptions: GOptionSheetOption<ThemePreference>[] = THEME_PREFERENCES.map((value) => ({
    value,
    label: t(THEME_KEY[value]),
  }));

  return (
    <GScreen header={{ title: t("settings.title"), onBack: () => router.back() }}>
      {saveError ? (
        <GErrorBanner code={saveError} onDismiss={() => setSaveError(null)} testID="settings-save-error" />
      ) : null}
      {savedNotice ? (
        <View style={[styles.notice, { backgroundColor: theme.successBg }]} accessibilityRole="alert">
          <Text style={[textStyle("body", locale), { color: theme.success }]}>{t("settings.saved")}</Text>
        </View>
      ) : null}

      <GSectionHeader title={t("settings.sections.profile")} divider={false} />
      <View style={styles.mixedGroup}>
        <GTextInput
          label={t("settings.fields.name")}
          value={form.name}
          onChangeText={(name) => setForm({ ...form, name })}
          error={nameError}
          testID="settings-name"
        />

        {/* Nested so the two ROWS keep the row rhythm (`rowGap`) even though
            the group around them keeps the field rhythm (`groupGap`). Without
            this the rows sat 12dp apart here and 4dp apart under Training,
            which read as an accident rather than as a density decision. */}
        <View style={styles.rowGroup}>
          <GSettingRow
            label={t("settings.fields.gender")}
            value={t(GENDER_KEY[form.gender])}
            onPress={() => setOpenSheet("gender")}
            testID="settings-gender-row"
          />
          <GSettingRow
            label={t("settings.fields.birthDate")}
            value={dateFormatter.format(fromIsoDate(form.birthDate))}
            onPress={() => setShowDatePicker(true)}
            testID="settings-birth-date"
          />
        </View>
        {showDatePicker ? (
          <DateTimePicker
            value={fromIsoDate(form.birthDate)}
            mode="date"
            display={Platform.OS === "ios" ? "spinner" : "default"}
            maximumDate={new Date(Date.now() - 13 * 365.25 * 24 * 60 * 60 * 1000)}
            minimumDate={new Date(Date.now() - 100 * 365.25 * 24 * 60 * 60 * 1000)}
            onChange={handleDateChange}
            testID="settings-birth-date-picker"
          />
        ) : null}

        {unit === "metric" ? (
          <GTextInput
            label={t("settings.fields.heightCm")}
            value={heightCmText}
            onChangeText={setHeightCmText}
            error={heightError}
            keyboardType="decimal-pad"
            testID="settings-height-cm"
          />
        ) : (
          <View style={styles.row}>
            <View style={styles.rowField}>
              <GTextInput
                label={t("settings.fields.feet")}
                value={feetText}
                onChangeText={setFeetText}
                error={heightError}
                keyboardType="number-pad"
                testID="settings-feet"
              />
            </View>
            <View style={styles.rowField}>
              <GTextInput
                label={t("settings.fields.inches")}
                value={inchesText}
                onChangeText={setInchesText}
                keyboardType="number-pad"
                testID="settings-inches"
              />
            </View>
          </View>
        )}

        {unit === "metric" ? (
          <GTextInput
            label={t("settings.fields.weightKg")}
            value={weightKgText}
            onChangeText={setWeightKgText}
            error={weightError}
            keyboardType="decimal-pad"
            testID="settings-weight-kg"
          />
        ) : (
          <GTextInput
            label={t("settings.fields.weightLb")}
            value={weightLbText}
            onChangeText={setWeightLbText}
            error={weightError}
            keyboardType="decimal-pad"
            testID="settings-weight-lb"
          />
        )}
      </View>

      <GSectionHeader title={t("settings.sections.training")} />
      <View style={styles.rowGroup}>
        <GSettingRow
          label={t("settings.fields.goal")}
          value={t(GOAL_KEY[form.goal])}
          onPress={() => setOpenSheet("goal")}
          testID="settings-goal-row"
        />
        <GSettingRow
          label={t("settings.fields.experienceLevel")}
          value={t(EXPERIENCE_KEY[form.experienceLevel])}
          onPress={() => setOpenSheet("experience")}
          testID="settings-experience-row"
        />
        <GSettingRow
          label={t("settings.fields.activityLevel")}
          value={
            form.activityLevel === null
              ? t("settings.fields.notSet")
              : t(ACTIVITY_KEY[form.activityLevel])
          }
          onPress={() => setOpenSheet("activity")}
          testID="settings-activity-row"
        />
      </View>

      <GSectionHeader title={t("settings.sections.preferences")} />
      <View style={styles.rowGroup}>
        <GSettingRow
          label={t("settings.units.label")}
          value={t(UNIT_KEY[unit])}
          onPress={() => setOpenSheet("unit")}
          testID="settings-unit-row"
        />
        <GSettingRow
          label={t("settings.language.label")}
          value={t(LANGUAGE_KEY[form.language])}
          onPress={() => setOpenSheet("language")}
          testID="settings-language-row"
        />
        <GSettingRow
          label={t("settings.theme.label")}
          value={t(THEME_KEY[themePreference])}
          onPress={() => setOpenSheet("theme")}
          testID="settings-theme-row"
        />
      </View>
      <View style={styles.timezoneGroup}>
        <GTextInput
          label={t("settings.fields.timezone")}
          value={form.timezone}
          onChangeText={(timezone) => setForm({ ...form, timezone })}
          testID="settings-timezone"
        />
        <GButton
          variant="ghost"
          label={t("settings.fields.timezoneUseDevice")}
          onPress={() => {
            const deviceTimezone = getCalendars()[0]?.timeZone;
            if (deviceTimezone) setForm({ ...form, timezone: deviceTimezone });
          }}
          testID="settings-timezone-use-device"
        />
      </View>

      {/* The one primary action on this screen. Everything above it is a row
          or a field and everything below it is `secondary` or `ghost`, so
          exactly one filled control competes for the eye. */}
      <View style={styles.saveBlock}>
        <GButton
          label={t("settings.save")}
          onPress={handleSave}
          loading={saving}
          fullWidth
          testID="settings-save"
        />
      </View>

      <GSectionHeader title={t("settings.sections.account")} />
      <View style={styles.accountGroup}>
        {accountError ? (
          <GErrorBanner
            code={accountError}
            onDismiss={() => setAccountError(null)}
            testID="settings-account-error"
          />
        ) : null}

        <GButton
          variant="secondary"
          label={t("settings.account.logOut")}
          onPress={handleLogout}
          loading={accountBusy === "logout"}
          disabled={accountBusy !== null}
          fullWidth
          testID="settings-logout"
        />
        <GButton
          variant="secondary"
          label={t("settings.account.logOutAll")}
          onPress={handleLogoutAll}
          loading={accountBusy === "logoutAll"}
          disabled={accountBusy !== null}
          fullWidth
          testID="settings-logout-all"
        />
      </View>

      {/* Destructive actions last and set apart by a full `sectionGap`, so
          "Delete account" is never what a thumb lands on next after "Log out".
          The typed-DELETE-plus-password confirm below is the one this screen
          already had, unchanged -- note it is an inline panel, not a GDialog;
          GDialog here covers the language-reload and account-deleted notices. */}
      <View style={styles.dangerZone}>
        {!deletePanelOpen ? (
          <GButton
            variant="ghost"
            label={t("settings.account.deleteAccount")}
            onPress={() => setDeletePanelOpen(true)}
            testID="settings-delete-open"
          />
        ) : (
          <View
            style={[styles.deletePanel, { borderColor: theme.error, backgroundColor: theme.errorBg }]}
          >
            <Text style={[textStyle("body", locale), { color: theme.error }]}>
              {t("settings.account.deleteWarning")}
            </Text>
            {hasPassword ? (
              <GTextInput
                label={t("settings.account.deletePasswordLabel")}
                value={deletePassword}
                onChangeText={setDeletePassword}
                secure
                testID="settings-delete-password"
              />
            ) : null}
            <GTextInput
              label={t("settings.account.deleteConfirmLabel")}
              value={deleteConfirmText}
              onChangeText={setDeleteConfirmText}
              testID="settings-delete-confirm-text"
            />
            <GButton
              label={t("settings.account.deleteConfirmButton")}
              onPress={handleDeleteAccount}
              loading={accountBusy === "delete"}
              disabled={!deleteConfirmValid || accountBusy !== null}
              fullWidth
              testID="settings-delete-confirm"
            />
            <GButton
              variant="ghost"
              label={t("settings.account.deleteCancel")}
              onPress={() => {
                setDeletePanelOpen(false);
                setDeletePassword("");
                setDeleteConfirmText("");
              }}
              disabled={accountBusy !== null}
              testID="settings-delete-cancel"
            />
          </View>
        )}
      </View>

      {/* The choices. Each sheet mounts nothing until its row is tapped, which
          is the whole reason the screen is no longer a wall. The testIDs are
          the ones the old cards carried -- GOptionSheet appends the option
          value, so "settings-goal" still yields "settings-goal-lose". */}
      <GOptionSheet
        visible={openSheet === "gender"}
        title={t("settings.fields.gender")}
        options={genderOptions}
        selected={form.gender}
        onSelect={(gender) => setForm({ ...form, gender })}
        onClose={() => setOpenSheet(null)}
        testID="settings-gender"
      />
      <GOptionSheet
        visible={openSheet === "goal"}
        title={t("settings.fields.goal")}
        options={goalOptions}
        selected={form.goal}
        onSelect={(goal) => setForm({ ...form, goal })}
        onClose={() => setOpenSheet(null)}
        testID="settings-goal"
      />
      <GOptionSheet
        visible={openSheet === "experience"}
        title={t("settings.fields.experienceLevel")}
        options={experienceOptions}
        selected={form.experienceLevel}
        onSelect={(experienceLevel) => setForm({ ...form, experienceLevel })}
        onClose={() => setOpenSheet(null)}
        testID="settings-experience"
      />
      <GOptionSheet
        visible={openSheet === "activity"}
        title={t("settings.fields.activityLevel")}
        options={activityOptions}
        selected={form.activityLevel}
        onSelect={(activityLevel) => setForm({ ...form, activityLevel })}
        onClose={() => setOpenSheet(null)}
        testID="settings-activity"
      />
      <GOptionSheet
        visible={openSheet === "unit"}
        title={t("settings.units.label")}
        options={unitOptions}
        selected={unit}
        onSelect={handleUnitChange}
        onClose={() => setOpenSheet(null)}
        testID="settings-unit"
      />
      <GOptionSheet
        visible={openSheet === "language"}
        title={t("settings.language.label")}
        options={languageOptions}
        selected={form.language}
        onSelect={handleLanguageChange}
        onClose={() => setOpenSheet(null)}
        testID="settings-language"
      />
      <GOptionSheet
        visible={openSheet === "theme"}
        title={t("settings.theme.label")}
        options={themeOptions}
        selected={themePreference}
        // Applies on this frame and persists locally; no Save, no reload
        // prompt -- unlike the language switch above, a palette swap does not
        // need one.
        onSelect={setThemePreference}
        onClose={() => setOpenSheet(null)}
        testID="settings-theme"
      />

      <GDialog
        visible={languageNoticeVisible}
        onClose={() => setLanguageNoticeVisible(false)}
        titleKey="auth.language.reloadTitle"
        bodyKey="auth.language.reloadMessage"
        actions={[
          {
            labelKey: "auth.language.ok",
            variant: "primary",
            onPress: () => setLanguageNoticeVisible(false),
          },
        ]}
        testID="settings-language-notice"
      />

      <GDialog
        visible={deletedNoticeVisible}
        onClose={() => {
          setDeletedNoticeVisible(false);
          router.replace("/(auth)/welcome");
        }}
        titleKey="settings.account.deletedNotice"
        actions={[
          {
            labelKey: "auth.language.ok",
            variant: "primary",
            onPress: () => {
              setDeletedNoticeVisible(false);
              router.replace("/(auth)/welcome");
            },
          },
        ]}
        testID="settings-deleted-notice"
      />
    </GScreen>
  );
}

const styles = StyleSheet.create({
  // Density, deliberately not uniform. A group that MIXES inline fields with
  // rows breathes at the field's rhythm (`groupGap`); a group of pure rows is
  // tighter (`rowGap`), because each row already carries its own 56dp of
  // height and so needs separation rather than distance. The space BETWEEN
  // groups is owned by GSectionHeader, so it is stated once for the whole app
  // instead of re-picked here.
  mixedGroup: {
    gap: layout.groupGap,
  },
  rowGroup: {
    gap: layout.rowGap,
  },
  timezoneGroup: {
    gap: layout.groupGap,
    marginTop: layout.looseGap,
  },
  saveBlock: {
    marginTop: layout.sectionGap,
  },
  accountGroup: {
    gap: layout.groupGap,
  },
  dangerZone: {
    marginTop: layout.sectionGap,
  },
  row: {
    flexDirection: "row",
    gap: space[2],
  },
  rowField: {
    flex: 1,
  },
  notice: {
    borderRadius: radius.md,
    padding: space[3],
    marginBottom: space[2],
  },
  deletePanel: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: space[3],
    gap: layout.groupGap,
  },
});
