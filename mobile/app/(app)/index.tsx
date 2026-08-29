/**
 * §5.12/§8.2 screen 16 — the dashboard. One `GET /dashboard` call renders
 * every block: greeting, resume banner, next workout, streak, this week,
 * weight sparkline, recent records, the stale-plan prompt, and the
 * disclaimer line. Replaces the T-23 placeholder.
 *
 * T-24 wrote every action here as a placeholder that landed on the `plan` or
 * `progress` tab, because "none of those screens exist yet (T-25/26/28)".
 * They exist now, so T-30 points the two that were actually wrong at their
 * real destinations: Resume goes to the active session, and the next
 * workout's Start goes to that program day rather than the plan list. Left
 * alone: "Build my plan" and "Review plan" (the plan tab IS where a plan is
 * built and reviewed) and "Log today's weight" (the log sheet lives on the
 * progress tab, which is where that button already goes).
 */
import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { router, useFocusEffect } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import {
  getDashboard,
  type DashboardData,
  type DashboardProgramStale,
  type DashboardWeightPoint,
} from "../../src/api/dashboard";
import { resolveErrorCode } from "../../src/api/errors";
import { useSession } from "../../src/auth/useSession";
import {
  GButton,
  GCard,
  GEmptyState,
  GErrorBanner,
  GListRow,
  GMetric,
  GScreen,
  GSectionHeader,
  GSkeleton,
  GStat,
} from "../../src/components";
import { useI18n, type Locale } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { layout, radius, space } from "../../src/theme/tokens";
import type { Theme } from "../../src/theme/tokens";

const GOAL_LABEL_KEYS: Record<string, string> = {
  lose: "settings.fields.goalLose",
  gain: "settings.fields.goalGain",
  maintain: "settings.fields.goalMaintain",
};

const EXPERIENCE_LABEL_KEYS: Record<string, string> = {
  beginner: "settings.fields.experienceBeginner",
  intermediate: "settings.fields.experienceIntermediate",
  advanced: "settings.fields.experienceAdvanced",
};

function formatShortDate(isoDate: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" }).format(
    new Date(isoDate),
  );
}

function formatTime(isoDateTime: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }).format(
    new Date(isoDateTime),
  );
}

function formatSignedKg(value: number): string {
  return value >= 0 ? `+${value.toFixed(1)}` : value.toFixed(1);
}

const SPARKLINE_HEIGHT = 40;

// Below this, a "sparkline" is not a trend, it is two bars whose heights are
// an artefact of the min/max normalisation: with two points one is always the
// floor and the other always the ceiling, no matter how close the weights
// actually are. Found on the device -- it drew a full-height slab beside a
// 4dp stub for a 0.2kg difference, which actively misinforms.
const SPARKLINE_MIN_POINTS = 3;

function WeightSparkline({ points, color }: { points: DashboardWeightPoint[]; color: string }) {
  if (points.length < SPARKLINE_MIN_POINTS) return null;
  const values = points.map((point) => point.weight_kg);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min;

  return (
    <View
      style={styles.sparkline}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      {points.map((point) => {
        const ratio = range > 0 ? (point.weight_kg - min) / range : 0.5;
        const height = Math.max(4, Math.round(ratio * SPARKLINE_HEIGHT));
        return (
          <View
            key={point.measured_on}
            style={[styles.sparklineBar, { height, backgroundColor: color }]}
          />
        );
      })}
    </View>
  );
}

