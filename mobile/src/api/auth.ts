/**
 * §5.2-5.7, §5.10: every auth and account call. Types are now GENERATED from
 * the committed openapi.json (see `schema.d.ts`) rather than transcribed to
 * mirror it — there is no account.ts in §3's file list, so account deletion (§5.10)
 * lives here alongside the other session-terminating calls (logout,
 * logout-all).
 */
import { client } from "./client";
import type { components } from "./schema";
import type { Language, ProfileData } from "./profile";

type Schemas = components["schemas"];

/** The only provider wired in §5.4. Apple is out of scope for this phase. */
export type SocialProvider = "google";

export type UserSummary = Schemas["UserSummary"];
export type TokenPairResponse = Schemas["TokenPairResponse"];
export type SocialSignInResponse = Schemas["SocialSignInResponse"];
export type AuthMeUser = Schemas["AuthMeUser"];
export type DeleteAccountResponse = Schemas["DeleteAccountResponse"];

/**
 * `profile` is narrowed to the six-union `ProfileData` from profile.ts rather
 * than left as the schema's own (which types the vocabulary fields as bare
 * strings) -- otherwise signing in would hand the app a profile whose
 * `gender` no longer fits the pickers that render it. See profile.ts's note.
 */
export type AuthMeResponse = Omit<Schemas["AuthMeResponse"], "profile"> & {
  profile: ProfileData | null;
};

/**
 * `language` carries a server-side default ("ar"), and openapi-typescript
 * marks any defaulted property required because it emits one type per schema
 * and cannot tell a request from a response. Restored to optional here, and
 * narrowed to the same union profile.ts uses. Same reasoning as
 * ProfileCreateInput -- the note there is the long version.
 */
export type RegisterInput = Omit<Schemas["RegisterRequest"], "language"> & {
  language?: Language;
};

export type LoginInput = Schemas["LoginRequest"];

export async function register(input: RegisterInput): Promise<TokenPairResponse> {
  const response = await client.post<TokenPairResponse>("/auth/register", input);
  return response.data;
}

export async function login(input: LoginInput): Promise<TokenPairResponse> {
  const response = await client.post<TokenPairResponse>("/auth/login", input);
  return response.data;
}

export async function socialSignIn(
  provider: SocialProvider,
  idToken: string,
): Promise<SocialSignInResponse> {
  const response = await client.post<SocialSignInResponse>(`/auth/social/${provider}`, {
    id_token: idToken,
  });
  return response.data;
}

/**
 * Exported for completeness (§5.5's contract), but the interceptor in
 * client.ts is the only caller in the normal silent-refresh path — see
 * §9.5's "client-side contract" note about serialising this through a
 * single-flight lock.
 */
export async function refresh(refreshToken: string): Promise<TokenPairResponse> {
  const response = await client.post<TokenPairResponse>("/auth/refresh", {
    refresh_token: refreshToken,
  });
  return response.data;
}

export async function logout(refreshToken: string): Promise<void> {
  await client.post("/auth/logout", { refresh_token: refreshToken });
}

export async function logoutAll(): Promise<void> {
  await client.post("/auth/logout-all");
}

export async function forgotPassword(
  email: string,
): Promise<Schemas["ForgotPasswordResponse"]> {
  const response = await client.post<Schemas["ForgotPasswordResponse"]>(
    "/auth/password/forgot",
    { email },
  );
  return response.data;
}

export async function verifyResetCode(
  email: string,
  code: string,
): Promise<Schemas["VerifyCodeResponse"]> {
  const response = await client.post<Schemas["VerifyCodeResponse"]>(
    "/auth/password/verify-code",
    { email, code },
  );
  return response.data;
}

export async function resetPassword(resetToken: string, newPassword: string): Promise<void> {
  await client.post("/auth/password/reset", {
    reset_token: resetToken,
    new_password: newPassword,
  });
}

export async function getMe(): Promise<AuthMeResponse> {
  const response = await client.get<AuthMeResponse>("/auth/me");
  return response.data;
}

/** §5.10: `password` is omitted for social-only accounts, required otherwise. */
export async function deleteAccount(password?: string): Promise<DeleteAccountResponse> {
  const response = await client.delete<DeleteAccountResponse>("/account", { data: { password } });
  return response.data;
}
