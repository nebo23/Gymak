/**
 * §9.3 screen 6 — new password. New password + confirm, spending the
 * `reset_token` verify-code handed off (§5.6's third call). On success every
 * session was revoked server-side, so this routes to login carrying a flag
 * that shows the "you were signed out everywhere" notice, rather than
 * signing the user back in here.
 */
import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { Controller, useForm, type FieldErrors, type Resolver } from "react-hook-form";
import { z, type ZodIssue } from "zod";

import { resetPassword } from "../../src/api/auth";
import { parseApiError, type ResolvedErrorCode } from "../../src/api/errors";
import { GButton, GErrorBanner, GScreen, GTextInput } from "../../src/components";
import { useI18n } from "../../src/i18n";
import { useTheme } from "../../src/theme/useTheme";
import { textStyle } from "../../src/theme/typography";
import { space } from "../../src/theme/tokens";
import { passwordSchema } from "../../src/validation/schemas";

const newPasswordSchema = z
  .object({
    newPassword: passwordSchema,
    confirmPassword: z.string(),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: "MISMATCH",
    path: ["confirmPassword"],
  });
type NewPasswordForm = z.infer<typeof newPasswordSchema>;

function fieldErrorKey(field: string, issue: ZodIssue): string {
  if (field === "newPassword") {
    return issue.code === "too_big" ? "fieldErrors.password.TOO_LONG" : "fieldErrors.password.TOO_SHORT";
  }
  if (field === "confirmPassword") return "fieldErrors.confirmPassword.MISMATCH";
  return "errors.VALIDATION_ERROR";
}

function resolveWithZod(schema: typeof newPasswordSchema): Resolver<NewPasswordForm> {
  return async (values) => {
    const result = schema.safeParse(values);
    if (result.success) {
      return { values: result.data, errors: {} };
    }
    const errors: FieldErrors<NewPasswordForm> = {};
    for (const issue of result.error.issues) {
      const path = (issue.path.join(".") || "root") as keyof NewPasswordForm;
      if (!errors[path]) {
        errors[path] = { type: issue.code, message: fieldErrorKey(String(path), issue) };
      }
    }
    return { values: {} as Record<string, never>, errors };
  };
}

export default function NewPassword() {
  const { t, locale } = useI18n();
  const theme = useTheme();
  const { resetToken } = useLocalSearchParams<{ resetToken: string; email?: string }>();
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
  } = useForm<NewPasswordForm>({
    resolver: resolveWithZod(newPasswordSchema),
    defaultValues: { newPassword: "", confirmPassword: "" },
  });

  const onSubmit = async (values: NewPasswordForm) => {
    setRequestError(null);
    setRetrySeconds(null);
    setSubmitting(true);
    try {
      await resetPassword(resetToken, values.newPassword);
      router.replace({ pathname: "/(auth)/login", params: { passwordReset: "1" } });
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
  const tokenInvalid = requestError === "RESET_TOKEN_INVALID";

  return (
    <GScreen header={{ title: t("auth.newPassword.title"), onBack: () => router.back() }}>
      {retrySeconds !== null && retrySeconds > 0 ? (
        <GErrorBanner
          message={t("auth.rateLimited.retryIn", { seconds: retrySeconds })}
          testID="new-password-rate-limited"
        />
      ) : requestError ? (
        <GErrorBanner
          code={requestError}
          onDismiss={() => setRequestError(null)}
          testID="new-password-error"
        />
      ) : null}

      <View style={styles.form}>
        <Text style={[textStyle("body", locale), { color: theme.textSecondary }]}>
          {t("auth.newPassword.instructions")}
        </Text>

        <Controller
          control={control}
          name="newPassword"
          render={({ field }) => (
            <GTextInput
              label={t("auth.newPassword.newPassword")}
              value={field.value}
              onChangeText={field.onChange}
              error={
                errors.newPassword
                  ? t(errors.newPassword.message ?? "errors.VALIDATION_ERROR")
                  : undefined
              }
              secure
              autoComplete="password-new"
              disabled={disabled}
              testID="new-password-password"
            />
          )}
        />

        <Controller
          control={control}
          name="confirmPassword"
          render={({ field }) => (
            <GTextInput
              label={t("auth.newPassword.confirmPassword")}
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
              testID="new-password-confirm"
            />
          )}
        />

        <GButton
          label={t("auth.newPassword.submit")}
          onPress={handleSubmit(onSubmit)}
          loading={submitting}
          disabled={disabled}
          fullWidth
          testID="new-password-submit"
        />

        {tokenInvalid ? (
          <GButton
            variant="ghost"
            label={t("auth.newPassword.startOver")}
            onPress={() => router.replace("/(auth)/forgot-password")}
            testID="new-password-start-over"
          />
        ) : null}
      </View>
    </GScreen>
  );
}

const styles = StyleSheet.create({
  form: {
    gap: space[3],
    marginTop: space[2],
  },
});
