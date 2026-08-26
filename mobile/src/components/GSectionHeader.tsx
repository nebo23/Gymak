/**
 * GSectionHeader — the heading that introduces one group, and the space (and
 * optionally the rule) that separates that group from the one before it.
 *
 * This is hierarchy rule 2 made reusable: real hierarchy comes from UNEQUAL
 * space. There is a lot of air above a heading (`layout.sectionGap`) and very
 * little between it and the rows it introduces (`layout.headingGap`) — a 4:1
 * ratio — so the heading reads as belonging to what follows rather than
 * floating between two groups. Every screen that hand-rolled
 * `marginTop: space[5] / marginBottom: space[1]` now gets that ratio from one
 * place, which is the only way it stays consistent.
 *
 * `separation` says how this group relates to what precedes it:
 *
 *   "first"   the first group on a screen. No space above, no rule — there is
 *             nothing above it to separate from.
 *   "spaced"  a new group, separated by space alone. The dashboard's headings
 *             use this: the screen is already a stack of cards, and adding
 *             hairlines between them would be one more line competing with the
 *             card edges.
 *   "ruled"   a new group with a hairline above it. Settings uses this, where
 *             rows sit on the bare ground and the rule is what tells one group
 *             from the next.
 *
 * Note "ruled" draws a line between GROUPS, never between every row. A line
 * under all seventeen rows is the wall this redesign removes, not a fix for it.
 *
 * The rule uses `border`, not `divider`. `divider` is 1.14:1 on `bg` in light
 * and 1.58:1 in dark -- below WCAG 1.4.11's 3:1 for a UI boundary. `border` is
 * 3.06:1 and 3.84:1 and passes. The grouping is carried redundantly by the
 * heading and the spacing either way, but a line that is meant to be seen
 * should actually be visible.
 */
import { StyleSheet, Text, View } from "react-native";

import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { layout } from "../theme/tokens";

export type GSectionSeparation = "first" | "spaced" | "ruled";

export interface GSectionHeaderProps {
  title: string;
  separation?: GSectionSeparation;
  testID?: string;
}

export function GSectionHeader({ title, separation = "ruled", testID }: GSectionHeaderProps) {
  const theme = useTheme();
  const { locale } = useI18n();

  return (
    <View
      testID={testID}
      style={separation === "first" ? undefined : styles.separated}
    >
      {separation === "ruled" ? (
        <View style={[styles.rule, { backgroundColor: theme.border }]} />
      ) : null}
      <Text
        style={[
          textStyle("label", locale),
          styles.title,
          { color: theme.textMuted, marginTop: separation === "ruled" ? layout.headingGap : 0 },
        ]}
        // A group heading names the group; `header` is what puts it into
        // TalkBack's heading navigation instead of reading it as loose text.
        accessibilityRole="header"
      >
        {title}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  separated: {
    marginTop: layout.sectionGap,
  },
  rule: {
    height: StyleSheet.hairlineWidth,
  },
  title: {
    marginBottom: layout.headingGap,
    // Tracking opens the label up so it reads as a category marker rather than
    // as a short line of body text. One step only -- more turns into a logo.
    letterSpacing: 0.6,
  },
});
