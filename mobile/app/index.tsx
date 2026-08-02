/**
 * expo-router needs a route at "/" to resolve on cold start, and the three
 * route groups below are siblings (a group's parentheses are stripped from
 * the URL, so `(auth)/welcome`, `(onboarding)/step-1` and `(app)/home` are
 * the only real paths — none of them is "/"). This is a fixed default, not
 * a session decision: no token read, no `/auth/me` call, no branching. T-12
 * replaces this file with the real gate from §9.2 (token → onboarding
 * state → destination).
 */
import { Redirect } from "expo-router";

export default function Index() {
  return <Redirect href="/(auth)/welcome" />;
}
