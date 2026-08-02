/**
 * §9.3 screen 12 — onboarding step 6: units and language. Both are real
 * `profiles` columns (§4.3) sent in the Finish call, not just local display
 * preferences — picking a language here also flips the live app locale
 * (§9.6), same affordance and reload notice as welcome.tsx's toggle.
 */
import { useState } from "react";
import { Alert, StyleSheet, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";

import { GButton, GProgressBar, GScreen, GSelectCard } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useOnboardingDraft } from "../../src/onboarding/draft";
import { space } from "../../src/theme/tokens";
import type { Language, UnitSystem } from "../../src/api/profile";

export default function OnboardingStepSix() {
  const { t, locale, setLocale } = useI18n();
  const params = useLocalSearchParams<{ from?: string }>();

  const unitSystem = useOnboardingDraft((s) => s.unitSystem);
  const language = useOnboardingDraft((s) => s.language);
  const setUnitSystem = useOnboardingDraft((s) => s.setUnitSystem);
  const setLanguage = useOnboardingDraft((s) => s.setLanguage);

  const [selectedLanguage, setSelectedLanguage] = useState<Language>(language);

  const handleUnitSelect = (next: UnitSystem) => {
    setUnitSystem(next);
  };

  const handleLanguageSelect = (next: Language) => {
    setLanguage(next);
    setSelectedLanguage(next);
    if (next !== locale) {
      setLocale(next);
      Alert.alert(t("auth.language.reloadTitle"), t("auth.language.reloadMessage"), [
        { text: t("auth.language.ok") },
      ]);
    }
  };

  const handleContinue = () => {
    if (params.from === "review") {
      router.back();
    } else {
      router.push("/(onboarding)/review");
    }
  };

  return (
    <GScreen
      header={{
        title: t("onboarding.step6.title"),
        onBack: router.canGoBack() ? () => router.back() : undefined,
      }}
    >
      <GProgressBar step={6} total={6} testID="onboarding-step6-progress" />
      <View style={styles.form}>
        <View style={styles.selectGroup}>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("onboarding.step6.metric")}
              selected={unitSystem === "metric"}
              onPress={() => handleUnitSelect("metric")}
              testID="onboarding-step6-metric"
            />
          </View>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("onboarding.step6.imperial")}
              selected={unitSystem === "imperial"}
              onPress={() => handleUnitSelect("imperial")}
              testID="onboarding-step6-imperial"
            />
          </View>
        </View>

        <View style={styles.selectGroup}>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("onboarding.step6.arabic")}
              selected={selectedLanguage === "ar"}
              onPress={() => handleLanguageSelect("ar")}
              testID="onboarding-step6-arabic"
            />
          </View>
          <View style={styles.rowField}>
            <GSelectCard
              title={t("onboarding.step6.english")}
              selected={selectedLanguage === "en"}
              onPress={() => handleLanguageSelect("en")}
              testID="onboarding-step6-english"
            />
          </View>
        </View>

        <GButton
          label={t("onboarding.continue")}
          onPress={handleContinue}
          fullWidth
          testID="onboarding-step6-continue"
        />
      </View>
    </GScreen>
  );
}

const styles = StyleSheet.create({
  form: {
    gap: space[4],
    marginTop: space[3],
  },
  selectGroup: {
    flexDirection: "row",
    gap: space[2],
  },
  rowField: {
    flex: 1,
  },
});
