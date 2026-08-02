/**
 * §9.3 screen 8 — onboarding step 2: birth date. "A native date picker or
 * three selects. Never a free-text field." — this uses the native picker.
 * iOS renders it inline (spinner display); Android's community picker only
 * paints a dialog while mounted, so it's shown behind a button that opens it
 * and unmounts it again on dismiss (the standard pattern for this library).
 */
import { useMemo, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import DateTimePicker, { type DateTimePickerEvent } from "@react-native-community/datetimepicker";

import { GButton, GProgressBar, GScreen } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useOnboardingDraft } from "../../src/onboarding/draft";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { controlHeight, radius, space } from "../../src/theme/tokens";
import { birthDateSchema } from "../../src/validation/schemas";

const MIN_AGE_YEARS = 13;
const MAX_AGE_YEARS = 100;

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

function addYears(date: Date, years: number): Date {
  const next = new Date(date);
  next.setFullYear(next.getFullYear() + years);
  return next;
}

export default function OnboardingStepTwo() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const params = useLocalSearchParams<{ from?: string }>();

  const birthDate = useOnboardingDraft((s) => s.birthDate);
  const setBirthDate = useOnboardingDraft((s) => s.setBirthDate);

  const today = useMemo(() => new Date(), []);
  const maximumDate = useMemo(() => addYears(today, -MIN_AGE_YEARS), [today]);
  const minimumDate = useMemo(() => addYears(today, -MAX_AGE_YEARS), [today]);

  const [date, setDate] = useState<Date>(() => (birthDate ? fromIsoDate(birthDate) : maximumDate));
  const [showPicker, setShowPicker] = useState(Platform.OS === "ios");
  const [error, setError] = useState<string | undefined>(undefined);

  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale === "ar" ? "ar-u-nu-latn" : "en", {
        year: "numeric",
        month: "long",
        day: "numeric",
      }),
    [locale],
  );

  const handleChange = (event: DateTimePickerEvent, selected?: Date) => {
    if (Platform.OS === "android") {
      setShowPicker(false);
    }
    if (event.type === "set" && selected) {
      setDate(selected);
      setError(undefined);
    }
  };

  const handleContinue = () => {
    const iso = toIsoDate(date);
    const result = birthDateSchema.safeParse(iso);
    if (!result.success) {
      setError(t("fieldErrors.birthDate.OUT_OF_RANGE"));
      return;
    }
    setBirthDate(iso);
    if (params.from === "review") {
      router.back();
    } else {
      router.push("/(onboarding)/step-3");
    }
  };

  return (
    <GScreen
      header={{
        title: t("onboarding.step2.title"),
        onBack: router.canGoBack() ? () => router.back() : undefined,
      }}
    >
      <GProgressBar step={2} total={6} testID="onboarding-step2-progress" />
      <View style={styles.form}>
        <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
          {t("onboarding.step2.label")}
        </Text>

        {Platform.OS === "android" ? (
          <Pressable
            onPress={() => setShowPicker(true)}
            accessibilityRole="button"
            accessibilityLabel={t("onboarding.step2.label")}
            style={[
              styles.androidField,
              { backgroundColor: theme.input, borderColor: error ? theme.error : theme.border },
            ]}
            testID="onboarding-step2-open-picker"
          >
            <Text style={[textStyle("body", "en"), { color: theme.textPrimary }]}>
              {dateFormatter.format(date)}
            </Text>
          </Pressable>
        ) : null}

        {showPicker ? (
          <DateTimePicker
            value={date}
            mode="date"
            display={Platform.OS === "ios" ? "spinner" : "default"}
            maximumDate={maximumDate}
            minimumDate={minimumDate}
            onChange={handleChange}
            testID="onboarding-step2-picker"
          />
        ) : null}

        {error ? (
          <Text
            style={[textStyle("caption", locale), { color: theme.error }]}
            accessibilityRole="alert"
            accessibilityLiveRegion="polite"
          >
            {error}
          </Text>
        ) : null}

        <GButton
          label={t("onboarding.continue")}
          onPress={handleContinue}
          fullWidth
          testID="onboarding-step2-continue"
        />
      </View>
    </GScreen>
  );
}

const styles = StyleSheet.create({
  form: {
    gap: space[3],
    marginTop: space[3],
  },
  androidField: {
    minHeight: controlHeight,
    borderRadius: radius.md,
    borderWidth: 1,
    justifyContent: "center",
    paddingHorizontal: space[3],
  },
});
