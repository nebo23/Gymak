/**
 * GSectionHeader — the heading that introduces one group of rows, and the
 * hairline that separates that group from the one before it.
 *
 * This is hierarchy rule 2 made reusable: real hierarchy comes from UNEQUAL
 * space. There is a lot of air above a heading (`layout.sectionGap`) and very
 * little between it and the rows it introduces (`layout.headingGap`), so the
 * heading reads as belonging to what follows rather than floating between two
 * groups. Every screen that used `marginTop: space[5] / marginBottom: space[1]`
 * by hand now gets the same ratio from one place.
 *
 * `divider` draws the rule BETWEEN groups — pass `false` on the first group of
 * a screen, where there is no previous group to separate from. Note this is a
 * rule between GROUPS, never between every row: a line under all seventeen
 * rows is the wall the redesign is removing, not a fix for it.
 */
import { StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { layout } from "../theme/tokens";

export interface GSectionHeaderProps {
  title: string;
  /** A hairline above the heading. Omit (`false`) for the first group. */
  divider?: boolean;
  testID?: string;
}

export function GSectionHeader({ title, divider = true, testID }: GSectionHeaderProps) {
  const theme = useTheme();
  const { locale } = useI18n();

  return (
    <View testID={testID}>
      {divider ? (
        <View style={[styles.rule, { backgroundColor: theme.divider }]} />
      ) : null}
      <Text
        style={[
          textStyle("label", locale),
          styles.title,
          { color: theme.textMuted, marginTop: divider ? layout.headingGap : 0 },
        ]}
        // A group heading names the group; `header` is what puts it in
        // TalkBack's heading navigation instead of reading it as loose text.
        accessibilityRole="header"
      >
        {title}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  rule: {
    height: StyleSheet.hairlineWidth,
    marginTop: layout.sectionGap,
  },
  title: {
    marginBottom: layout.headingGap,
    // Tracking opens the label up so it reads as a category marker rather than
    // as a short line of body text. One step only -- more turns into a logo.
    letterSpacing: 0.6,
  },
});
