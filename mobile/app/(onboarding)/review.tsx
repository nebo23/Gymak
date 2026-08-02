/**
 * §9.3 screen 13 — onboarding review. Every value collected across the six
 * steps, each row tappable to jump back to the step that owns it (pushed
 * with `?from=review`, so that step's Continue pops back here instead of
 * advancing — see step-1..step-6's own `params.from` handling). Finish makes
 * the onboarding flow's one and only network call: POST /profile.
 */
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";

import { createProfile } from "../../src/api/profile";
import { parseApiError, type ResolvedErrorCode } from "../../src/api/errors";
import { useSessionStore } from "../../src/auth/session";
import { GButton, GErrorBanner, GProgressBar, GScreen } from "../../src/components";
import { useI18n, type Locale } from "../../src/i18n";
import { draftToProfileInput, useOnboardingDraft } from "../../src/onboarding/draft";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { minTouchTarget, radius, space } from "../../src/theme/tokens";
import { cmToFeetInches, kgToLbs } from "../../src/validation/schemas";

function formatBirthDate(iso: string, locale: Locale): string {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-u-nu-latn" : "en", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(date);
}

interface ReviewRowProps {
  label: string;
  value: string;
  onEdit: () => void;
  testID?: string;
}

function ReviewRow({ label, value, onEdit, testID }: ReviewRowProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  return (
    <Pressable
      onPress={onEdit}
      accessibilityRole="button"
      accessibilityLabel={`${label}: ${value}. ${t("onboarding.review.edit")}`}
      style={[styles.row, { borderColor: theme.divider }]}
      testID={testID}
    >
      <View style={styles.rowText}>
        <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>{label}</Text>
        <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>{value}</Text>
      </View>
      <Text style={[textStyle("label", locale), { color: theme.textLink }]}>
        {t("onboarding.review.edit")}
      </Text>
    </Pressable>
  );
}

