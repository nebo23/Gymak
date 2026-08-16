/**
 * The pure decision behind `useSyncDeviceTimezone` in `(app)/_layout.tsx`,
 * pulled out so it can be unit-tested without React, TanStack Query, or a
 * device — this is the one piece of logic in T-23 that silently mutates a
 * user's profile, so it is not the one thing in the task left untested.
 */

// profiles.timezone's DB default (Phase 2 §4.2) — the only value a profile
// can carry before any client has ever written a real one to it.
export const SERVER_DEFAULT_TIMEZONE = "Africa/Cairo";

export interface TimezoneSyncCheck {
  storedTimezone: string;
  deviceTimezone: string | null | undefined;
}

/**
 * True only when the stored value is still the untouched server default and
 * the device reports a different, real zone. A previously-synced value or a
 * manual Settings edit is never equal to the default, so it is never
 * eligible here — this is what guarantees an account never has a real zone
 * overwritten once it carries one.
 */
export function shouldSyncDeviceTimezone({
  storedTimezone,
  deviceTimezone,
}: TimezoneSyncCheck): boolean {
  if (storedTimezone !== SERVER_DEFAULT_TIMEZONE) return false;
  if (!deviceTimezone) return false;
  if (deviceTimezone === storedTimezone) return false;
  return true;
}
