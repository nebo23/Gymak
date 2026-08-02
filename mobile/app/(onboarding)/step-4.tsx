/**
 * §9.3 screen 10 — onboarding step 4: goal. Three cards; `lose` is disabled
 * (not hidden) for a draft birth date under 18, with the reason inline on the
 * card itself (§10.5's GSelectCard `disabledReason`), mirroring P1-SAF-001.
 *
 * The "handles the server's 422 as well" requirement: this screen makes no
 * network call itself (§9.3's note — exactly one POST /profile, from
 * review.tsx), but a user can select `lose` while 18, then go back to step 2
 * and lower the birth date before Finish, which the server correctly rejects
 * with 422 GOAL_NOT_PERMITTED_FOR_MINOR. review.tsx clears the now-invalid
 * goal and routes back here with `?serverRejected=1`, which this screen
 * reads to show why the previous selection is gone.
 */
import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";

import { GButton, GErrorBanner, GProgressBar, GScreen, GSelectCard } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useOnboardingDraft } from "../../src/onboarding/draft";
import { space } from "../../src/theme/tokens";
import { isGoalPermitted } from "../../src/validation/schemas";
import type { Goal } from "../../src/api/profile";

export default function OnboardingStepFour() {
  const { t } = useI18n();
  const params = useLocalSearchParams<{ from?: string; serverRejected?: string }>();

  const goal = useOnboardingDraft((s) => s.goal);
  const birthDate = useOnboardingDraft((s) => s.birthDate);
  const setGoal = useOnboardingDraft((s) => s.setGoal);

  const [error, setError] = useState(false);
  const [showServerRejected, setShowServerRejected] = useState(params.serverRejected === "1");

  const loseDisabled = !isGoalPermitted("lose", birthDate ?? "");

  const handleSelect = (next: Goal) => {
    setGoal(next);
    setError(false);
    setShowServerRejected(false);
  };

  const handleContinue = () => {
    if (!goal) {
      setError(true);
      return;
    }
    if (params.from === "review") {
      router.back();
    } else {
      router.push("/(onboarding)/step-5");
    }
  };

  return (
    <GScreen
      header={{
        title: t("onboarding.step4.title"),
        onBack: router.canGoBack() ? () => router.back() : undefined,
      }}
    >
      <GProgressBar step={4} total={6} testID="onboarding-step4-progress" />

      {showServerRejected ? (
        <GErrorBanner
          message={t("onboarding.step4.serverRejected")}
          onDismiss={() => setShowServerRejected(false)}
          testID="onboarding-step4-server-rejected"
        />
      ) : null}

      <View style={styles.form}>
        <GSelectCard
          title={t("onboarding.step4.lose")}
          selected={goal === "lose"}
          onPress={() => handleSelect("lose")}
          disabled={loseDisabled}
          disabledReason={loseDisabled ? t("onboarding.step4.loseDisabledReason") : undefined}
          testID="onboarding-step4-lose"
        />
        <GSelectCard
          title={t("onboarding.step4.gain")}
          selected={goal === "gain"}
          onPress={() => handleSelect("gain")}
          testID="onboarding-step4-gain"
        />
        <GSelectCard
          title={t("onboarding.step4.maintain")}
          selected={goal === "maintain"}
          onPress={() => handleSelect("maintain")}
          testID="onboarding-step4-maintain"
        />

        {error ? (
          <GErrorBanner message={t("fieldErrors.goal.REQUIRED")} testID="onboarding-step4-error" />
        ) : null}

        <GButton
          label={t("onboarding.continue")}
          onPress={handleContinue}
          fullWidth
          testID="onboarding-step4-continue"
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
