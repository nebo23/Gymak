/**
 * The React-facing view of the session store. Components read this instead
 * of `useSessionStore` directly, so screens select just the fields they
 * render (Zustand only re-renders on a changed selection) and never touch
 * `signIn`/`setTokens`/`hydrate` in a raw form outside the auth flow.
 */
import { useSessionStore, type SessionStatus, type SessionUser } from "./session";

export interface Session {
  status: SessionStatus;
  user: SessionUser | null;
  onboardingCompleted: boolean;
  isAuthenticated: boolean;
}

export function useSession(): Session {
  return useSessionStore((state) => ({
    status: state.status,
    user: state.user,
    onboardingCompleted: state.onboardingCompleted,
    isAuthenticated: state.status === "onboarding" || state.status === "active",
  }));
}

export function useSignIn() {
  return useSessionStore((state) => state.signIn);
}

export function useSignOut() {
  return useSessionStore((state) => state.signOut);
}
