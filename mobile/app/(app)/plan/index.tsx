/**
 * §5.3/§5.4/§8.2 screen 17 — the plan overview. One `GET /program` call
 * renders the week as day cards: label (translated from `label_key`), focus
 * chips, exercise count, estimated minutes. A page-level "regenerate" action
 * sits behind a confirm. A brand-new account (404 PROGRAM_NOT_FOUND) gets the
 * days-per-week picker instead, wired to `POST /program/generate`.
 *
 * Replaces the T-23 placeholder (`mobile/app/(app)/plan.tsx`, deleted in this
 * commit): Expo Router resolves a directory's own `index.tsx` to the same
 * route name as the directory itself, so `plan/index.tsx` serves the "plan"
 * tab `(app)/_layout.tsx` already declares, unchanged.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { router } from "expo-router";
import { useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";

import { generateProgram, getProgram, type ProgramSummary } from "../../../src/api/program";
import { resolveErrorCode } from "../../../src/api/errors";
import { useSession } from "../../../src/auth/useSession";
import { GButton, GCard, GChip, GErrorBanner, GScreen, GSkeleton } from "../../../src/components";
import { useI18n } from "../../../src/i18n";
import { useTheme } from "../../../src/theme/useTheme";
import { textStyle } from "../../../src/theme/typography";
import { radius, space } from "../../../src/theme/tokens";

const DAYS_PER_WEEK_OPTIONS = [2, 3, 4, 5, 6] as const;

export default function PlanOverview() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const { user } = useSession();
  const queryClient = useQueryClient();
  const [selectedDays, setSelectedDays] = useState<number>(4);

  const programQuery = useQuery({
    queryKey: ["program"],
    queryFn: getProgram,
    enabled: user !== null,
    // 404 PROGRAM_NOT_FOUND is a well-formed, common first-run state, not a
    // transient failure -- retrying it three times would only delay the
    // empty state's own picker from appearing.
    retry: false,
  });

  const generateMutation = useMutation({
    mutationFn: (daysPerWeek: number) => generateProgram(daysPerWeek),
    onSuccess: (data) => {
      // §5.3: a freshly generated program can never be stale against the
      // profile that just produced it -- primes the GET /program cache
      // directly rather than refetching, so the new day cards render from
      // this response instantly (P2-NFR-08's own mechanism: never a
      // skeleton once data exists).
      queryClient.setQueryData(["program"], { program: data.program, stale: null });
    },
  });

  const isEmptyProgram =
    programQuery.isError && resolveErrorCode(programQuery.error) === "PROGRAM_NOT_FOUND";

  const handleRegenerate = (program: ProgramSummary) => {
    Alert.alert(
      t("plan.overview.regenerateConfirmTitle"),
      t("plan.overview.regenerateConfirmBody", { days: program.days_per_week }),
      [
        { text: t("common.cancel"), style: "cancel" },
        {
          text: t("plan.overview.regenerateConfirmAction"),
          onPress: () => generateMutation.mutate(program.days_per_week),
        },
      ],
    );
  };

  return (
    <GScreen>
      {generateMutation.isError ? (
        <GErrorBanner
          testID="plan-generate-error"
          code={resolveErrorCode(generateMutation.error)}
          onDismiss={() => generateMutation.reset()}
        />
      ) : null}

      {programQuery.data ? (
        <View style={styles.section}>
          {generateMutation.data && generateMutation.data.notes_key.length > 0 ? (
            <View style={[styles.notes, { backgroundColor: theme.infoBg }]} testID="plan-notes">
              {generateMutation.data.notes_key.map((key) => (
                <Text key={key} style={[textStyle("label", locale), { color: theme.info }]}>
                  {t(key)}
                </Text>
              ))}
            </View>
          ) : null}

          {programQuery.data.program.days.map((day) => (
            <GCard
              key={day.id}
              testID={`plan-day-${day.day_index}`}
              title={t(day.label_key)}
              subtitle={t("plan.overview.footer", {
                count: day.exercise_count,
                minutes: day.estimated_minutes,
              })}
              onPress={() => router.push(`/(app)/plan/${day.id}`)}
              footer={
                <View style={styles.chipsRow}>
                  {day.focus_muscles.map((muscle) => (
                    <GChip
                      key={muscle}
                      label={t(`muscles.${muscle}`)}
                      selected={false}
                      disabled
                      onPress={() => {}}
                    />
                  ))}
                </View>
              }
            />
          ))}

          <GButton
            variant="secondary"
            label={t("plan.overview.regenerate")}
            onPress={() => handleRegenerate(programQuery.data.program)}
            loading={generateMutation.isPending}
            disabled={generateMutation.isPending}
            fullWidth
            testID="plan-regenerate"
          />
        </View>
      ) : isEmptyProgram ? (
        <View style={styles.section} testID="plan-empty">
          <Text style={[textStyle("h2", locale), { color: theme.textPrimary }]}>
            {t("plan.empty.title")}
          </Text>
          <Text style={[textStyle("body", locale), { color: theme.textSecondary }]}>
            {t("plan.empty.body")}
          </Text>
          <View>
            <Text style={[textStyle("label", locale), styles.pickerLabel, { color: theme.textSecondary }]}>
              {t("plan.empty.daysPerWeekLabel")}
            </Text>
            <View style={styles.chipsRow}>
              {DAYS_PER_WEEK_OPTIONS.map((days) => (
                <GChip
                  key={days}
                  label={String(days)}
                  selected={selectedDays === days}
                  onPress={() => setSelectedDays(days)}
                  accessibilityLabel={t("plan.empty.daysPerWeekOption", { days })}
                  testID={`plan-days-per-week-${days}`}
                />
              ))}
            </View>
          </View>
          <GButton
            label={t("plan.empty.generate")}
            onPress={() => generateMutation.mutate(selectedDays)}
            loading={generateMutation.isPending}
            disabled={generateMutation.isPending}
            fullWidth
            testID="plan-generate"
          />
        </View>
      ) : programQuery.isError ? (
        <GErrorBanner
          testID="plan-error"
          code={resolveErrorCode(programQuery.error)}
          onRetry={() => programQuery.refetch()}
        />
      ) : (
        <View style={styles.section} testID="plan-skeleton">
          <GSkeleton width="70%" height={28} />
          <GSkeleton width="100%" height={140} radius={radius.lg} />
          <GSkeleton width="100%" height={140} radius={radius.lg} />
          <GSkeleton width="100%" height={140} radius={radius.lg} />
        </View>
      )}

      <Text style={[textStyle("caption", locale), styles.disclaimer, { color: theme.textMuted }]}>
        {t("common.medicalDisclaimer")}
      </Text>
    </GScreen>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: space[4],
  },
  chipsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space[2],
  },
  pickerLabel: {
    marginBottom: space[2],
  },
  notes: {
    borderRadius: radius.sm,
    padding: space[3],
    gap: space[1],
  },
  disclaimer: {
    textAlign: "center",
    marginTop: space[4],
  },
});
