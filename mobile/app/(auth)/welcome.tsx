/**
 * §9.3 screen 1 — welcome. Logo on the sand background, one line of
 * positioning copy, Create account (primary) / Log in (secondary), a
 * divider, the Google social button (Facebook deferred to Phase 2, 13.1.2),
 * and a language toggle in the corner. Built only from T-11 primitives.
 */
import { useState } from "react";
import { Alert, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { router } from "expo-router";

import { socialSignIn } from "../../src/api/auth";
import { resolveErrorCode, type ResolvedErrorCode } from "../../src/api/errors";
import {
  SocialSignInCancelledError,
  SocialSignInMisconfiguredError,
  SocialSignInUnavailableError,
  signInWithGoogle,
} from "../../src/auth/firebase";
import { useSessionStore } from "../../src/auth/session";
import { GButton, GErrorBanner, GLogo, GScreen } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { space } from "../../src/theme/tokens";

export default function Welcome() {
  const theme = useTheme();
  const { t, locale, setLocale } = useI18n();
  const { width } = useWindowDimensions();
  const logoSize = Math.min(140, width * 0.38);
  const [socialLoading, setSocialLoading] = useState(false);
  const [error, setError] = useState<ResolvedErrorCode | null>(null);

  const handleToggleLanguage = () => {
    setLocale(locale === "ar" ? "en" : "ar");
    Alert.alert(t("auth.language.reloadTitle"), t("auth.language.reloadMessage"), [
      { text: t("auth.language.ok") },
    ]);
  };

  const handleGoogleSignIn = async () => {
    setError(null);
    setSocialLoading(true);
    try {
      const idToken = await signInWithGoogle();
      const result = await socialSignIn("google", idToken);
      await useSessionStore.getState().setTokens(result.access_token, result.refresh_token);
      await useSessionStore.getState().hydrate();
      router.replace("/");
    } catch (err) {
      if (err instanceof SocialSignInCancelledError) {
        // User backed out of the picker — §9.4 has no error state for this.
      } else if (err instanceof SocialSignInMisconfiguredError) {
        setError("SOCIAL_SIGN_IN_MISCONFIGURED");
      } else if (err instanceof SocialSignInUnavailableError) {
        setError("UPSTREAM_UNAVAILABLE");
      } else {
        setError(resolveErrorCode(err));
      }
    } finally {
      setSocialLoading(false);
    }
  };

  return (
    <GScreen>
      <View style={styles.languageRow}>
        <GButton
          variant="ghost"
          label={t("auth.language.switchTo")}
          accessibilityLabel={t("common.languageToggleLabel")}
          onPress={handleToggleLanguage}
        />
      </View>

      <View style={styles.hero}>
        <GLogo size={logoSize} />
        <Text
          style={[textStyle("body", locale), styles.tagline, { color: theme.textSecondary }]}
        >
          {t("auth.welcome.tagline")}
        </Text>
      </View>

      {error ? (
        <GErrorBanner code={error} onDismiss={() => setError(null)} testID="welcome-error" />
      ) : null}

      <View style={styles.actions}>
        <GButton
          label={t("auth.welcome.createAccount")}
          variant="primary"
          fullWidth
          onPress={() => router.push("/(auth)/register")}
          testID="welcome-create-account"
        />
        <GButton
          label={t("auth.welcome.logIn")}
          variant="secondary"
          fullWidth
          onPress={() => router.push("/(auth)/login")}
          testID="welcome-log-in"
        />

        <View style={styles.dividerRow}>
          <View style={[styles.dividerLine, { backgroundColor: theme.divider }]} />
          <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
            {t("auth.welcome.or")}
          </Text>
          <View style={[styles.dividerLine, { backgroundColor: theme.divider }]} />
        </View>

        <GButton
          label={t("auth.social.continueWithGoogle")}
          variant="social"
          fullWidth
          loading={socialLoading}
          onPress={handleGoogleSignIn}
          testID="welcome-google"
        />
      </View>
    </GScreen>
  );
}

const styles = StyleSheet.create({
  languageRow: {
    flexDirection: "row",
    justifyContent: "flex-end",
  },
  hero: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  tagline: {
    textAlign: "center",
    marginTop: space[3],
    paddingHorizontal: space[4],
  },
  actions: {
    gap: space[3],
    marginBottom: space[4],
  },
  dividerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space[3],
    marginVertical: space[1],
  },
  dividerLine: {
    flex: 1,
    height: 1,
  },
});
