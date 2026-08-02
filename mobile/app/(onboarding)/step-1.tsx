/**
 * §9.3 screen 7 — onboarding step 1: name and gender. First step, no back
 * target in the normal flow (only reachable if this screen was itself
 * pushed for a review-edit jump, in which case `router.canGoBack()` is true
 * and GScreen shows the chevron for free).
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
import { nameSchema } from "../../src/validation/schemas";

export default function OnboardingStepOne() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const params = useLocalSearchParams<{ from?: string }>();

  const name = useOnboardingDraft((s) => s.name);
  const gender = useOnboardingDraft((s) => s.gender);
  const setName = useOnboardingDraft((s) => s.setName);
  const setGender = useOnboardingDraft((s) => s.setGender);

  const [localName, setLocalName] = useState(name);
  const [nameError, setNameError] = useState<string | undefined>(undefined);
  const [genderError, setGenderError] = useState(false);

  const handleContinue = () => {
    const result = nameSchema.safeParse(localName);
    let hasError = false;
    if (!result.success) {
      setNameError(t("fieldErrors.name.INVALID"));
      hasError = true;
    } else {
      setNameError(undefined);
    }
    if (!gender) {
      setGenderError(true);
      hasError = true;
    } else {
      setGenderError(false);
    }
    if (hasError || !result.success) return;

    setName(result.data);
    if (params.from === "review") {
      router.back();
    } else {
      router.push("/(onboarding)/step-2");
    }
  };

  return (
    <GScreen header={{ title: t("onboarding.step1.title"), onBack: router.canGoBack() ? () => router.back() : undefined }}>
      <GProgressBar step={1} total={6} testID="onboarding-step1-progress" />
      <View style={styles.form}>
        <GTextInput
          label={t("onboarding.step1.name")}
          value={localName}
          onChangeText={setLocalName}
          error={nameError}
          autoComplete="name"
          testID="onboarding-step1-name"
        />

        <View style={styles.selectGroup}>
          <GSelectCard
            title={t("onboarding.step1.male")}
            selected={gender === "male"}
            onPress={() => {
              setGender("male");
              setGenderError(false);
            }}
            testID="onboarding-step1-male"
          />
          <GSelectCard
            title={t("onboarding.step1.female")}
            selected={gender === "female"}
            onPress={() => {
              setGender("female");
              setGenderError(false);
            }}
            testID="onboarding-step1-female"
          />
        </View>
        {genderError ? (
          <Text
            style={[textStyle("caption", locale), { color: theme.error }]}
            accessibilityRole="alert"
            accessibilityLiveRegion="polite"
          >
            {t("fieldErrors.gender.REQUIRED")}
          </Text>
        ) : null}

        <GButton
          label={t("onboarding.continue")}
          onPress={handleContinue}
          fullWidth
          testID="onboarding-step1-continue"
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
    gap: space[2],
  },
});
