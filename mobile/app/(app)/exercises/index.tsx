/**
 * §5.2/§8.2 screen 23 -- the exercise library list, and (per T-29's own brief)
 * "the same list, in a GSheet, is the exercise picker for an empty session". One
 * route serves both: `?picker=1` switches the wrapping chrome from a full GScreen to
 * a GSheet and swaps the row-press action from "open detail" to "hand back a
 * selection" (`handlePick` below).
 *
 * §8.1 registers this route directly in `(app)/_layout.tsx`'s <Tabs> (`href: null`,
 * same treatment as workout/active, plan/[dayId] and history -- see that file for
 * why), not nested in its own stack, so -- like those -- this screen's component
 * instance persists across visits instead of unmounting when the user leaves; a
 * plain `useState` for the search text and filters is enough, unlike
 * workout/active.tsx's `ensureFresh`, because there is no server-owned session state
 * to resync here.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { router, useLocalSearchParams } from "expo-router";
import { FlatList, ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";

import { resolveErrorCode } from "../../../src/api/errors";
import {
  listExercises,
  type ExerciseDetailData,
  type ExerciseListItem,
} from "../../../src/api/exercises";
import { ExerciseFormSheet } from "../../../src/exercises/ExerciseFormSheet";
import { useSession } from "../../../src/auth/useSession";
import { useActiveSessionStore } from "../../../src/workout/activeSession";
import {
  GButton,
  GChip,
  GEmptyState,
  GErrorBanner,
  GListRow,
  GScreen,
  GSheet,
  GSkeleton,
  GTextInput,
} from "../../../src/components";
import { useI18n } from "../../../src/i18n";
import { useTheme } from "../../../src/theme/useTheme";
import { textStyle } from "../../../src/theme/typography";
import { layout, radius, space } from "../../../src/theme/tokens";

// §4.1a's closed 17-value muscle vocabulary and §4.1's 7-value equipment vocabulary
// -- the filter chips enumerate these two fixed sets exhaustively, never derived
// from whatever page of results happens to be loaded (which would shrink the chip
// list itself as filters narrow the results down). Mirrors the `muscles`/`equipment`
// i18n namespaces key-for-key.
const MUSCLE_FILTER_VALUES = [
  "chest", "back", "lats", "traps", "front_delts", "side_delts", "rear_delts",
  "biceps", "triceps", "forearms", "quads", "hamstrings", "glutes", "calves",
  "abs", "obliques", "lower_back",
] as const;

const EQUIPMENT_FILTER_VALUES = [
  "barbell", "dumbbell", "machine", "cable", "bodyweight", "kettlebell", "band",
] as const;

// §5.2/§7.3: "Debounce the query field properly -- an undebounced search box burns
// that budget [120/hour] in under a minute of typing." 400ms is short enough that a
// pause between words still reads as responsive, but long enough that a normal
// typing cadence collapses a whole word into one request instead of one per
// keystroke -- a full search (a few words, a correction or two) costs single-digit
// requests, nowhere near the budget even shared with pagination and the picker.
const SEARCH_DEBOUNCE_MS = 400;

// GSheet hugs its content (`maxHeight: "85%"`, no height of its own), which is
// right for progress.tsx's log-weight form -- every child there is intrinsically
// sized. This body is not: its FlatList and its wrapper both carry `flex: 1`, and
// a flex child of a hug-content parent contributes a base height of zero, so the
// sheet collapsed to its own header with the list rendered entirely off-screen.
// T-30 found that the first time anything actually opened this picker (T-29 built
// it with no entry point, so it had never been seen on a device). Bounding the
// body to a real pixel height is what gives those flex children something to fill.
// Measured from the live window rather than hardcoded, so it stays correct across
// rotation and font scale; 0.62 leaves the sheet's header, handle and padding
// comfortably inside GSheet's own 85% cap.
const PICKER_BODY_HEIGHT_RATIO = 0.62;

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timeout = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timeout);
  }, [value, delayMs]);
  return debounced;
}

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** A user's own exercise, marked so it is distinguishable from the seeded library at a
 * glance. A tinted text badge rather than a colour-only cue: §10.5's "never colour
 * alone" applies here as much as anywhere, and the word is what a screen reader reads
 * out -- the badge is inside the row's accessibility label, not decoration beside it. */
