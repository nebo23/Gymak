/**
 * §9.3's auth stack. Every screen renders its own header (or none) through
 * GScreen, so the native stack header stays off throughout.
 */
import { Stack } from "expo-router";

export default function AuthLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="welcome" />
      <Stack.Screen name="login" />
      <Stack.Screen name="register" />
      <Stack.Screen name="forgot-password" />
      <Stack.Screen name="verify-code" />
      <Stack.Screen name="new-password" />
    </Stack>
  );
}
