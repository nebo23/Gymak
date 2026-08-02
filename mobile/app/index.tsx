/**
 * §9.2's three-way session gate. By the time this renders, app/_layout.tsx
 * has already awaited the boot sequence (SecureStore read, then GET
 * /auth/me if a session was found), so `status` here is never "booting" —
 * this is a plain, synchronous redirect, not one more round trip.
 */
import { Redirect } from "expo-router";

import { useSession } from "../src/auth/useSession";

export default function Index() {
  const { status } = useSession();

  if (status === "onboarding") {
    return <Redirect href="/(onboarding)/step-1" />;
  }
  if (status === "active") {
    return <Redirect href="/(app)/home" />;
  }
  return <Redirect href="/(auth)/welcome" />;
}
