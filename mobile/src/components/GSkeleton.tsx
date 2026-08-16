/**
 * §9.2 GSkeleton — `width`/`height`/`radius?`. `skeleton` token, a subtle
 * opacity pulse that honours `prefers-reduced-motion` (§10.6): the loop
 * never starts — the block just sits static — when the OS reports reduced
 * motion, checked on mount and re-checked on every OS-level change.
 * Decorative only, so it is hidden from screen readers rather than
 * announced as an unlabelled block.
 */
import { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated } from "react-native";

import { useTheme } from "../theme/useTheme";
import { motion, radius as radiusScale } from "../theme/tokens";

export interface GSkeletonProps {
  width: number | `${number}%`;
  height: number | `${number}%`;
  radius?: number;
  testID?: string;
}

export function GSkeleton({ width, height, radius = radiusScale.sm, testID }: GSkeletonProps) {
  const theme = useTheme();
  const opacity = useRef(new Animated.Value(1)).current;
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      if (mounted) setReduceMotion(enabled);
    });
    const subscription = AccessibilityInfo.addEventListener("reduceMotionChanged", setReduceMotion);
    return () => {
      mounted = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (reduceMotion) {
      opacity.setValue(1);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.5, duration: motion.slow, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 1, duration: motion.slow, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [reduceMotion, opacity]);

  return (
    <Animated.View
      testID={testID}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{
        width,
        height,
        borderRadius: radius,
        backgroundColor: theme.skeleton,
        opacity,
      }}
    />
  );
}
