/**
 * §9.2 GRestTimer — `seconds`, `onComplete`, `onSkip`, `paused`. Wall-clock
 * based (§8.3.4): `seconds` seeds an internal end-of-rest timestamp the
 * moment it (or `paused`) changes, and a 250ms interval only ever re-derives
 * the displayed value from `Date.now()` against that timestamp — it never
 * decrements a counter itself, so a backgrounded/suspended JS timer cannot
 * leave the display frozen or wrong when it resumes (device check 6).
 *
 * The canonical timestamp this seeds from lives one level up, in
 * activeSession.ts's `restEndsAt` (§8.3.7: "never only in a component") — the
 * screen recomputes `seconds` fresh from that store on every render that
 * matters (a new rest period, a pause/resume toggle, an app-foreground
 * resync), and a `key` change forces this component to re-seed rather than
 * silently drift. Completion is announced once to screen readers here, since
 * §9.2 lists that as this component's own responsibility. No haptic:
 * expo-haptics is not an installed dependency (checked node_modules; Phase 2
 * Appendix A.2 does not add it), and §9.2 lists it as optional.
 */
import { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { minTouchTarget, space } from "../theme/tokens";
import { GButton } from "./GButton";

export interface GRestTimerProps {
  seconds: number;
  onComplete: () => void;
  onSkip: () => void;
  paused: boolean;
  testID?: string;
}

const TICK_MS = 250;

function formatMmSs(totalSeconds: number): string {
  const clamped = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(clamped / 60);
  const seconds = clamped % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function GRestTimer({ seconds, onComplete, onSkip, paused, testID }: GRestTimerProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const [remaining, setRemaining] = useState(Math.max(0, Math.round(seconds)));

  // Re-seeds and restarts the tick loop whenever the parent hands down a
  // fresh `seconds`/`paused` pair — a new rest period, a pause/resume
  // toggle, or an app-foreground resync. One effect, not two, so there is
  // never a stale interval left running against a since-replaced anchor.
  useEffect(() => {
    const anchorEndsAt = Date.now() + seconds * 1000;
    const initialRemaining = Math.max(0, Math.round(seconds));
    setRemaining(initialRemaining);

    let completed = false;
    const fireComplete = () => {
      completed = true;
      AccessibilityInfo.announceForAccessibility(t("workout.active.restTimer.complete"));
      onComplete();
    };

    // Already elapsed the moment this (re)seeds -- e.g. the rest period was
    // shorter than however long the app sat backgrounded. Still announce
    // completion once rather than silently sitting at zero forever.
    if (initialRemaining <= 0) {
      fireComplete();
      return;
    }
    if (paused) return;

    const interval = setInterval(() => {
      const next = Math.max(0, Math.round((anchorEndsAt - Date.now()) / 1000));
      setRemaining(next);
      if (next <= 0 && !completed) fireComplete();
    }, TICK_MS);
    return () => clearInterval(interval);
  }, [seconds, paused, onComplete, t]);

  return (
    <View testID={testID} style={styles.container}>
      <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
        {t("workout.active.restTimer.label")}
      </Text>
      <Text
        style={[textStyle("stat", locale), styles.time, { color: theme.textPrimary }]}
        accessibilityLabel={t("workout.active.restTimer.accessibilityValue", { count: remaining })}
      >
        {formatMmSs(remaining)}
      </Text>
      <GButton
        variant="ghost"
        label={t("workout.active.restTimer.skip")}
        onPress={onSkip}
        testID={testID ? `${testID}-skip` : undefined}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    gap: space[1],
    minHeight: minTouchTarget,
  },
  time: {
    letterSpacing: 0,
  },
});
