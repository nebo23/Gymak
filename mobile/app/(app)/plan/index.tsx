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
import { StyleSheet, Text, View } from "react-native";

import { generateProgram, getProgram, type ProgramSummary } from "../../../src/api/program";
import { resolveErrorCode } from "../../../src/api/errors";
import { useSession } from "../../../src/auth/useSession";
import {
  GButton,
  GCard,
  GChip,
  GDialog,
  GErrorBanner,
  GScreen,
  GSkeleton,
} from "../../../src/components";
import { useI18n } from "../../../src/i18n";
import { useTheme } from "../../../src/theme/useTheme";
import { textStyle } from "../../../src/theme/typography";
import { layout, radius, space } from "../../../src/theme/tokens";

const DAYS_PER_WEEK_OPTIONS = [2, 3, 4, 5, 6] as const;

/**
 * A day's focus muscles are CONTENT, not controls. They were rendered as
 * `disabled` GChips with a no-op onPress, which is both semantically wrong (a
 * screen reader was told these were disabled buttons) and a real accessibility
 * failure: GChip's disabled state is `textDisabled` on `surfaceVariant`, which
 * is 2.67:1 in light and 2.74:1 in dark -- well under WCAG AA's 4.5:1 for
 * text, and it looked exactly as washed out as that number predicts.
 *
 * As a static tag in `textSecondary` it is 7.23:1 and 5.83:1, and it no longer
 * claims to be interactive.
 */
function FocusTag({ label }: { label: string }) {
  const theme = useTheme();
  const { locale } = useI18n();
  return (
    <View style={[styles.focusTag, { backgroundColor: theme.surfaceVariant }]}>
      <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>{label}</Text>
    </View>
  );
}

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

  // Holds what the OS alert used to capture in its closure: which program's
  // day count to regenerate once the user confirms.
  const [regenerateFor, setRegenerateFor] = useState<ProgramSummary | null>(null);

  const handleRegenerate = (program: ProgramSummary) => {
    setRegenerateFor(program);
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

      <Text style={[textStyle("h1", locale), styles.screenTitle, { color: theme.textPrimary }]}>
        {t("nav.plan")}
      </Text>

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
                    <FocusTag key={muscle} label={t(`muscles.${muscle}`)} />
                  ))}
                </View>
              }
            />
          ))}

        </View>
      ) : null}

      {programQuery.data ? (
        <View style={styles.secondaryActions}>
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
        <View style={styles.emptyBlock} testID="plan-empty">
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
          <View style={styles.emptyAction}>
            <GButton
              label={t("plan.empty.generate")}
              onPress={() => generateMutation.mutate(selectedDays)}
              loading={generateMutation.isPending}
              disabled={generateMutation.isPending}
              fullWidth
              testID="plan-generate"
            />
          </View>
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

      {/* T-30: §8.1 says the exercise library is reached "from plan and from the
          active session". The active-session half is workout/active.tsx's own
          "add exercise" picker; this is the plan half, and until T-30 neither
          existed -- screen 23 was as unreachable as history.tsx was, which
          fails §10.3 item 1 the same way. Outside the conditional blocks above
          so it is there whether or not a program exists: browsing the library
          is exactly what someone with no plan yet may want to do. */}
      <View style={styles.libraryAction}>
        <GButton
          variant="secondary"
          label={t("exercises.title")}
          onPress={() => router.push("/(app)/exercises")}
          fullWidth
          testID="plan-open-exercise-library"
        />
      </View>

      <Text style={[textStyle("caption", locale), styles.disclaimer, { color: theme.textMuted }]}>
        {t("common.medicalDisclaimer")}
      </Text>

      <GDialog
        visible={regenerateFor !== null}
        onClose={() => setRegenerateFor(null)}
        titleKey="plan.overview.regenerateConfirmTitle"
        bodyKey="plan.overview.regenerateConfirmBody"
        bodyParams={{ days: regenerateFor?.days_per_week ?? 0 }}
        actions={[
          { labelKey: "common.cancel", onPress: () => setRegenerateFor(null) },
          {
            labelKey: "plan.overview.regenerateConfirmAction",
            variant: "primary",
            onPress: () => {
              const program = regenerateFor;
              setRegenerateFor(null);
              if (program) generateMutation.mutate(program.days_per_week);
            },
          },
        ]}
        testID="plan-regenerate-confirm"
      />
    </GScreen>
  );
}

const styles = StyleSheet.create({
  screenTitle: {
    marginBottom: layout.looseGap,
  },
  // Day cards are the content: dense, so more of the week is visible at once
  // (hierarchy rule 5 -- this screen is scanned, not read).
  section: {
    gap: layout.denseGap,
  },
  // Prose and the day picker stay tight together at `groupGap`; the one
  // primary action on this screen is then pushed a further `looseGap` clear of
  // them, so 12 + 20 = a full `sectionGap` of air above "Build my plan".
  emptyBlock: {
    gap: layout.groupGap,
  },
  emptyAction: {
    marginTop: layout.looseGap,
  },
  secondaryActions: {
    marginTop: layout.sectionGap,
  },
  libraryAction: {
    marginTop: layout.groupGap,
  },
  chipsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space[2],
  },
  focusTag: {
    borderRadius: radius.pill,
    paddingHorizontal: space[2],
    paddingVertical: space[0],
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
    marginTop: layout.sectionGap,
  },
});
