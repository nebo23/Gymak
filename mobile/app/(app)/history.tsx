/**
 * §5.9/§8.2 screen 21 -- the history list. Infinite, cursor-paginated,
 * grouped by month, newest first. GET /workouts already returns items in
 * that order (§5.9), so grouping is a single linear pass over an
 * already-sorted array, never a re-sort.
 *
 * §8.2 never says where this screen is reached from, and §8.1's tab list is
 * exactly four (index/plan/progress/settings) -- a fifth would be wrong.
 * _layout.tsx is touched (below) only to give this route `href: null`, the
 * same treatment workout/active and plan/[dayId] already get, so Expo
 * Router does not auto-register it as a tab. No button anywhere points here
 * yet: inventing a location for one (which screen, what label) is a product
 * decision this task's own instructions say to flag rather than guess at.
 * See this session's report for the flag.
 */
import { useCallback, useMemo } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { router } from "expo-router";
import { ActivityIndicator, SectionList, StyleSheet, Text, View } from "react-native";

import { resolveErrorCode } from "../../src/api/errors";
import { listWorkouts, type WorkoutHistoryItem } from "../../src/api/workouts";
import { useSession } from "../../src/auth/useSession";
import {
  GEmptyState,
  GErrorBanner,
  GListRow,
  GMetric,
  GScreen,
  GSkeleton,
} from "../../src/components";
import { useI18n, type Locale } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { layout, space } from "../../src/theme/tokens";
import type { Theme } from "../../src/theme/tokens";

type Translate = (key: string, options?: Record<string, unknown>) => string;

interface HistorySection {
  key: string;
  title: string;
  data: WorkoutHistoryItem[];
}

// Shared with workout/[id].tsx's own summary card -- same seconds-to-words
// rule (§5.8) as workout/active.tsx's finish summary, duplicated for the
// same reason noted there: a five-line pure formatter is not worth reaching
// into a committed screen outside this task's file list to share.
function formatDuration(totalSeconds: number, t: Translate): string {
  const minutes = Math.round(totalSeconds / 60);
  if (minutes < 60) return t("workout.active.summaryDurationMinutes", { minutes });
  return t("workout.active.summaryDurationHoursMinutes", {
    hours: Math.floor(minutes / 60),
    minutes: minutes % 60,
  });
}

/**
 * `local_date` is already the correct calendar day in the user's own
 * timezone (§4.6) -- it must render as the digits it literally contains,
 * never re-shifted by the device's own zone. `new Date("YYYY-MM-DDT00:00:00Z")`
 * parses as UTC midnight; formatting with `timeZone: "UTC"` is what stops a
 * device west of UTC from rendering the day *before* the one the string
 * names. Western digits always (Phase 1 §9.6: "dates ... stay left-to-right
 * and use Western digits even in Arabic"), via the `-u-nu-latn` locale
 * extension rather than a numberingSystem option, for broader engine support.
 */
function formatDay(localDate: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-u-nu-latn" : "en", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${localDate}T00:00:00Z`));
}

function formatMonthTitle(monthKey: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-u-nu-latn" : "en", {
    year: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(new Date(`${monthKey}-01T00:00:00Z`));
}

function groupByMonth(items: WorkoutHistoryItem[], locale: Locale): HistorySection[] {
  const sections: HistorySection[] = [];
  for (const item of items) {
    const monthKey = item.local_date.slice(0, 7);
    const current = sections[sections.length - 1];
    if (current && current.key === monthKey) {
      current.data.push(item);
    } else {
      sections.push({ key: monthKey, title: formatMonthTitle(monthKey, locale), data: [item] });
    }
  }
  return sections;
}

