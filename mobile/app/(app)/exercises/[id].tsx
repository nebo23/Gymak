/**
 * §5.2/§5.11/§8.2 screen 24 -- exercise detail: name, muscles, equipment,
 * instructions, and this user's record for it. `name`/`instructions` arrive already
 * resolved to the caller's profile language (§5.2's own exception to "the server
 * never sends display text") and render as-is, never wrapped in `t()`. The record
 * comes from a second, independent request (GET /records?exercise_id=), so a slow or
 * failed record fetch never blocks the exercise content above it from showing.
 */
import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { router, useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import { resolveErrorCode } from "../../../src/api/errors";
import {
  deleteExercise,
  getExercise,
  getExerciseRecord,
  type ExerciseDetailData,
} from "../../../src/api/exercises";
import { ExerciseFormSheet } from "../../../src/exercises/ExerciseFormSheet";
import { useSession } from "../../../src/auth/useSession";
import {
  GButton,
  GCard,
  GDialog,
  GEmptyState,
  GErrorBanner,
  GScreen,
  GSkeleton,
} from "../../../src/components";
import { useI18n } from "../../../src/i18n";
import { useTheme } from "../../../src/theme/useTheme";
import { textStyle } from "../../../src/theme/typography";
import { radius, space } from "../../../src/theme/tokens";

function DetailSkeleton() {
  return (
    <View style={styles.section} testID="exercise-detail-skeleton">
      <GSkeleton width="60%" height={24} />
      <GSkeleton width="100%" height={100} radius={radius.lg} />
      <GSkeleton width="100%" height={140} radius={radius.lg} />
      <GSkeleton width="100%" height={100} radius={radius.lg} />
    </View>
  );
}

export default function ExerciseDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useSession();
  const { t, locale } = useI18n();
  const theme = useTheme();

  const exerciseQuery = useQuery({
    queryKey: ["exercises", "detail", id],
    queryFn: () => getExercise(id),
    enabled: user !== null && id !== undefined,
  });

  const recordQuery = useQuery({
    queryKey: ["exercises", "record", id],
    queryFn: () => getExerciseRecord(id),
    enabled: user !== null && id !== undefined,
  });

  const exercise = exerciseQuery.data?.exercise;
  const weightUnit = t("workout.active.weightUnit");

  const queryClient = useQueryClient();
  const [editVisible, setEditVisible] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteErrorCode, setDeleteErrorCode] = useState<string | null>(null);

  const handleSaved = useCallback(
    (updated: ExerciseDetailData) => {
      queryClient.setQueryData(["exercise", updated.id], { exercise: updated });
      void queryClient.invalidateQueries({ queryKey: ["exercises"] });
    },
    [queryClient],
  );

  /** Soft delete: the row leaves the library but still resolves by id, so any session
   * that already logged it keeps its name. Nothing is destroyed, which is why the
   * confirmation says the sets survive rather than warning about losing them. */
  const handleDelete = useCallback(async () => {
    setConfirmDelete(false);
    setDeleteErrorCode(null);
    try {
      await deleteExercise(id);
      void queryClient.invalidateQueries({ queryKey: ["exercises"] });
      router.back();
    } catch (error) {
      setDeleteErrorCode(resolveErrorCode(error));
    }
  }, [id, queryClient]);

  return (
    <GScreen
      header={{ title: exercise?.name ?? "", onBack: () => router.back() }}
      testID="exercise-detail-screen"
    >
      {exerciseQuery.isError ? (
        <GErrorBanner
          testID="exercise-detail-error"
          code={resolveErrorCode(exerciseQuery.error)}
          onRetry={() => void exerciseQuery.refetch()}
        />
      ) : null}

      {exercise ? (
        <View style={styles.section}>
          <GCard testID="exercise-detail-info">
            <View style={styles.infoRow}>
              <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                {t("exercises.detail.primaryMuscleLabel")}
              </Text>
              <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                {t(`muscles.${exercise.primary_muscle}`)}
              </Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                {t("exercises.detail.equipmentLabel")}
              </Text>
              <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                {t(`equipment.${exercise.equipment}`)}
              </Text>
            </View>
            {exercise.secondary_muscles.length > 0 ? (
              <View style={styles.secondaryBlock}>
                <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                  {t("exercises.detail.secondaryMusclesLabel")}
                </Text>
                <Text style={[textStyle("body", locale), { color: theme.textPrimary }]}>
                  {exercise.secondary_muscles.map((muscle) => t(`muscles.${muscle}`)).join(", ")}
                </Text>
              </View>
            ) : null}
          </GCard>

          <View>
            <Text style={[textStyle("label", locale), styles.blockHeading, { color: theme.textSecondary }]}>
              {t("exercises.detail.instructionsTitle")}
            </Text>
            <GCard testID="exercise-detail-instructions">
              <Text style={[textStyle("body", locale), { color: theme.textPrimary }]}>
                {exercise.instructions}
              </Text>
            </GCard>
          </View>

          {/* Own rows only. A seeded row offers neither action, because the API would
              answer a PATCH or DELETE on one with the same 404 it gives a stranger's
              row -- showing the buttons would be promising something that cannot work. */}
          {exercise.is_custom ? (
            <View style={styles.ownerActions}>
              {deleteErrorCode ? (
                <GErrorBanner code={deleteErrorCode} testID="exercise-detail-delete-error" />
              ) : null}
              <GButton
                variant="secondary"
                label={t("exercises.custom.editAction")}
                onPress={() => setEditVisible(true)}
                testID="exercise-detail-edit"
              />
              <GButton
                variant="ghost"
                label={t("exercises.custom.deleteAction")}
                onPress={() => setConfirmDelete(true)}
                testID="exercise-detail-delete"
              />
            </View>
          ) : null}

          <View>
            <Text style={[textStyle("label", locale), styles.blockHeading, { color: theme.textSecondary }]}>
              {t("exercises.detail.recordTitle")}
            </Text>
            {recordQuery.isLoading ? (
              <GSkeleton width="100%" height={100} radius={radius.lg} testID="exercise-detail-record-skeleton" />
            ) : recordQuery.isError ? (
              <GErrorBanner
                testID="exercise-detail-record-error"
                code={resolveErrorCode(recordQuery.error)}
                onRetry={() => void recordQuery.refetch()}
              />
            ) : recordQuery.data ? (
              <GCard testID="exercise-detail-record">
                <View style={styles.infoRow}>
                  <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                    {t("exercises.detail.heaviestSetLabel")}
                  </Text>
                  <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                    {recordQuery.data.heaviest_set.weight_kg} {weightUnit} ×{" "}
                    {recordQuery.data.heaviest_set.reps}
                  </Text>
                </View>
                <View style={styles.infoRow}>
                  <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                    {t("exercises.detail.bestE1rmLabel")}
                  </Text>
                  <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                    {recordQuery.data.best_e1rm.value_kg} {weightUnit}
                  </Text>
                </View>
                <View style={styles.infoRow}>
                  <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                    {t("exercises.detail.bestVolumeLabel")}
                  </Text>
                  <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                    {recordQuery.data.best_session_volume.volume_kg} {weightUnit}
                  </Text>
                </View>
                <View style={styles.infoRow}>
                  <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                    {t("exercises.detail.totalSetsLabel")}
                  </Text>
                  <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                    {recordQuery.data.total_sets}
                  </Text>
                </View>
              </GCard>
            ) : (
              <GEmptyState
                testID="exercise-detail-record-empty"
                titleKey="exercises.detail.noRecordTitle"
                bodyKey="exercises.detail.noRecordBody"
              />
            )}
          </View>
        </View>
      ) : exerciseQuery.isError ? null : (
        <DetailSkeleton />
      )}
      <ExerciseFormSheet
        visible={editVisible}
        onClose={() => setEditVisible(false)}
        initial={exercise ?? null}
        onSaved={handleSaved}
        testID="exercise-edit-sheet"
      />

      <GDialog
        visible={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        titleKey="exercises.custom.deleteConfirmTitle"
        bodyKey="exercises.custom.deleteConfirmBody"
        actions={[
          { labelKey: "common.cancel", onPress: () => setConfirmDelete(false) },
          {
            labelKey: "exercises.custom.deleteConfirmAction",
            variant: "destructive",
            onPress: () => void handleDelete(),
          },
        ]}
        testID="exercise-delete-confirm"
      />
    </GScreen>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: space[4],
  },
  ownerActions: {
    gap: space[2],
  },
  infoRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
  secondaryBlock: {
    marginTop: space[3],
    gap: space[1],
  },
  blockHeading: {
    marginBottom: space[1],
  },
});
