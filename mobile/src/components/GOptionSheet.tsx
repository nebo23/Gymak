/**
 * GOptionSheet — the choices behind a `GSettingRow`, in a `GSheet`.
 *
 * The whole point of the settings restructure is that a setting's options do
 * not occupy the screen when nobody is choosing. `GSheet` renders through RN's
 * `Modal`, which mounts nothing while `visible` is false, so the options here
 * genuinely only exist while the sheet is open — this is not a hidden `View`
 * with `display: none`.
 *
 * `GSelectCard` is reused unchanged inside the sheet: §10.5's selected
 * treatment (rust border plus `primaryContainer` fill, never a small radio
 * dot) is exactly right for a set of choices. It was never wrong as a
 * component — it was wrong as seventeen simultaneous ones on a settings screen.
 */
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { GSelectCard } from "./GSelectCard";
import { GSheet } from "./GSheet";
import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { layout, space } from "../theme/tokens";

export interface GOptionSheetOption<T extends string> {
  value: T;
  /** Already translated. */
  label: string;
  description?: string;
  disabled?: boolean;
  /** Shown on a disabled option so the reason is never left to be guessed. */
  disabledReason?: string;
}

export interface GOptionSheetProps<T extends string> {
  visible: boolean;
  /** The setting's name, already translated — the sheet's own heading. */
  title: string;
  options: readonly GOptionSheetOption<T>[];
  selected: T | null;
  onSelect: (value: T) => void;
  onClose: () => void;
  testID?: string;
}

export function GOptionSheet<T extends string>({
  visible,
  title,
  options,
  selected,
  onSelect,
  onClose,
  testID,
}: GOptionSheetProps<T>) {
  const theme = useTheme();
  const { locale } = useI18n();

  return (
    <GSheet visible={visible} onClose={onClose} testID={testID}>
      <Text
        style={[textStyle("h3", locale), styles.title, { color: theme.textPrimary }]}
        accessibilityRole="header"
      >
        {title}
      </Text>
      {/* The five activity levels at the 130% font scale of device check 15
          are taller than the sheet's own 85% cap, so the list scrolls rather
          than clipping its last option. */}
      <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
        {options.map((option) => (
          <GSelectCard
            key={option.value}
            title={option.label}
            description={option.description}
            selected={selected === option.value}
            disabled={option.disabled}
            disabledReason={option.disabledReason}
            // Choosing closes the sheet: a one-of-N choice is complete the
            // moment it is made, so a confirm button would be a second tap
            // that decides nothing.
            onPress={() => {
              onSelect(option.value);
              onClose();
            }}
            testID={testID ? `${testID}-${option.value}` : undefined}
          />
        ))}
      </ScrollView>
      <View style={styles.bottomInset} />
    </GSheet>
  );
}

const styles = StyleSheet.create({
  title: {
    marginBottom: layout.groupGap,
    paddingHorizontal: space[1],
  },
  list: {
    flexGrow: 0,
  },
  listContent: {
    gap: layout.rowGap,
  },
  bottomInset: {
    height: space[1],
  },
});
