/**
 * §5.5/§8.2 screen 18 — plan day detail. One `GET /program/days/{day_id}`
 * call renders the day's exercises in order with their target and
 * `last_performance`. The exercise list arrives pre-ordered by `position`
 * (compounds first, per the generator's own slot ordering, §6.3) -- nothing
 * to re-sort client-side.
 *
 * The Start button used to say "coming soon" -- T-26's active-workout screen
 * did not exist yet when this file was first written. It exists now, so
 * this is the one file T-26 touches outside its own list: leaving a
 * now-inaccurate "arrives in a later update" alert on the button for the
 * exact screen that just shipped would be actively wrong, not merely
 * conservative. `startWorkout` follows §5.6 exactly, including its 409
 * SESSION_ALREADY_ACTIVE / Resume / Discard-and-start-new contract.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { router, useLocalSearchParams } from "expo-router";
import { Alert, StyleSheet, Text, View } from "react-native";

import { getProgramDay } from "../../../src/api/program";
import { parseApiError, resolveErrorCode, type ResolvedErrorCode } from "../../../src/api/errors";
import { abandonWorkout, startWorkout } from "../../../src/api/workouts";
import { useSession } from "../../../src/auth/useSession";
import { GButton, GErrorBanner, GListRow, GScreen, GSkeleton } from "../../../src/components";
import { useI18n } from "../../../src/i18n";
import { useTheme } from "../../../src/theme/useTheme";
import { textStyle } from "../../../src/theme/typography";
import { space } from "../../../src/theme/tokens";

export default function PlanDayDetail() {
  const { dayId } = useLocalSearchParams<{ dayId: string }>();
  const { user } = useSession();
  const { t, locale } = useI18n();
  const theme = useTheme();

  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<ResolvedErrorCode | null>(null);

  const dayQuery = useQuery({
    queryKey: ["program", "day", dayId],
    queryFn: () => getProgramDay(dayId),
    enabled: user !== null && dayId !== undefined,
  });

  const beginSession = async (programDayId: string) => {
    setStarting(true);
    setStartError(null);
    try {
      await startWorkout(programDayId);
      router.push("/(app)/workout/active");
    } catch (err) {
      const problem = parseApiError(err);
      if (problem.code === "SESSION_ALREADY_ACTIVE") {
        Alert.alert(t("plan.dayDetail.activeSessionTitle"), t("plan.dayDetail.activeSessionBody"), [
          { text: t("common.cancel"), style: "cancel" },
          { text: t("plan.dayDetail.resume"), onPress: () => router.push("/(app)/workout/active") },
          {
            text: t("plan.dayDetail.discardAndStartNew"),
            style: "destructive",
            onPress: () => void discardAndStartNew(problem.detail, programDayId),
          },
        ]);
      } else {
        setStartError(problem.code);
      }
    } finally {
      setStarting(false);
    }
  };

  const discardAndStartNew = async (activeSessionId: string | undefined, programDayId: string) => {
    if (activeSessionId) {
      try {
        await abandonWorkout(activeSessionId);
      } catch (err) {
        setStartError(resolveErrorCode(err));
        return;
      }
    }
    await beginSession(programDayId);
  };

  const handleStart = () => {
    if (!dayId) return;
    void beginSession(dayId);
  };

  return (
    <GScreen
      header={{
        title: dayQuery.data ? t(dayQuery.data.day.label_key) : "",
        onBack: () => router.back(),
      }}
      footer={
        dayQuery.data ? (
          <GButton
            label={t("plan.dayDetail.start")}
            onPress={handleStart}
            loading={starting}
            disabled={starting}
            fullWidth
            testID="plan-day-start"
          />
        ) : undefined
      }
    >
      {dayQuery.isError ? (
        <GErrorBanner
          testID="plan-day-error"
          code={resolveErrorCode(dayQuery.error)}
          onRetry={() => dayQuery.refetch()}
        />
      ) : null}

      {startError ? (
        <GErrorBanner
          testID="plan-day-start-error"
          code={startError}
          onDismiss={() => setStartError(null)}
        />
      ) : null}

      {dayQuery.data ? (
        <View style={styles.section} testID="plan-day-exercises">
          {dayQuery.data.day.exercises.map((exercise) => (
            <GListRow
              key={exercise.id}
              testID={`plan-day-exercise-${exercise.position}`}
              title={exercise.exercise.name}
              subtitle={t("plan.dayDetail.target", {
                sets: exercise.target_sets,
                min: exercise.target_reps_min,
                max: exercise.target_reps_max,
                seconds: exercise.rest_seconds,
              })}
              trailing={
                exercise.last_performance ? (
                  <View style={styles.lastPerformance}>
                    <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
                      {t("plan.dayDetail.lastPerformanceLabel")}
                    </Text>
                    <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                      {t("plan.dayDetail.lastPerformanceValue", {
                        reps: exercise.last_performance.best_set.reps,
                        weight: exercise.last_performance.best_set.weight_kg,
                      })}
                    </Text>
                  </View>
                ) : undefined
              }
            />
          ))}
          <Text style={[textStyle("caption", locale), styles.disclaimer, { color: theme.textMuted }]}>
            {t("common.medicalDisclaimer")}
          </Text>
        </View>
      ) : dayQuery.isError ? null : (
        <View style={styles.section} testID="plan-day-skeleton">
          <GSkeleton width="100%" height={64} />
          <GSkeleton width="100%" height={64} />
          <GSkeleton width="100%" height={64} />
          <GSkeleton width="100%" height={64} />
        </View>
      )}
    </GScreen>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: space[3],
  },
  lastPerformance: {
    alignItems: "flex-end",
  },
  disclaimer: {
    textAlign: "center",
    marginTop: space[4],
  },
});
