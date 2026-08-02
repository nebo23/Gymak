/**
 * §9.3 screen 11 — onboarding step 5: experience level. Three cards, each
 * with one clarifying line, per the screen inventory's own example text.
 */
import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";

import { GButton, GErrorBanner, GProgressBar, GScreen, GSelectCard } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useOnboardingDraft } from "../../src/onboarding/draft";
import { space } from "../../src/theme/tokens";
import type { ExperienceLevel } from "../../src/api/profile";

export default function OnboardingStepFive() {
  const { t } = useI18n();
  const params = useLocalSearchParams<{ from?: string }>();

  const experienceLevel = useOnboardingDraft((s) => s.experienceLevel);
  const setExperienceLevel = useOnboardingDraft((s) => s.setExperienceLevel);
  const [error, setError] = useState(false);

  const handleSelect = (next: ExperienceLevel) => {
    setExperienceLevel(next);
    setError(false);
  };

  const handleContinue = () => {
    if (!experienceLevel) {
      setError(true);
      return;
    }
    if (params.from === "review") {
      router.back();
    } else {
      router.push("/(onboarding)/step-6");
    }
  };

  return (
    <GScreen
      header={{
        title: t("onboarding.step5.title"),
        onBack: router.canGoBack() ? () => router.back() : undefined,
      }}
    >
      <GProgressBar step={5} total={6} testID="onboarding-step5-progress" />
      <View style={styles.form}>
        <GSelectCard
          title={t("onboarding.step5.beginner")}
          description={t("onboarding.step5.beginnerDescription")}
          selected={experienceLevel === "beginner"}
          onPress={() => handleSelect("beginner")}
          testID="onboarding-step5-beginner"
        />
        <GSelectCard
          title={t("onboarding.step5.intermediate")}
          description={t("onboarding.step5.intermediateDescription")}
          selected={experienceLevel === "intermediate"}
          onPress={() => handleSelect("intermediate")}
          testID="onboarding-step5-intermediate"
        />
        <GSelectCard
          title={t("onboarding.step5.advanced")}
          description={t("onboarding.step5.advancedDescription")}
          selected={experienceLevel === "advanced"}
          onPress={() => handleSelect("advanced")}
          testID="onboarding-step5-advanced"
        />

        {error ? (
          <GErrorBanner
            message={t("fieldErrors.experienceLevel.REQUIRED")}
            testID="onboarding-step5-error"
          />
        ) : null}

        <GButton
          label={t("onboarding.continue")}
          onPress={handleContinue}
          fullWidth
          testID="onboarding-step5-continue"
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
});
