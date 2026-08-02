/**
 * The Zustand session store (§9.1: "tokens and user identity only. Not a
 * dumping ground for form state."). Built with plain `create` rather than a
 * React-only hook wrapper, so code outside components — api/client.ts's
 * interceptor — can read and write it via `useSessionStore.getState()`.
 *
 * `status` directly encodes §9.2's three-way navigation gate, so app/index.tsx
 * never has to re-derive it: "signedOut" → (auth)/welcome, "onboarding" →
 * (onboarding)/step-1, "active" → (app)/home. "booting" is the splash state.
 */
import { create } from "zustand";

import { getMe, type AuthMeUser } from "../api/auth";
import * as storage from "./storage";

export type SessionStatus = "booting" | "signedOut" | "onboarding" | "active";

export interface SessionUser {
  id: string;
  email: string;
  emailVerified: boolean;
  authMethods: string[];
}

export interface SignInInput {
  accessToken: string;
  refreshToken: string;
  user: SessionUser;
  onboardingCompleted: boolean;
}

interface SessionState {
  status: SessionStatus;
  accessToken: string | null;
  refreshToken: string | null;
  user: SessionUser | null;
  onboardingCompleted: boolean;
  /** Persists tokens + user, and resolves the post-auth status (§9.2). */
  signIn: (input: SignInInput) => Promise<void>;
  /** Clears SecureStore and resets every field to its signed-out default. */
  signOut: () => Promise<void>;
  /** Persists a refreshed token pair without touching user/onboarding state. */
  setTokens: (accessToken: string, refreshToken: string) => Promise<void>;
  /** §9.2's boot sequence: read SecureStore, then GET /auth/me if present. */
  hydrate: () => Promise<void>;
}

function toSessionUser(user: AuthMeUser): SessionUser {
  return {
    id: user.id,
    email: user.email,
    emailVerified: user.email_verified,
    authMethods: user.auth_methods,
  };
}

export const useSessionStore = create<SessionState>((set) => ({
  status: "booting",
  accessToken: null,
  refreshToken: null,
  user: null,
  onboardingCompleted: false,

  signIn: async ({ accessToken, refreshToken, user, onboardingCompleted }) => {
    await storage.saveTokens({ accessToken, refreshToken });
    set({
      accessToken,
      refreshToken,
      user,
      onboardingCompleted,
      status: onboardingCompleted ? "active" : "onboarding",
    });
  },

  signOut: async () => {
    await storage.clearTokens();
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      onboardingCompleted: false,
      status: "signedOut",
    });
  },

  setTokens: async (accessToken, refreshToken) => {
    await storage.saveTokens({ accessToken, refreshToken });
    set({ accessToken, refreshToken });
  },

  hydrate: async () => {
    const tokens = await storage.loadTokens();
    if (!tokens) {
      set({ status: "signedOut" });
      return;
    }
    // Set the tokens before calling /auth/me: the request interceptor reads
    // them from this store, and a corrupt/expired access token here is
    // exactly what exercises the silent-refresh path on cold boot.
    set({ accessToken: tokens.accessToken, refreshToken: tokens.refreshToken });
    try {
      const me = await getMe();
      set({
        user: toSessionUser(me.user),
        onboardingCompleted: me.onboarding_completed,
        status: me.onboarding_completed ? "active" : "onboarding",
      });
    } catch {
      // §9.5 rule 3 already cleared SecureStore and reset this store if the
      // failure came from the refresh interceptor (expired access token +
      // an invalid/reused/corrupted refresh token — manual check 6). This
      // is a safety net for any other /auth/me failure, so boot never gets
      // stuck on "booting".
      await storage.clearTokens();
      set({
        accessToken: null,
        refreshToken: null,
        user: null,
        onboardingCompleted: false,
        status: "signedOut",
      });
    }
  },
}));
