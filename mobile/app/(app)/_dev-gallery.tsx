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
  GErrorBanner,
  GLogo,
  GOtpInput,
  GProgressBar,
  GScreen,
  GSelectCard,
  GTextInput,
} from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { radius, space } from "../../src/theme/tokens";

function noop() {
  // Gallery buttons demonstrate visual state only; nothing to do on press.
}

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

  if (!__DEV__) {
    return <Redirect href="/(app)/home" />;
  }

  return (
    <GScreen header={{ title: t("devGallery.title") }}>
      <View style={[styles.badge, { backgroundColor: theme.warningBg }]}>
        <Text style={[textStyle("label", locale), { color: theme.warningText }]}>
          {t("devGallery.badge")}
        </Text>
      </View>

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
            message={t("auth.rateLimited.retryIn", { seconds: 30 })}
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
    </GScreen>
  );
}

const styles = StyleSheet.create({
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
