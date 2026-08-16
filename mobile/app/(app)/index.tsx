/**
 * §5.12/§8.2 screen 16 — the dashboard. One `GET /dashboard` call renders
 * every block: greeting, resume banner, next workout, streak, this week,
 * weight sparkline, recent records, the stale-plan prompt, and the
 * disclaimer line. Replaces the T-23 placeholder.
 *
 * "Start"/"Resume"/"Build my plan"/"Log today's weight"/"Review plan" all
 * land on the `plan`/`progress` tabs rather than a program day, an active
 * session, or a body-weight entry sheet — none of those screens exist yet
 * (T-25/26/28), and building them is explicitly out of this task's scope.
 */
import { useQuery } from "@tanstack/react-query";
import { router } from "expo-router";
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
  GScreen,
  GSkeleton,
  GStat,
} from "../../src/components";
import { useI18n, type Locale } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { radius, space } from "../../src/theme/tokens";
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

function WeightSparkline({ points, color }: { points: DashboardWeightPoint[]; color: string }) {
  if (points.length === 0) return null;
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
    <View testID="dashboard-skeleton" style={styles.section}>
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

  return (
    <View style={styles.section}>
      <Text style={[textStyle("h1", locale), { color: theme.textPrimary }]}>
        {t("dashboard.greeting", { name: data.greeting_name })}
      </Text>

      {data.active_session ? (
        <GCard
          testID="dashboard-resume"
          title={t("dashboard.resume.title")}
          subtitle={t("dashboard.resume.subtitle", {
            time: formatTime(data.active_session.started_at, locale),
          })}
          footer={
            <GButton
              label={t("dashboard.resume.action")}
              onPress={() => router.push("/(app)/plan")}
              fullWidth
              testID="dashboard-resume-action"
            />
          }
        />
      ) : null}

      <View>
        <Text style={[textStyle("label", locale), styles.blockHeading, { color: theme.textSecondary }]}>
          {t("dashboard.nextWorkout.heading")}
        </Text>
        {data.next_workout ? (
          <GCard
            testID="dashboard-next-workout"
            title={t(data.next_workout.label_key)}
            subtitle={t("dashboard.nextWorkout.footer", {
              count: data.next_workout.exercise_count,
              minutes: data.next_workout.estimated_minutes,
            })}
            footer={
              <GButton
                label={t("dashboard.nextWorkout.start")}
                onPress={() => router.push("/(app)/plan")}
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
      </View>

      <GCard testID="dashboard-stats">
        <View style={styles.statsRow}>
          <GStat
            testID="dashboard-streak"
            label={t("dashboard.streak.label")}
            value={data.streak.current_days}
            unit={t("dashboard.streak.unit")}
            tone="neutral"
          />
          {data.this_week.target > 0 ? (
            <GStat
              testID="dashboard-this-week"
              label={t("dashboard.thisWeek.label")}
              value={t("dashboard.thisWeek.value", {
                completed: data.this_week.completed,
                target: data.this_week.target,
              })}
              tone="neutral"
            />
          ) : (
            <View>
              <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                {t("dashboard.thisWeek.label")}
              </Text>
              <Text style={[textStyle("body", locale), { color: theme.textMuted }]}>
                {t("common.notEnoughData")}
              </Text>
            </View>
          )}
        </View>
        {data.streak.longest_days > data.streak.current_days ? (
          <Text style={[textStyle("caption", locale), styles.streakLongest, { color: theme.textMuted }]}>
            {t("dashboard.streak.longest", { days: data.streak.longest_days })}
          </Text>
        ) : null}
      </GCard>

      <View>
        <Text style={[textStyle("label", locale), styles.blockHeading, { color: theme.textSecondary }]}>
          {t("dashboard.weight.label")}
        </Text>
        {data.weight.latest_kg != null ? (
          <GCard testID="dashboard-weight">
            <View style={styles.statsRow}>
              <GStat
                label={t("dashboard.weight.label")}
                value={data.weight.latest_kg.toFixed(1)}
                unit={t("dashboard.weight.unit")}
                tone="neutral"
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
      </View>

      <View>
        <Text style={[textStyle("label", locale), styles.blockHeading, { color: theme.textSecondary }]}>
          {t("dashboard.records.heading")}
        </Text>
        {data.recent_records.length > 0 ? (
          <GCard testID="dashboard-records">
            {data.recent_records.map((record, index) => (
              <GListRow
                key={`${record.exercise_name}-${record.local_date}-${index}`}
                title={record.exercise_name}
                subtitle={`${t("dashboard.records.e1rmLabel")} · ${formatShortDate(record.local_date, locale)}`}
                trailing={
                  <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                    {`${record.value.toFixed(1)} ${t("dashboard.weight.unit")}`}
                  </Text>
                }
              />
            ))}
          </GCard>
        ) : (
          <GEmptyState
            testID="dashboard-records-empty"
            titleKey="dashboard.records.emptyTitle"
            bodyKey="dashboard.records.emptyBody"
          />
        )}
      </View>

      {data.program_stale ? (
        <StalePlanPrompt stale={data.program_stale} theme={theme} locale={locale} />
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
  section: {
    gap: space[4],
  },
  blockHeading: {
    marginBottom: space[1],
  },
  statsRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
  streakLongest: {
    marginTop: space[2],
  },
  weightUpdated: {
    marginTop: space[1],
  },
  sparkline: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: space[0],
    height: SPARKLINE_HEIGHT,
    marginTop: space[3],
  },
  sparklineBar: {
    flex: 1,
    borderRadius: radius.sm / 2,
  },
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
    textAlign: "center",
  },
});
