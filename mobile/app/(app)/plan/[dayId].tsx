/**
 * §5.5/§8.2 screen 18 — plan day detail. One `GET /program/days/{day_id}`
 * call renders the day's exercises in order with their target and
 * `last_performance`. The exercise list arrives pre-ordered by `position`
 * (compounds first, per the generator's own slot ordering, §6.3) -- nothing
 * to re-sort client-side.
 *
 * The Start button is present and labelled per spec, but starting a session
 * for real is T-26's active-workout screen, which does not exist yet and is
 * explicitly out of this task's scope. Tapping it says so, rather than doing
 * nothing or -- worse -- calling the real `POST /workouts` with no screen
 * able to finish or abandon what it started (which would also block plan
 * regeneration with 409 SESSION_ACTIVE_BLOCKS_REGENERATION until the user
 * found some other way to close it).
 */
import { useQuery } from "@tanstack/react-query";
import { router, useLocalSearchParams } from "expo-router";
import { Alert, StyleSheet, Text, View } from "react-native";

import { getProgramDay } from "../../../src/api/program";
import { resolveErrorCode } from "../../../src/api/errors";
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

  const dayQuery = useQuery({
    queryKey: ["program", "day", dayId],
    queryFn: () => getProgramDay(dayId),
    enabled: user !== null && dayId !== undefined,
  });

  const handleStart = () => {
    Alert.alert(t("plan.dayDetail.start"), t("plan.dayDetail.startComingSoon"));
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
