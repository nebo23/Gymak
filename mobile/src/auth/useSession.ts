/**
 * The React-facing view of the session store. Components read this instead
 * of `useSessionStore` directly, so screens select just the fields they
 * render (Zustand only re-renders on a changed selection) and never touch
 * `signIn`/`setTokens`/`hydrate` in a raw form outside the auth flow.
 *
 * `useSession` subscribes to each field individually rather than selecting
 * `{ status, user, onboardingCompleted, isAuthenticated }` as one object: a
 * selector that builds a new object literal returns a new reference every
 * call, and Zustand v5's `useStore` feeds that straight into React's
 * `useSyncExternalStore`, which requires `getSnapshot` to return a cached
 * reference when nothing changed. A fresh object every render breaks that
 * contract — React sees "changed", re-renders, calls the selector again,
 * gets another fresh object, and never stops (this is exactly what produced
 * "Maximum update depth exceeded" on app/(app)/home.tsx). `useShallow` from
 * `zustand/react/shallow` also fixes this (it memoizes the selector's output
 * behind a shallow-equality check), but per-field subscriptions were chosen
 * instead: `state.status`/`state.onboardingCompleted` are primitives and
 * `state.user` is only ever replaced — never rebuilt in place — by
 * session.ts's own `set()` calls, so each subscription is already stable on
 * its own with no comparison wrapper needed, no new import, and it matches
 * `useSignIn`/`useSignOut` right below, which already select one store field
 * the same way.
 */
import { useSessionStore, type SessionStatus, type SessionUser } from "./session";

export interface Session {
  status: SessionStatus;
  user: SessionUser | null;
  onboardingCompleted: boolean;
  isAuthenticated: boolean;
}

export function useSession(): Session {
  const status = useSessionStore((state) => state.status);
  const user = useSessionStore((state) => state.user);
  const onboardingCompleted = useSessionStore((state) => state.onboardingCompleted);

  // Built fresh every render, same as any custom hook's return value — this
  // is fine. It's only a `getSnapshot` result (the thing `useSyncExternalStore`
  // demands a cached reference for) that isn't allowed to do this, and none
  // of the three subscriptions above return one.
  return {
    status,
    user,
    onboardingCompleted,
    isAuthenticated: status === "onboarding" || status === "active",
  };
}

export function useSignIn() {
  return useSessionStore((state) => state.signIn);
}

export function useSignOut() {
  return useSessionStore((state) => state.signOut);
}
