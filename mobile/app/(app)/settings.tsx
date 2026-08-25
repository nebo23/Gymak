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
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
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
  GScreen,
  GSelectCard,
  GTextInput,
} from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { controlHeight, radius, space } from "../../src/theme/tokens";
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

      <Text style={[textStyle("h3", locale), styles.sectionTitle, { color: theme.textPrimary }]}>
        {t("settings.sections.profile")}
      </Text>
      <View style={styles.form}>
        <GTextInput
          label={t("settings.fields.name")}
          value={form.name}
          onChangeText={(name) => setForm({ ...form, name })}
          error={nameError}
          testID="settings-name"
        />

        <View style={styles.row}>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("settings.fields.male")}
              selected={form.gender === "male"}
              onPress={() => setForm({ ...form, gender: "male" })}
              testID="settings-gender-male"
            />
          </View>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("settings.fields.female")}
              selected={form.gender === "female"}
              onPress={() => setForm({ ...form, gender: "female" })}
              testID="settings-gender-female"
            />
          </View>
        </View>

        <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
          {t("settings.fields.birthDate")}
        </Text>
        <Pressable
          onPress={() => setShowDatePicker(true)}
          accessibilityRole="button"
          accessibilityLabel={t("settings.fields.birthDate")}
          style={[styles.dateField, { backgroundColor: theme.input, borderColor: theme.border }]}
          testID="settings-birth-date"
        >
          <Text style={[textStyle("body", "en"), { color: theme.textPrimary }]}>
            {dateFormatter.format(fromIsoDate(form.birthDate))}
          </Text>
        </Pressable>
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

        <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
          {t("settings.fields.goal")}
        </Text>
        <GSelectCard
          title={t("settings.fields.goalLose")}
          selected={form.goal === "lose"}
          onPress={() => setForm({ ...form, goal: "lose" })}
          disabled={loseDisabled}
          disabledReason={loseDisabled ? t("settings.fields.goalLoseDisabledReason") : undefined}
          testID="settings-goal-lose"
        />
        <GSelectCard
          title={t("settings.fields.goalGain")}
          selected={form.goal === "gain"}
          onPress={() => setForm({ ...form, goal: "gain" })}
          testID="settings-goal-gain"
        />
        <GSelectCard
          title={t("settings.fields.goalMaintain")}
          selected={form.goal === "maintain"}
          onPress={() => setForm({ ...form, goal: "maintain" })}
          testID="settings-goal-maintain"
        />

        <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
          {t("settings.fields.experienceLevel")}
        </Text>
        <GSelectCard
          title={t("settings.fields.experienceBeginner")}
          selected={form.experienceLevel === "beginner"}
          onPress={() => setForm({ ...form, experienceLevel: "beginner" })}
          testID="settings-experience-beginner"
        />
        <GSelectCard
          title={t("settings.fields.experienceIntermediate")}
          selected={form.experienceLevel === "intermediate"}
          onPress={() => setForm({ ...form, experienceLevel: "intermediate" })}
          testID="settings-experience-intermediate"
        />
        <GSelectCard
          title={t("settings.fields.experienceAdvanced")}
          selected={form.experienceLevel === "advanced"}
          onPress={() => setForm({ ...form, experienceLevel: "advanced" })}
          testID="settings-experience-advanced"
        />

        <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
          {t("settings.fields.activityLevel")}
        </Text>
        {ACTIVITY_LEVELS.map((level) => (
          <GSelectCard
            key={level}
            title={t(ACTIVITY_KEY[level])}
            selected={form.activityLevel === level}
            onPress={() => setForm({ ...form, activityLevel: level })}
            testID={`settings-activity-${level}`}
          />
        ))}
      </View>

      <Text style={[textStyle("h3", locale), styles.sectionTitle, { color: theme.textPrimary }]}>
        {t("settings.sections.preferences")}
      </Text>
      <View style={styles.form}>
        <View style={styles.row}>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("settings.units.metric")}
              selected={unit === "metric"}
              onPress={() => handleUnitChange("metric")}
              testID="settings-unit-metric"
            />
          </View>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("settings.units.imperial")}
              selected={unit === "imperial"}
              onPress={() => handleUnitChange("imperial")}
              testID="settings-unit-imperial"
            />
          </View>
        </View>
        <View style={styles.row}>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("settings.language.arabic")}
              selected={form.language === "ar"}
              onPress={() => handleLanguageChange("ar")}
              testID="settings-language-ar"
            />
          </View>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("settings.language.english")}
              selected={form.language === "en"}
              onPress={() => handleLanguageChange("en")}
              testID="settings-language-en"
            />
          </View>
        </View>

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

      <GButton
        label={t("settings.save")}
        onPress={handleSave}
        loading={saving}
        fullWidth
        testID="settings-save"
      />

      <Text style={[textStyle("h3", locale), styles.sectionTitle, { color: theme.textPrimary }]}>
        {t("settings.sections.account")}
      </Text>
      <View style={styles.form}>
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

        {!deletePanelOpen ? (
          <GButton
            variant="ghost"
            label={t("settings.account.deleteAccount")}
            onPress={() => setDeletePanelOpen(true)}
            testID="settings-delete-open"
          />
        ) : (
          <View style={[styles.deletePanel, { borderColor: theme.error }]}>
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
  sectionTitle: {
    marginTop: space[5],
    marginBottom: space[1],
  },
  form: {
    gap: space[3],
  },
  row: {
    flexDirection: "row",
    gap: space[2],
  },
  rowField: {
    flex: 1,
  },
  dateField: {
    minHeight: controlHeight,
    borderRadius: radius.md,
    borderWidth: 1,
    justifyContent: "center",
    paddingHorizontal: space[3],
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
    gap: space[3],
  },
});
