/**
 * GSettingRow — one settings entry drawn the way the platform draws it: the
 * label, the CURRENT VALUE, and a disclosure chevron. Tapping opens the
 * choices; the choices themselves do not exist until then.
 *
 * WHY THIS EXISTS
 * Settings rendered roughly seventeen `GSelectCard`s at once — every option of
 * every setting on screen simultaneously, each the same size, weight and
 * distance from its neighbours. Nothing could be more important than anything
 * else because everything was drawn identically. This is Material's "show the
 * setting's status instead of describing the setting" and Android's "secondary
 * text should only show the current status of a setting", which is also the
 * only layout that scales: a fifth activity level costs a line inside a sheet,
 * not another card on the screen.
 *
 * NOT FOR THE ACTIVE-WORKOUT SCREEN. §8.3.2 puts logging a set at most two taps
 * from resting, so nothing there may go behind a disclosure. That screen's
 * density is a requirement, not an oversight.
 *
 * The row deliberately has no card, border or shadow: a settings screen is a
 * LIST, and its rows are not discrete objects. Grouping comes from
 * `GSectionHeader` above it and from space around it.
 */
import { Pressable, StyleSheet, Text, View } from "react-native";

import { GIcon } from "./GIcon";
import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { minTouchTarget, space } from "../theme/tokens";

export interface GSettingRowProps {
  label: string;
  /** The setting's CURRENT VALUE — already translated. Not a description of it. */
  value?: string;
  onPress: () => void;
  disabled?: boolean;
  accessibilityLabel?: string;
  testID?: string;
}

export function GSettingRow({
  label,
  value,
  onPress,
  disabled = false,
  accessibilityLabel,
  testID,
}: GSettingRowProps) {
  const theme = useTheme();
  const { locale } = useI18n();

  return (
    <Pressable
      testID={testID}
      onPress={disabled ? undefined : onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      // The value rides as `accessibilityValue`, not glued into the label, so
      // TalkBack reads "Goal, Gain muscle, button" and re-announces only the
      // part that changed when it changes.
      accessibilityValue={value !== undefined ? { text: value } : undefined}
      accessibilityState={{ disabled }}
      style={({ pressed }) => [
        styles.row,
        pressed && !disabled ? { backgroundColor: theme.surfaceVariant } : null,
      ]}
    >
      <Text
        style={[
          textStyle("body", locale),
          styles.label,
          { color: disabled ? theme.textDisabled : theme.textPrimary },
        ]}
        numberOfLines={1}
      >
        {label}
      </Text>
      {/* `alignItems: "flex-end"` inside a `flexDirection: "row"` resolves to
          the END side, which RN flips itself under RTL. RN's `textAlign` has no
          "end", so aligning the Text directly would need a left/right literal
          and break §9.6. */}
      <View style={styles.valueWrap}>
        {value !== undefined ? (
          <Text
            style={[
              textStyle("body", locale),
              { color: disabled ? theme.textDisabled : theme.textSecondary },
            ]}
            numberOfLines={1}
          >
            {value}
          </Text>
        ) : null}
      </View>
      <View style={styles.chevron}>
        <GIcon name="chevron" size="sm" color={disabled ? theme.textDisabled : theme.textMuted} />
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    // 48dp touch target plus one gutter -- the same floor GListRow derives.
    minHeight: minTouchTarget + space[1],
    flexDirection: "row",
    alignItems: "center",
    // The row's TEXT aligns with the screen's content column, while its
    // pressed highlight bleeds one step past it on both sides -- so the
    // highlight reads as a row being touched rather than as a box inset
    // inside the column. `marginHorizontal` is side-neutral, so no §9.6
    // start/end concern.
    paddingHorizontal: space[1],
    marginHorizontal: -space[1],
    gap: space[2],
  },
  label: {
    flexShrink: 1,
  },
  valueWrap: {
    flex: 1,
    alignItems: "flex-end",
  },
  chevron: {
    // Optical alignment: the chevron's drawn stroke sits inside its 16dp box,
    // so it needs to hang slightly past the text's own edge to look aligned
    // with it rather than inset from it.
    marginEnd: -space[0] / 2,
  },
});
