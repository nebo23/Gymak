/**
 * §10.5 GTextInput — label, error, secure (with a reveal toggle), keyboardType,
 * autoComplete. Focus ring in rust (theme.primary); error state uses
 * theme.error with the message below, and the message is announced (not
 * colour-only), per §10.6.
 */
import { useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type KeyboardTypeOptions,
  type TextInputProps,
} from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { controlHeight, minTouchTarget, radius, space } from "../theme/tokens";

export interface GTextInputProps {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  error?: string;
  secure?: boolean;
  keyboardType?: KeyboardTypeOptions;
  autoComplete?: TextInputProps["autoComplete"];
  placeholder?: string;
  disabled?: boolean;
  accessibilityLabel?: string;
  testID?: string;
}

export function GTextInput({
  label,
  value,
  onChangeText,
  error,
  secure = false,
  keyboardType = "default",
  autoComplete,
  placeholder,
  disabled = false,
  accessibilityLabel,
  testID,
}: GTextInputProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const [focused, setFocused] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    if (error) {
      AccessibilityInfo.announceForAccessibility(error);
    }
  }, [error]);

  const borderColor = error ? theme.error : focused ? theme.primary : theme.border;

  return (
    <View style={styles.container}>
      <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>{label}</Text>
      <View
        style={[
          styles.field,
          {
            backgroundColor: disabled ? theme.surfaceVariant : theme.input,
            borderColor,
            borderWidth: focused || error ? 2 : 1,
          },
        ]}
      >
        <TextInput
          ref={inputRef}
          testID={testID}
          style={[
            textStyle("body", locale),
            styles.input,
            { color: disabled ? theme.textDisabled : theme.textPrimary },
          ]}
          value={value}
          onChangeText={onChangeText}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          secureTextEntry={secure && !revealed}
          keyboardType={keyboardType}
          autoComplete={autoComplete}
          editable={!disabled}
          placeholder={placeholder}
          placeholderTextColor={theme.textMuted}
          accessibilityLabel={accessibilityLabel ?? label}
          accessibilityState={{ disabled }}
        />
        {secure ? (
          <Pressable
            onPress={() => setRevealed((prev) => !prev)}
            hitSlop={toggleHitSlop}
            accessibilityRole="button"
            accessibilityLabel={
              revealed
                ? t("components.textInput.hidePassword")
                : t("components.textInput.showPassword")
            }
            style={styles.toggle}
          >
            <Text style={[textStyle("label", locale), { color: theme.textLink }]}>
              {revealed
                ? t("components.textInput.hidePassword")
                : t("components.textInput.showPassword")}
            </Text>
          </Pressable>
        ) : null}
      </View>
      {error ? (
        <Text
          style={[textStyle("caption", locale), styles.error, { color: theme.error }]}
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
        >
          {error}
        </Text>
      ) : null}
    </View>
  );
}

// The reveal toggle's text is shorter than `minTouchTarget`; hit-slop
// brings its effective touch area up to the §10.6 floor.
const toggleTextHeight = 20;
const toggleHitSlopPad = Math.max(0, (minTouchTarget - toggleTextHeight) / 2);
// `hitSlop`'s Insets type is physical (left/right), not logical — it has no
// start/end variant, so this is not a §9.6 layout-direction violation.
const toggleHitSlop = {
  top: toggleHitSlopPad,
  bottom: toggleHitSlopPad,
  left: toggleHitSlopPad,
  right: toggleHitSlopPad,
};

const styles = StyleSheet.create({
  container: {
    width: "100%",
  },
  field: {
    marginTop: space[1],
    minHeight: controlHeight,
    borderRadius: radius.md,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: space[3],
  },
  input: {
    flex: 1,
    paddingVertical: space[2],
  },
  toggle: {
    minHeight: minTouchTarget,
    justifyContent: "center",
    paddingStart: space[2],
  },
  error: {
    marginTop: space[1],
  },
});
