/**
 * §9.3 screen 4 — forgot password. Email only. On 202 (always — the backend
 * never reveals whether the address exists, §5.6) navigate to verify-code
 * carrying the email. An actual failure (offline, rate-limited, malformed
 * body) keeps the user here with the usual §9.4 states.
 */
import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";
import { Controller, useForm, type FieldErrors, type Resolver } from "react-hook-form";
import { z, type ZodIssue } from "zod";

import { forgotPassword } from "../../src/api/auth";
import { parseApiError, type ResolvedErrorCode } from "../../src/api/errors";
import { GButton, GErrorBanner, GScreen, GTextInput } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { space } from "../../src/theme/tokens";
import { emailSchema } from "../../src/validation/schemas";

const forgotPasswordSchema = z.object({ email: emailSchema });
type ForgotPasswordForm = z.infer<typeof forgotPasswordSchema>;

function fieldErrorKey(_field: string, _issue: ZodIssue): string {
  return "fieldErrors.email.INVALID";
}

function resolveWithZod(schema: typeof forgotPasswordSchema): Resolver<ForgotPasswordForm> {
  return async (values) => {
    const result = schema.safeParse(values);
    if (result.success) {
      return { values: result.data, errors: {} };
    }
    const errors: FieldErrors<ForgotPasswordForm> = {};
    for (const issue of result.error.issues) {
      const path = (issue.path.join(".") || "root") as keyof ForgotPasswordForm;
      if (!errors[path]) {
        errors[path] = { type: issue.code, message: fieldErrorKey(String(path), issue) };
      }
    }
    return { values: {} as Record<string, never>, errors };
  };
}

export default function ForgotPassword() {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const [submitting, setSubmitting] = useState(false);
  const [requestError, setRequestError] = useState<ResolvedErrorCode | null>(null);
  const [retrySeconds, setRetrySeconds] = useState<number | null>(null);

  useEffect(() => {
    if (retrySeconds === null || retrySeconds <= 0) return;
    const id = setTimeout(() => setRetrySeconds((s) => (s ?? 1) - 1), 1000);
    return () => clearTimeout(id);
  }, [retrySeconds]);

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotPasswordForm>({
    resolver: resolveWithZod(forgotPasswordSchema),
    defaultValues: { email: "" },
  });

  const onSubmit = async ({ email }: ForgotPasswordForm) => {
    setRequestError(null);
    setRetrySeconds(null);
    setSubmitting(true);
    try {
      await forgotPassword(email);
      router.push({ pathname: "/(auth)/verify-code", params: { email } });
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
    <GScreen header={{ title: t("auth.forgotPassword.title"), onBack: () => router.back() }}>
      {retrySeconds !== null && retrySeconds > 0 ? (
        <GErrorBanner
          message={t("auth.rateLimited.retryIn", { count: retrySeconds })}
          testID="forgot-password-rate-limited"
        />
      ) : requestError ? (
        <GErrorBanner
          code={requestError}
          onDismiss={() => setRequestError(null)}
          testID="forgot-password-error"
        />
      ) : null}

      <View style={styles.form}>
        <Text style={[textStyle("body", locale), styles.instructions, { color: theme.textSecondary }]}>
          {t("auth.forgotPassword.instructions")}
        </Text>

        <Controller
          control={control}
          name="email"
          render={({ field }) => (
            <GTextInput
              label={t("auth.forgotPassword.email")}
              value={field.value}
              onChangeText={field.onChange}
              error={errors.email ? t(errors.email.message ?? "errors.VALIDATION_ERROR") : undefined}
              keyboardType="email-address"
              autoComplete="email"
              disabled={disabled}
              testID="forgot-password-email"
            />
          )}
        />

        <GButton
          label={t("auth.forgotPassword.submit")}
          onPress={handleSubmit(onSubmit)}
          loading={submitting}
          disabled={disabled}
          fullWidth
          testID="forgot-password-submit"
        />

        <GButton
          variant="ghost"
          label={t("auth.forgotPassword.backToLogin")}
          onPress={() => router.back()}
          testID="forgot-password-back"
        />
      </View>
    </GScreen>
  );
}

const styles = StyleSheet.create({
  form: {
    gap: space[3],
    marginTop: space[2],
  },
  instructions: {
    marginBottom: space[1],
  },
});
