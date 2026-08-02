/**
 * §9.3 screen 9 — onboarding step 3: height and weight, with a unit toggle
 * that converts live. The two GSelectCards below aren't a selection between
 * mutually-exclusive *options* in the domain sense (§10.5's own contract is
 * about that shape too — a two-way toggle is just a selection of size 2), so
 * they double as the toggle. Whichever unit is active, the values entered are
 * converted to SI (cm / kg) before being written to the draft — the wire
 * format the server accepts is never imperial (§7.1).
 */
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";

import { GButton, GProgressBar, GScreen, GSelectCard, GTextInput } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useOnboardingDraft } from "../../src/onboarding/draft";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { space } from "../../src/theme/tokens";
import {
  cmToFeetInches,
  feetInchesToCm,
  heightCmSchema,
  kgToLbs,
  lbsToKg,
  weightKgSchema,
} from "../../src/validation/schemas";
import type { UnitSystem } from "../../src/api/profile";

export default function OnboardingStepThree() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const params = useLocalSearchParams<{ from?: string }>();

  const draftUnit = useOnboardingDraft((s) => s.unitSystem);
  const draftHeightCm = useOnboardingDraft((s) => s.heightCm);
  const draftWeightKg = useOnboardingDraft((s) => s.weightKg);
  const setUnitSystem = useOnboardingDraft((s) => s.setUnitSystem);
  const setHeightWeight = useOnboardingDraft((s) => s.setHeightWeight);

  const [unit, setUnit] = useState<UnitSystem>(draftUnit);
  const initialImperial = draftHeightCm ? cmToFeetInches(draftHeightCm) : null;
  const [heightCmText, setHeightCmText] = useState(draftHeightCm ? String(draftHeightCm) : "");
  const [weightKgText, setWeightKgText] = useState(draftWeightKg ? String(draftWeightKg) : "");
  const [feetText, setFeetText] = useState(initialImperial ? String(initialImperial.feet) : "");
  const [inchesText, setInchesText] = useState(initialImperial ? String(initialImperial.inches) : "");
  const [weightLbText, setWeightLbText] = useState(
    draftWeightKg ? String(kgToLbs(draftWeightKg)) : "",
  );
  const [heightError, setHeightError] = useState<string | undefined>(undefined);
  const [weightError, setWeightError] = useState<string | undefined>(undefined);

  const handleUnitChange = (next: UnitSystem) => {
    if (next === unit) return;
    if (next === "imperial") {
      const cm = Number.parseFloat(heightCmText);
      const kg = Number.parseFloat(weightKgText);
      if (Number.isFinite(cm)) {
        const { feet, inches } = cmToFeetInches(cm);
        setFeetText(String(feet));
        setInchesText(String(inches));
      }
      if (Number.isFinite(kg)) {
        setWeightLbText(String(kgToLbs(kg)));
      }
    } else {
      const feet = Number.parseFloat(feetText);
      const inches = Number.parseFloat(inchesText);
      const lb = Number.parseFloat(weightLbText);
      if (Number.isFinite(feet) && Number.isFinite(inches)) {
        setHeightCmText(String(feetInchesToCm(feet, inches)));
      }
      if (Number.isFinite(lb)) {
        setWeightKgText(String(lbsToKg(lb)));
      }
    }
    setUnit(next);
    setUnitSystem(next);
    setHeightError(undefined);
    setWeightError(undefined);
  };

  const handleContinue = () => {
    let heightCm: number;
    let weightKg: number;

    if (unit === "metric") {
      heightCm = Number.parseFloat(heightCmText);
      weightKg = Number.parseFloat(weightKgText);
    } else {
      const feet = Number.parseFloat(feetText);
      const inches = Number.parseFloat(inchesText);
      heightCm = feetInchesToCm(feet, inches);
      weightKg = lbsToKg(Number.parseFloat(weightLbText));
    }

    const heightResult = heightCmSchema.safeParse(heightCm);
    const weightResult = weightKgSchema.safeParse(weightKg);
    setHeightError(heightResult.success ? undefined : t("fieldErrors.height.OUT_OF_RANGE"));
    setWeightError(weightResult.success ? undefined : t("fieldErrors.weight.OUT_OF_RANGE"));
    if (!heightResult.success || !weightResult.success) return;

    setHeightWeight(heightResult.data, weightResult.data);
    if (params.from === "review") {
      router.back();
    } else {
      router.push("/(onboarding)/step-4");
    }
  };

  return (
    <GScreen
      header={{
        title: t("onboarding.step3.title"),
        onBack: router.canGoBack() ? () => router.back() : undefined,
      }}
    >
      <GProgressBar step={3} total={6} testID="onboarding-step3-progress" />
      <View style={styles.form}>
        <View style={styles.selectGroup}>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("onboarding.step3.metric")}
              selected={unit === "metric"}
              onPress={() => handleUnitChange("metric")}
              testID="onboarding-step3-metric"
            />
          </View>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("onboarding.step3.imperial")}
              selected={unit === "imperial"}
              onPress={() => handleUnitChange("imperial")}
              testID="onboarding-step3-imperial"
            />
          </View>
        </View>

        {unit === "metric" ? (
          <GTextInput
            label={t("onboarding.step3.heightCm")}
            value={heightCmText}
            onChangeText={setHeightCmText}
            error={heightError}
            keyboardType="decimal-pad"
            testID="onboarding-step3-height-cm"
          />
        ) : (
          <View style={styles.row}>
            <View style={styles.rowField}>
              <GTextInput
                label={t("onboarding.step3.feet")}
                value={feetText}
                onChangeText={setFeetText}
                error={heightError}
                keyboardType="number-pad"
                testID="onboarding-step3-feet"
              />
            </View>
            <View style={styles.rowField}>
              <GTextInput
                label={t("onboarding.step3.inches")}
                value={inchesText}
                onChangeText={setInchesText}
                keyboardType="number-pad"
                testID="onboarding-step3-inches"
              />
            </View>
          </View>
        )}

        {unit === "metric" ? (
          <GTextInput
            label={t("onboarding.step3.weightKg")}
            value={weightKgText}
            onChangeText={setWeightKgText}
            error={weightError}
            keyboardType="decimal-pad"
            testID="onboarding-step3-weight-kg"
          />
        ) : (
          <GTextInput
            label={t("onboarding.step3.weightLb")}
            value={weightLbText}
            onChangeText={setWeightLbText}
            error={weightError}
            keyboardType="decimal-pad"
            testID="onboarding-step3-weight-lb"
          />
        )}

        <GButton
          label={t("onboarding.continue")}
          onPress={handleContinue}
          fullWidth
          testID="onboarding-step3-continue"
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
  selectGroup: {
    flexDirection: "row",
    gap: space[2],
  },
  row: {
    flexDirection: "row",
    gap: space[2],
  },
  rowField: {
    flex: 1,
  },
});
