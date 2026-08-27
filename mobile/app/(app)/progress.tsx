/**
 * §5.10/§5.11/§8.2 screen 22 -- the progress tab: weight chart with 30/90/
 * 365-day range chips, the moving-average line, a log-today sheet, an
 * editable/deletable entry list, and the records list below. Replaces the
 * T-23 placeholder (`comingSoon.progress`, removed from ar.json/en.json --
 * nothing else in either catalogue referenced those keys).
 *
 * P2-ADR-06's two-way coupling (body-weight log <-> profiles.weight_kg) is
 * already live server-side; this screen never recomputes or reimplements
 * either direction. What it does own is making sure ITS OWN cache reflects
 * a change made elsewhere (Settings): `useFocusEffect` refetches on every
 * tab focus, because Expo Router's tab navigator keeps every tab's screen
 * mounted, so switching tabs alone never remounts this one or triggers
 * React Query's normal mount-based refetch. The reverse direction --
 * Settings/dashboard reflecting a change made here -- is handled by
 * invalidating their query keys after every successful write below, which
 * React Query propagates to any of their already-mounted (if inactive)
 * observers immediately, and to a not-yet-mounted one the next time it
 * mounts cold.
 *
 * P2-SAF-002: `summary.change_kg` is not the dashboard's `change_30d_kg` --
 * schemas/metrics.py's own BodyWeightSummaryData carries it unconditionally,
 * with no minor-based omission, and §6.5 names only the dashboard's key as
 * the framing-restricted one. This screen still adds none of its own
 * gain/lose framing: the change value renders in plain `textSecondary`,
 * never a tone-coloured delta, exactly like dashboard.tsx's own treatment of
 * the same number.
 */
import { useCallback, useMemo, useState } from "react";
import { router, useFocusEffect } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pressable, StyleSheet, Text, View } from "react-native";

import {
  deleteBodyWeight,
  listBodyWeight,
  upsertBodyWeight,
  type BodyWeightPoint,
} from "../../src/api/bodyWeight";
import { resolveErrorCode, type ResolvedErrorCode } from "../../src/api/errors";
import { getProfile } from "../../src/api/profile";
import { getRecords, type RecordEntryData } from "../../src/api/records";
import { useSession } from "../../src/auth/useSession";
import {
  GButton,
  GCard,
  GChip,
  GDialog,
  GEmptyState,
  GErrorBanner,
  GLineChart,
  GIcon,
  GListRow,
  GMetric,
  GNumberField,
  GScreen,
  GSectionHeader,
  GSheet,
  GSkeleton,
} from "../../src/components";
import { useI18n, type Locale } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { layout, minTouchTarget, radius, space } from "../../src/theme/tokens";
import type { Theme } from "../../src/theme/tokens";

const RANGE_OPTIONS = [30, 90, 365] as const;
type RangeDays = (typeof RANGE_OPTIONS)[number];
const DEFAULT_RANGE_DAYS: RangeDays = 90;

const WEIGHT_STEP_KG = 0.5;
const WEIGHT_MIN_KG = 30;
const WEIGHT_MAX_KG = 300;
const WEIGHT_PRECISION = 1;

/** `en-CA` formats as "YYYY-MM-DD" by construction -- the same trick used to
 * get a fixed, parseable shape out of `Intl` without a date library (§A.2). */
