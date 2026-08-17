/**
 * §5.9/§8.2 screen 20 -- a completed session, read-only: duration, volume,
 * per-exercise sets in position order (already ordered server-side, §5.9 --
 * nothing re-sorted or recomputed here), records set, notes. Warm-up sets
 * render alongside their exercise's other sets, visually distinguished
 * (P2-ADR-04) rather than hidden.
 *
 * Reached today from history.tsx's row press. The route itself is not
 * status-restricted -- an in_progress or abandoned session's id resolves
 * here too, rendered with whatever GET /workouts/{id} actually returns: a
 * status badge stands in for the duration/volume/records a session that
 * never finished never has (those fields, and records_set, are simply
 * omitted rather than shown as zero -- §8.6's "nothing happened yet" rule).
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { router, useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import { resolveErrorCode } from "../../../src/api/errors";
import {
  getWorkout,
  type SessionDetailExerciseGroup,
  type WorkoutSetData,
} from "../../../src/api/workouts";
import { GCard, GErrorBanner, GScreen, GSkeleton } from "../../../src/components";
import { useI18n, type Locale } from "../../../src/i18n";
import { useTheme } from "../../../src/theme/useTheme";
import { textStyle } from "../../../src/theme/typography";
import { radius, space } from "../../../src/theme/tokens";
import type { Theme } from "../../../src/theme/tokens";

type Translate = (key: string, options?: Record<string, unknown>) => string;

// Shared with workout/active.tsx's own finish summary -- same seconds-to-
// words rule (§5.8), duplicated rather than imported since active.tsx is
// outside this task's file list and the function is a five-line pure
// formatter, not worth reaching into a committed screen to share.
function formatDuration(totalSeconds: number, t: Translate): string {
  const minutes = Math.round(totalSeconds / 60);
  if (minutes < 60) return t("workout.active.summaryDurationMinutes", { minutes });
  return t("workout.active.summaryDurationHoursMinutes", {
    hours: Math.floor(minutes / 60),
    minutes: minutes % 60,
  });
}

function DetailSkeleton() {
  return (
    <View style={styles.section} testID="workout-detail-skeleton">
      <GSkeleton width="60%" height={24} />
      <GSkeleton width="100%" height={100} radius={radius.lg} />
      <GSkeleton width="100%" height={140} radius={radius.lg} />
    </View>
  );
}

function SetLine({
  set,
  index,
  locale,
  theme,
  t,
}: {
  set: WorkoutSetData;
  index: number;
  locale: Locale;
  theme: Theme;
  t: Translate;
}) {
  return (
    <View style={styles.setLine} testID={`workout-detail-set-${set.id}`}>
      <Text style={[textStyle("body", locale), { color: theme.textPrimary }]}>
        {t("workout.active.setLabel", { index: index + 1 })} · {set.reps} × {set.weight_kg}{" "}
        {t("workout.active.weightUnit")} ·{" "}
        {t("workout.detail.e1rmLabel", { value: set.derived.e1rm_kg })}
      </Text>
      {set.is_warmup ? (
        <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
          {t("workout.active.warmupBadge")}
        </Text>
      ) : null}
    </View>
  );
}

function ExerciseGroupCard({
  group,
  locale,
  theme,
  t,
}: {
  group: SessionDetailExerciseGroup;
  locale: Locale;
  theme: Theme;
  t: Translate;
}) {
  return (
    <GCard title={group.exercise.name} testID={`workout-detail-exercise-${group.exercise.id}`}>
      {group.sets.map((set, index) => (
        <SetLine key={set.id} set={set} index={index} locale={locale} theme={theme} t={t} />
      ))}
    </GCard>
  );
}

export default function WorkoutDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const theme = useTheme();
  const { t, locale } = useI18n();

  const detailQuery = useQuery({
    queryKey: ["workout", id],
    queryFn: () => getWorkout(id),
    enabled: id !== undefined,
  });

  const session = detailQuery.data?.session;

  // Resolves a record's exercise_id to the name GET /workouts/{id} already
  // resolved server-side for that same exercise's own group (§5.2's
  // exception to "the server never sends display text") -- never a second
  // lookup, and never re-translated on the device.
  const exerciseNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const group of session?.exercises ?? []) map.set(group.exercise.id, group.exercise.name);
    return map;
  }, [session]);

  const title = session?.label_key ? t(session.label_key) : t("workout.untitledSession");

  return (
    <GScreen header={{ title, onBack: () => router.back() }} testID="workout-detail-screen">
      {detailQuery.isLoading ? <DetailSkeleton /> : null}

      {detailQuery.isError ? (
        <GErrorBanner
          testID="workout-detail-error"
          code={resolveErrorCode(detailQuery.error)}
          onRetry={() => void detailQuery.refetch()}
        />
      ) : null}

      {session ? (
        <View style={styles.section}>
          {session.status !== "completed" ? (
            <Text
              style={[
                textStyle("label", locale),
                { color: session.status === "abandoned" ? theme.error : theme.textMuted },
              ]}
              testID="workout-detail-status"
            >
              {t(
                session.status === "abandoned"
                  ? "workout.status.abandoned"
                  : "workout.status.inProgress",
              )}
            </Text>
          ) : null}

          <GCard testID="workout-detail-summary">
            {session.duration_seconds !== null ? (
              <View style={styles.summaryRow}>
                <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                  {t("workout.active.summaryDuration")}
                </Text>
                <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                  {formatDuration(session.duration_seconds, t)}
                </Text>
              </View>
            ) : null}
            <View style={styles.summaryRow}>
              <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                {t("workout.active.summarySets")}
              </Text>
              <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                {session.set_count}
              </Text>
            </View>
            {session.total_volume_kg !== null ? (
              <View style={styles.summaryRow}>
                <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                  {t("workout.active.summaryVolume")}
                </Text>
                <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                  {session.total_volume_kg} {t("workout.active.weightUnit")}
                </Text>
              </View>
            ) : null}
          </GCard>

          {session.exercises.map((group) => (
            <ExerciseGroupCard key={group.exercise.id} group={group} locale={locale} theme={theme} t={t} />
          ))}

          {session.records_set.length > 0 ? (
            <View>
              <Text
                style={[textStyle("label", locale), styles.blockHeading, { color: theme.textSecondary }]}
              >
                {t("workout.active.summaryRecords")}
              </Text>
              <GCard testID="workout-detail-records">
                {session.records_set.map((recordItem, index) => (
                  <Text
                    key={`${recordItem.exercise_id}-${index}`}
                    style={[textStyle("body", locale), { color: theme.textPrimary }]}
                  >
                    {exerciseNameById.get(recordItem.exercise_id) ?? recordItem.exercise_id} ·{" "}
                    {recordItem.value} {t("workout.active.weightUnit")}
                  </Text>
                ))}
              </GCard>
            </View>
          ) : null}

          {session.notes ? (
            <View>
              <Text
                style={[textStyle("label", locale), styles.blockHeading, { color: theme.textSecondary }]}
              >
                {t("workout.detail.notesHeading")}
              </Text>
              <GCard testID="workout-detail-notes">
                <Text style={[textStyle("body", locale), { color: theme.textPrimary }]}>
                  {session.notes}
                </Text>
              </GCard>
            </View>
          ) : null}
        </View>
      ) : null}
    </GScreen>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: space[4],
  },
  summaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
  setLine: {
    marginBottom: space[2],
    gap: space[0],
  },
  blockHeading: {
    marginBottom: space[1],
  },
});
