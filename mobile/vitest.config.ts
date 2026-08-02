import { defineConfig } from "vitest/config";

// Dev-only unit tests for pure functions (currently: the imperial ↔ SI
// conversion helpers in src/validation/schemas.ts). Deliberately scoped to
// src/**/*.test.ts — component/screen code needs React Native's runtime and
// is verified on-device per §11.2, not here.
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
  },
});
