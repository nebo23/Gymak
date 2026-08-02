/**
 * §9.3's onboarding stack: six steps plus review. Every screen renders its
 * own header (or none) through GScreen, same convention as (auth)/_layout.tsx.
 */
import { Stack } from "expo-router";

export default function OnboardingLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="step-1" />
      <Stack.Screen name="step-2" />
      <Stack.Screen name="step-3" />
      <Stack.Screen name="step-4" />
      <Stack.Screen name="step-5" />
      <Stack.Screen name="step-6" />
      <Stack.Screen name="review" />
    </Stack>
  );
}
