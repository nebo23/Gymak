/**
 * §9.3 screen 2 — register. Email, password, confirm password, a password
 * hint, a terms checkbox (§13.1's terms/privacy pages don't exist yet in
 * Phase 1, so the checkbox copy is static text, not a live link), submit.
 * Every §9.4 state: submitting, field error, request-error banner, offline,
 * rate-limited countdown, and immediate navigation on success.
 *
 * `zodResolver` (`@hookform/resolvers`) isn't in Appendix A.2's dependency
 * list, so `resolveWithZod` below is a ~15-line inline stand-in built only
 * from `react-hook-form` and `zod`, both already permitted.
 */
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";
import { Controller, useForm, useWatch, type FieldErrors, type Resolver } from "react-hook-form";
import type { ZodIssue, z } from "zod";

import { register as registerAccount } from "../../src/api/auth";
import { parseApiError, type ResolvedErrorCode } from "../../src/api/errors";
import { useSessionStore } from "../../src/auth/session";
import { GButton, GErrorBanner, GScreen, GTextInput } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { iconSize, minTouchTarget, radius, space } from "../../src/theme/tokens";
import { registerSchema } from "../../src/validation/schemas";

type RegisterForm = z.infer<typeof registerSchema>;

function fieldErrorKey(field: string, issue: ZodIssue): string {
  if (field === "email") return "fieldErrors.email.INVALID";
  if (field === "password") {
    return issue.code === "too_big" ? "fieldErrors.password.TOO_LONG" : "fieldErrors.password.TOO_SHORT";
  }
  if (field === "confirmPassword") return "fieldErrors.confirmPassword.MISMATCH";
  return "errors.VALIDATION_ERROR";
}

function resolveWithZod(schema: typeof registerSchema): Resolver<RegisterForm> {
  return async (values) => {
    const result = schema.safeParse(values);
    if (result.success) {
      return { values: result.data, errors: {} };
    }
    const errors: FieldErrors<RegisterForm> = {};
    for (const issue of result.error.issues) {
      const path = (issue.path.join(".") || "root") as keyof RegisterForm;
      if (!errors[path]) {
        errors[path] = { type: issue.code, message: fieldErrorKey(String(path), issue) };
      }
    }
    return { values: {} as Record<string, never>, errors };
  };
}