function StalePlanPrompt({
  stale,
  theme,
  locale,
}: {
  stale: DashboardProgramStale;
  theme: Theme;
  locale: Locale;
}) {
  const { t } = useI18n();
  const valueKey =
    stale.reason === "goal_changed" ? GOAL_LABEL_KEYS[stale.to] : EXPERIENCE_LABEL_KEYS[stale.to];
  const bodyKey = stale.reason === "goal_changed" ? "dashboard.stale.goalChanged" : "dashboard.stale.experienceChanged";

  return (
    <View
      testID="dashboard-stale-plan"
      style={[styles.stalePrompt, { backgroundColor: theme.warningBg, borderStartColor: theme.warning }]}
    >
      <Text style={[textStyle("bodyStrong", locale), { color: theme.warningText }]}>
        {t("dashboard.stale.title")}
      </Text>
      <Text style={[textStyle("body", locale), styles.staleBody, { color: theme.warningText }]}>
        {t(bodyKey, { value: valueKey ? t(valueKey) : stale.to })}
      </Text>
      <GButton
        variant="secondary"
        label={t("dashboard.stale.action")}
        onPress={() => router.push("/(app)/plan")}
        testID="dashboard-stale-plan-action"
      />
    </View>
  );
}

function DashboardSkeleton() {
  return (
    <View testID="dashboard-skeleton" style={styles.skeleton}>
      <GSkeleton width="60%" height={28} />
      <GSkeleton width="100%" height={120} radius={radius.lg} />
      <GSkeleton width="100%" height={80} radius={radius.lg} />
      <GSkeleton width="100%" height={130} radius={radius.lg} />
      <GSkeleton width="100%" height={150} radius={radius.lg} />
    </View>
  );
}