export default function OnboardingReview() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const draft = useOnboardingDraft();

  const [submitting, setSubmitting] = useState(false);
  const [requestError, setRequestError] = useState<ResolvedErrorCode | null>(null);
  const [retrySeconds, setRetrySeconds] = useState<number | null>(null);

  useEffect(() => {
    if (retrySeconds === null || retrySeconds <= 0) return;
    const id = setTimeout(() => setRetrySeconds((s) => (s ?? 1) - 1), 1000);
    return () => clearTimeout(id);
  }, [retrySeconds]);

  // Reachable only by direct deep-link (Fast Refresh, a resumed dev build) —
  // the normal step-1..step-6 flow can't land here with a gap. Send the user
  // back to fill in whatever step-1..step-6 didn't set, rather than crashing
  // on a null `input` below.
  useEffect(() => {
    if (draftToProfileInput(draft) === null) {
      router.replace("/(onboarding)/step-1");
    }
  }, [draft]);

  const input = draftToProfileInput(draft);
  if (!input) {
    return null;
  }

  const heightDisplay =
    draft.unitSystem === "imperial" && draft.heightCm !== null
      ? (() => {
          const { feet, inches } = cmToFeetInches(draft.heightCm);
          return `${feet}' ${inches}" (${draft.heightCm} cm)`;
        })()
      : `${draft.heightCm} cm`;

  const weightDisplay =
    draft.unitSystem === "imperial" && draft.weightKg !== null
      ? `${kgToLbs(draft.weightKg)} lb (${draft.weightKg} kg)`
      : `${draft.weightKg} kg`;

  const handleFinish = async () => {
    setRequestError(null);
    setRetrySeconds(null);
    setSubmitting(true);
    try {
      await createProfile(input);
      useOnboardingDraft.getState().reset();
      await useSessionStore.getState().hydrate();
      router.replace("/");
    } catch (err) {
      const problem = parseApiError(err);
      if (problem.code === "GOAL_NOT_PERMITTED_FOR_MINOR") {
        useOnboardingDraft.getState().setGoal(null);
        router.push({ pathname: "/(onboarding)/step-4", params: { serverRejected: "1" } });
      } else if (problem.retryAfterSeconds) {
        setRetrySeconds(problem.retryAfterSeconds);
      } else {
        setRequestError(problem.code);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const editStep1 = () => router.push({ pathname: "/(onboarding)/step-1", params: { from: "review" } });
  const editStep2 = () => router.push({ pathname: "/(onboarding)/step-2", params: { from: "review" } });
  const editStep3 = () => router.push({ pathname: "/(onboarding)/step-3", params: { from: "review" } });
  const editStep4 = () => router.push({ pathname: "/(onboarding)/step-4", params: { from: "review" } });
  const editStep5 = () => router.push({ pathname: "/(onboarding)/step-5", params: { from: "review" } });
  const editStep6 = () => router.push({ pathname: "/(onboarding)/step-6", params: { from: "review" } });

  return (
    <GScreen
      header={{
        title: t("onboarding.review.title"),
        onBack: router.canGoBack() ? () => router.back() : undefined,
      }}
    >
      <GProgressBar step={6} total={6} showLabel={false} testID="onboarding-review-progress" />

      {retrySeconds !== null && retrySeconds > 0 ? (
        <GErrorBanner
          message={t("auth.rateLimited.retryIn", { seconds: retrySeconds })}
          testID="onboarding-review-rate-limited"
        />
      ) : requestError ? (
        <GErrorBanner
          code={requestError}
          onDismiss={() => setRequestError(null)}
          testID="onboarding-review-error"
        />
      ) : null}

      <View style={styles.list}>
        <ReviewRow
          label={t("onboarding.review.name")}
          value={draft.name}
          onEdit={editStep1}
          testID="onboarding-review-name"
        />
        <ReviewRow
          label={t("onboarding.review.gender")}
          value={draft.gender === "male" ? t("onboarding.step1.male") : t("onboarding.step1.female")}
          onEdit={editStep1}
          testID="onboarding-review-gender"
        />
        <ReviewRow
          label={t("onboarding.review.birthDate")}
          value={draft.birthDate ? formatBirthDate(draft.birthDate, locale) : ""}
          onEdit={editStep2}
          testID="onboarding-review-birth-date"
        />
        <ReviewRow
          label={t("onboarding.review.height")}
          value={heightDisplay}
          onEdit={editStep3}
          testID="onboarding-review-height"
        />
        <ReviewRow
          label={t("onboarding.review.weight")}
          value={weightDisplay}
          onEdit={editStep3}
          testID="onboarding-review-weight"
        />
        <ReviewRow
          label={t("onboarding.review.goal")}
          value={t(`onboarding.step4.${draft.goal}`)}
          onEdit={editStep4}
          testID="onboarding-review-goal"
        />
        <ReviewRow
          label={t("onboarding.review.experienceLevel")}
          value={t(`onboarding.step5.${draft.experienceLevel}`)}
          onEdit={editStep5}
          testID="onboarding-review-experience"
        />
        <ReviewRow
          label={t("onboarding.review.units")}
          value={t(`onboarding.step6.${draft.unitSystem}`)}
          onEdit={editStep6}
          testID="onboarding-review-units"
        />
        <ReviewRow
          label={t("onboarding.review.language")}
          value={draft.language === "ar" ? t("onboarding.step6.arabic") : t("onboarding.step6.english")}
          onEdit={editStep6}
          testID="onboarding-review-language"
        />
      </View>

      <GButton
        label={t("onboarding.review.finish")}
        onPress={handleFinish}
        loading={submitting}
        disabled={retrySeconds !== null && retrySeconds > 0}
        fullWidth
        testID="onboarding-review-finish"
      />
    </GScreen>
  );
}

const styles = StyleSheet.create({
  list: {
    marginTop: space[2],
    marginBottom: space[4],
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    minHeight: minTouchTarget,
    paddingVertical: space[2],
    borderBottomWidth: 1,
    borderRadius: radius.sm,
  },
  rowText: {
    flex: 1,
  },
});
