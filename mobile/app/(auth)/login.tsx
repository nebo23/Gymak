/**
 * §9.3 screen 3 — login. Email, password (reveal toggle lives inside
 * GTextInput itself), "Forgot password?", submit, Google social button.
 * Also renders the notice new-password.tsx (screen 6) hands off after a
 * successful reset: every device was signed out, sign in again.
 */
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { Controller, useForm, type FieldErrors, type Resolver } from "react-hook-form";
import type { ZodIssue, z } from "zod";

import { login, socialSignIn } from "../../src/api/auth";
import { parseApiError, resolveErrorCode, type ResolvedErrorCode } from "../../src/api/errors";
import {
  SocialSignInCancelledError,
  SocialSignInMisconfiguredError,
  SocialSignInUnavailableError,
  signInWithGoogle,
} from "../../src/auth/firebase";
import { useSessionStore } from "../../src/auth/session";
import { GButton, GErrorBanner, GScreen, GTextInput } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { minTouchTarget, radius, space } from "../../src/theme/tokens";
import { loginSchema } from "../../src/validation/schemas";

type LoginForm = z.infer<typeof loginSchema>;

function fieldErrorKey(field: string, issue: ZodIssue): string {
  if (field === "email") return "fieldErrors.email.INVALID";
  if (field === "password") return "fieldErrors.password.REQUIRED";
  return "errors.VALIDATION_ERROR";
}

function resolveWithZod(schema: typeof loginSchema): Resolver<LoginForm> {
  return async (values) => {
    const result = schema.safeParse(values);
    if (result.success) {
      return { values: result.data, errors: {} };
    }
    const errors: FieldErrors<LoginForm> = {};
    for (const issue of result.error.issues) {
      const path = (issue.path.join(".") || "root") as keyof LoginForm;
      if (!errors[path]) {
        errors[path] = { type: issue.code, message: fieldErrorKey(String(path), issue) };
      }
    }
    return { values: {} as Record<string, never>, errors };
  };
}

