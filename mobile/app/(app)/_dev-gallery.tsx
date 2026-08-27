/**
 * T-11 dev-only component gallery. Every §10.5 primitive, in every state,
 * so states can be reviewed side by side instead of hunting through real
 * screens for each one.
 *
 * DEV ONLY: renders nothing and redirects away outside `__DEV__`, so this
 * screen cannot be reached in a production build even though its filename
 * makes it routable (expo-router does not exclude "_"-prefixed files from
 * routing — only the exact name "_layout" is special-cased).
 */
import { type ReactNode, useState } from "react";
import { Redirect } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import {
  GButton,
  GCard,
  GChip,
  GEmptyState,
  GErrorBanner,
  GIcon,
  GLineChart,
  GListRow,
  GLogo,
  GNumberField,
  GOtpInput,
  GProgressBar,
  GRestTimer,
  GScreen,
  GSelectCard,
  GSheet,
  GDialog,
  GSkeleton,
  GStat,
  GTextInput,
  type GIconName,
  type GIconSize,
} from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { radius, space } from "../../src/theme/tokens";

// Every glyph in the set, so one screenshot proves the stroke weight, the
// corner treatment and the optical mass are actually shared rather than
// per-icon. The size ramp row exists to show the SUB-LINEAR stroke: xl is 3x
// sm's box but nowhere near 3x its stroke.
const ICON_NAMES: readonly GIconName[] = [
  "home",
  "plan",
  "progress",
  "settings",
  "chevron",
  "chevronBack",
  "eye",
  "eyeOff",
  "minus",
  "plus",
  "check",
  "search",
  "close",
];

const ICON_SIZES: readonly GIconSize[] = ["sm", "md", "lg", "xl"];

function noop() {
  // Gallery buttons demonstrate visual state only; nothing to do on press.
}