function DashboardContent({ data }: { data: DashboardData }) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  // Narrowed once so the Start handler below closes over a non-null id rather
  // than re-reading `data.next_workout` inside a callback TypeScript cannot
  // see the enclosing null check from.
  const nextWorkout = data.next_workout;
  // Hierarchy rule 1 -- ONE primary action per screen. An unfinished session is
  // the most urgent thing on this screen when it exists, so it takes the filled
  // button and the next workout's Start drops to `secondary`. Two filled rust
  // buttons stacked on one screen is exactly the "nothing is ever primary"
  // problem: the eye has no idea which one it is meant to land on.
  const hasActiveSession = data.active_session !== null;

  return (
    <View>
      <Text style={[textStyle("h1", locale), { color: theme.textPrimary }]}>
        {t("dashboard.greeting", { name: data.greeting_name })}
      </Text>

      {data.active_session ? (
        <View style={styles.afterGreeting}>
          <GCard
            testID="dashboard-resume"
            title={t("dashboard.resume.title")}
            subtitle={t("dashboard.resume.subtitle", {
              time: formatTime(data.active_session.started_at, locale),
            })}
            footer={
              <GButton
                label={t("dashboard.resume.action")}
                onPress={() => router.push("/(app)/workout/active")}
                fullWidth
                testID="dashboard-resume-action"
              />
            }
          />
        </View>
      ) : null}

      {/* Always "spaced", never "first": the greeting above is content, not a
          screen chrome title, so this heading has something real to separate
          itself from whether or not the resume card is there. */}
      <GSectionHeader title={t("dashboard.nextWorkout.heading")} separation="spaced" />
      {nextWorkout ? (
        <GCard
          testID="dashboard-next-workout"
          title={t(nextWorkout.label_key)}
          subtitle={t("dashboard.nextWorkout.footer", {
            // Two counts, one sentence. `i18n-js` pluralises on a single
            // `count`, so each number is inflected on its own through `units.*`
            // and the sentence interpolates the finished phrases.
            exercises: t("units.exercise", { count: nextWorkout.exercise_count }),
            duration: t("units.minute", { count: nextWorkout.estimated_minutes }),
          })}
          footer={
            <GButton
              label={t("dashboard.nextWorkout.start")}
              variant={hasActiveSession ? "secondary" : "primary"}
              onPress={() => router.push(`/(app)/plan/${nextWorkout.program_day_id}`)}
              fullWidth
              testID="dashboard-next-workout-start"
            />
          }
        />
      ) : (
        <GEmptyState
          testID="dashboard-no-program"
          titleKey="dashboard.noProgram.title"
          bodyKey="dashboard.noProgram.body"
          actionLabelKey="dashboard.noProgram.action"
          onAction={() => router.push("/(app)/plan")}
        />
      )}

      {/* Hierarchy rule 4 -- a card means "a discrete object". A streak and a
          week's count are not an object, they are two readings; they sit on the
          ground instead, which also lets the numbers themselves be the visual
          weight rather than a box around them. Rule 3 too: the streak is the
          hero at `stat` (34) and this-week is deliberately a step down at
          `metric` (22), because they were both 34 and therefore tied. */}
      <View style={styles.statsBlock}>
        <View style={styles.statsRow}>
          <GStat
            testID="dashboard-streak"
            label={t("dashboard.streak.label")}
            value={data.streak.current_days}
            unit={t("dashboard.streak.unit", { count: data.streak.current_days })}
            tone="neutral"
          />
          <View style={styles.thisWeek}>
            <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
              {t("dashboard.thisWeek.label")}
            </Text>
            {data.this_week.target > 0 ? (
              <GMetric
                testID="dashboard-this-week"
                value={t("dashboard.thisWeek.value", {
                  completed: data.this_week.completed,
                  target: data.this_week.target,
                })}
              />
            ) : (
              <Text style={[textStyle("body", locale), { color: theme.textMuted }]}>
                {t("common.notEnoughData")}
              </Text>
            )}
          </View>
        </View>
        {data.streak.longest_days > data.streak.current_days ? (
          <Text style={[textStyle("caption", locale), styles.streakLongest, { color: theme.textMuted }]}>
            {t("dashboard.streak.longest", { count: data.streak.longest_days })}
          </Text>
        ) : null}
      </View>

      <GSectionHeader title={t("dashboard.weight.label")} separation="spaced" />
      {data.weight.latest_kg != null ? (
        <GCard testID="dashboard-weight">
          <View style={styles.weightRow}>
            <GMetric
              value={data.weight.latest_kg.toFixed(1)}
              unit={t("dashboard.weight.unit")}
              size="lg"
            />
            {typeof data.weight.change_30d_kg === "number" ? (
              <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                {t("dashboard.weight.change", { value: formatSignedKg(data.weight.change_30d_kg) })}
              </Text>
            ) : null}
          </View>
          {data.weight.measured_on ? (
            <Text style={[textStyle("caption", locale), styles.weightUpdated, { color: theme.textMuted }]}>
              {t("dashboard.weight.updated", { date: formatShortDate(data.weight.measured_on, locale) })}
            </Text>
          ) : null}
          <WeightSparkline points={data.weight.sparkline} color={theme.chart3} />
        </GCard>
      ) : (
        <GEmptyState
          testID="dashboard-weight-empty"
          titleKey="dashboard.weight.emptyTitle"
          bodyKey="dashboard.weight.emptyBody"
          actionLabelKey="dashboard.weight.emptyAction"
          onAction={() => router.push("/(app)/progress")}
        />
      )}

      <GSectionHeader title={t("dashboard.records.heading")} separation="spaced" />
      {data.recent_records.length > 0 ? (
        // Rule 4 again: a list of records IS a list, so it renders as rows on
        // the ground rather than as rows inside a card pretending to be one
        // object. The negative margin cancels GListRow's own 16dp inset so the
        // row text lines up with the section heading above it, while the press
        // highlight still bleeds wider than the text.
        <View style={styles.recordList} testID="dashboard-records">
          {data.recent_records.map((record, index) => (
            <GListRow
              key={`${record.exercise_name}-${record.local_date}-${index}`}
              title={record.exercise_name}
              subtitle={`${t("dashboard.records.e1rmLabel")} · ${formatShortDate(record.local_date, locale)}`}
              trailing={
                <GMetric
                  value={record.value.toFixed(1)}
                  unit={t("dashboard.weight.unit")}
                  size="sm"
                />
              }
            />
          ))}
        </View>
      ) : (
        <GEmptyState
          testID="dashboard-records-empty"
          titleKey="dashboard.records.emptyTitle"
          bodyKey="dashboard.records.emptyBody"
        />
      )}

      {data.program_stale ? (
        <View style={styles.staleBlock}>
          <StalePlanPrompt stale={data.program_stale} theme={theme} locale={locale} />
        </View>
      ) : null}

      <Text style={[textStyle("caption", locale), styles.disclaimer, { color: theme.textMuted }]}>
        {t(data.disclaimer_key)}
      </Text>
    </View>
  );
}