export default function Login() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const params = useLocalSearchParams<{ passwordReset?: string }>();
  const [submitting, setSubmitting] = useState(false);
  const [socialLoading, setSocialLoading] = useState(false);
  const [requestError, setRequestError] = useState<ResolvedErrorCode | null>(null);
  const [retrySeconds, setRetrySeconds] = useState<number | null>(null);
  const [showResetNotice, setShowResetNotice] = useState(params.passwordReset === "1");

  useEffect(() => {
    if (retrySeconds === null || retrySeconds <= 0) return;
    const id = setTimeout(() => setRetrySeconds((s) => (s ?? 1) - 1), 1000);
    return () => clearTimeout(id);
  }, [retrySeconds]);

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({
    resolver: resolveWithZod(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const finishSignIn = async (accessToken: string, refreshToken: string) => {
    await useSessionStore.getState().setTokens(accessToken, refreshToken);
    await useSessionStore.getState().hydrate();
    router.replace("/");
  };

  const onSubmit = async (values: LoginForm) => {
    setRequestError(null);
    setRetrySeconds(null);
    setShowResetNotice(false);
    setSubmitting(true);
    try {
      const result = await login(values);
      await finishSignIn(result.access_token, result.refresh_token);
    } catch (err) {
      const problem = parseApiError(err);
      if (problem.retryAfterSeconds) {
        setRetrySeconds(problem.retryAfterSeconds);
      } else {
        setRequestError(problem.code);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleSignIn = async () => {
    setRequestError(null);
    setRetrySeconds(null);
    setShowResetNotice(false);
    setSocialLoading(true);
    try {
      const idToken = await signInWithGoogle();
      const result = await socialSignIn("google", idToken);
      await finishSignIn(result.access_token, result.refresh_token);
    } catch (err) {
      if (err instanceof SocialSignInCancelledError) {
        // User backed out — §9.4 has no error state for this.
      } else if (err instanceof SocialSignInMisconfiguredError) {
        setRequestError("SOCIAL_SIGN_IN_MISCONFIGURED");
      } else if (err instanceof SocialSignInUnavailableError) {
        setRequestError("UPSTREAM_UNAVAILABLE");
      } else {
        setRequestError(resolveErrorCode(err));
      }
    } finally {
      setSocialLoading(false);
    }
  };

  const disabled = submitting || socialLoading || (retrySeconds !== null && retrySeconds > 0);

  return (
    <GScreen header={{ title: t("auth.login.title"), onBack: () => router.back() }}>
      {showResetNotice ? (
        <View
          style={[styles.notice, { backgroundColor: theme.successBg }]}
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
          testID="login-reset-notice"
        >
          <Text style={[textStyle("body", locale), { color: theme.success }]}>
            {t("auth.login.passwordResetNotice")}
          </Text>
        </View>
      ) : null}

      {retrySeconds !== null && retrySeconds > 0 ? (
        <GErrorBanner
          message={t("auth.rateLimited.retryIn", { count: retrySeconds })}
          testID="login-rate-limited"
        />
      ) : requestError ? (
        <GErrorBanner
          code={requestError}
          onDismiss={() => setRequestError(null)}
          testID="login-error"
        />
      ) : null}

      <View style={styles.form}>
        <Controller
          control={control}
          name="email"
          render={({ field }) => (
            <GTextInput
              label={t("auth.login.email")}
              value={field.value}
              onChangeText={field.onChange}
              error={errors.email ? t(errors.email.message ?? "errors.VALIDATION_ERROR") : undefined}
              keyboardType="email-address"
              autoComplete="email"
              disabled={disabled}
              testID="login-email"
            />
          )}
        />

        <View>
          <Controller
            control={control}
            name="password"
            render={({ field }) => (
              <GTextInput
                label={t("auth.login.password")}
                value={field.value}
                onChangeText={field.onChange}
                error={
                  errors.password ? t(errors.password.message ?? "errors.VALIDATION_ERROR") : undefined
                }
                secure
                autoComplete="password"
                disabled={disabled}
                testID="login-password"
              />
            )}
          />
          <Pressable
            onPress={() => router.push("/(auth)/forgot-password")}
            hitSlop={linkHitSlop}
            accessibilityRole="button"
            accessibilityLabel={t("auth.login.forgotPassword")}
            style={styles.forgotPasswordLink}
            testID="login-forgot-password"
          >
            <Text style={[textStyle("bodyStrong", locale), { color: theme.textLink }]}>
              {t("auth.login.forgotPassword")}
            </Text>
          </Pressable>
        </View>

        <GButton
          label={t("auth.login.submit")}
          onPress={handleSubmit(onSubmit)}
          loading={submitting}
          disabled={disabled}
          fullWidth
          testID="login-submit"
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
          disabled={disabled}
          onPress={handleGoogleSignIn}
          testID="login-google"
        />

        <View style={styles.footerRow}>
          <Text style={[textStyle("body", locale), { color: theme.textSecondary }]}>
            {t("auth.login.noAccount")}
          </Text>
          <Pressable
            onPress={() => router.replace("/(auth)/register")}
            hitSlop={linkHitSlop}
            accessibilityRole="button"
            accessibilityLabel={t("auth.login.createAccount")}
            testID="login-go-register"
          >
            <Text style={[textStyle("bodyStrong", locale), { color: theme.textLink }]}>
              {t("auth.login.createAccount")}
            </Text>
          </Pressable>
        </View>
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
    gap: space[3],
    marginTop: space[4],
  },
  forgotPasswordLink: {
    alignSelf: "flex-end",
    marginTop: space[1],
  },
  dividerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space[3],
    marginVertical: space[1],
  },
  // A hairline rule: 1dp is the line itself, not a spacing choice, so it is
  // one-off geometry rather than a value the scale should own.
  dividerLine: {
    flex: 1,
    height: 1,
  },
  footerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: space[1],
    marginTop: space[2],
  },
});

// The inline text links (forgot-password, footer) are shorter than
// `minTouchTarget`; hit-slop brings each one's effective touch area up to
// the §10.6 floor (same pattern as GErrorBanner's actionHitSlop /
// GTextInput's toggleHitSlop).
const linkVisualHeight = 24;
const linkHitSlopPad = Math.max(0, (minTouchTarget - linkVisualHeight) / 2);
const linkHitSlop = {
  top: linkHitSlopPad,
  bottom: linkHitSlopPad,
  left: linkHitSlopPad,
  right: linkHitSlopPad,
};
