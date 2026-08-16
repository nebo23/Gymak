/**
 * §9.2 GNumberField — `value`/`onChange`/`step`/`min`/`max`/`unit`/
 * `precision`. Stepper buttons ≥ 48 dp flank a tap-to-type field
 * (`keyboardType="decimal-pad"`, §8.3.3) rather than swapping between a
 * "display" and an "edit" mode: the `TextInput` is always mounted, so a
 * re-render can never remount it out from under the user's focus. External
 * changes to `value` (a stepper tap, a parent re-seeding the field) only
 * overwrite the typed text while the field is *not* focused — mid-edit, the
 * user's own keystrokes are the source of truth until they blur.
 */
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { controlHeight, minTouchTarget, radius, space } from "../theme/tokens";

export interface GNumberFieldProps {
  value: number;
  onChange: (value: number) => void;
  step: number;
  min: number;
  max: number;
  unit: string;
  precision: number;
  label?: string;
  accessibilityLabel?: string;
  testID?: string;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function format(value: number, precision: number): string {
  return value.toFixed(precision);
}

export function GNumberField({
  value,
  onChange,
  step,
  min,
  max,
  unit,
  precision,
  label,
  accessibilityLabel,
  testID,
}: GNumberFieldProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const [focused, setFocused] = useState(false);
  const [text, setText] = useState(() => format(value, precision));

  useEffect(() => {
    if (!focused) setText(format(value, precision));
  }, [value, precision, focused]);

  const commit = (next: number) => onChange(clamp(next, min, max));

  const handleStep = (direction: 1 | -1) => {
    commit(Number((value + direction * step).toFixed(precision)));
  };

  const handleChangeText = (raw: string) => {
    setText(raw);
    const parsed = Number.parseFloat(raw);
    if (Number.isFinite(parsed)) commit(parsed);
  };

  const handleBlur = () => {
    setFocused(false);
    setText(format(value, precision));
  };

  const decrementDisabled = value <= min;
  const incrementDisabled = value >= max;

  return (
    <View testID={testID}>
      {label ? (
        <Text style={[textStyle("label", locale), styles.label, { color: theme.textSecondary }]}>
          {label}
        </Text>
      ) : null}
      <View
        style={[
          styles.field,
          {
            backgroundColor: theme.input,
            borderColor: focused ? theme.primary : theme.border,
            borderWidth: focused ? 2 : 1,
          },
        ]}
      >
        <Pressable
          onPress={decrementDisabled ? undefined : () => handleStep(-1)}
          disabled={decrementDisabled}
          accessibilityRole="button"
          accessibilityLabel={t("components.numberField.decrement")}
          accessibilityState={{ disabled: decrementDisabled }}
          style={styles.stepper}
          hitSlop={stepperHitSlop}
        >
          <View
            style={[
              styles.minusGlyph,
              { backgroundColor: decrementDisabled ? theme.textDisabled : theme.primary },
            ]}
          />
        </Pressable>

        <View style={styles.valueWrap}>
          <TextInput
            testID={testID ? `${testID}-input` : undefined}
            style={[textStyle("stat", locale), styles.input, { color: theme.textPrimary }]}
            value={text}
            onChangeText={handleChangeText}
            onFocus={() => setFocused(true)}
            onBlur={handleBlur}
            keyboardType="decimal-pad"
            textAlign="center"
            accessibilityLabel={accessibilityLabel ?? label}
            accessibilityValue={{ min, max, now: value, text: `${format(value, precision)} ${unit}` }}
          />
          {unit ? (
            <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>{unit}</Text>
          ) : null}
        </View>

        <Pressable
          onPress={incrementDisabled ? undefined : () => handleStep(1)}
          disabled={incrementDisabled}
          accessibilityRole="button"
          accessibilityLabel={t("components.numberField.increment")}
          accessibilityState={{ disabled: incrementDisabled }}
          style={styles.stepper}
          hitSlop={stepperHitSlop}
        >
          <View style={styles.plusGlyph}>
            <View
              style={[
                styles.minusGlyph,
                { backgroundColor: incrementDisabled ? theme.textDisabled : theme.primary },
              ]}
            />
            <View
              style={[
                styles.plusGlyphVertical,
                { backgroundColor: incrementDisabled ? theme.textDisabled : theme.primary },
              ]}
            />
          </View>
        </Pressable>
      </View>
    </View>
  );
}

const stepperHitSlop = { top: 0, bottom: 0, start: space[1], end: space[1] };

const styles = StyleSheet.create({
  label: {
    marginBottom: space[1],
  },
  field: {
    minHeight: controlHeight,
    borderRadius: radius.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  stepper: {
    minWidth: minTouchTarget,
    minHeight: minTouchTarget,
    alignItems: "center",
    justifyContent: "center",
  },
  valueWrap: {
    flex: 1,
    alignItems: "center",
  },
  input: {
    minWidth: space[8],
    textAlign: "center",
    padding: 0,
  },
  minusGlyph: {
    width: 14,
    height: 2,
    borderRadius: 1,
  },
  plusGlyph: {
    width: 14,
    height: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  plusGlyphVertical: {
    position: "absolute",
    width: 2,
    height: 14,
    borderRadius: 1,
  },
});
