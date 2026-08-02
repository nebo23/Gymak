/**
 * §5.2-5.7, §5.10: every auth and account call. Types mirror the backend's
 * committed openapi.json exactly (TokenPairResponse, AuthMeResponse, etc.) —
 * there is no account.ts in §3's file list, so account deletion (§5.10)
 * lives here alongside the other session-terminating calls (logout,
 * logout-all).
 */
import { client } from "./client";
import type { ProfileData } from "./profile";

export type SocialProvider = "google";

export interface UserSummary {
  id: string;
  email: string;
  onboarding_completed: boolean;
}

export interface TokenPairResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
  refresh_expires_in: number;
  user: UserSummary;
}

export interface SocialSignInResponse extends TokenPairResponse {
  is_new_user: boolean;
}

export interface AuthMeUser {
  id: string;
  email: string;
  email_verified: boolean;
  created_at: string;
  auth_methods: string[];
}

export interface AuthMeResponse {
  user: AuthMeUser;
  onboarding_completed: boolean;
  profile: ProfileData | null;
}

export interface RegisterInput {
  email: string;
  password: string;
  language?: "ar" | "en";
}

export interface LoginInput {
  email: string;
  password: string;
}

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

export async function forgotPassword(email: string): Promise<{ message: string }> {
  const response = await client.post("/auth/password/forgot", { email });
  return response.data;
}

export async function verifyResetCode(
  email: string,
  code: string,
): Promise<{ reset_token: string; expires_in: number }> {
  const response = await client.post("/auth/password/verify-code", { email, code });
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

export interface DeleteAccountResponse {
  deletion_requested_at: string;
  purge_after_days: number;
}

/** §5.10: `password` is omitted for social-only accounts, required otherwise. */
export async function deleteAccount(password?: string): Promise<DeleteAccountResponse> {
  const response = await client.delete<DeleteAccountResponse>("/account", { data: { password } });
  return response.data;
}