function CustomBadge({ label }: { label: string }) {
  const theme = useTheme();
  const { locale } = useI18n();
  return (
    <View style={[styles.badge, { backgroundColor: theme.primaryContainer }]}>
      <Text style={[textStyle("caption", locale), { color: theme.textLink }]}>{label}</Text>
    </View>
  );
}

function ExerciseRow({
  item,
  onPress,
  t,
}: {
  item: ExerciseListItem;
  onPress: () => void;
  t: Translate;
}) {
  const subtitle = t("exercises.row.subtitle", {
    muscle: t(`muscles.${item.primary_muscle}`),
    equipment: t(`equipment.${item.equipment}`),
  });
  const badgeLabel = t("exercises.custom.badge");
  return (
    <GListRow
      title={item.name}
      subtitle={subtitle}
      trailing={item.is_custom ? <CustomBadge label={badgeLabel} /> : undefined}
      accessibilityLabel={
        item.is_custom ? `${item.name}, ${badgeLabel}, ${subtitle}` : `${item.name}, ${subtitle}`
      }
      onPress={onPress}
      testID={`exercise-row-${item.id}`}
    />
  );
}

function ListSkeleton() {
  return (
    <View style={styles.skeletonSection} testID="exercises-list-skeleton">
      <GSkeleton width="100%" height={56} />
      <GSkeleton width="100%" height={56} />
      <GSkeleton width="100%" height={56} />
      <GSkeleton width="100%" height={56} />
      <GSkeleton width="100%" height={56} />
    </View>
  );
}