function todayInTimezone(timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function subtractDaysIso(isoDate: string, days: number): string {
  const utcMs = Date.parse(`${isoDate}T00:00:00Z`);
  return new Date(utcMs - days * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function formatSignedKg(value: number): string {
  return value >= 0 ? `+${value.toFixed(1)}` : value.toFixed(1);
}

/** Same UTC-anchored technique history.tsx's own formatDay uses, so a
 * `measured_on` string renders as the calendar day it literally names,
 * never shifted by the device's own zone. */
function formatEntryDate(isoDate: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-u-nu-latn" : "en", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${isoDate}T00:00:00Z`));
}

function ProgressSkeleton() {
  return (
    <View style={styles.section} testID="progress-skeleton">
      <GSkeleton width="40%" height={24} />
      <GSkeleton width="100%" height={200} radius={radius.lg} />
      <GSkeleton width="100%" height={52} radius={radius.md} />
      <GSkeleton width="100%" height={120} radius={radius.lg} />
    </View>
  );
}

function RecordRow({
  record,
  theme,
  locale,
}: {
  record: RecordEntryData;
  theme: Theme;
  locale: Locale;
}) {
  const { t } = useI18n();
  return (
    <GListRow
      testID={`progress-record-${record.exercise.id}`}
      title={record.exercise.name}
      subtitle={t("plan.dayDetail.lastPerformanceValue", {
        reps: record.heaviest_set.reps,
        weight: record.heaviest_set.weight_kg,
      })}
      trailing={
        <GMetric value={record.best_e1rm.value_kg} unit={t("dashboard.weight.unit")} size="sm" />
      }
    />
  );
}

function EntryRow({
  entry,
  theme,
  locale,
  onEdit,
  onDelete,
}: {
  entry: BodyWeightPoint;
  theme: Theme;
  locale: Locale;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useI18n();
  const formattedDate = formatEntryDate(entry.measured_on, locale);

  return (
    <GListRow
      testID={`progress-entry-${entry.measured_on}`}
      title={formattedDate}
      accessibilityLabel={t("progress.entries.rowAccessibilityLabel", {
        date: formattedDate,
        weight: entry.weight_kg,
      })}
      onPress={onEdit}
      trailing={
        // The value and the delete affordance sit SIDE BY SIDE. They were
        // stacked, with delete as a full 52dp `controlHeight` ghost button,
        // which made every log row three lines tall and left the date floating
        // against the middle of that stack. An icon-only touchable keeps the
        // row one line and still clears the 48dp floor via `entryDelete`.
        <View style={styles.entryTrailing}>
          <GMetric value={entry.weight_kg} unit={t("dashboard.weight.unit")} size="sm" />
          <Pressable
            onPress={onDelete}
            accessibilityRole="button"
            accessibilityLabel={t("progress.entries.deleteLabel", { date: formattedDate })}
            style={styles.entryDelete}
            testID={`progress-entry-delete-${entry.measured_on}`}
          >
            <GIcon name="trash" size="sm" color={theme.error} />
          </Pressable>
        </View>
      }
    />
  );
}

export default function Progress() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const { user } = useSession();
  const queryClient = useQueryClient();

  const [rangeDays, setRangeDays] = useState<RangeDays>(DEFAULT_RANGE_DAYS);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sheetMeasuredOn, setSheetMeasuredOn] = useState<string | null>(null);
  const [sheetWeight, setSheetWeight] = useState(WEIGHT_MIN_KG);
  const [sheetError, setSheetError] = useState<ResolvedErrorCode | null>(null);

  const profileQuery = useQuery({ queryKey: ["profile"], queryFn: getProfile, enabled: user !== null });
  const timezone = profileQuery.data?.timezone;

  const today = timezone ? todayInTimezone(timezone) : null;
  const from = today ? subtractDaysIso(today, rangeDays - 1) : undefined;

  const bodyWeightQuery = useQuery({
    queryKey: ["bodyWeight", rangeDays],
    queryFn: () => listBodyWeight({ from }),
    enabled: today !== null,
  });

  const recordsQuery = useQuery({
    queryKey: ["records"],
    queryFn: getRecords,
    enabled: user !== null,
  });

  // §8.5/device check 13: Expo Router's tab navigator keeps every tab
  // mounted, so a plain useQuery never remounts (and never refetches) just
  // from switching tabs back to this one -- a change made in Settings would
  // otherwise sit stale until something else happened to invalidate it.
  useFocusEffect(
    useCallback(() => {
      void bodyWeightQuery.refetch();
    }, [bodyWeightQuery.refetch]),
  );

  const invalidateAfterWrite = () => {
    void queryClient.invalidateQueries({ queryKey: ["bodyWeight"] });
    void queryClient.invalidateQueries({ queryKey: ["profile"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const upsertMutation = useMutation({
    mutationFn: upsertBodyWeight,
    onSuccess: () => {
      invalidateAfterWrite();
      setSheetOpen(false);
    },
    onError: (err) => setSheetError(resolveErrorCode(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteBodyWeight,
    onSuccess: invalidateAfterWrite,
  });

  const openSheetFor = (entry?: BodyWeightPoint) => {
    setSheetError(null);
    setSheetMeasuredOn(entry?.measured_on ?? today);
    setSheetWeight(entry?.weight_kg ?? profileQuery.data?.weight_kg ?? WEIGHT_MIN_KG);
    setSheetOpen(true);
  };

  const handleSheetSave = () => {
    if (!sheetMeasuredOn) return;
    setSheetError(null);
    upsertMutation.mutate({ measured_on: sheetMeasuredOn, weight_kg: sheetWeight });
  };

  // The entry pending deletion -- what the OS alert captured in its closure.
  const [pendingDelete, setPendingDelete] = useState<BodyWeightPoint | null>(null);

  const handleDelete = (entry: BodyWeightPoint) => {
    setPendingDelete(entry);
  };

  const entries = bodyWeightQuery.data?.entries ?? [];
  const movingAverage = bodyWeightQuery.data?.moving_average_7d ?? [];
  const summary = bodyWeightQuery.data?.summary;
  const records = recordsQuery.data?.records ?? [];

  const chartAccessibilityLabel = useMemo(() => {
    if (entries.length < 2 || !today || !from) return "";
    const firstEntry = entries[0]!;
    const lastEntry = entries[entries.length - 1]!;
    return t("progress.chart.accessibilityLabel", {
      entries: t("units.entry", { count: entries.length }),
      first: firstEntry.weight_kg,
      last: lastEntry.weight_kg,
      period: t("units.day", { count: rangeDays }),
    });
  }, [entries, today, from, rangeDays, t]);

  const isLoading = profileQuery.isLoading || bodyWeightQuery.isLoading;
  const isError = profileQuery.isError || bodyWeightQuery.isError;

  return (
    <GScreen testID="progress-screen">
      <Text style={[textStyle("h1", locale), { color: theme.textPrimary }]}>{t("progress.title")}</Text>

      {isError ? (
        <GErrorBanner
          testID="progress-error"
          code={resolveErrorCode(profileQuery.error ?? bodyWeightQuery.error)}
          onRetry={() => {
            void profileQuery.refetch();
            void bodyWeightQuery.refetch();
          }}
        />
      ) : null}

      {isLoading ? (
        <ProgressSkeleton />
      ) : (
        <View style={styles.section}>
          <View style={styles.chipsRow}>
            {RANGE_OPTIONS.map((days) => (
              <GChip
                key={days}
                label={t("progress.range.option", { count: days })}
                selected={rangeDays === days}
                onPress={() => setRangeDays(days)}
                testID={`progress-range-${days}`}
              />
            ))}
          </View>

          {entries.length >= 2 && today && from ? (
            <GCard testID="progress-chart-card">
              <GLineChart
                testID="progress-chart"
                series={[
                  { data: movingAverage, color: theme.chart1, strokeWidth: 3 },
                  { data: entries, color: theme.chart3, strokeWidth: 2, showDots: true },
                ]}
                xAccessor={(point: BodyWeightPoint) => point.measured_on}
                yAccessor={(point: BodyWeightPoint) => point.weight_kg}
                range={{ start: from, end: today }}
                accessibilityLabel={chartAccessibilityLabel}
              />
              {summary ? (
                <View style={styles.summaryRow} testID="progress-summary">
                  <View>
                    <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                      {t("progress.summary.first")}
                    </Text>
                    {summary.first !== null ? (
                      <GMetric
                        value={summary.first}
                        unit={t("dashboard.weight.unit")}
                        size="sm"
                      />
                    ) : (
                      <Text style={[textStyle("body", locale), { color: theme.textMuted }]}>
                        {t("common.notEnoughData")}
                      </Text>
                    )}
                  </View>
                  <View>
                    <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                      {t("progress.summary.latest")}
                    </Text>
                    {summary.latest !== null ? (
                      <GMetric
                        value={summary.latest}
                        unit={t("dashboard.weight.unit")}
                        size="sm"
                      />
                    ) : (
                      <Text style={[textStyle("body", locale), { color: theme.textMuted }]}>
                        {t("common.notEnoughData")}
                      </Text>
                    )}
                  </View>
                  {summary.change_kg !== null ? (
                    <View>
                      <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
                        {t("progress.summary.change")}
                      </Text>
                      <GMetric
                        value={formatSignedKg(summary.change_kg)}
                        unit={t("dashboard.weight.unit")}
                        size="sm"
                      />
                    </View>
                  ) : null}
                </View>
              ) : null}
            </GCard>
          ) : (
            <GEmptyState
              testID="progress-chart-empty"
              titleKey="common.notEnoughData"
              bodyKey="progress.chart.emptyBody"
            />
          )}

          {/* Hierarchy rule 1: the only filled button on this screen. */}
          <GButton
            label={t("dashboard.weight.emptyAction")}
            onPress={() => openSheetFor()}
            fullWidth
            testID="progress-log-today"
          />

          {entries.length > 0 ? (
            <View>
              <GSectionHeader title={t("progress.entries.heading")} separation="spaced" />
              {/* A weight log is a LIST. It was a GCard wrapping rows, which
                  gave a shadowed, bordered object the shape of a single thing
                  when it is many things. */}
              <View style={styles.rowList} testID="progress-entries">
                {[...entries].reverse().map((entry) => (
                  <EntryRow
                    key={entry.measured_on}
                    entry={entry}
                    theme={theme}
                    locale={locale}
                    onEdit={() => openSheetFor(entry)}
                    onDelete={() => handleDelete(entry)}
                  />
                ))}
              </View>
            </View>
          ) : null}

          <View>
            <GSectionHeader title={t("progress.records.heading")} separation="spaced" />
            {records.length > 0 ? (
              <View style={styles.rowList} testID="progress-records">
                {records.map((record) => (
                  <RecordRow key={record.exercise.id} record={record} theme={theme} locale={locale} />
                ))}
              </View>
            ) : (
              <GEmptyState
                testID="progress-records-empty"
                titleKey="dashboard.records.emptyTitle"
                bodyKey="dashboard.records.emptyBody"
              />
            )}
          </View>

          {/* T-30 gap 2: history.tsx worked but nothing opened it, which fails
              §10.3 item 1 (every P2-FR demonstrated on a device) on its own.
              §8.2 never says where history is reached from and §8.1 fixes the
              tab bar at exactly four, so a fifth tab is out. This tab is the
              least surprising of the remaining options: Progress is already
              the backward-looking surface (the weight chart, the entry log,
              the records list), whereas the dashboard's blocks are enumerated
              by §5.12 and Plan is forward-looking. Placed under records, so
              "what have I done" reads top to bottom. */}
          <View style={styles.historyRow} testID="progress-history-card">
            <GListRow
              title={t("history.title")}
              subtitle={t("history.entryPointSubtitle")}
              onPress={() => router.push("/(app)/history")}
              trailing={<GIcon name="chevron" size="sm" color={theme.textMuted} />}
              testID="progress-open-history"
            />
          </View>
        </View>
      )}

      <GSheet visible={sheetOpen} onClose={() => setSheetOpen(false)} testID="progress-log-sheet">
        <Text style={[textStyle("h3", locale), styles.sheetTitle, { color: theme.textPrimary }]}>
          {t("progress.logSheet.title", {
            date: sheetMeasuredOn ? formatEntryDate(sheetMeasuredOn, locale) : "",
          })}
        </Text>
        {sheetError ? (
          <GErrorBanner
            testID="progress-sheet-error"
            code={sheetError}
            onDismiss={() => setSheetError(null)}
          />
        ) : null}
        <GNumberField
          label={t("settings.fields.weightKg")}
          value={sheetWeight}
          onChange={setSheetWeight}
          step={WEIGHT_STEP_KG}
          min={WEIGHT_MIN_KG}
          max={WEIGHT_MAX_KG}
          unit={t("dashboard.weight.unit")}
          precision={WEIGHT_PRECISION}
          testID="progress-sheet-weight"
        />
        <GButton
          label={t("progress.logSheet.save")}
          onPress={handleSheetSave}
          loading={upsertMutation.isPending}
          fullWidth
          testID="progress-sheet-save"
        />
        <GButton
          variant="ghost"
          label={t("common.cancel")}
          onPress={() => setSheetOpen(false)}
          testID="progress-sheet-cancel"
        />
      </GSheet>

      <GDialog
        visible={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        titleKey="progress.entries.deleteConfirmTitle"
        bodyKey="progress.entries.deleteConfirmBody"
        bodyParams={{
          date: pendingDelete ? formatEntryDate(pendingDelete.measured_on, locale) : "",
        }}
        actions={[
          { labelKey: "common.cancel", onPress: () => setPendingDelete(null) },
          {
            labelKey: "progress.entries.deleteConfirmAction",
            variant: "destructive",
            onPress: () => {
              const entry = pendingDelete;
              setPendingDelete(null);
              if (entry) deleteMutation.mutate(entry.measured_on);
            },
          },
        ]}
        testID="progress-delete-confirm"
      />
    </GScreen>
  );
}

const styles = StyleSheet.create({
  // Dense inside a section; the 32dp between sections comes from
  // GSectionHeader. One uniform `space[4]` on everything is what made the
  // chart, the button and the two lists all read as equally important.
  section: {
    gap: layout.denseGap,
  },
  // Cancels GListRow's own inset so row text lines up with the section
  // heading above it. Side-neutral, so no §9.6 start/end concern.
  rowList: {
    marginHorizontal: -space[3],
  },
  historyRow: {
    marginTop: layout.sectionGap,
    marginHorizontal: -space[3],
  },
  chipsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space[2],
  },
  summaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: layout.looseGap,
  },
  entryTrailing: {
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
  },
  entryDelete: {
    minWidth: minTouchTarget,
    minHeight: minTouchTarget,
    alignItems: "center",
    justifyContent: "center",
  },
  sheetTitle: {
    marginBottom: space[2],
  },
});