export default function Register() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const [submitting, setSubmitting] = useState(false);
  const [requestError, setRequestError] = useState<ResolvedErrorCode | null>(null);
  const [retrySeconds, setRetrySeconds] = useState<number | null>(null);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [termsError, setTermsError] = useState(false);

  useEffect(() => {
    if (retrySeconds === null || retrySeconds <= 0) return;
    const id = setTimeout(() => setRetrySeconds((s) => (s ?? 1) - 1), 1000);
    return () => clearTimeout(id);
  }, [retrySeconds]);

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<RegisterForm>({
    resolver: resolveWithZod(registerSchema),
    defaultValues: { email: "", password: "", confirmPassword: "" },
  });
  const passwordValue = useWatch({ control, name: "password", defaultValue: "" });

  const onSubmit = async (values: RegisterForm) => {
    setRequestError(null);
    setRetrySeconds(null);
    if (!termsAccepted) {
      setTermsError(true);
      return;
    }
    setTermsError(false);
    setSubmitting(true);
    try {
      const result = await registerAccount({
        email: values.email,
        password: values.password,
        language: locale,
      });
      await useSessionStore.getState().setTokens(result.access_token, result.refresh_token);
      await useSessionStore.getState().hydrate();
      router.replace("/");
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

  const disabled = submitting || (retrySeconds !== null && retrySeconds > 0);

  return (
    <GScreen header={{ title: t("auth.register.title"), onBack: () => router.back() }}>
      {retrySeconds !== null && retrySeconds > 0 ? (
        <GErrorBanner
          message={t("auth.rateLimited.retryIn", { seconds: retrySeconds })}
          testID="register-rate-limited"
        />
      ) : requestError ? (
        <GErrorBanner
          code={requestError}
          onDismiss={() => setRequestError(null)}
          testID="register-error"
        />
      ) : null}

      <View style={styles.form}>
        <Controller
          control={control}
          name="email"
          render={({ field }) => (
            <GTextInput
              label={t("auth.register.email")}
              value={field.value}
              onChangeText={field.onChange}
              error={errors.email ? t(errors.email.message ?? "errors.VALIDATION_ERROR") : undefined}
              keyboardType="email-address"
              autoComplete="email"
              disabled={disabled}
              testID="register-email"
            />
          )}
        />

        <View>
          <Controller
            control={control}
            name="password"
            render={({ field }) => (
              <GTextInput
                label={t("auth.register.password")}
                value={field.value}
                onChangeText={field.onChange}
                error={
                  errors.password ? t(errors.password.message ?? "errors.VALIDATION_ERROR") : undefined
                }
                secure
                autoComplete="password-new"
                disabled={disabled}
                testID="register-password"
              />
            )}
          />
          <Text
            style={[
              textStyle("caption", locale),
              styles.hint,
              { color: passwordValue.length >= 8 ? theme.success : theme.textMuted },
            ]}
          >
            {t("auth.register.passwordHint")}
          </Text>
        </View>

        <Controller
          control={control}
          name="confirmPassword"
          render={({ field }) => (
            <GTextInput
              label={t("auth.register.confirmPassword")}
              value={field.value}
              onChangeText={field.onChange}
              error={
                errors.confirmPassword
                  ? t(errors.confirmPassword.message ?? "errors.VALIDATION_ERROR")
                  : undefined
              }
              secure
              autoComplete="password-new"
              disabled={disabled}
              testID="register-confirm-password"
            />
          )}
        />

        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked: termsAccepted, disabled }}
          accessibilityLabel={`${t("auth.register.termsPrefix")} ${t(
            "auth.register.termsLink",
          )} ${t("auth.register.termsAnd")} ${t("auth.register.privacyLink")}`}
          onPress={() => {
            setTermsAccepted((prev) => !prev);
            setTermsError(false);
          }}
          disabled={disabled}
          style={styles.termsRow}
          testID="register-terms"
        >
          <View
            style={[
              styles.checkbox,
              {
                borderColor: termsError ? theme.error : theme.border,
                backgroundColor: termsAccepted ? theme.primary : theme.input,
              },
            ]}
          >
            {termsAccepted ? (
              <Text style={[textStyle("bodyStrong", "en"), { color: theme.onPrimary }]}>✓</Text>
            ) : null}
          </View>
          <Text style={[textStyle("body", locale), styles.termsText, { color: theme.textSecondary }]}>
            {t("auth.register.termsPrefix")}{" "}
            <Text style={{ color: theme.textPrimary }}>{t("auth.register.termsLink")}</Text>{" "}
            {t("auth.register.termsAnd")}{" "}
            <Text style={{ color: theme.textPrimary }}>{t("auth.register.privacyLink")}</Text>
          </Text>
        </Pressable>
        {termsError ? (
          <Text
            style={[textStyle("caption", locale), { color: theme.error }]}
            accessibilityRole="alert"
            accessibilityLiveRegion="polite"
          >
            {t("fieldErrors.terms.REQUIRED")}
          </Text>
        ) : null}

        <GButton
          label={t("auth.register.submit")}
          onPress={handleSubmit(onSubmit)}
          loading={submitting}
          disabled={retrySeconds !== null && retrySeconds > 0}
          fullWidth
          testID="register-submit"
        />

        <View style={styles.footerRow}>
          <Text style={[textStyle("body", locale), { color: theme.textSecondary }]}>
            {t("auth.register.haveAccount")}
          </Text>
          <Pressable
            onPress={() => router.replace("/(auth)/login")}
            hitSlop={linkHitSlop}
            accessibilityRole="button"
            accessibilityLabel={t("auth.register.logIn")}
            testID="register-go-login"
          >
            <Text style={[textStyle("bodyStrong", locale), { color: theme.textLink }]}>
              {t("auth.register.logIn")}
            </Text>
          </Pressable>
        </View>
      </View>
    </GScreen>
  );
}

// The inline footer link is shorter than `minTouchTarget`; hit-slop brings
// its effective touch area up to the §10.6 floor (same pattern as
// GErrorBanner's actionHitSlop / GTextInput's toggleHitSlop).
const linkVisualHeight = 24;
const linkHitSlopPad = Math.max(0, (minTouchTarget - linkVisualHeight) / 2);
const linkHitSlop = {
  top: linkHitSlopPad,
  bottom: linkHitSlopPad,
  left: linkHitSlopPad,
  right: linkHitSlopPad,
};

const styles = StyleSheet.create({
  form: {
    gap: space[3],
    marginTop: space[4],
  },
  hint: {
    marginTop: space[1],
  },
  termsRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    minHeight: minTouchTarget,
    paddingVertical: space[1],
    gap: space[2],
  },
  checkbox: {
    width: iconSize.md,
    height: iconSize.md,
    borderRadius: radius.sm,
    borderWidth: 2,
    alignItems: "center",
    justifyContent: "center",
    marginTop: space[1],
  },
  termsText: {
    flex: 1,
  },
  footerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: space[1],
    marginTop: space[2],
  },
});
