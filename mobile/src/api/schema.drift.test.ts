/**
 * The mobile half of the OpenAPI contract check.
 *
 * backend/tests/unit/test_openapi_contract.py already fails the backend suite
 * when `backend/openapi.json` drifts from the live FastAPI app. That closes
 * only the first of two gaps. The second is this one: `src/api/schema.d.ts`
 * is generated from that document and committed, so a backend field rename
 * could land with a correctly-regenerated openapi.json and still leave the
 * app translating against types nobody regenerated — the failure would first
 * appear as wrong data on a user's screen.
 *
 * This test regenerates the types the same way `npm run api:generate` does —
 * the same binary, the same arguments — and fails if the committed file
 * differs by a single byte. Deliberately the same shape as the backend's
 * check, including its error message: the fix is always "run the generator
 * and commit the result", never "edit schema.d.ts".
 *
 * Running the real CLI in a subprocess rather than importing the library is
 * the point. Importing it would test a code path `api:generate` does not use,
 * and the failure this guards against is precisely someone's generated output
 * differing from someone else's.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const MOBILE_ROOT = resolve(__dirname, "..", "..");
const OPENAPI_PATH = resolve(MOBILE_ROOT, "..", "backend", "openapi.json");
const COMMITTED_SCHEMA = resolve(MOBILE_ROOT, "src", "api", "schema.d.ts");

/**
 * The generator's own entry point, resolved from node_modules rather than
 * invoked through `npx`: npx may go to the network on a cache miss, and a
 * unit test that can reach the internet is a unit test that fails in CI for
 * reasons unrelated to the thing it checks.
 */
const GENERATOR_BIN = resolve(
  MOBILE_ROOT,
  "node_modules",
  "openapi-typescript",
  "bin",
  "cli.js",
);

describe("src/api/schema.d.ts is generated, not written", () => {
  it("matches a fresh generation from backend/openapi.json", () => {
    expect(existsSync(OPENAPI_PATH)).toBe(true);
    expect(existsSync(GENERATOR_BIN)).toBe(true);

    const workDir = mkdtempSync(join(tmpdir(), "gymak-schema-drift-"));
    const freshPath = join(workDir, "schema.d.ts");

    try {
      execFileSync(process.execPath, [GENERATOR_BIN, OPENAPI_PATH, "-o", freshPath], {
        cwd: MOBILE_ROOT,
        stdio: "pipe",
      });

      const fresh = readFileSync(freshPath, "utf8");
      const committed = readFileSync(COMMITTED_SCHEMA, "utf8");

      expect(committed).toBe(fresh);
    } finally {
      rmSync(workDir, { recursive: true, force: true });
    }
  }, 60_000);
});