// A deliberate 3-day gap (Jan 4-6) so the gallery's own chart proves the
// same "gaps are gaps" rule (§9.3) real data gets on the progress screen.
const CHART_SAMPLE_RAW = [
  { measured_on: "2026-01-01", weight_kg: 82.0 },
  { measured_on: "2026-01-02", weight_kg: 81.6 },
  { measured_on: "2026-01-03", weight_kg: 81.8 },
  { measured_on: "2026-01-07", weight_kg: 80.9 },
  { measured_on: "2026-01-08", weight_kg: 80.5 },
  { measured_on: "2026-01-09", weight_kg: 80.7 },
  { measured_on: "2026-01-10", weight_kg: 80.2 },
];
const CHART_SAMPLE_AVERAGE = [
  { measured_on: "2026-01-03", weight_kg: 81.8 },
  { measured_on: "2026-01-08", weight_kg: 80.7 },
  { measured_on: "2026-01-09", weight_kg: 80.6 },
  { measured_on: "2026-01-10", weight_kg: 80.5 },
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  const theme = useTheme();
  const { locale } = useI18n();
  return (
    <View style={styles.section}>
      <Text style={[textStyle("h3", locale), { color: theme.textPrimary }]}>{title}</Text>
      <View style={styles.sectionBody}>{children}</View>
    </View>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  const theme = useTheme();
  const { locale } = useI18n();
  return (
    <View style={styles.row}>
      <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>{label}</Text>
      <View style={styles.rowBody}>{children}</View>
    </View>
  );
}

export default function DevGallery() {
  const theme = useTheme();
  const { t, locale } = useI18n();

  const [emailValue, setEmailValue] = useState("");
  const [filledValue, setFilledValue] = useState("hello@example.com");
  const [passwordValue, setPasswordValue] = useState("correct-horse");

  const [otpIdle, setOtpIdle] = useState("");
  const [otpError, setOtpError] = useState("K7M2QXR4");
  const [otpDisabled] = useState("ABCD");

  const [selectedCard, setSelectedCard] = useState<"a" | "b">("a");

  const [bannerDismissed, setBannerDismissed] = useState(false);

  const [chipSelected, setChipSelected] = useState<"chest" | "barbell" | "legs">("chest");
  const [repsValue, setRepsValue] = useState(8);
  const [weightValue, setWeightValue] = useState(60);
  const [sheetOpen, setSheetOpen] = useState(false);
  // Every GDialog state the contract names, so all four can be eyeballed in
  // both themes and both languages without navigating the real screens.
  const [dialogDemo, setDialogDemo] = useState<
    "one" | "two" | "destructive" | "long" | null
  >(null);

  if (!__DEV__) {
    return <Redirect href="/(app)" />;
  }

  return (
    <GScreen header={{ title: t("devGallery.title") }}>
      <View style={[styles.badge, { backgroundColor: theme.warningBg }]}>
        <Text style={[textStyle("label", locale), { color: theme.warningText }]}>
          {t("devGallery.badge")}
        </Text>
      </View>

      <Section title={t("devGallery.sections.icon")}>
        <Row label={t("devGallery.icon.set")}>
          <View style={styles.iconGrid}>
            {ICON_NAMES.map((name) => (
              <GIcon key={name} name={name} color={theme.textPrimary} />
            ))}
          </View>
        </Row>
        <Row label={t("devGallery.icon.scale")}>
          <View style={styles.iconGrid}>
            {ICON_SIZES.map((size) => (
              <GIcon key={size} name="settings" size={size} color={theme.textPrimary} />
            ))}
          </View>
        </Row>
      </Section>

      <Section title={t("devGallery.sections.button")}>
        <Row label={t("devGallery.state.idle")}>
          <View style={styles.buttonRow}>
            <GButton label={t("devGallery.sample.buttonPrimary")} variant="primary" onPress={noop} />
            <GButton
              label={t("devGallery.sample.buttonSecondary")}
              variant="secondary"
              onPress={noop}
            />
            <GButton label={t("devGallery.sample.buttonGhost")} variant="ghost" onPress={noop} />
            <GButton label={t("devGallery.sample.buttonSocial")} variant="social" onPress={noop} />
          </View>
        </Row>
        <Row label={t("devGallery.state.loading")}>
          <GButton label={t("devGallery.sample.buttonPrimary")} loading onPress={noop} />
        </Row>
        <Row label={t("devGallery.state.disabled")}>
          <GButton label={t("devGallery.sample.buttonPrimary")} disabled onPress={noop} />
        </Row>
        <Row label={t("devGallery.state.fullWidth")}>
          <GButton label={t("devGallery.sample.buttonPrimary")} fullWidth onPress={noop} />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.textInput")}>
        <Row label={t("devGallery.state.idle")}>
          <GTextInput
            label={t("devGallery.sample.textInputLabel")}
            placeholder={t("devGallery.sample.textInputPlaceholder")}
            value={emailValue}
            onChangeText={setEmailValue}
            keyboardType="email-address"
            autoComplete="email"
          />
        </Row>
        <Row label={t("devGallery.state.filled")}>
          <GTextInput
            label={t("devGallery.sample.textInputLabel")}
            value={filledValue}
            onChangeText={setFilledValue}
          />
        </Row>
        <Row label={t("devGallery.state.secure")}>
          <GTextInput
            label={t("devGallery.sample.passwordLabel")}
            value={passwordValue}
            onChangeText={setPasswordValue}
            secure
            autoComplete="password"
          />
        </Row>
        <Row label={t("devGallery.state.error")}>
          <GTextInput
            label={t("devGallery.sample.textInputLabel")}
            value="not-an-email"
            onChangeText={noop}
            error={t("devGallery.sample.textInputError")}
          />
        </Row>
        <Row label={t("devGallery.state.disabled")}>
          <GTextInput
            label={t("devGallery.sample.textInputLabel")}
            value={t("devGallery.sample.textInputPlaceholder")}
            onChangeText={noop}
            disabled
          />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.otp")}>
        <Row label={t("devGallery.state.idle")}>
          <GOtpInput value={otpIdle} onChange={setOtpIdle} />
        </Row>
        <Row label={t("devGallery.state.error")}>
          <GOtpInput value={otpError} onChange={setOtpError} error />
        </Row>
        <Row label={t("devGallery.state.disabled")}>
          <GOtpInput value={otpDisabled} onChange={noop} disabled />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.selectCard")}>
        <Row label={t("devGallery.state.selected")}>
          <GSelectCard
            title={t("devGallery.sample.selectCardATitle")}
            description={t("devGallery.sample.selectCardADescription")}
            selected={selectedCard === "a"}
            onPress={() => setSelectedCard("a")}
          />
        </Row>
        <Row label={t("devGallery.state.unselected")}>
          <GSelectCard
            title={t("devGallery.sample.selectCardBTitle")}
            selected={selectedCard === "b"}
            onPress={() => setSelectedCard("b")}
          />
        </Row>
        <Row label={t("devGallery.state.disabled")}>
          <GSelectCard
            title={t("devGallery.sample.selectCardCTitle")}
            selected={false}
            onPress={noop}
            disabled
            disabledReason={t("devGallery.sample.selectCardDisabledReason")}
          />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.progressBar")}>
        <Row label={t("components.progressBar.stepLabel", { step: 2, total: 6 })}>
          <GProgressBar step={2} total={6} />
        </Row>
        <Row label={t("components.progressBar.stepLabel", { step: 5, total: 6 })}>
          <GProgressBar step={5} total={6} />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.errorBanner")}>
        <Row label={t("devGallery.state.withRetry")}>
          <GErrorBanner code="GENERIC" onRetry={noop} />
        </Row>
        <Row label={t("devGallery.state.dismissible")}>
          {bannerDismissed ? (
            <GButton
              label={t("devGallery.state.dismissible")}
              variant="ghost"
              onPress={() => setBannerDismissed(false)}
            />
          ) : (
            <GErrorBanner code="OFFLINE" onDismiss={() => setBannerDismissed(true)} />
          )}
        </Row>
        <Row label={t("devGallery.state.messageOnly")}>
          <GErrorBanner
            message={t("auth.rateLimited.retryIn", { count: 30 })}
            testID="dev-gallery-error-message-only"
          />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.logo")}>
        <View style={styles.buttonRow}>
          <GLogo size={space[8]} />
          <GLogo size={space[8] * 2} />
        </View>
      </Section>

      <Section title={t("devGallery.sections.card")}>
        <Row label={t("devGallery.state.idle")}>
          <GCard
            title={t("devGallery.sample.cardTitle")}
            subtitle={t("devGallery.sample.cardSubtitle")}
            footer={
              <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
                {t("devGallery.sample.cardFooter")}
              </Text>
            }
          />
        </Row>
        <Row label={t("devGallery.state.pressable")}>
          <GCard
            title={t("devGallery.sample.cardTitle")}
            subtitle={t("devGallery.sample.cardSubtitle")}
            onPress={noop}
            testID="dev-gallery-card-pressable"
          />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.stat")}>
        <Row label={t("devGallery.state.positive")}>
          <GStat
            label={t("devGallery.sample.statLabel")}
            value={t("devGallery.sample.statValue")}
            unit={t("devGallery.sample.statUnit")}
            delta={2}
            tone="positive"
          />
        </Row>
        <Row label={t("devGallery.state.negative")}>
          <GStat
            label={t("devGallery.sample.statLabel")}
            value={t("devGallery.sample.statValue")}
            unit={t("devGallery.sample.statUnit")}
            delta={-1}
            tone="negative"
          />
        </Row>
        <Row label={t("devGallery.state.neutral")}>
          <GStat
            label={t("devGallery.sample.statLabel")}
            value={t("devGallery.sample.statValue")}
            unit={t("devGallery.sample.statUnit")}
            tone="neutral"
          />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.chip")}>
        <Row label={t("devGallery.state.selected")}>
          <View style={styles.buttonRow}>
            <GChip
              label={t("devGallery.sample.chipChest")}
              selected={chipSelected === "chest"}
              onPress={() => setChipSelected("chest")}
            />
            <GChip
              label={t("devGallery.sample.chipBarbell")}
              selected={chipSelected === "barbell"}
              onPress={() => setChipSelected("barbell")}
            />
          </View>
        </Row>
        <Row label={t("devGallery.state.unselected")}>
          <GChip
            label={t("devGallery.sample.chipLegs")}
            selected={chipSelected === "legs"}
            onPress={() => setChipSelected("legs")}
          />
        </Row>
        <Row label={t("devGallery.state.disabled")}>
          <GChip label={t("devGallery.sample.chipLegs")} selected={false} onPress={noop} disabled />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.emptyState")}>
        <Row label={t("devGallery.state.withAction")}>
          <GEmptyState
            titleKey="devGallery.sample.emptyStateTitle"
            bodyKey="devGallery.sample.emptyStateBody"
            actionLabelKey="devGallery.sample.emptyStateAction"
            onAction={noop}
          />
        </Row>
        <Row label={t("devGallery.state.withoutAction")}>
          <GEmptyState
            titleKey="devGallery.sample.emptyStateTitle"
            bodyKey="devGallery.sample.emptyStateBody"
          />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.skeleton")}>
        <Row label={t("devGallery.sample.skeletonTextLine")}>
          <GSkeleton width={160} height={16} />
        </Row>
        <Row label={t("devGallery.sample.skeletonCard")}>
          <GSkeleton width={240} height={96} radius={radius.lg} />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.listRow")}>
        <Row label={t("devGallery.state.withSubtitle")}>
          <GListRow
            title={t("devGallery.sample.listRowTitle")}
            subtitle={t("devGallery.sample.listRowSubtitle")}
            trailing={
              <Text style={[textStyle("bodyStrong", locale), { color: theme.textPrimary }]}>
                {t("devGallery.sample.listRowTrailing")}
              </Text>
            }
          />
        </Row>
        <Row label={t("devGallery.state.pressable")}>
          <GListRow title={t("devGallery.sample.listRowTitle")} onPress={noop} />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.numberField")}>
        <Row label={t("devGallery.sample.numberFieldReps")}>
          <GNumberField
            label={t("devGallery.sample.numberFieldReps")}
            value={repsValue}
            onChange={setRepsValue}
            step={1}
            min={0}
            max={50}
            unit=""
            precision={0}
            testID="dev-gallery-number-field-reps"
          />
        </Row>
        <Row label={t("devGallery.sample.numberFieldWeight")}>
          <GNumberField
            label={t("devGallery.sample.numberFieldWeight")}
            value={weightValue}
            onChange={setWeightValue}
            step={2.5}
            min={0}
            max={300}
            unit={t("devGallery.sample.unitKg")}
            precision={1}
            testID="dev-gallery-number-field-weight"
          />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.restTimer")}>
        <Row label={t("devGallery.state.running")}>
          <GRestTimer
            seconds={90}
            paused={false}
            onComplete={noop}
            onSkip={noop}
            testID="dev-gallery-rest-timer-running"
          />
        </Row>
        <Row label={t("devGallery.state.paused")}>
          <GRestTimer
            seconds={45}
            paused
            onComplete={noop}
            onSkip={noop}
            testID="dev-gallery-rest-timer-paused"
          />
        </Row>
      </Section>

      <Section title={t("devGallery.sections.sheet")}>
        <Row label={sheetOpen ? t("devGallery.state.open") : t("devGallery.state.closed")}>
          <GButton
            label={t("devGallery.sample.openSheet")}
            variant="secondary"
            onPress={() => setSheetOpen(true)}
            testID="dev-gallery-sheet-open"
          />
        </Row>
      </Section>
      <GSheet visible={sheetOpen} onClose={() => setSheetOpen(false)} testID="dev-gallery-sheet">
        <Text style={[textStyle("body", locale), { color: theme.textPrimary }]}>
          {t("devGallery.sample.sheetBody")}
        </Text>
        <GButton
          label={t("common.dismiss")}
          variant="ghost"
          onPress={() => setSheetOpen(false)}
          testID="dev-gallery-sheet-close"
        />
      </GSheet>

      <Section title={t("devGallery.sections.dialog")}>
        <View style={styles.buttonRow}>
          <GButton
            label={t("devGallery.sample.openDialogOne")}
            variant="secondary"
            onPress={() => setDialogDemo("one")}
            testID="dev-gallery-dialog-one"
          />
          <GButton
            label={t("devGallery.sample.openDialogTwo")}
            variant="secondary"
            onPress={() => setDialogDemo("two")}
            testID="dev-gallery-dialog-two"
          />
          <GButton
            label={t("devGallery.sample.openDialogDestructive")}
            variant="secondary"
            onPress={() => setDialogDemo("destructive")}
            testID="dev-gallery-dialog-destructive"
          />
          <GButton
            label={t("devGallery.sample.openDialogLong")}
            variant="secondary"
            onPress={() => setDialogDemo("long")}
            testID="dev-gallery-dialog-long"
          />
        </View>
      </Section>

      {/* One action. */}
      <GDialog
        visible={dialogDemo === "one"}
        onClose={() => setDialogDemo(null)}
        titleKey="devGallery.sample.dialogTitle"
        bodyKey="devGallery.sample.dialogBody"
        actions={[
          {
            labelKey: "auth.language.ok",
            variant: "primary",
            onPress: () => setDialogDemo(null),
          },
        ]}
        testID="dev-gallery-dialog-one-panel"
      />

      {/* Two actions: cancel + primary. */}
      <GDialog
        visible={dialogDemo === "two"}
        onClose={() => setDialogDemo(null)}
        titleKey="devGallery.sample.dialogTitle"
        bodyKey="devGallery.sample.dialogBody"
        actions={[
          { labelKey: "common.cancel", onPress: () => setDialogDemo(null) },
          {
            labelKey: "devGallery.sample.dialogConfirm",
            variant: "primary",
            onPress: () => setDialogDemo(null),
          },
        ]}
        testID="dev-gallery-dialog-two-panel"
      />

      {/* Destructive: `error` token, and never the focused action. */}
      <GDialog
        visible={dialogDemo === "destructive"}
        onClose={() => setDialogDemo(null)}
        titleKey="devGallery.sample.dialogDestructiveTitle"
        bodyKey="devGallery.sample.dialogDestructiveBody"
        actions={[
          { labelKey: "common.cancel", onPress: () => setDialogDemo(null) },
          {
            labelKey: "devGallery.sample.dialogDestructiveAction",
            variant: "destructive",
            onPress: () => setDialogDemo(null),
          },
        ]}
        testID="dev-gallery-dialog-destructive-panel"
      />

      {/* Long labels: both wrap, so the row must stack instead of clipping. */}
      <GDialog
        visible={dialogDemo === "long"}
        onClose={() => setDialogDemo(null)}
        titleKey="devGallery.sample.dialogTitle"
        bodyKey="devGallery.sample.dialogBody"
        actions={[
          {
            labelKey: "devGallery.sample.dialogLongLabelA",
            onPress: () => setDialogDemo(null),
          },
          {
            labelKey: "devGallery.sample.dialogLongLabelB",
            variant: "primary",
            onPress: () => setDialogDemo(null),
          },
        ]}
        testID="dev-gallery-dialog-long-panel"
      />

      <Section title={t("devGallery.sections.lineChart")}>
        <GLineChart
          series={[
            { data: CHART_SAMPLE_AVERAGE, color: theme.chart1, strokeWidth: 3 },
            { data: CHART_SAMPLE_RAW, color: theme.chart3, strokeWidth: 2, showDots: true },
          ]}
          xAccessor={(point) => point.measured_on}
          yAccessor={(point) => point.weight_kg}
          range={{ start: "2026-01-01", end: "2026-01-10" }}
          accessibilityLabel={t("devGallery.sample.lineChartAccessibilityLabel")}
          testID="dev-gallery-line-chart"
        />
      </Section>
    </GScreen>
  );
}

const styles = StyleSheet.create({
  iconGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: space[3],
  },
  badge: {
    borderRadius: radius.sm,
    padding: space[2],
    marginBottom: space[4],
  },
  section: {
    marginBottom: space[5],
  },
  sectionBody: {
    marginTop: space[2],
  },
  row: {
    marginBottom: space[3],
  },
  rowBody: {
    marginTop: space[1],
  },
  buttonRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space[2],
    alignItems: "center",
  },
});