function ExerciseLibraryBody({
  onPressExercise,
  onCreate,
}: {
  onPressExercise: (item: ExerciseListItem) => void;
  onCreate: () => void;
}) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const { user } = useSession();

  const [queryText, setQueryText] = useState("");
  const [selectedMuscle, setSelectedMuscle] = useState<string | null>(null);
  const [selectedEquipment, setSelectedEquipment] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(queryText, SEARCH_DEBOUNCE_MS);

  const listQuery = useInfiniteQuery({
    queryKey: ["exercises", "list", debouncedQuery, selectedMuscle, selectedEquipment],
    queryFn: ({ pageParam }) =>
      listExercises({
        // The user's raw text, untouched -- T-16b's Arabic-aware normalisation runs
        // server-side only; normalising or stripping anything here would
        // double-normalise and break matches the server would otherwise find.
        q: debouncedQuery.length > 0 ? debouncedQuery : undefined,
        muscle: selectedMuscle ?? undefined,
        equipment: selectedEquipment ?? undefined,
        cursor: pageParam,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: user !== null,
  });

  const items = useMemo(
    () => listQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [listQuery.data],
  );

  const handleEndReached = useCallback(() => {
    if (listQuery.hasNextPage && !listQuery.isFetchingNextPage) {
      void listQuery.fetchNextPage();
    }
  }, [listQuery]);

  const handleClearFilters = useCallback(() => {
    setQueryText("");
    setSelectedMuscle(null);
    setSelectedEquipment(null);
  }, []);

  const isEmpty = !listQuery.isLoading && !listQuery.isError && items.length === 0;

  return (
    <View style={styles.body}>
      <View style={styles.controls}>
        <GTextInput
          label={t("exercises.searchLabel")}
          value={queryText}
          onChangeText={setQueryText}
          placeholder={t("exercises.searchPlaceholder")}
          testID="exercises-search-input"
        />

        <Text
          style={[textStyle("label", locale), styles.filterLabel, { color: theme.textMuted }]}
          accessibilityRole="header"
        >
          {t("exercises.filters.muscleLabel")}
        </Text>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipsRow}
        >
          <GChip
            label={t("exercises.filters.allMuscles")}
            selected={selectedMuscle === null}
            onPress={() => setSelectedMuscle(null)}
            testID="exercises-filter-muscle-all"
          />
          {MUSCLE_FILTER_VALUES.map((muscle) => (
            <GChip
              key={muscle}
              label={t(`muscles.${muscle}`)}
              selected={selectedMuscle === muscle}
              onPress={() => setSelectedMuscle(muscle === selectedMuscle ? null : muscle)}
              testID={`exercises-filter-muscle-${muscle}`}
            />
          ))}
        </ScrollView>

        <Text
          style={[textStyle("label", locale), styles.filterLabel, { color: theme.textMuted }]}
          accessibilityRole="header"
        >
          {t("exercises.filters.equipmentLabel")}
        </Text>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipsRow}
        >
          <GChip
            label={t("exercises.filters.allEquipment")}
            selected={selectedEquipment === null}
            onPress={() => setSelectedEquipment(null)}
            testID="exercises-filter-equipment-all"
          />
          {EQUIPMENT_FILTER_VALUES.map((equipment) => (
            <GChip
              key={equipment}
              label={t(`equipment.${equipment}`)}
              selected={selectedEquipment === equipment}
              onPress={() =>
                setSelectedEquipment(equipment === selectedEquipment ? null : equipment)
              }
              testID={`exercises-filter-equipment-${equipment}`}
            />
          ))}
        </ScrollView>
      </View>

      {/* The create affordance sits directly above the results in BOTH modes. The
          in-workout picker is the case this feature exists for -- being mid-session and
          needing a movement the library does not have -- so it cannot live only on the
          browse screen, and putting it here rather than in each mode's header gives it
          one implementation instead of two. */}
      <View style={styles.createRow}>
        <GButton
          variant="secondary"
          label={t("exercises.form.addAction")}
          onPress={onCreate}
          testID="exercises-create-action"
        />
      </View>

      {listQuery.isLoading ? (
        <ListSkeleton />
      ) : listQuery.isError ? (
        <GErrorBanner
          testID="exercises-list-error"
          code={resolveErrorCode(listQuery.error)}
          onRetry={() => void listQuery.refetch()}
        />
      ) : isEmpty ? (
        <GEmptyState
          testID="exercises-list-empty"
          titleKey="exercises.empty.title"
          bodyKey="exercises.empty.body"
          actionLabelKey="exercises.empty.action"
          onAction={handleClearFilters}
        />
      ) : (
        <FlatList
          testID="exercises-list"
          style={styles.list}
          data={items}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => (
            <ExerciseRow item={item} onPress={() => onPressExercise(item)} t={t} />
          )}
          onEndReached={handleEndReached}
          onEndReachedThreshold={0.5}
          keyboardShouldPersistTaps="handled"
          ListFooterComponent={
            listQuery.isFetchingNextPage ? (
              <View style={styles.footerLoading} testID="exercises-loading-more">
                <GSkeleton width="100%" height={56} />
              </View>
            ) : null
          }
        />
      )}
    </View>
  );
}

