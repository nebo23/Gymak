/**
 * §8.3 screen 19 — the active workout. "The screen the phase lives or dies
 * on." Reached today from `plan/[dayId].tsx`'s Start button (a plan-backed
 * session). T-30 added the "add exercise" entry point below, which opens the
 * §5.2 library as a picker sheet (`/(app)/exercises?picker=1`) and hands the
 * selection back through activeSession.ts's `selectAdHocExercise` -- so an
 * exercise the program day never prescribed, and an empty session (no
 * `program_day_id`) whose `emptyExercises` state used to be a dead end, are
 * both loggable now. The backend already allowed it: §5.7's
 * `POST /workouts/{id}/sets` accepts any valid `exercise_id`.
 *
 * This route is registered directly in `(app)/_layout.tsx`'s `<Tabs>` (with
 * `href: null`, so it never becomes a tab button) rather than nested in its
 * own stack, per §8.1's "outside the tabs" -- which means React Navigation
 * keeps this screen's component instance alive across visits the same way
 * it keeps every tab alive, instead of unmounting it when the user leaves.
 * A plain mount-only effect would therefore only ever rehydrate once, for
 * the *first* session started in a given app run, and silently show stale
 * state for every session after that -- exactly the bug a first live pass
 * surfaced (a finished session's summary title stuck over a fresh "no
 * session" body). `useFocusEffect` below is what makes every re-entry
 * behave like a fresh visit; `handleSummaryDone`/`doAbandon` clear this
 * screen's own local UI state for the same reason `reset()` clears the
 * store's.
 *
 * Every eight of §8.3's numbered requirements, and where each lives:
 *  1. Current exercise pinned above the fold, everything else scrolls.
 *  2. Reps/weight pre-fill (activeSession.ts's `computePrefill`); Log Set is
 *     the only tap needed when they're unchanged from the last set.
 *  3. GNumberField steppers, decimal-pad, never remounted mid-edit.
 *  4. Rest timer: wall-clock, via GRestTimer + activeSession.ts's `restEndsAt`.
 *  5. Optimistic set rows, unsent marker, per-row retry (P2-ADR-08).
 *  6. Guarded back (React Navigation `beforeRemove` + Android `BackHandler`);
 *     Finish/Abandon are the only ways out, both behind a confirm.
 *  7. All session state reads from `useActiveSessionStore`, not local state.
 *  8. Finish shows a summary (from the finish response, not recomputed) before
 *     the screen actually navigates away.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { router, useFocusEffect, useNavigation } from "expo-router";
import {
  AccessibilityInfo,
  AppState,
  BackHandler,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { resolveErrorCode, type ResolvedErrorCode } from "../../../src/api/errors";
import type { WorkoutFinishResponse } from "../../../src/api/workouts";
import {
  computePrefill,
  computeRemainingSeconds,
  hasUnsentSets,
  useActiveSessionStore,
  type ExerciseTarget,
  type SessionSetRow,
} from "../../../src/workout/activeSession";
import {
  GButton,
  GCard,
  GChip,
  GErrorBanner,
  GNumberField,
  GRestTimer,
  GScreen,
  GSkeleton,
} from "../../../src/components";
import { useI18n, type Locale } from "../../../src/i18n";
import { useTheme } from "../../../src/theme/useTheme";
import { textStyle } from "../../../src/theme/typography";
import { radius, space } from "../../../src/theme/tokens";
import type { Theme } from "../../../src/theme/tokens";

function formatDuration(totalSeconds: number, t: (key: string, options?: Record<string, unknown>) => string): string {
  const minutes = Math.round(totalSeconds / 60);
  if (minutes < 60) return t("workout.active.summaryDurationMinutes", { minutes });
  return t("workout.active.summaryDurationHoursMinutes", {
    hours: Math.floor(minutes / 60),
    minutes: minutes % 60,
  });
}

function ActiveWorkoutSkeleton() {
  return (
    <View style={styles.section} testID="active-workout-skeleton">
      <GSkeleton width="70%" height={24} />
      <GSkeleton width="100%" height={140} radius={radius.lg} />
      <GSkeleton width="100%" height={80} radius={radius.lg} />
      <GSkeleton width="100%" height={200} radius={radius.lg} />
    </View>
  );
}

function NoActiveSessionView() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  return (
    <View style={styles.centeredSection} testID="active-workout-no-session">
      <Text style={[textStyle("body", locale), { color: theme.textSecondary }]}>
        {t("workout.active.noActiveSession")}
      </Text>
      <GButton
        variant="secondary"
        label={t("workout.active.backToPlan")}
        onPress={() => router.replace("/(app)/plan")}
        testID="active-workout-back-to-plan"
      />
    </View>
  );
}

function SetRow({
  row,
  index,
  locale,
  theme,
  t,
  onRetry,
}: {
  row: SessionSetRow;
  index: number;
  locale: Locale;
  theme: Theme;
  t: (key: string, options?: Record<string, unknown>) => string;
  onRetry: (localId: string) => void;
}) {
  const reps = row.kind === "confirmed" ? row.data.reps : row.input.reps;
  const weightKg = row.kind === "confirmed" ? row.data.weight_kg : row.input.weightKg;
  const isWarmup = row.kind === "confirmed" ? row.data.is_warmup : row.input.isWarmup;

  return (
    <View style={styles.setRow} testID={`active-workout-set-${row.localId}`}>
      <Text style={[textStyle("body", locale), styles.setRowLabel, { color: theme.textPrimary }]}>
        {t("workout.active.setLabel", { index: index + 1 })} · {reps} × {weightKg} {t("workout.active.weightUnit")}
      </Text>
      {isWarmup ? (
        <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
          {t("workout.active.warmupBadge")}
        </Text>
      ) : null}
      {row.kind === "pending" ? (
        row.sending ? (
          <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
            {t("workout.active.sendingBadge")}
          </Text>
        ) : (
          <View style={styles.unsentRow}>
            <Text style={[textStyle("caption", locale), { color: theme.error }]}>
              {t("workout.active.unsentBadge")}
            </Text>
            <GButton
              variant="ghost"
              label={t("common.retry")}
              onPress={() => onRetry(row.localId)}
              testID={`active-workout-retry-${row.localId}`}
            />
          </View>
        )
      ) : null}
    </View>
  );
}

function FinishSummaryView({
  summary,
  exercises,
  onDone,
}: {
  summary: WorkoutFinishResponse;
  exercises: ExerciseTarget[];
  onDone: () => void;
}) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const exerciseName = (exerciseId: string): string =>
    exercises.find((exercise) => exercise.exerciseId === exerciseId)?.name ?? exerciseId;

  return (
    <View style={styles.section} testID="active-workout-summary">
      <Text style={[textStyle("h1", locale), { color: theme.textPrimary }]}>
        {t("workout.active.summaryTitle")}
      </Text>
      <GCard testID="active-workout-summary-stats">
        <View style={styles.summaryRow}>
          <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
            {t("workout.active.summaryDuration")}
          </Text>
          <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
            {formatDuration(summary.session.duration_seconds ?? 0, t)}
          </Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
            {t("workout.active.summarySets")}
          </Text>
          <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
            {summary.session.set_count}
          </Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
            {t("workout.active.summaryVolume")}
          </Text>
          <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
            {summary.session.total_volume_kg ?? 0} {t("workout.active.weightUnit")}
          </Text>
        </View>
      </GCard>

      {summary.records_set.length > 0 ? (
        <View>
          <Text style={[textStyle("label", locale), styles.blockHeading, { color: theme.textSecondary }]}>
            {t("workout.active.summaryRecords")}
          </Text>
          <GCard testID="active-workout-summary-records">
            {summary.records_set.map((recordItem, index) => (
              <Text
                key={`${recordItem.exercise_id}-${index}`}
                style={[textStyle("body", locale), { color: theme.textPrimary }]}
              >
                {exerciseName(recordItem.exercise_id)} · {recordItem.value} {t("workout.active.weightUnit")}
              </Text>
            ))}
          </GCard>
        </View>
      ) : null}

      <GButton
        label={t("workout.active.summaryDone")}
        onPress={onDone}
        fullWidth
        testID="active-workout-summary-done"
      />
    </View>
  );
}

export default function ActiveWorkout() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const navigation = useNavigation();
  const queryClient = useQueryClient();

  const status = useActiveSessionStore((s) => s.status);
  const loadErrorCode = useActiveSessionStore((s) => s.loadErrorCode);
  const dayLabelKey = useActiveSessionStore((s) => s.dayLabelKey);
  const exercises = useActiveSessionStore((s) => s.exercises);
  const currentExerciseIndex = useActiveSessionStore((s) => s.currentExerciseIndex);
  const sets = useActiveSessionStore((s) => s.sets);
  const sessionTotals = useActiveSessionStore((s) => s.sessionTotals);
  const restEndsAt = useActiveSessionStore((s) => s.restEndsAt);
  const restPausedRemainingSeconds = useActiveSessionStore((s) => s.restPausedRemainingSeconds);
  const lastSetRecord = useActiveSessionStore((s) => s.lastSetRecord);
  const lastSetRecordNonce = useActiveSessionStore((s) => s.lastSetRecordNonce);
  const finishing = useActiveSessionStore((s) => s.finishing);
  const abandoning = useActiveSessionStore((s) => s.abandoning);

  const ensureFresh = useActiveSessionStore((s) => s.ensureFresh);
  const setCurrentExerciseIndex = useActiveSessionStore((s) => s.setCurrentExerciseIndex);
  const logSet = useActiveSessionStore((s) => s.logSet);
  const retrySet = useActiveSessionStore((s) => s.retrySet);
  const retryAllUnsent = useActiveSessionStore((s) => s.retryAllUnsent);
  const discardUnsent = useActiveSessionStore((s) => s.discardUnsent);
  const pauseRest = useActiveSessionStore((s) => s.pauseRest);
  const resumeRest = useActiveSessionStore((s) => s.resumeRest);
  const skipRest = useActiveSessionStore((s) => s.skipRest);
  const completeRest = useActiveSessionStore((s) => s.completeRest);
  const finish = useActiveSessionStore((s) => s.finish);
  const abandon = useActiveSessionStore((s) => s.abandon);
  const reset = useActiveSessionStore((s) => s.reset);

  const [logMoreEnabled, setLogMoreEnabled] = useState(false);
  const [repsValue, setRepsValue] = useState(8);
  const [weightValue, setWeightValue] = useState(0);
  const [rpeValue, setRpeValue] = useState(8);
  const [warmupValue, setWarmupValue] = useState(false);
  const [finishSummary, setFinishSummary] = useState<WorkoutFinishResponse | null>(null);
  const [actionErrorCode, setActionErrorCode] = useState<ResolvedErrorCode | null>(null);
  const [showRecordBanner, setShowRecordBanner] = useState(false);
  const [restResyncTick, forceRestResync] = useState(0);

  const allowExitRef = useRef(false);
  const exercisesAtFinishRef = useRef<ExerciseTarget[]>([]);
  // This screen is a persistent Tabs.Screen (see the file-level comment), so
  // its BackHandler subscription below stays registered even when the T-30
  // picker sheet is pushed on top of it -- without this, dismissing that sheet
  // with the hardware back button would trip *this* screen's leave-confirm
  // instead of closing the sheet. `useFocusEffect` is the only thing that
  // knows the difference; a ref rather than state because both guards read it
  // at event time, not render time.
  const focusedRef = useRef(false);

  // Not a plain mount effect: this screen is a persistent Tabs.Screen (see
  // the file-level comment), so `useFocusEffect` is what makes returning to
  // it -- for a second, unrelated session -- rehydrate instead of showing
  // whatever was left over from the last visit. `ensureFresh` itself still
  // no-ops when a session is already loaded, so refocusing mid-session
  // (backgrounding, a guarded nav bounce) costs nothing extra.
  useFocusEffect(
    useCallback(() => {
      focusedRef.current = true;
      void ensureFresh();
      return () => {
        focusedRef.current = false;
      };
    }, [ensureFresh]),
  );

  const currentExercise = exercises[currentExerciseIndex];

  // §8.3.2's pre-fill. Reads a fresh snapshot of `sets` directly from the
  // store rather than subscribing to it, so a set confirming or retrying in
  // the background never clobbers reps/weight the user is mid-typing for the
  // *next* set -- this only re-seeds when the current exercise itself changes.
  useEffect(() => {
    if (!currentExercise) return;
    const prefill = computePrefill(currentExercise, useActiveSessionStore.getState().sets);
    setRepsValue(prefill.reps);
    setWeightValue(prefill.weightKg);
  }, [currentExercise]);

  // Re-render on app-foreground so the rest timer's live `seconds` prop below
  // is recomputed from the canonical `restEndsAt` immediately, not after the
  // next 250ms tick (device check 6).
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (next) => {
      if (next === "active") forceRestResync((n) => n + 1);
    });
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (lastSetRecordNonce === 0 || lastSetRecord === null) return;
    setShowRecordBanner(true);
    AccessibilityInfo.announceForAccessibility(t("workout.active.recordAnnouncement"));
    const timeout = setTimeout(() => setShowRecordBanner(false), 4000);
    return () => clearTimeout(timeout);
  }, [lastSetRecordNonce, lastSetRecord, t]);

  const doFinish = useCallback(async () => {
    setActionErrorCode(null);
    try {
      exercisesAtFinishRef.current = useActiveSessionStore.getState().exercises;
      const response = await finish();
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setFinishSummary(response);
    } catch (err) {
      setActionErrorCode(resolveErrorCode(err));
    }
  }, [finish, queryClient]);

  const doAbandon = useCallback(async () => {
    setActionErrorCode(null);
    try {
      await abandon();
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      allowExitRef.current = true;
      reset();
      // This screen's own local state, not the store's -- see the file-level
      // comment on why a persistent Tabs.Screen needs this cleared explicitly.
      setFinishSummary(null);
      setActionErrorCode(null);
      router.replace("/(app)");
    } catch (err) {
      setActionErrorCode(resolveErrorCode(err));
    }
  }, [abandon, queryClient, reset]);

  const handleAbandonPress = useCallback(() => {
    Alert.alert(t("workout.active.abandonConfirmTitle"), t("workout.active.abandonConfirmBody"), [
      { text: t("common.cancel"), style: "cancel" },
      {
        text: t("workout.active.abandonConfirmAction"),
        style: "destructive",
        onPress: () => void doAbandon(),
      },
    ]);
  }, [t, doAbandon]);

  const handleFinishPress = useCallback(() => {
    if (hasUnsentSets(useActiveSessionStore.getState().sets)) {
      const unsentCount = useActiveSessionStore
        .getState()
        .sets.filter((row) => row.kind === "pending").length;
      Alert.alert(
        t("workout.active.unsentBlockTitle"),
        t("workout.active.unsentBlockBody", { count: unsentCount }),
        [
          { text: t("common.cancel"), style: "cancel" },
          { text: t("workout.active.retryAll"), onPress: () => void retryAllUnsent() },
          { text: t("workout.active.discardUnsent"), style: "destructive", onPress: discardUnsent },
        ],
      );
      return;
    }
    Alert.alert(t("workout.active.finishConfirmTitle"), t("workout.active.finishConfirmBody"), [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("workout.active.finishConfirmAction"), onPress: () => void doFinish() },
    ]);
  }, [t, retryAllUnsent, discardUnsent, doFinish]);

  const showLeaveConfirm = useCallback(() => {
    Alert.alert(t("workout.active.backConfirmTitle"), t("workout.active.backConfirmBody"), [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("workout.active.finish"), onPress: handleFinishPress },
      { text: t("workout.active.abandon"), style: "destructive", onPress: handleAbandonPress },
    ]);
  }, [t, handleFinishPress, handleAbandonPress]);

  const guardActive = status === "ready" && finishSummary === null;

  // §8.3.6: back and the tab bar are blocked while a session is in progress.
  // `beforeRemove` covers the iOS swipe-back gesture, the header chevron's
  // router.back(), and the tab bar's own screen switch; BackHandler is the
  // belt-and-suspenders Android hardware-button path React Navigation's own
  // event doesn't always preempt. `allowExitRef` is the escape hatch this
  // screen's own Finish/Abandon/Done handlers set right before they navigate
  // away themselves, so they don't trip their own guard.
  useEffect(() => {
    const unsubscribe = navigation.addListener("beforeRemove", (e) => {
      if (allowExitRef.current || !guardActive || !focusedRef.current) return;
      e.preventDefault();
      showLeaveConfirm();
    });
    return unsubscribe;
  }, [navigation, guardActive, showLeaveConfirm]);

  useEffect(() => {
    const subscription = BackHandler.addEventListener("hardwareBackPress", () => {
      if (allowExitRef.current || !guardActive || !focusedRef.current) return false;
      showLeaveConfirm();
      return true;
    });
    return () => subscription.remove();
  }, [guardActive, showLeaveConfirm]);

  const handleSummaryDone = useCallback(() => {
    allowExitRef.current = true;
    reset();
    setFinishSummary(null);
    setActionErrorCode(null);
    router.replace("/(app)");
  }, [reset]);

  const handleLogSet = useCallback(() => {
    void logSet({
      reps: repsValue,
      weightKg: weightValue,
      rpe: logMoreEnabled ? rpeValue : null,
      isWarmup: logMoreEnabled ? warmupValue : false,
    });
    // Warm-up is a per-set choice; it must not silently carry onto the next one.
    setWarmupValue(false);
  }, [logSet, repsValue, weightValue, logMoreEnabled, rpeValue, warmupValue]);

  // Deliberately memoized, not computed inline: `Date.now()` would otherwise
  // produce a "new" value on every render of this screen -- including ones
  // caused by unrelated state, like typing in the reps field -- which would
  // hand GRestTimer a changed `seconds` prop and force a spurious reseed on
  // every keystroke. This only recomputes when one of the three things that
  // should actually reseed the timer happens: the rest period itself moves,
  // a pause/resume toggle fires, or the app-foreground resync tick bumps.
  const restRemainingSeconds = useMemo(
    () =>
      restPausedRemainingSeconds !== null
        ? restPausedRemainingSeconds
        : computeRemainingSeconds(restEndsAt, Date.now()),
    [restEndsAt, restPausedRemainingSeconds, restResyncTick],
  );
  const restIsPaused = restPausedRemainingSeconds !== null;

  const headerTitle = finishSummary
    ? t("workout.active.summaryTitle")
    : dayLabelKey
      ? t(dayLabelKey)
      : t("workout.active.title");

  // Fixed footer, outside the scroll area -- Finish/Abandon must stay
  // reachable without scrolling past a long set list.
  const footerContent =
    status === "ready" && !finishSummary ? (
      <View style={styles.footerActions}>
        <GButton
          label={t("workout.active.finish")}
          onPress={handleFinishPress}
          loading={finishing}
          disabled={abandoning}
          fullWidth
          testID="active-workout-finish"
        />
        <GButton
          variant="secondary"
          label={t("workout.active.abandon")}
          onPress={handleAbandonPress}
          loading={abandoning}
          disabled={finishing}
          fullWidth
          testID="active-workout-abandon"
        />
      </View>
    ) : undefined;

  return (
    <GScreen
      scroll={false}
      header={{
        title: headerTitle,
        onBack: finishSummary ? handleSummaryDone : guardActive ? showLeaveConfirm : () => router.back(),
      }}
      footer={footerContent}
      testID="active-workout-screen"
    >
      {actionErrorCode ? (
        <GErrorBanner
          testID="active-workout-action-error"
          code={actionErrorCode}
          onDismiss={() => setActionErrorCode(null)}
        />
      ) : null}

      {status === "loading" || status === "idle" ? <ActiveWorkoutSkeleton /> : null}

      {status === "noSession" ? <NoActiveSessionView /> : null}

      {status === "error" ? (
        <GErrorBanner
          testID="active-workout-load-error"
          code={loadErrorCode ?? "GENERIC"}
          onRetry={() => void ensureFresh()}
        />
      ) : null}

      {status === "ready" && finishSummary ? (
        <FinishSummaryView
          summary={finishSummary}
          exercises={exercisesAtFinishRef.current}
          onDone={handleSummaryDone}
        />
      ) : null}

      {status === "ready" && !finishSummary ? (
        <View style={styles.readyContainer}>
          {/* Only §8.3.1's own list -- exercise, target, rest time, last
              performance -- plus the §8.3.4 live rest timer ("visible from
              anywhere on the screen") stay outside the scroll. A first live
              pass on a six-exercise day surfaced why nothing else can: with
              the chip switcher, totals, and the full log form also pinned,
              their combined natural height exceeded the space left above
              the fixed footer on a real device, and Android silently clips
              a plain View's overflow -- Log Set and the disclosure toggle
              were rendered nowhere, not even off-screen, un-tappable and
              absent from the accessibility tree alike. Bounding pinned to
              only these two blocks caps its height independent of exercise
              count or name length, so that can't recur. */}
          <View style={styles.pinned}>
            {currentExercise ? (
              <GCard testID="active-workout-current-exercise">
                <Text style={[textStyle("h2", locale), { color: theme.textPrimary }]}>
                  {currentExercise.name}
                </Text>
                {currentExercise.targetSets !== null &&
                currentExercise.targetRepsMin !== null &&
                currentExercise.targetRepsMax !== null ? (
                  <Text style={[textStyle("body", locale), styles.targetLine, { color: theme.textSecondary }]}>
                    {t("plan.dayDetail.target", {
                      sets: currentExercise.targetSets,
                      min: currentExercise.targetRepsMin,
                      max: currentExercise.targetRepsMax,
                      seconds: currentExercise.restSeconds,
                    })}
                  </Text>
                ) : null}
                {currentExercise.lastPerformance ? (
                  <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
                    {t("plan.dayDetail.lastPerformanceLabel")}:{" "}
                    {t("plan.dayDetail.lastPerformanceValue", {
                      reps: currentExercise.lastPerformance.reps,
                      weight: currentExercise.lastPerformance.weightKg,
                    })}
                  </Text>
                ) : null}
              </GCard>
            ) : (
              <Text style={[textStyle("body", locale), { color: theme.textSecondary }]}>
                {t("workout.active.emptyExercises")}
              </Text>
            )}

            {restEndsAt !== null ? (
              <View style={styles.restRow}>
                <GRestTimer
                  seconds={restRemainingSeconds}
                  paused={restIsPaused}
                  onComplete={completeRest}
                  onSkip={skipRest}
                  testID="active-workout-rest-timer"
                />
                <GButton
                  variant="ghost"
                  label={t(restIsPaused ? "workout.active.restTimer.resume" : "workout.active.restTimer.pause")}
                  onPress={restIsPaused ? resumeRest : pauseRest}
                  testID="active-workout-rest-pause-toggle"
                />
              </View>
            ) : null}
          </View>

          <ScrollView
            style={styles.scrollable}
            contentContainerStyle={styles.scrollableContent}
            keyboardShouldPersistTaps="handled"
          >
            {/* T-30 gap 1: the picker's entry point, as the last chip in the
                switcher rather than a button of its own. Always present, not
                only when the day prescribed nothing -- §5.7 lets any exercise
                be logged into any session, and swapping a prescribed machine
                for whatever is free is the ordinary case in a real gym, not an
                edge case. A chip because a full-width button here cost a whole
                row of vertical space: once the rest timer is showing, §8.3.1's
                pinned block already pushes the log form to the edge of the
                fold, and a device pass at 130% font (check 15) is exactly where
                one extra row stops fitting. That is also why the row now
                renders for any exercise count instead of only `> 1`. */}
            <View style={styles.chipsRow} testID="active-workout-exercise-switcher">
              {exercises.map((exercise, index) => (
                <GChip
                  key={exercise.exerciseId}
                  label={exercise.name}
                  selected={index === currentExerciseIndex}
                  onPress={() => setCurrentExerciseIndex(index)}
                  testID={`active-workout-exercise-chip-${index}`}
                />
              ))}
              <GChip
                label={t("workout.active.addExercise")}
                selected={false}
                onPress={() => router.push("/(app)/exercises?picker=1")}
                testID="active-workout-add-exercise"
              />
            </View>

            {sessionTotals ? (
              <Text style={[textStyle("label", locale), { color: theme.textSecondary }]} testID="active-workout-totals">
                {sessionTotals.sets} · {sessionTotals.volumeKg} {t("workout.active.weightUnit")}
              </Text>
            ) : null}

            {showRecordBanner ? (
              <View style={[styles.recordBanner, { backgroundColor: theme.successBg }]} accessibilityRole="alert">
                <Text style={[textStyle("bodyStrong", locale), { color: theme.success }]}>
                  {t("workout.active.recordAnnouncement")}
                </Text>
              </View>
            ) : null}

            {currentExercise ? (
              <View style={styles.logForm}>
                <View style={styles.logFormRow}>
                  <View style={styles.logFormField}>
                    <GNumberField
                      label={t("workout.active.repsLabel")}
                      value={repsValue}
                      onChange={setRepsValue}
                      step={1}
                      min={1}
                      max={100}
                      unit=""
                      precision={0}
                      testID="active-workout-reps"
                    />
                  </View>
                  <View style={styles.logFormField}>
                    <GNumberField
                      label={t("workout.active.weightLabel")}
                      value={weightValue}
                      onChange={setWeightValue}
                      step={2.5}
                      min={0}
                      max={500}
                      unit={t("workout.active.weightUnit")}
                      precision={1}
                      testID="active-workout-weight"
                    />
                  </View>
                </View>

                {logMoreEnabled ? (
                  <View style={styles.logFormRow}>
                    <View style={styles.logFormField}>
                      <GNumberField
                        label={t("workout.active.rpeLabel")}
                        value={rpeValue}
                        onChange={setRpeValue}
                        step={0.5}
                        min={5}
                        max={10}
                        unit=""
                        precision={1}
                        testID="active-workout-rpe"
                      />
                    </View>
                    <View style={styles.logFormField}>
                      <GChip
                        label={t("workout.active.warmupLabel")}
                        selected={warmupValue}
                        onPress={() => setWarmupValue((value) => !value)}
                        testID="active-workout-warmup-toggle"
                      />
                    </View>
                  </View>
                ) : null}

                <GButton
                  label={t("workout.active.logSet")}
                  onPress={handleLogSet}
                  fullWidth
                  testID="active-workout-log-set"
                />

                <GButton
                  variant="ghost"
                  label={t(logMoreEnabled ? "workout.active.hideMore" : "workout.active.showMore")}
                  onPress={() => setLogMoreEnabled((value) => !value)}
                  testID="active-workout-disclosure-toggle"
                />
              </View>
            ) : null}

            {currentExercise ? (
              <>
                <Text style={[textStyle("label", locale), styles.blockHeading, { color: theme.textSecondary }]}>
                  {t("workout.active.setsHeading")}
                </Text>
                {sets
                  .filter((row) => row.exerciseId === currentExercise.exerciseId)
                  .map((row, index) => (
                    <SetRow
                      key={row.localId}
                      row={row}
                      index={index}
                      locale={locale}
                      theme={theme}
                      t={t}
                      onRetry={(localId) => void retrySet(localId)}
                    />
                  ))}
              </>
            ) : null}

            <Text style={[textStyle("caption", locale), styles.disclaimer, { color: theme.textMuted }]}>
              {t("common.medicalDisclaimer")}
            </Text>
          </ScrollView>
        </View>
      ) : null}
    </GScreen>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: space[4],
  },
  centeredSection: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: space[4],
    paddingHorizontal: space[6],
  },
  readyContainer: {
    flex: 1,
  },
  // GScreen's own `scroll={false}` wrapper already applies `screenPadding`
  // horizontally and vertical padding around `readyContainer` as a whole --
  // adding it again here would double-inset the content.
  pinned: {
    gap: space[3],
  },
  scrollable: {
    flex: 1,
  },
  scrollableContent: {
    paddingTop: space[3],
    gap: space[3],
  },
  chipsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space[2],
  },
  targetLine: {
    marginTop: space[1],
  },
  restRow: {
    alignItems: "center",
    gap: space[1],
  },
  logForm: {
    gap: space[2],
  },
  logFormRow: {
    flexDirection: "row",
    gap: space[2],
  },
  logFormField: {
    flex: 1,
    justifyContent: "flex-end",
  },
  blockHeading: {
    marginBottom: space[1],
  },
  setRow: {
    minHeight: space[8],
    justifyContent: "center",
    gap: space[0],
  },
  setRowLabel: {
    flexShrink: 1,
  },
  unsentRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space[2],
  },
  recordBanner: {
    borderRadius: radius.sm,
    padding: space[2],
    alignItems: "center",
  },
  summaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
  disclaimer: {
    textAlign: "center",
    marginTop: space[2],
  },
  footerActions: {
    gap: space[2],
    marginTop: space[2],
  },
});
