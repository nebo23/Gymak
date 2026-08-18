/**
 * §7.2/§7.3: every failure is a `problem+json` envelope with a stable `code`.
 * `title` and `detail` are for developers and are never shown to a user —
 * user-facing copy is localised on the device, keyed by `code` (§9.6). This
 * module is the one place that turns a raw axios failure into that `code`,
 * so a screen never has to reach into `error.response.data` itself.
 */
import axios from "axios";

// Phase 1 §7.3, in table order — the client must handle every one of these.
export const API_ERROR_CODES = [
  "MALFORMED_BODY",
  "PROVIDER_NOT_SUPPORTED",
  "INVALID_CREDENTIALS",
  "TOKEN_MISSING",
  "TOKEN_EXPIRED",
  "TOKEN_INVALID",
  "TOKEN_REUSED",
  "SOCIAL_TOKEN_INVALID",
  "RESET_TOKEN_INVALID",
  "ACCOUNT_DISABLED",
  "NOT_FOUND",
  "PROFILE_NOT_FOUND",
  "EMAIL_ALREADY_REGISTERED",
  "PROFILE_ALREADY_EXISTS",
  "IDENTITY_ALREADY_LINKED",
  "VALIDATION_ERROR",
  "GOAL_NOT_PERMITTED_FOR_MINOR",
  "RESET_CODE_INVALID",
  "RESET_CODE_EXPIRED",
  "RATE_LIMIT_EXCEEDED",
  "RESET_CODE_ATTEMPTS_EXCEEDED",
  "INTERNAL_ERROR",
  "UPSTREAM_UNAVAILABLE",
  // Phase 2 §7.2, in table order -- already translated in ar.json/en.json (each
  // backend task added its own errors.<CODE> key under the standing i18n exception
  // as it shipped, per §7.2's own "every code gets an entry in the same task that
  // introduces it"), but never added here until T-25 became the first mobile task
  // to actually reach one of these over the wire. Without an entry here,
  // parseApiError falls through to GENERIC for a real, already-translated code --
  // T-25's own SESSION_ACTIVE_BLOCKS_REGENERATION requirement is what surfaced it.
  "PROGRAM_NOT_FOUND",
  "SESSION_NOT_FOUND",
  "SESSION_ALREADY_ACTIVE",
  "SESSION_NOT_ACTIVE",
  "SESSION_ACTIVE_BLOCKS_REGENERATION",
  "EMPTY_SESSION",
  "PLAN_GENERATION_FAILED",
  // Same story as the block above's own comment, one task later: §7.2 already
  // documented EXERCISE_NOT_FOUND (routers/exercises.py's GET /exercises/{id},
  // T-16's own backend precedent), but no mobile screen called that route until
  // T-29's exercise detail screen -- so T-29 is what adds both this entry and the
  // errors.EXERCISE_NOT_FOUND string in ar.json/en.json, per §7.2's "every code
  // gets an entry in the same task that introduces it" (introduces it *to the
  // client*, here, since the backend and the spec table already had it).
  "EXERCISE_NOT_FOUND",
] as const;

export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

/** Client-only fallback codes, not part of §7.3 but sharing the same `errors.<code>` i18n namespace. */
export type ClientFallbackCode = "GENERIC" | "OFFLINE" | "SOCIAL_SIGN_IN_MISCONFIGURED";

export type ResolvedErrorCode = ApiErrorCode | ClientFallbackCode;

const KNOWN_CODES = new Set<string>(API_ERROR_CODES);

/** Every §7.3 code mapped to its translation key — see en.json/ar.json's `errors` object. */
export const ERROR_CODE_I18N_KEYS: Record<ApiErrorCode, string> = Object.fromEntries(
  API_ERROR_CODES.map((code) => [code, `errors.${code}`]),
) as Record<ApiErrorCode, string>;

export interface FieldError {
  field: string;
  code: string;
}

export interface ApiProblem {
  /** Always one of API_ERROR_CODES, or GENERIC/OFFLINE for a failure with no server code. */
  code: ResolvedErrorCode;
  /** The raw server code, kept even when unrecognised, purely for logging. */
  rawCode?: string;
  status?: number;
  detail?: string;
  traceId?: string;
  errors: FieldError[];
  retryAfterSeconds?: number;
}

interface ProblemBody {
  code?: unknown;
  detail?: unknown;
  trace_id?: unknown;
  errors?: unknown;
}

function parseRetryAfter(headerValue: unknown): number | undefined {
  if (typeof headerValue !== "string") return undefined;
  const seconds = Number.parseInt(headerValue, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
}

function parseFieldErrors(raw: unknown): FieldError[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (entry): entry is FieldError =>
      typeof entry === "object" &&
      entry !== null &&
      typeof (entry as FieldError).field === "string" &&
      typeof (entry as FieldError).code === "string",
  );
}

/**
 * Turns any error thrown by an `api/client.ts` call into a `code` the UI can
 * switch on. A missing network response (offline, DNS failure, timeout)
 * becomes `OFFLINE` — never a raw axios message (§9.4). A response with a
 * `code` outside API_ERROR_CODES — a server version skew, most likely —
 * becomes `GENERIC` and is logged, rather than surfacing an unlocalised
 * string or crashing the error banner.
 */
export function parseApiError(error: unknown): ApiProblem {
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return { code: "OFFLINE", errors: [] };
    }

    const body = (error.response.data ?? {}) as ProblemBody;
    const rawCode = typeof body.code === "string" ? body.code : undefined;
    const resolvedCode: ResolvedErrorCode =
      rawCode && KNOWN_CODES.has(rawCode) ? (rawCode as ApiErrorCode) : "GENERIC";

    if (rawCode && resolvedCode === "GENERIC") {
      console.warn(`[api] unrecognised error code from server: "${rawCode}"`);
    }

    return {
      code: resolvedCode,
      rawCode,
      status: error.response.status,
      detail: typeof body.detail === "string" ? body.detail : undefined,
      traceId: typeof body.trace_id === "string" ? body.trace_id : undefined,
      errors: parseFieldErrors(body.errors),
      retryAfterSeconds: parseRetryAfter(error.response.headers?.["retry-after"]),
    };
  }

  console.warn("[api] non-axios error surfaced from an API call", error);
  return { code: "GENERIC", errors: [] };
}

/** Bare code suitable for `<GErrorBanner code={...} />`, which builds `errors.<code>` itself. */
export function resolveErrorCode(error: unknown): ResolvedErrorCode {
  return parseApiError(error).code;
}

/** Full dotted i18n key, e.g. `errors.TOKEN_EXPIRED`, for callers that call `t()` directly. */
export function resolveErrorTranslationKey(error: unknown): string {
  return `errors.${resolveErrorCode(error)}`;
}
