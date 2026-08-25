/**
 * §9.2 GListRow — `title`/`subtitle?`/`trailing?`/`onPress?`. The history
 * and entry-list primitive. Min height 56, which is the row's real height
 * floor — `minHeight`, not `height`, so a wrapped title/subtitle at large
 * font scale grows the row instead of clipping it.
 */
import type { ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { minTouchTarget, space } from "../theme/tokens";

export interface GListRowProps {
  title: string;
  subtitle?: string;
  trailing?: ReactNode;
  onPress?: () => void;
  accessibilityLabel?: string;
  testID?: string;
}

export function GListRow({
  title,
  subtitle,
  trailing,
  onPress,
  accessibilityLabel,
  testID,
}: GListRowProps) {
  const theme = useTheme();
  const { locale } = useI18n();

  const content = (
    <View style={styles.row}>
      <View style={styles.text}>
        <Text
          style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}
          numberOfLines={1}
        >
          {title}
        </Text>
        {subtitle ? (
          <Text
            style={[textStyle("caption", locale), styles.subtitle, { color: theme.textSecondary }]}
            numberOfLines={1}
          >
            {subtitle}
          </Text>
        ) : null}
      </View>
      {trailing ? <View style={styles.trailing}>{trailing}</View> : null}
    </View>
  );

  if (onPress) {
    return (
      <Pressable
        testID={testID}
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel ?? title}
        style={({ pressed }) => [
          styles.container,
          pressed ? { backgroundColor: theme.surfaceVariant } : null,
        ]}
      >
        {content}
      </Pressable>
    );
  }

  return (
    <View testID={testID} style={styles.container}>
      {content}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    // 48dp touch target plus one gutter -- same 56 as before, now derived.
    minHeight: minTouchTarget + space[1],
    justifyContent: "center",
    paddingHorizontal: space[3],
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
  },
  text: {
    flex: 1,
  },
  subtitle: {
    marginTop: space[0],
  },
  trailing: {
    marginStart: space[2],
  },
});
