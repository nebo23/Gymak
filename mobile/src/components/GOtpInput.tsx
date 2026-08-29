/**
 * §10.5 GOtpInput — P1-ADR-07: 8 alphanumeric boxes, uppercase on entry,
 * `autoCapitalize="characters"`, auto-advance, backspace to the previous box,
 * paste distributes across boxes, characters outside the §7.1 alphabet are
 * silently dropped, auto-submit fires on the eighth character, and the whole
 * thing stays LTR even under a forced-RTL (Arabic) layout.
 *
 * Implementation note: rather than juggling focus across 8 real `TextInput`s
 * (which is where most RN OTP-input paste bugs come from — native `maxLength`
 * truncates a multi-character paste before `onChangeText` ever sees it), a
 * single hidden `TextInput` holds the real value and 8 `View`s render it.
 * Paste, backspace-to-previous and auto-advance all fall out of that for
 * free: they are just different lengths of one string.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  AccessibilityInfo,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { minTouchTarget, radius, space } from "../theme/tokens";

// §7.1 / P1-ADR-07: RFC 4648 Base32 minus the visually ambiguous `I` and `O`.
export const OTP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ234567";
export const OTP_LENGTH = 8;

export interface GOtpInputHandle {
  clear: () => void;
  focus: () => void;
}

export interface GOtpInputProps {
  value: string;
  onChange: (value: string) => void;
  onComplete?: (value: string) => void;
  error?: boolean;
  disabled?: boolean;
  accessibilityLabel?: string;
  testID?: string;
}

function sanitize(raw: string): string {
  return raw
    .toUpperCase()
    .split("")
    .filter((ch) => OTP_ALPHABET.includes(ch))
    .slice(0, OTP_LENGTH)
    .join("");
}

export const GOtpInput = forwardRef<GOtpInputHandle, GOtpInputProps>(function GOtpInput(
  { value, onChange, onComplete, error = false, disabled = false, accessibilityLabel, testID },
  ref,
) {
  const theme = useTheme();
  const { t } = useI18n();
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<TextInput>(null);
  const announcedCompleteFor = useRef<string | null>(null);

  useImperativeHandle(ref, () => ({
    clear: () => onChange(""),
    focus: () => inputRef.current?.focus(),
  }));

  const handleChangeText = (raw: string) => {
    const next = sanitize(raw);
    onChange(next);
    if (next.length === OTP_LENGTH && announcedCompleteFor.current !== next) {
      announcedCompleteFor.current = next;
      inputRef.current?.blur();
      onComplete?.(next);
    }
  };

  useEffect(() => {
    if (value.length < OTP_LENGTH) {
      announcedCompleteFor.current = null;
    }
  }, [value]);

  useEffect(() => {
    if (error) {
      AccessibilityInfo.announceForAccessibility(t("components.otp.invalid"));
    }
  }, [error, t]);

  const boxes = Array.from({ length: OTP_LENGTH }, (_, i) => value[i] ?? "");
  const activeIndex = Math.min(value.length, OTP_LENGTH - 1);

  return (
    <Pressable
      testID={testID}
      onPress={() => inputRef.current?.focus()}
      style={styles.wrapper}
      accessible={false}
    >
      <TextInput
        ref={inputRef}
        value={value}
        onChangeText={handleChangeText}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        // Deliberately not `maxLength={OTP_LENGTH}`: native maxLength
        // truncates the raw pasted string *before* onChangeText fires, which
        // would cut off valid trailing characters from a code pasted with
        // separators (e.g. "K7M2-QXR4"). `sanitize()` filters to the §7.1
        // alphabet and then takes the first 8 — this generous cap only
        // guards against pasting something absurdly long.
        maxLength={64}
        autoCapitalize="characters"
        autoCorrect={false}
        spellCheck={false}
        editable={!disabled}
        style={styles.hiddenInput}
        accessibilityLabel={accessibilityLabel ?? t("components.otp.label")}
        accessibilityValue={{
          text: t("components.otp.progress", {
            // The noun agrees with the TOTAL ("3 of 8 characters"), not with
            // how many are typed -- so the typed count must not be named
            // `count`, or `i18n-js` would inflect the sentence on the wrong
            // number. Arabic makes the difference audible: 8 takes «أحرف».
            entered: value.length,
            total: t("units.character", { count: OTP_LENGTH }),
          }),
        }}
        accessibilityState={{ disabled }}
      />
      <View
        style={styles.row}
        importantForAccessibility="no-hide-descendants"
        accessibilityElementsHidden
      >
        {boxes.map((char, index) => {
          const isActive = focused && index === activeIndex && !disabled;
          const borderColor = error ? theme.error : isActive ? theme.primary : theme.border;
          return (
            <View
              key={index}
              style={[
                styles.box,
                {
                  backgroundColor: disabled ? theme.surfaceVariant : theme.input,
                  borderColor,
                  borderWidth: isActive || error ? 2 : 1,
                },
              ]}
            >
              <Text
                style={[
                  textStyle("h2", "en"),
                  styles.boxText,
                  { color: disabled ? theme.textDisabled : theme.textPrimary },
                ]}
              >
                {char}
              </Text>
            </View>
          );
        })}
      </View>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  // Forces LTR (and therefore left-to-right box order and caret motion) even
  // when the surrounding app is mirrored for Arabic — §9.6 and §10.5 both
  // require the OTP boxes to never flip. `minHeight` keeps the whole
  // component — the real touch target, since the boxes below are decorative
  // — at the §10.6 floor even though 8 individually-48dp boxes would not fit
  // most phone widths.
  wrapper: {
    direction: "ltr",
    minHeight: minTouchTarget,
    justifyContent: "center",
  },
  hiddenInput: {
    position: "absolute",
    opacity: 0,
    width: "100%",
    height: "100%",
  },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
  box: {
    width: space[6],
    height: space[7],
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  boxText: {
    writingDirection: "ltr",
  },
});
