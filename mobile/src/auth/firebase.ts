/**
 * P1-ADR-01's client half: obtain a **Firebase** ID token — never the raw
 * Google one — so `POST /auth/social/google` can verify it server-side with
 * `firebase_admin.auth.verify_id_token`. The Firebase token never leaves this
 * module except as the return value posted to that one endpoint (api/auth.ts's
 * `socialSignIn`); it is never stored and never treated as a Gymak session.
 *
 * Google only — Facebook is deferred to Phase 2 (decision 13.1.2, A-15).
 *
 * Flow: `@react-native-google-signin` drives the native account picker and
 * returns a Google ID token → `GoogleAuthProvider.credential` wraps it →
 * `signInWithCredential` exchanges it for a Firebase user → that user's
 * `getIdToken()` is the value the backend actually verifies.
 */
import { getApp } from "@react-native-firebase/app";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithCredential,
} from "@react-native-firebase/auth";
import {
  GoogleSignin,
  isErrorWithCode,
  isSuccessResponse,
  statusCodes,
} from "@react-native-google-signin/google-signin";

/** The user closed the picker or backed out. Not an error — show nothing. */
export class SocialSignInCancelledError extends Error {}

/** Play Services missing/outdated, or Google returned no ID token. */
export class SocialSignInUnavailableError extends Error {}

let configured = false;

function ensureConfigured(): void {
  if (configured) return;
  const webClientId = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID;
  if (!webClientId) {
    // Fails fast, like api/client.ts's own EXPO_PUBLIC_API_BASE_URL guard —
    // a silently-missing client id would otherwise surface as an opaque
    // native Google Sign-In failure with no clue why.
    throw new SocialSignInUnavailableError(
      "EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID is not set. See mobile/.env.example.",
    );
  }
  GoogleSignin.configure({ webClientId });
  configured = true;
}

/**
 * Runs the full Google → Firebase exchange and resolves the Firebase ID
 * token. Throws `SocialSignInCancelledError` if the user backed out (callers
 * should treat this as a silent no-op, not an error banner) and
 * `SocialSignInUnavailableError` if Play Services is missing/outdated or
 * Google returned no token. Any other failure (network, malformed response)
 * propagates as-is for the caller's normal error handling.
 */
export async function signInWithGoogle(): Promise<string> {
  ensureConfigured();

  try {
    await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
    const response = await GoogleSignin.signIn();
    if (!isSuccessResponse(response)) {
      throw new SocialSignInCancelledError();
    }

    const { idToken } = response.data;
    if (!idToken) {
      throw new SocialSignInUnavailableError("Google did not return an ID token");
    }

    const credential = GoogleAuthProvider.credential(idToken);
    const userCredential = await signInWithCredential(getAuth(getApp()), credential);
    return await userCredential.user.getIdToken();
  } catch (error) {
    if (isErrorWithCode(error)) {
      switch (error.code) {
        case statusCodes.SIGN_IN_CANCELLED:
        case statusCodes.IN_PROGRESS:
          throw new SocialSignInCancelledError();
        case statusCodes.PLAY_SERVICES_NOT_AVAILABLE:
          throw new SocialSignInUnavailableError("Google Play Services unavailable");
        default:
          throw error;
      }
    }
    throw error;
  }
}
