/**
 * The mobile test runner.
 *
 * WHY jest-expo AND NOT vitest
 * The previous runner (`vitest.config.ts`, deleted with this change) scoped
 * itself to `src/**\/*.test.ts` and said so in its own comment: "component/
 * screen code needs React Native's runtime and is verified on-device per
 * §11.2, not here." That was true of vitest — it has no React Native runtime —
 * but it meant 24 screens and 24 components carried zero automated coverage,
 * and a defect like «1 أيام» could only be caught by a human holding a phone.
 * `jest-expo` ships the React Native preset, the module mocks for Expo's
 * native modules, and the Babel transform this app already uses
 * (`babel-preset-expo`), so a component can be rendered and asserted on here.
 *
 * moduleNameMapper: expo-asset
 * `expo-font/build/FontLoader.js` imports `expo-asset`, but does not declare
 * it — it is a dependency of `expo` and npm installed it NESTED, at
 * `node_modules/expo/node_modules/expo-asset`. Node's resolution walks up
 * from expo-font and never reaches it; Metro, which the device build uses,
 * resolves it fine, which is why fonts work on a phone and only jest trips.
 * The mapping below hands jest the module that is actually installed rather
 * than a fabricated double, so the real font code path stays under test. It
 * is computed, not a hardcoded path, so a different (hoisted) install layout
 * keeps working.
 *
 * transformIgnorePatterns
 * `node_modules` is NOT transformed by default, but React Native and every
 * Expo package ship untranspiled ESM/Flow and therefore MUST be. The negative
 * lookahead below is the allow-list of scopes to transform anyway. It is the
 * jest-expo recommended pattern, extended with the four non-Expo native
 * dependencies this app actually installs — @react-native-firebase,
 * @react-native-google-signin, @react-native-community, and
 * react-native-svg — because omitting one produces a bare
 * "SyntaxError: Cannot use import statement outside a module" that reads like
 * a broken test rather than a missing entry here.
 */
const expoAssetPath = require.resolve("expo-asset", {
  paths: [require("path").dirname(require.resolve("expo/package.json"))],
});

module.exports = {
  preset: "jest-expo",
  moduleNameMapper: {
    "^expo-asset$": expoAssetPath,
  },
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  testMatch: ["<rootDir>/src/**/*.test.ts", "<rootDir>/src/**/*.test.tsx"],
  transformIgnorePatterns: [
    "node_modules/(?!(?:jest-)?react-native|@react-native(-community)?|@react-native-firebase|@react-native-google-signin|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|react-navigation|@react-navigation/.*|@sentry/react-native|native-base|react-native-svg)",
  ],
};
