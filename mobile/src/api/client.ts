/**
 * §9.1/§9.5: one axios instance, one interceptor pair — the single place
 * that attaches the bearer token and runs the refresh dance.
 *
 * §9.5's five rules, and where each lives below:
 *   1. Request interceptor attaches the access token.
 *   2. A 401 TOKEN_EXPIRED on a non-exempt route either joins the single
 *      in-flight `refreshPromise` (single-flight lock) or starts it.
 *   3. TOKEN_REUSED, TOKEN_INVALID, or a failed refresh call itself →
 *      `handleSessionExpired()`: clear SecureStore, reset the session
 *      store, redirect to (auth)/welcome. A failed refresh is never retried.
 *   4. `isAuthExemptUrl` — login, register, refresh itself, and every
 *      password/* call never trigger a refresh attempt.
 *   5. `config._retry` caps a request at one replay; a second 401 on an
 *      already-retried request is treated as a logout, not another refresh.
 */
import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";
import { router } from "expo-router";

import { useSessionStore } from "../auth/session";
import { parseApiError } from "./errors";

const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL;

if (!API_BASE_URL) {
  // Fail fast, like the backend's config.py — a silently-undefined base URL
  // would otherwise surface as a confusing "Network Error" on first request.
  throw new Error("EXPO_PUBLIC_API_BASE_URL is not set. See mobile/.env.example.");
}

// §9.5 rule 4, plus /auth/social/*: none of these are bearer-authenticated
// (§5.1's Auth column is "none" or "refresh" for all of them), so they never
// get an Authorization header and never trigger a refresh-on-401.
const PUBLIC_AUTH_PATHS = [
  "/auth/login",
  "/auth/register",
  "/auth/refresh",
  "/auth/social/",
  "/auth/password/",
];

function isAuthExemptUrl(url: string | undefined): boolean {
  if (!url) return false;
  return PUBLIC_AUTH_PATHS.some((path) => url.includes(path));
}

interface RetryableConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

export const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { Accept: "application/json" },
});

// A dedicated instance for the refresh call itself: it must never pass
// through this file's response interceptor, or a failed refresh would
// re-enter the same 401 handling it is already inside of.
const refreshClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { Accept: "application/json" },
});

client.interceptors.request.use((config) => {
  const { accessToken } = useSessionStore.getState();
  if (accessToken && !isAuthExemptUrl(config.url)) {
    config.headers.set("Authorization", `Bearer ${accessToken}`);
  }
  return config;
});

async function handleSessionExpired(): Promise<void> {
  await useSessionStore.getState().signOut();
  try {
    router.replace("/(auth)/welcome");
  } catch {
    // Can be called before the root navigator has mounted (e.g. a request
    // fired during initial boot). index.tsx's own declarative redirect
    // already lands on welcome once `status` flips to "signedOut", so a
    // failed imperative replace here is a no-op, not a bug.
  }
}

// Module-level single-flight lock (§9.5 rule 2a): every 401 TOKEN_EXPIRED
// that arrives while a refresh is already in flight awaits this same
// promise instead of starting a second /auth/refresh call.
let refreshPromise: Promise<{ accessToken: string }> | null = null;

async function refreshTokens(): Promise<{ accessToken: string }> {
  const { refreshToken } = useSessionStore.getState();
  if (!refreshToken) {
    throw new Error("No refresh token available");
  }
  const response = await refreshClient.post("/auth/refresh", { refresh_token: refreshToken });
  const { access_token: accessToken, refresh_token: newRefreshToken } = response.data as {
    access_token: string;
    refresh_token: string;
  };
  await useSessionStore.getState().setTokens(accessToken, newRefreshToken);
  return { accessToken };
}

client.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error) || !error.response) {
      // No response at all: offline, timeout, DNS failure. Not this
      // interceptor's job — §9.4's offline handling reads this from the
      // caller, via errors.ts's parseApiError.
      return Promise.reject(error);
    }

    const axiosError = error as AxiosError;
    const config = axiosError.config as RetryableConfig | undefined;
    if (axiosError.response?.status !== 401 || !config) {
      return Promise.reject(error);
    }

    const problem = parseApiError(error);

    if (problem.code === "TOKEN_REUSED" || problem.code === "TOKEN_INVALID") {
      await handleSessionExpired();
      return Promise.reject(error);
    }

    if (problem.code === "TOKEN_EXPIRED" && !isAuthExemptUrl(config.url)) {
      if (config._retry) {
        // Already replayed once with a freshly refreshed token and still
        // got a 401 — §9.5 rule 5: a second 401 is a logout, not a third try.
        await handleSessionExpired();
        return Promise.reject(error);
      }
      config._retry = true;

      try {
        if (!refreshPromise) {
          refreshPromise = refreshTokens().finally(() => {
            refreshPromise = null;
          });
        }
        const { accessToken } = await refreshPromise;
        config.headers.set("Authorization", `Bearer ${accessToken}`);
        return client(config);
      } catch (refreshError) {
        // §9.5 rule 3: a failed refresh is never retried — it is a logout.
        await handleSessionExpired();
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  },
);
