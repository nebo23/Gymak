/**
 * Native-module doubles, loaded before every test file.
 *
 * Everything mocked here is a module that reaches for a native binary that
 * does not exist in a Node process. None of it is mocked to make an assertion
 * easier — a mock that changes behaviour under test rather than merely
 * supplying the runtime is how a green suite stops meaning anything. Each
 * double therefore mirrors the real module's *contract* (sync vs async,
 * return shapes) and nothing more.
 *
 * NOT MOCKED, deliberately:
 *   expo-haptics — the task list allowed a mock "if used". It is not: no
 *   import of it exists anywhere under src/ or app/, and it is not in
 *   package.json. A mock for an absent module would be dead code that
 *   outlives the reason it was written.
 */

/**
 * expo-secure-store.
 *
 * Backed by a real in-memory Map rather than jest.fn() stubs returning
 * undefined, because two modules read a value back that they themselves
 * wrote: `src/theme/useTheme.ts` (theme preference) and `src/i18n/index.ts`
 * (locale preference). Both read SYNCHRONOUSLY at module scope so the value
 * is known before first paint — a double that always returned undefined
 * would silently exercise only the "nothing stored yet" path and never the
 * one users actually hit on second launch.
 */
jest.mock("expo-secure-store", () => {
  // Declared INSIDE the factory: jest hoists `jest.mock` above the file's
  // own statements, so a Map defined at module scope would not exist yet
  // when this runs ("out-of-scope variables" error).
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => {
      store.set(key, value);
    },
    getItemAsync: async (key) => (store.has(key) ? store.get(key) : null),
    setItemAsync: async (key, value) => {
      store.set(key, value);
    },
    deleteItemAsync: async (key) => {
      store.delete(key);
    },
  };
});

/**
 * expo-router. `router` is a singleton object of navigation verbs; the hooks
 * return the shapes callers destructure. `useLocalSearchParams` returns an
 * empty object rather than undefined — 13 call sites destructure it directly,
 * and undefined would throw before any assertion in the test could run.
 */
jest.mock("expo-router", () => {
  const React = require("react");
  return {
    router: {
      push: jest.fn(),
      replace: jest.fn(),
      back: jest.fn(),
      navigate: jest.fn(),
      dismissAll: jest.fn(),
      canGoBack: jest.fn(() => false),
      setParams: jest.fn(),
    },
    useRouter: () => ({
      push: jest.fn(),
      replace: jest.fn(),
      back: jest.fn(),
      navigate: jest.fn(),
      canGoBack: jest.fn(() => false),
      setParams: jest.fn(),
    }),
    useLocalSearchParams: () => ({}),
    useSegments: () => [],
    usePathname: () => "/",
    useNavigation: () => ({ setOptions: jest.fn(), addListener: jest.fn(() => jest.fn()) }),
    useFocusEffect: (callback) => {
      React.useEffect(() => callback(), [callback]);
    },
    Link: ({ children }) => children,
    Redirect: () => null,
    Slot: ({ children }) => children,
    Stack: Object.assign(
      ({ children }) => children ?? null,
      { Screen: () => null },
    ),
    Tabs: Object.assign(
      ({ children }) => children ?? null,
      { Screen: () => null },
    ),
    SplashScreen: { preventAutoHideAsync: jest.fn(), hideAsync: jest.fn() },
  };
});

/**
 * expo-localization. Arabic, because that is what `detectInitialLocale()`
 * treats as the default and what the app ships as its primary language —
 * a double reporting "en" would make Arabic the exceptional path in tests
 * while it is the ordinary one on users' phones. Tests that need English
 * switch through the provider (see src/test-utils/render.tsx), not by
 * changing this.
 */
jest.mock("expo-localization", () => ({
  getLocales: () => [
    { languageCode: "ar", languageTag: "ar-EG", regionCode: "EG", textDirection: "rtl" },
  ],
  getCalendars: () => [{ timeZone: "Africa/Cairo", calendar: "gregory" }],
}));

/**
 * @react-native-firebase/app and /auth. The credential flow is exercised
 * against the real backend on device; here these exist only so that importing
 * a module which imports them does not crash the runner.
 */
jest.mock("@react-native-firebase/app", () => ({
  getApp: jest.fn(() => ({ name: "[DEFAULT]" })),
}));

jest.mock("@react-native-firebase/auth", () => ({
  getAuth: jest.fn(() => ({ currentUser: null, signOut: jest.fn(async () => undefined) })),
  GoogleAuthProvider: { credential: jest.fn((idToken) => ({ providerId: "google.com", idToken })) },
  signInWithCredential: jest.fn(async () => ({
    user: { getIdToken: jest.fn(async () => "test-firebase-id-token") },
  })),
}));

jest.mock("@react-native-google-signin/google-signin", () => ({
  GoogleSignin: {
    configure: jest.fn(),
    hasPlayServices: jest.fn(async () => true),
    signIn: jest.fn(async () => ({ type: "success", data: { idToken: "test-google-id-token" } })),
    signOut: jest.fn(async () => undefined),
  },
  isErrorWithCode: jest.fn(() => false),
  isSuccessResponse: jest.fn((r) => r?.type === "success"),
  statusCodes: { SIGN_IN_CANCELLED: "SIGN_IN_CANCELLED", IN_PROGRESS: "IN_PROGRESS" },
}));
