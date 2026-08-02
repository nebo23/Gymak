/**
 * §9.3 screen 5 — verify code. P1-ADR-07's 8-character alphanumeric code:
 * `GOtpInput` already owns uppercasing, ambiguous-character rejection on
 * paste, auto-advance and auto-submit on the eighth character (§10.5/A-04).
 * This screen adds the visible countdown that gates the resend button, and
 * a manual "Verify" affordance alongside auto-submit for anyone who lands
 * here without it firing (e.g. TalkBack, §11.2 check 14).
 *
 * The countdown is a client-side resend cooldown (60s, a UX choice — §6.4
 * caps requests per hour but names no minimum spacing), not the server's
 * 10-minute code TTL, which this screen never learns (`forgot`'s 202 body
 * carries no expiry).
 */
import { useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";

import { forgotPassword, verifyResetCode } from "../../src/api/auth";
import { parseApiError, type ResolvedErrorCode } from "../../src/api/errors";
import {
  GButton,
  GErrorBanner,
  GOtpInput,
  GScreen,
  type GOtpInputHandle,
} from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { radius, space } from "../../src/theme/tokens";

const RESEND_COOLDOWN_SECONDS = 60;

export default function VerifyCode() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const { email } = useLocalSearchParams<{ email: string }>();
  const otpRef = useRef<GOtpInputHandle>(null);

  const [code, setCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [resending, setResending] = useState(false);
  const [requestError, setRequestError] = useState<ResolvedErrorCode | null>(null);
  const [retrySeconds, setRetrySeconds] = useState<number | null>(null);
  const [resendCooldown, setResendCooldown] = useState(RESEND_COOLDOWN_SECONDS);
  const [resendNotice, setResendNotice] = useState(false);

  useEffect(() => {
    if (retrySeconds === null || retrySeconds <= 0) return;
    const id = setTimeout(() => setRetrySeconds((s) => (s ?? 1) - 1), 1000);
    return () => clearTimeout(id);
  }, [retrySeconds]);

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const id = setTimeout(() => setResendCooldown((s) => s - 1), 1000);
    return () => clearTimeout(id);
  }, [resendCooldown]);

  useEffect(() => {
    if (!resendNotice) return;
    const id = setTimeout(() => setResendNotice(false), 4000);
    return () => clearTimeout(id);
  }, [resendNotice]);

  const handleVerify = async (candidate: string) => {
    if (verifying || candidate.length < 8) return;
    setRequestError(null);
    setRetrySeconds(null);
    setResendNotice(false);
    setVerifying(true);
    try {
      const { reset_token: resetToken } = await verifyResetCode(email, candidate);
      router.push({ pathname: "/(auth)/new-password", params: { resetToken, email } });
    } catch (err) {
      const problem = parseApiError(err);
      if (problem.retryAfterSeconds) {
        setRetrySeconds(problem.retryAfterSeconds);
      } else {
        setRequestError(problem.code);
      }
      setCode("");
      otpRef.current?.focus();
    } finally {
      setVerifying(false);
    }
  };

  const handleResend = async () => {
    if (resendCooldown > 0 || resending) return;
    setRequestError(null);
    setRetrySeconds(null);
    setResending(true);
    try {
      await forgotPassword(email);
      setCode("");
      setResendCooldown(RESEND_COOLDOWN_SECONDS);
      setResendNotice(true);
      otpRef.current?.focus();
    } catch (err) {
      const problem = parseApiError(err);
      if (problem.retryAfterSeconds) {
        setRetrySeconds(problem.retryAfterSeconds);
      } else {
        setRequestError(problem.code);
      }
    } finally {
      setResending(false);
    }
  };

  const codeError = requestError === "RESET_CODE_INVALID" || requestError === "RESET_CODE_EXPIRED";
  const disabled = verifying || resending;

  return (
    <GScreen header={{ title: t("auth.verifyCode.title"), onBack: () => router.back() }}>
      {resendNotice ? (
        <View
          style={[styles.notice, { backgroundColor: theme.successBg }]}
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
          testID="verify-code-resend-notice"
        >
          <Text style={[textStyle("body", locale), { color: theme.success }]}>
            {t("auth.verifyCode.codeSent")}
          </Text>
        </View>
      ) : null}

      {retrySeconds !== null && retrySeconds > 0 ? (
        <GErrorBanner
          message={t("auth.rateLimited.retryIn", { seconds: retrySeconds })}
          testID="verify-code-rate-limited"
        />
      ) : requestError ? (
        <GErrorBanner
          code={requestError}
          onDismiss={() => setRequestError(null)}
          testID="verify-code-error"
        />
      ) : null}

      <View style={styles.form}>
        <Text style={[textStyle("body", locale), styles.instructions, { color: theme.textSecondary }]}>
          {t("auth.verifyCode.instructions", { email })}
        </Text>

        <GOtpInput
          ref={otpRef}
          value={code}
          onChange={setCode}
          onComplete={handleVerify}
          error={codeError}
          disabled={disabled}
          testID="verify-code-otp"
        />

        <GButton
          label={t("auth.verifyCode.submit")}
          onPress={() => handleVerify(code)}
          loading={verifying}
          disabled={disabled || code.length < 8}
          fullWidth
          testID="verify-code-submit"
        />

        <GButton
          variant="ghost"
          label={
            resendCooldown > 0
              ? t("auth.verifyCode.resendIn", { seconds: resendCooldown })
              : t("auth.verifyCode.resend")
          }
          onPress={handleResend}
          loading={resending}
          disabled={disabled || resendCooldown > 0}
          testID="verify-code-resend"
        />
      </View>
    </GScreen>
  );
}

const styles = StyleSheet.create({
  notice: {
    borderRadius: radius.md,
    padding: space[3],
    marginBottom: space[2],
  },
  form: {
    gap: space[4],
    marginTop: space[2],
  },
  instructions: {
    marginBottom: space[1],
  },
});