export default function ExerciseLibrary() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const params = useLocalSearchParams<{ picker?: string }>();
  const isPicker = params.picker === "1";
  const selectAdHocExercise = useActiveSessionStore((s) => s.selectAdHocExercise);
  const { height: windowHeight } = useWindowDimensions();

  // Both this route and workout/active are sibling <Tabs.Screen>s of the same
  // navigator (§8.1's "outside the tabs", `href: null`), not entries on a stack.
  // `router.back()` therefore pops the *tab navigator's* history, which lands on
  // its initial route -- the dashboard -- not on the screen that opened the
  // sheet. Observed on a device the first time anything opened this picker.
  // Picker mode has exactly one opener, the active session, so it names that
  // destination explicitly; browse mode keeps `back()`, which is correct for a
  // screen reached from more than one place.
  const handleClose = useCallback(() => {
    if (isPicker) router.replace("/(app)/workout/active");
    else router.back();
  }, [isPicker]);

  const [formVisible, setFormVisible] = useState(false);
  const queryClient = useQueryClient();

  const handleBrowsePress = useCallback((item: ExerciseListItem) => {
    router.push(`/(app)/exercises/${item.id}`);
  }, []);

  const handleCreate = useCallback(() => setFormVisible(true), []);

  /** A new exercise has to appear in the list it was created from, so the library query
   * is invalidated rather than the row being spliced in locally: the list is paginated
   * and filtered server-side, so only the server knows where (or whether) the new row
   * belongs under the filters currently applied. */
  const handleSaved = useCallback(
    (exercise: ExerciseDetailData) => {
      void queryClient.invalidateQueries({ queryKey: ["exercises"] });
      // Created from inside the picker: the reason to make it mid-session is to log
      // against it immediately, so it is selected and the sheet closes, exactly as
      // picking an existing row does.
      if (isPicker) {
        selectAdHocExercise(exercise);
        handleClose();
      }
    },
    [queryClient, isPicker, selectAdHocExercise, handleClose],
  );

  // Picker mode's own row-press. T-30 closed the gap T-29 and T-26 each left to the
  // other: the hand-back goes through activeSession.ts's module-level Zustand store
  // rather than a navigation param, because that store -- not any screen's props --
  // is already where §8.3.7 says session state lives, and workout/active.tsx re-reads
  // it on focus anyway. `router.back()` then returns to the active screen with the
  // picked exercise current, which is T-29's own done-when.
  const handlePick = useCallback(
    (item: ExerciseListItem) => {
      selectAdHocExercise(item);
      handleClose();
    },
    [selectAdHocExercise, handleClose],
  );

  if (isPicker) {
    return (
      <GSheet visible onClose={handleClose} testID="exercise-picker-sheet">
        <View style={styles.pickerHeader}>
          <Text style={[textStyle("h3", locale), { color: theme.textPrimary }]}>
            {t("exercises.picker.title")}
          </Text>
          <GButton
            variant="ghost"
            label={t("exercises.picker.close")}
            onPress={handleClose}
            testID="exercise-picker-close"
          />
        </View>
        <View style={{ height: windowHeight * PICKER_BODY_HEIGHT_RATIO }}>
          <ExerciseLibraryBody onPressExercise={handlePick} onCreate={handleCreate} />
        </View>
        <ExerciseFormSheet
          visible={formVisible}
          onClose={() => setFormVisible(false)}
          onSaved={handleSaved}
          testID="exercise-form-sheet"
        />
      </GSheet>
    );
  }

  return (
    <GScreen
      scroll={false}
      header={{ title: t("exercises.title"), onBack: () => router.back() }}
      testID="exercises-list-screen"
    >
      <ExerciseLibraryBody onPressExercise={handleBrowsePress} onCreate={handleCreate} />
      <ExerciseFormSheet
        visible={formVisible}
        onClose={() => setFormVisible(false)}
        onSaved={handleSaved}
        testID="exercise-form-sheet"
      />
    </GScreen>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: space[1],
    paddingVertical: space[0],
    borderRadius: radius.pill,
  },
  filterLabel: {
    letterSpacing: 0.6,
  },
  createRow: {
    marginBottom: layout.groupGap,
  },
  // A dense screen on purpose (hierarchy rule 5): this is a search surface,
  // scanned rather than read, so the controls stay tight and the results get
  // as much of the viewport as possible.
  body: {
    flex: 1,
    gap: layout.groupGap,
  },
  controls: {
    gap: space[1],
  },
  chipsRow: {
    flexDirection: "row",
    gap: space[2],
    paddingVertical: space[1],
  },
  list: {
    flex: 1,
  },
  skeletonSection: {
    gap: space[2],
    paddingTop: space[2],
  },
  footerLoading: {
    paddingVertical: space[2],
  },
  pickerHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: space[2],
  },
});