export default function Dashboard() {
  const { user } = useSession();

  const dashboardQuery = useQuery({
    queryKey: ["dashboard"],
    queryFn: getDashboard,
    enabled: user !== null,
  });

  // T-30, found on a device: generate a plan, tap Home, and the dashboard still
  // said "No plan yet". Expo Router's tab navigator keeps every tab's screen
  // mounted, so switching back to this one never remounts it and React Query's
  // mount-based refetch never fires -- and `POST /program/generate` (plan/index)
  // and `PATCH /profile` (settings) both change what this screen shows without
  // invalidating ["dashboard"]. Refetching on focus is the same fix progress.tsx
  // already documents for the same cause, and it covers every writer rather than
  // needing each one to remember this key.
  const refetchDashboard = dashboardQuery.refetch;
  useFocusEffect(
    useCallback(() => {
      if (user !== null) void refetchDashboard();
    }, [user, refetchDashboard]),
  );

  return (
    <GScreen>
      {dashboardQuery.isError ? (
        <GErrorBanner
          testID="dashboard-error"
          code={resolveErrorCode(dashboardQuery.error)}
          onRetry={() => dashboardQuery.refetch()}
        />
      ) : null}

      {dashboardQuery.data ? (
        <DashboardContent data={dashboardQuery.data} />
      ) : dashboardQuery.isError ? null : (
        <DashboardSkeleton />
      )}
    </GScreen>
  );
}

const styles = StyleSheet.create({
  skeleton: {
    gap: layout.denseGap,
  },
  // Density (hierarchy rule 5): the dashboard is glanced at between sets, so
  // blocks inside a section sit at `denseGap` (12). The 32dp between SECTIONS
  // comes from GSectionHeader, not from here -- which is the point. Before
  // this, one `gap: space[4]` on the container put every block exactly 20dp
  // from every other block, so a section heading was as far from its own card
  // as that card was from the next section, and nothing read as grouped.
  afterGreeting: {
    marginTop: layout.denseGap,
  },
  statsBlock: {
    marginTop: layout.sectionGap,
  },
  statsRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  thisWeek: {
    alignItems: "flex-end",
  },
  streakLongest: {
    marginTop: layout.groupGap,
  },
  weightRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
  },
  weightUpdated: {
    marginTop: space[1],
  },
  recordList: {
    // Cancels GListRow's own paddingHorizontal so row text aligns with the
    // section heading. Side-neutral, so no §9.6 start/end concern.
    marginHorizontal: -space[3],
  },
  sparkline: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    gap: space[0],
    height: SPARKLINE_HEIGHT,
    marginTop: layout.denseGap,
  },
  sparklineBar: {
    flex: 1,
    // `flex: 1` alone made a two-point series render as two half-screen-wide
    // slabs -- found on the device, not in review. The cap keeps a bar looking
    // like a bar at any series length; short series now sit at the start of
    // the track instead of stretching to fill it.
    maxWidth: space[1],
    borderRadius: radius.sm / 2,
  },
  staleBlock: {
    marginTop: layout.sectionGap,
  },
  // A warning strip, not a card: the start-edge rule carries the meaning and
  // the tint carries the tone, so it does not need a border and a shadow too.
  stalePrompt: {
    borderRadius: radius.sm,
    borderStartWidth: 3,
    padding: space[3],
    gap: space[2],
    alignItems: "flex-start",
  },
  staleBody: {
    marginBottom: space[1],
  },
  disclaimer: {
    marginTop: layout.sectionGap,
    textAlign: "center",
  },
});