function HistoryRow({
  item,
  locale,
  theme,
  t,
}: {
  item: WorkoutHistoryItem;
  locale: Locale;
  theme: Theme;
  t: Translate;
}) {
  const title = item.label_key ? t(item.label_key) : t("workout.untitledSession");
  const subtitle = t("history.rowSubtitle", {
    date: formatDay(item.local_date, locale),
    count: item.set_count,
  });

  const trailing =
    item.status === "completed" ? (
      <View style={styles.trailingStack}>
        <GMetric
          value={item.total_volume_kg ?? 0}
          unit={t("workout.active.weightUnit")}
          size="sm"
        />
        {item.duration_seconds !== null ? (
          <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
            {formatDuration(item.duration_seconds, t)}
          </Text>
        ) : null}
      </View>
    ) : (
      <Text
        style={[
          textStyle("caption", locale),
          { color: item.status === "abandoned" ? theme.error : theme.textMuted },
        ]}
      >
        {t(item.status === "abandoned" ? "workout.status.abandoned" : "workout.status.inProgress")}
      </Text>
    );

  return (
    <GListRow
      title={title}
      subtitle={subtitle}
      trailing={trailing}
      onPress={() => router.push(`/(app)/workout/${item.id}`)}
      testID={`history-row-${item.id}`}
    />
  );
}

export default function History() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const { user } = useSession();

  const historyQuery = useInfiniteQuery({
    queryKey: ["workouts", "history"],
    queryFn: ({ pageParam }) => listWorkouts(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: user !== null,
  });

  const items = useMemo(
    () => historyQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [historyQuery.data],
  );
  const sections = useMemo(() => groupByMonth(items, locale), [items, locale]);

  const handleEndReached = useCallback(() => {
    if (historyQuery.hasNextPage && !historyQuery.isFetchingNextPage) {
      void historyQuery.fetchNextPage();
    }
  }, [historyQuery]);

  const isEmpty = !historyQuery.isLoading && !historyQuery.isError && items.length === 0;

  return (
    <GScreen
      scroll={false}
      header={{ title: t("history.title"), onBack: () => router.back() }}
      testID="history-screen"
    >
      {historyQuery.isLoading ? (
        <View style={styles.skeletonSection} testID="history-skeleton">
          <GSkeleton width="40%" height={20} />
          <GSkeleton width="100%" height={64} />
          <GSkeleton width="100%" height={64} />
          <GSkeleton width="100%" height={64} />
        </View>
      ) : historyQuery.isError ? (
        <GErrorBanner
          testID="history-error"
          code={resolveErrorCode(historyQuery.error)}
          onRetry={() => void historyQuery.refetch()}
        />
      ) : isEmpty ? (
        <GEmptyState
          testID="history-empty"
          titleKey="history.empty.title"
          bodyKey="history.empty.body"
          actionLabelKey="history.empty.action"
          onAction={() => router.push("/(app)/plan")}
        />
      ) : (
        <SectionList
          testID="history-list"
          sections={sections}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => <HistoryRow item={item} locale={locale} theme={theme} t={t} />}
          renderSectionHeader={({ section }) => (
            <View style={[styles.sectionHeader, { backgroundColor: theme.bg }]}>
              <Text
                style={[textStyle("label", locale), styles.sectionTitle, { color: theme.textMuted }]}
                accessibilityRole="header"
              >
                {section.title}
              </Text>
            </View>
          )}
          onEndReached={handleEndReached}
          onEndReachedThreshold={0.5}
          stickySectionHeadersEnabled
          ListFooterComponent={
            historyQuery.isFetchingNextPage ? (
              <View
                style={styles.footerLoading}
                testID="history-loading-more"
                accessibilityRole="progressbar"
                accessibilityLabel={t("history.loadingMore")}
              >
                <ActivityIndicator color={theme.textMuted} />
              </View>
            ) : null
          }
        />
      )}
    </GScreen>
  );
}

const styles = StyleSheet.create({
  skeletonSection: {
    gap: space[3],
    paddingTop: space[2],
  },
  sectionHeader: {
    paddingTop: layout.sectionGap,
    paddingBottom: layout.headingGap,
  },
  sectionTitle: {
    // Matches GSectionHeader's tracking so month headings and screen section
    // headings read as the same kind of label.
    letterSpacing: 0.6,
  },
  trailingStack: {
    alignItems: "flex-end",
    gap: space[0],
  },
  footerLoading: {
    paddingVertical: space[4],
    alignItems: "center",
  },
});
