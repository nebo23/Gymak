# Gymak — Phase 1 Build Specification

> **Document ID** GYMAK-P1-SPEC-001 · **Version** 1.3 · **Date** 31 July 2026
> **Owner** Nabil — sole developer · **Phase** 1 of N — authentication, session management, one-time profile capture
> **Stack** FastAPI · PostgreSQL · Firebase Auth (social sign-in only) · React Native (Expo)
> **Derives from** AIFC-SRS-TDD-001 v1.0 (Vol. 2, 4, 5) · Gymak Color System
>
> **This file is the single source of truth for Phase 1.** If this document and your instinct
> disagree, the document wins. Build nothing from the section 1.2 out-of-scope list. Execute one
> task from section 12 at a time, touching only the files that task names.
>
> **v1.0 is superseded and must not be used.** Any copy dated v1.0 still describes the 6-digit,
> user-id-salted reset code that P1-ADR-07 rejects. Delete it. If two versions of this document
> are reachable by a coding agent, the single-source-of-truth rule is already broken.

### Amendments in v1.2

| ID   | Section                     | Change                                                                                                   |
|------|-----------------------------|----------------------------------------------------------------------------------------------------------|
| **P1-ADR-07** | §4.5, §5.6, §7.1, §9.3, §10.5, §12 T-03, §12 T-07 | Reset codes are peppered with a key outside the database. 8 characters from a reduced Base32 alphabet, stored as HMAC-SHA256. Raised at T-02 review, owned by T-07. |
| A-01 | §5.6                        | The `verify-code` request example carried a 6-digit code. Replaced with the ADR-07 format.                |
| A-02 | §4.7, §4.6                  | DDL corrected to what T-02 actually shipped: `FORCE ROW LEVEL SECURITY`, the `NULLIF` guard, the `refresh_tokens` owner policy, and no foreign key on `audit_log.actor_user_id`. |
| A-03 | §12 T-13                    | Auto-submit on the eighth character, not the sixth digit.                                                |
| A-04 | §12 T-11                    | `GOtpInput` is eight alphanumeric boxes.                                                                 |
| A-05 | §12 T-12                    | Done-when referenced check 12; the checks it describes are 5 and 6.                                      |
| A-06 | §12 T-04                    | `app/core/errors.py` added to the file list so the `Retry-After` header §6.4 requires can actually be emitted. |
| A-07 | §6.2                        | The common-password denylist is pinned to a named source instead of an invented list.                     |
| A-08 | §11.1, §11.3                | Coverage must be measured with greenlet concurrency enabled, or every line after the first database `await` is reported as unexecuted. |
| A-09 | §4.3, §13.1                 | Decision 13.1.1 resolved: `weight_kg` and `activity_level` are in, and shipped in T-02. `[confirm]` markers removed. |
| A-10 | §A.5 (new)                  | Carried-forward technical debt recorded with an owning task, so it stops living only in chat history.     |
| A-11 | §0.3                        | Build status added. T-01, T-01b, T-02, T-03 are complete.                                                |
| A-12 | §4.7, §6.5, §13.2           | The `gymak_migrator` / `gymak_app` role split recorded as required before any production data.            |
| A-13 | §12 T-09                    | `ruff format --check` added to the gate.                                                                  |
| A-14 | §0.3, §A.5                  | T-04, T-04b and T-04c complete. Two defects surfaced only by running the application for real: it could not start under uvicorn at all, and the migration needs privileges the application is forbidden from holding. Recorded as §A.5 items 10 and 11. |

### Amendments in v1.3

| ID   | Section                     | Change                                                                                                   |
|------|-----------------------------|----------------------------------------------------------------------------------------------------------|
| A-15 | §1.1, §8.1, §8.2, §9.1, §9.3, §11.3, §12 T-06, §13.1, §13.2, Appendix A.2, A.3 | Decision 13.1.2 closed: Google ships in Phase 1, Facebook is deferred to Phase 2. P1-FR-004 marked deferred rather than removed; the §8.2 Facebook console section kept as a record of the deferred work; `react-native-fbsdk-next` dropped from the dependency list; Facebook sign-in added to the deferred table; T-06 now names Google only; every place that assumed Facebook shipped alongside Google in Phase 1 corrected. `user_identities.provider` CHECK is unchanged — it already allows `facebook`, so no migration is needed now or when Phase 2 picks this up. |

---

## 0 · How to use this document

This is not a design essay. It is an **execution contract**. Every section either tells the agent exactly what to build, or tells it exactly what it is forbidden from touching.

### 0.1 Reading order

- **1** — Phase 1 scope — what ships, what is explicitly deferred
- **2** — Architecture decisions (P1-ADR-01 … 07) — Firebase vs. Postgres split, JWT model, reset-code hashing
- **3** — Repository layout — backend and mobile trees
- **4** — Data model — full DDL, constraints, indexes, RLS
- **5** — API contract — every endpoint, request, response, error
- **6** — Security requirements — hashing, tokens, codes, rate limits
- **7** — Validation rules and the error code catalogue
- **8** — Firebase configuration — Google (Facebook deferred to Phase 2, §13.1)
- **9** — Mobile application — screens, states, navigation, i18n
- **10** — Design tokens — the complete Gymak palette and type scale
- **11** — Testing requirements and Phase 1 definition of done
- **12** — Task pack — ordered, copy-paste prompts T-01 … T-14
- **13** — Decisions Nabil must confirm
- **A** — Appendix — environment variables, dependency list, open debt, glossary

### 0.2 Rules of engagement for the coding agent

> **These rules override any instinct to be helpful beyond the task.**
>
> 1.  **One task at a time.** Execute exactly one task from section 12. Do not start the next task, do not "also fix" an adjacent file, do not refactor code you were not asked about.
> 2.  **Named files only.** Each task lists the files it may create or modify. Touching any other file is a failure of the task, even if the change is an improvement. **Standing exception:** `pyproject.toml` and `tests/**` are always in scope, because a task that cannot adjust its own test configuration will delete a test instead.
> 3.  **No scope invention.** If a feature is not in section 1's "in scope" list, it does not get built, stubbed, or scaffolded — not workouts, not nutrition, not AI, not payments.
> 4.  **Ask, don't assume.** If a required detail is genuinely absent from this document, stop and ask one specific question. Do not invent a schema column, an endpoint, or a library.
> 5.  **No new dependencies** beyond Appendix A.2 without asking first.
> 6.  **Report before changing.** State what the current implementation actually does before you modify it. Four separate corrections in this project were prevented by that single sentence, and five real defects were found because of it.
> 7.  **Every task ends with its tests passing** and the diff summarised in plain language: files touched, what changed, what to verify manually, and what you deliberately did not do. Paste real command output with exit codes — `ruff`, `mypy --strict`, `pytest`.

### 0.3 The three steps this document covers

| Step       | Deliverable                                                                                                         | Tasks       | Done when                                            |
|------------|---------------------------------------------------------------------------------------------------------------------|-------------|------------------------------------------------------|
| **Step 1** | Backend authentication: register, login, social sign-in, refresh rotation, logout, password reset by emailed code   | T-01 … T-07 | All auth endpoints green in tests, OpenAPI published |
| **Step 2** | Backend profile: the one-time settings capture, read and edit, account deletion request, audit log                  | T-08 … T-09 | Profile endpoints green, cross-tenant matrix passes  |
| **Step 3** | React Native client: design system primitives, auth screens, onboarding flow, secure token storage, session refresh | T-10 … T-14 | A real device completes register → onboarding → home |

Steps run in order. Step 3 depends on step 1 and 2 being reachable from the phone (local network or staging). Do not begin step 3 while any step-1 test is red.

#### Build status at v1.2

| Task | Status | Note                                                                                                     |
|------|--------|----------------------------------------------------------------------------------------------------------|
| T-01 | Done   | 11 files. Skeleton, error contract, structured logging, health, testcontainers.                            |
| T-01b| Done   | Remediation. `set_rls_user` was executing successfully while protecting nothing under `AUTOCOMMIT`.        |
| T-02 | Done   | Six tables, 18 tests, migration forward and backward three cycles. See A-02 for what the DDL now records.  |
| T-03 | Done   | Security primitives, including the ADR-07 reset-code primitive. Coverage gate met after the A-08 fix.      |
| T-04 | Done   | Register and login. 22 integration tests, `Retry-After` on every 429. RLS blocked the refresh-token insert in the pre-auth flow — the first time the barrier stopped real code rather than passing a test. |
| T-04b| Done   | Defect. `database.py` called `asyncio.run()` at import time, so the application could not start under uvicorn at all. Moved into a FastAPI lifespan handler. See §A.5 item 10. |
| T-04c| Done   | Device milestone met. `GET /api/v1/health` returns 200 in a phone browser over the LAN. |
| T-05 | Done   | Refresh rotation, logout, logout-all.                                                                     |
| T-06 | Next   | Social sign-in. Google only — decision 13.1.2 closed, Facebook deferred to Phase 2 (A-15).                 |

> **The device milestone after T-04 is met, and it earned its place.** One health check reached from a phone browser over the LAN surfaced two defects that 196 passing tests could not: an import-time `asyncio.run()` that made the application unable to start under uvicorn at all, and a migration that needs `CREATE EXTENSION` privileges the application role must never hold. Neither was visible from the suite, because the suite drives the ASGI app through httpx and never touches uvicorn or a standalone database.
>
> Keep the rule for every remaining backend task: start the server, reach `/api/v1/health` from the device that will consume it, and only then commit. A green suite is not evidence that the application runs.

## 1 · Phase 1 scope

### 1.1 In scope — build exactly this

| ID         | Requirement                                                                       | Layer     |
|------------|-----------------------------------------------------------------------------------|-----------|
| P1-FR-001  | Register an account with email and password                                       | API + app |
| P1-FR-002  | Log in with email and password, receiving an access/refresh token pair            | API + app |
| P1-FR-003  | Sign in or register with Google, brokered through Firebase Auth                   | API + app |
| P1-FR-004  | Sign in or register with Facebook, brokered through Firebase Auth — **deferred to Phase 2, decision 13.1.2 (A-15)** | API + app |
| P1-FR-005  | Issue short-lived access tokens and single-use rotating refresh tokens            | API       |
| P1-FR-006  | Detect refresh-token reuse and invalidate the whole token family                  | API       |
| P1-FR-007  | Log out of the current device; log out of all devices                             | API + app |
| P1-FR-008  | Reset a forgotten password with a single-use code delivered by email (P1-ADR-07)  | API + app |
| P1-FR-009  | Link a social identity to an existing email account on matching verified email    | API       |
| P1-FR-010  | Capture the profile once, immediately after first sign-up, resumable if abandoned | API + app |
| P1-FR-011  | Read and edit profile fields after onboarding (the Settings surface)              | API + app |
| P1-FR-012  | Request account deletion; account is soft-deleted and access revoked immediately  | API       |
| P1-FR-013  | Record an append-only audit entry for every security-relevant action              | API       |
| P1-FR-014  | Switch interface language between Arabic and English, including RTL layout        | App       |
| P1-FR-015  | Store tokens in the platform secure keystore and refresh them transparently       | App       |
| P1-SAF-001 | A user under 18 cannot select a weight-loss goal (inherits SRS SAF-007)           | API + app |

### 1.2 Out of scope — do not build, stub, or scaffold

> **Anything below appearing in a Phase 1 pull request is a defect.**
>
> - Exercise library, programmes, workout sessions, set logging
> - Nutrition targets, food search, meal logging
> - Any LLM call, RAG pipeline, or AI coach surface
> - Subscriptions, receipt validation, paywalls
> - Push notifications and FCM wiring
> - Progress photos, charts, analytics, dashboards
> - Apple Health / Google Fit integration
> - Apple Sign-In (required by the App Store only when the iOS build ships — Phase 3 of the roadmap, not now)
> - Offline mutation queue (auth and onboarding are online-only operations)

### 1.3 Non-functional targets that apply now

| ID        | Target                                                                                               | Verified by                              |
|-----------|------------------------------------------------------------------------------------------------------|------------------------------------------|
| P1-NFR-01 | p95 under 400 ms for every endpoint in this phase, excluding email dispatch                          | Manual timing plus a locust/k6 smoke run |
| P1-NFR-02 | Passwords hashed with Argon2id at the parameters in §6.1; never logged, never returned               | Unit test plus grep gate in CI           |
| P1-NFR-03 | No user can read or write another user's row through any endpoint                                    | Generated cross-tenant test matrix       |
| P1-NFR-04 | All traffic over TLS in staging and production; no plaintext fallback                                | Deployment configuration review          |
| P1-NFR-05 | Backend line coverage at or above 80%, and at or above 95% in the auth and security modules          | pytest-cov gate, greenlet-aware (A-08)   |
| P1-NFR-06 | Health fields and secrets are redacted at the logging boundary by an allowlist serialiser            | Unit test asserting redaction            |
| P1-NFR-07 | The generated OpenAPI document is committed and matches the code                                     | Schema drift check                       |
| P1-NFR-08 | Every interactive element is at least 48 dp, labelled for screen readers, and meets WCAG AA contrast | Manual audit against §10.6               |

## 2 · Architecture decisions

These seven decisions are settled. They are recorded here so the agent does not relitigate them mid-build, and so a future reader understands why the code looks the way it does. P1-ADR-07 was added after the v1.0 baseline and **amends** §4.5, §5.6, §7.1, §9.3 and §10.5; where it and an unamended sentence elsewhere disagree, the ADR wins.

### P1-ADR-01 · PostgreSQL is the single source of truth. Firebase is an identity broker only.

| | |
|---|---|
| **Decision**    | Every user record, credential hash, profile field, session, and audit entry lives in PostgreSQL. Firebase Auth is used for exactly one job: verifying that a Google or Facebook sign-in really happened. Firestore, Firebase Realtime Database, and Firebase-managed email/password accounts are **not** used. |
| **Why**         | Two writable stores holding the same user means a permanent reconciliation problem — which one is authoritative when they disagree? A fitness app also stores special-category health data (weight, injuries, body composition later), and keeping it inside one boundary we control is the simpler privacy story. Firebase earns its place because Google and Facebook OAuth done by hand is fiddly and easy to get subtly wrong, and because FCM will be wanted in a later phase. |
| **Shape**       | Mobile app runs the Firebase client SDK → obtains a Firebase ID token → posts it to our API → `firebase-admin` verifies the signature server-side → we find or create the Postgres user → **we** issue our own Gymak token pair. The Firebase token never travels further than that one endpoint and is never trusted as a session. |
| **Consequence** | Email/password registration does not touch Firebase at all. There is one Postgres `users` row per human, and social identities hang off it in a child table, so one person signing in with Google and later with email lands on the same account. |

### P1-ADR-02 · Self-issued JWT access tokens with opaque rotating refresh tokens

| | |
|---|---|
| **Decision** | Access token: JWT, 15-minute lifetime, signed with Ed25519 (EdDSA). Carries `sub`, `tv` (token version), `iat`, `exp`, `jti`, `aud` and nothing else. Refresh token: 256 bits of opaque entropy, stored only as a SHA-256 hash, 60-day lifetime, single-use, rotated on every exchange. |
| **Why**      | A stateless access token keeps the hot path free of database reads. Statefulness lives in the refresh token, which is where revocation actually needs to work. Reuse of a consumed refresh token is the standard signal of theft, and invalidating the entire family on reuse is the standard response. |
| **Rules**    | No profile data, no email, and no health field ever goes inside a token. Bumping `users.token_version` invalidates every outstanding access token for that user instantly — used on password reset, logout-all, and account deletion. |

### P1-ADR-03 · `users` and `profiles` are separate tables

`users` holds identity and credentials. `profiles` holds the body and preference data from the Settings screen, one-to-one, created when onboarding completes. The split keeps the auth module free of domain knowledge (SRS §2.5) and lets onboarding be partially saved and resumed without an account existing in a half-valid state. A user with no profile row is a legitimate state: it means onboarding is unfinished, and the app routes them back into it.

### P1-ADR-04 · Password reset is an emailed code exchanged for a reset token

> **Code format and hashing amended by P1-ADR-07.** The three-step shape below is unchanged and still correct; only the code's alphabet, length and at-rest hashing are superseded.

Three steps, not one. `forgot` sends a code; `verify-code` exchanges a correct code for a short-lived single-purpose reset token; `reset` spends that token to set the new password. The intermediate token means the code is never re-sent over the wire and never sits in app state while the user types a new password. Codes are hashed at rest, valid for 10 minutes, single use, capped at 5 attempts, and the `forgot` endpoint returns `202` whether or not the email exists so it cannot be used to enumerate accounts. The code is a typed short string rather than a clicked link — see P1-ADR-07's rejected alternative for why, and for the conditions under which that should be revisited.

### P1-ADR-05 · Email delivery sits behind an interface, with a console backend for development

Define `EmailSender` with one method. Ship two implementations: a console sender that prints the message during development and tests, and an HTTP sender for the production provider (Resend or Brevo — see §13). No application code imports a provider SDK directly, so swapping providers is a one-file change and tests never send real mail.

### P1-ADR-06 · UUID v7 primary keys, generated in the application

Keys are UUID v7 — time-ordered, so index locality stays close to a sequence, while remaining safe to expose in URLs. PostgreSQL 16 has no native `uuidv7()`, so generate them in Python (`uuid6` package, `uuid7()`) and pass them explicitly on insert rather than relying on a server default. Do not use auto-increment integers: they leak user counts and make offline-generated identifiers impossible in later phases.

### P1-ADR-07 · Reset codes are peppered with a key outside the database, not merely salted with a value inside it

> **This ADR amends §4.5, §5.6, §7.1, §9.3 and §10.5. It was raised during T-02 review, before any reset code was implemented. T-07 must not ship the superseded design.**

| | |
|---|---|
| **Superseded design**    | 6 decimal digits, stored as `SHA-256(user_id ‖ code)`. |
| **Why it fails**         | The salt is `user_id`, which is stored **in the same row** as the hash, and the search space is 10⁶ with no key stretching. Anyone who can read one row recovers the plaintext code offline in well under a second — a single SHA-256 pass over a million candidates. Hashing therefore contributes almost nothing against the attacker who matters here. Worse, it is not limited to accounts already mid-reset: `/auth/password/forgot` is unauthenticated and always returns `202`, so an attacker with read access can **induce** a fresh code for any address, read it, and take over that account on demand. Read access to `password_reset_codes` is account takeover of arbitrary users, not a data leak. |
| **Decision**             | Two independent changes. **(a) Keyed hash:** store `HMAC-SHA256(key=RESET_CODE_PEPPER, msg=user_id ‖ code)`. `RESET_CODE_PEPPER` is a required environment variable (Appendix A.1) and never enters the database. **(b) Longer code:** 8 characters drawn with `secrets.choice` from the 30-character reduced Base32 alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ234567` — RFC 4648 Base32 (`A–Z`, `2–7`) with the visually ambiguous `I` and `O` removed. `0`, `1` and lowercase `l` are absent from that alphabet already; input is uppercased before comparison. |
| **Which one carries it** | Be precise about this, because it decides what may be traded away. **The pepper is the control that defeats offline recovery**: without the key, an attacker holding the whole table cannot compute a single candidate hash, whatever the code length. **The code length defeats online guessing** and buys margin if the pepper is ever compromised too — 30⁸ ≈ 6.6 × 10¹¹ (~39 bits) against 10⁶ (~20 bits). Note that 39 bits is *not* itself sufficient against offline search on a fast unkeyed hash, so length is defence in depth and the pepper is load-bearing, not the reverse. |
| **If UX keeps 6 digits** | Acceptable, but then **(a) is mandatory rather than defence-in-depth**, and the §5.6 attempt cap plus the per-email rate limit become the only barriers to online guessing. Do not drop both. |
| **Rejected alternative** | A random link token — `secrets.token_urlsafe(32)`, 256 bits, stored as a plain SHA-256 — would make the brute-force concern moot outright: no pepper needed, no code length to argue about, because 2²⁵⁶ is not searchable whether or not the hash is keyed. It was **not** chosen, for four reasons. **1.** P1-ADR-04 deliberately picked a typed code exchanged for a reset token so the code never sits in app state and is never re-sent over the wire; a link inverts that. **2.** A 43-character token cannot be typed, so the flow becomes click-a-link, which requires universal links / Android App Links — native configuration that is out of Phase 1 scope. **3.** A link breaks when the user reads mail on a different device from the app. **4.** Mail scanners and corporate proxies pre-fetch links and can silently consume a single-use token. **Revisit in Phase 2**, where email verification (Appendix A.3) needs link infrastructure anyway — at that point the reset flow can share it and this ADR should be reopened. |
| **Consequence**          | `RESET_CODE_PEPPER` joins the fail-fast required secrets, so a deployment missing it will not start rather than silently falling back to an unkeyed hash. Rotating the pepper invalidates every outstanding reset code, which is acceptable against a 10-minute TTL. The client-side input is no longer digits-only: §7.1's `code` rule, §9.3 screen 5 and §10.5's `GOtpInput` contract are amended to 8 alphanumeric boxes, uppercase-normalised, ambiguous characters rejected on paste. |

## 3 · Repository layout

One repository, two top-level applications. Module boundaries mirror SRS §2.5, so a module can be lifted out later without redesigning its interface.

```text
gymak/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app factory, router mounting, middleware
│   │   ├── config.py                # pydantic-settings, all env vars, fails fast if missing
│   │   ├── database.py              # async engine, session factory, RLS session variable
│   │   ├── core/
│   │   │   ├── security.py          # Argon2id hashing, JWT sign/verify, token generation
│   │   │   ├── dependencies.py      # get_current_user, get_db, require_active
│   │   │   ├── errors.py            # AppError hierarchy + problem+json handler
│   │   │   ├── rate_limit.py        # Redis-backed or in-memory fixed-window limiter
│   │   │   ├── logging.py           # structured JSON logs + redaction allowlist
│   │   │   └── ids.py               # uuid7() helper
│   │   ├── models/                  # SQLAlchemy 2.0 declarative models
│   │   │   ├── user.py  identity.py  refresh_token.py
│   │   │   ├── profile.py  reset_code.py  audit.py
│   │   ├── schemas/                 # Pydantic v2 request/response models
│   │   │   ├── auth.py  profile.py  common.py
│   │   ├── repositories/            # ALL database access lives here, user-scoped by signature
│   │   │   ├── user_repo.py  profile_repo.py  token_repo.py  audit_repo.py
│   │   ├── services/                # business logic, no HTTP objects, no raw SQL
│   │   │   ├── auth_service.py  social_service.py
│   │   │   ├── password_reset_service.py  profile_service.py  audit_service.py
│   │   ├── routers/                 # thin HTTP layer: validate, call service, shape response
│   │   │   ├── auth.py  profile.py  account.py  health.py
│   │   └── integrations/
│   │       ├── firebase.py          # admin SDK init + verify_id_token
│   │       └── email/  base.py console.py http_provider.py templates/
│   ├── alembic/versions/
│   ├── tests/
│   │   ├── conftest.py              # testcontainers Postgres, app client, factories
│   │   ├── unit/  integration/  security/
│   ├── pyproject.toml  .env.example  openapi.json  README.md
└── mobile/
    ├── app/                         # expo-router file-based routes
    │   ├── _layout.tsx              # providers: query, i18n, theme, session gate
    │   ├── (auth)/  welcome.tsx login.tsx register.tsx
    │   │            forgot-password.tsx verify-code.tsx new-password.tsx
    │   ├── (onboarding)/ _layout.tsx step-1..step-6.tsx review.tsx
    │   └── (app)/   _layout.tsx home.tsx settings.tsx
    ├── src/
    │   ├── theme/     tokens.ts  typography.ts  useTheme.ts
    │   ├── components/ GButton.tsx GTextInput.tsx GOtpInput.tsx GSelectCard.tsx
    │   │               GProgressBar.tsx GScreen.tsx GLogo.tsx GErrorBanner.tsx
    │   ├── api/       client.ts  auth.ts  profile.ts  errors.ts
    │   ├── auth/      session.ts  storage.ts  useSession.ts  firebase.ts
    │   ├── i18n/      index.ts  ar.json  en.json
    │   └── validation/ schemas.ts
    ├── assets/  logo.png  icon.png  splash.png
    └── app.json  package.json  tsconfig.json  .env.example
```

> **The layering rule, enforced by review**
>
> Routers may not import models. Services may not import HTTP objects. Repositories are the only place a SQLAlchemy query is written, and every repository function that reads user-owned data takes `user_id` as a mandatory first argument. A route handler that forgets an ownership check therefore cannot leak data, because there is no repository function that would let it.

## 4 · Data model

Six tables. Nothing else is created in Phase 1. Every timestamp is `timestamptz` stored in UTC; the client applies the user's zone. Every table gets `created_at`, and every mutable table gets `updated_at` maintained by a trigger.

### 4.1 users

| Column         | Type        | Constraints            | Notes                                                                            |
|----------------|-------------|------------------------|----------------------------------------------------------------------------------|
| id             | uuid        | PK                     | UUID v7, generated in Python (P1-ADR-06)                                         |
| email          | citext      | UNIQUE, NOT NULL       | Case-insensitive so `A@x.com` and `a@x.com` cannot both register                 |
| password_hash  | text        | NULL allowed           | NULL for accounts created purely through a social provider                       |
| email_verified | boolean     | NOT NULL DEFAULT false | True immediately for social sign-ins where the provider asserts a verified email |
| token_version  | int         | NOT NULL DEFAULT 0     | Incremented to kill every outstanding access token at once                       |
| is_active      | boolean     | NOT NULL DEFAULT true  | False blocks login with `403 ACCOUNT_DISABLED`                                   |
| last_login_at  | timestamptz | NULL                   | Updated on successful login and successful refresh                               |
| created_at     | timestamptz | NOT NULL DEFAULT now() |                                                                                  |
| updated_at     | timestamptz | NOT NULL DEFAULT now() | Trigger-maintained                                                               |
| deleted_at     | timestamptz | NULL                   | Set on a deletion request; a purge job (later phase) reads this column           |

A row with `deleted_at IS NOT NULL` is invisible to every query except the purge job. Login against a deleted account returns the same generic `401 INVALID_CREDENTIALS` as a wrong password.

### 4.2 user_identities

| Column            | Type        | Constraints                    | Notes                                                                       |
|-------------------|-------------|--------------------------------|-----------------------------------------------------------------------------|
| id                | uuid        | PK                             |                                                                             |
| user_id           | uuid        | FK users(id) ON DELETE CASCADE |                                                                             |
| provider          | text        | CHECK IN ('google','facebook','apple') | `'apple'` is allowed by the check now so the later phase needs no migration |
| provider_uid      | text        | NOT NULL                       | The provider's stable subject identifier                                    |
| firebase_uid      | text        | NOT NULL                       | Kept for support and debugging                                              |
| email_at_provider | citext      | NULL                           | Facebook may not return one; that is expected, not an error                 |
| created_at        | timestamptz | NOT NULL DEFAULT now()         |                                                                             |

**UNIQUE (provider, provider_uid)** — the same Google account cannot attach to two Gymak users.

### 4.3 profiles — the Settings data

| Column                  | Type         | Constraints                                                  | Notes                                                                                               |
|-------------------------|--------------|--------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| user_id                 | uuid         | PK, FK users(id) ON DELETE CASCADE                           | One-to-one, no surrogate key                                                                        |
| name                    | text         | NOT NULL, length 2–60                                        | Display name, trimmed, collapsed whitespace                                                         |
| gender                  | text         | CHECK IN ('male','female')                                   | Required: it selects the Mifflin-St Jeor branch in a later phase, and is not a social question here |
| birth_date              | date         | NOT NULL, age 13–100                                         | Drives P1-SAF-001; stored as a date, never as an age                                                |
| height_cm               | numeric(5,1) | CHECK BETWEEN 100 AND 250                                    | Always centimetres on the wire, regardless of display units                                         |
| weight_kg               | numeric(5,2) | CHECK BETWEEN 30 AND 300                                     | Confirmed by decision 13.1.1 and shipped in T-02                                                    |
| goal                    | text         | CHECK IN ('lose','gain','maintain')                          |                                                                                                     |
| experience_level        | text         | CHECK IN ('beginner','intermediate','advanced')              | Maps to the SRS volume landmark bands in a later phase                                              |
| activity_level          | text         | CHECK IN ('sedentary','light','moderate','high','very_high') | Confirmed by decision 13.1.1 and shipped in T-02                                                    |
| unit_system             | text         | CHECK IN ('metric','imperial') DEFAULT 'metric'              | Display concern only; storage and the API are always SI                                             |
| language                | text         | CHECK IN ('ar','en') DEFAULT 'ar'                            |                                                                                                     |
| onboarding_completed    | boolean      | NOT NULL DEFAULT false                                       | Flips true only when every NOT NULL field is satisfied                                              |
| created_at / updated_at | timestamptz  | NOT NULL                                                     |                                                                                                     |

> **Why units and language live on the server**
>
> They are read on the very first render after a fresh install on a new device, before any local preference exists. Keeping them server-side means a user who reinstalls does not land in the wrong language with the wrong units, and the same values are available later to render an email in Arabic.

### 4.4 refresh_tokens

| Column          | Type        | Notes                                                                                     |
|-----------------|-------------|-------------------------------------------------------------------------------------------|
| id              | uuid        | PK                                                                                        |
| user_id         | uuid        | FK users(id) ON DELETE CASCADE                                                            |
| token_hash      | text        | UNIQUE. SHA-256 of the raw token. The raw value exists only in the response body, once.   |
| family_id       | uuid        | Constant across a rotation chain. One family = one device session.                        |
| parent_id       | uuid        | NULL for the first token in a family. Lets the chain be reconstructed during an incident. |
| expires_at      | timestamptz | Issued at + 60 days. Rotation does not extend the family beyond this.                     |
| consumed_at     | timestamptz | Set the moment the token is exchanged. A second exchange is a reuse event.                |
| revoked_at      | timestamptz | Set on logout, on family invalidation, on password reset, on account deletion.            |
| user_agent / ip | text / inet | Captured at issue for the future "active sessions" screen. Not shown in Phase 1.          |

### 4.5 password_reset_codes

> **Amended by P1-ADR-07.** The original `SHA-256(user_id ‖ 6 digits)` is **superseded** and must not be implemented: the salt lived in the same row as the hash over a 10⁶ space, making every code recoverable offline in under a second by anyone who could read the table. Read the ADR before writing T-07.

| Column        | Type        | Notes                                                                                                              |
|---------------|-------------|--------------------------------------------------------------------------------------------------------------------|
| id / user_id  | uuid        | PK / FK CASCADE                                                                                                    |
| code_hash     | text        | `HMAC-SHA256(key=RESET_CODE_PEPPER, msg=user_id ‖ code)`. The pepper comes from the environment and is never stored. Never store the code itself. |
| expires_at    | timestamptz | Issued at + `RESET_CODE_TTL_SECONDS` (default 10 minutes). Enforced in the SQL `WHERE`, never in Python after fetch. |
| attempt_count | int         | NOT NULL DEFAULT 0, hard stop at 5. Incremented on every failed verify, including expired ones.                     |
| consumed_at   | timestamptz | Single use. Set in the same statement that redeems the code, so a concurrent second redemption updates zero rows.   |
| requested_ip  | inet        | For abuse investigation                                                                                            |

Requesting a new code marks every previous unconsumed code for that user as consumed, so only the newest code works.

The column set is unchanged by the ADR — only what goes **into** `code_hash`, and how the other three columns are enforced. The T-02 migration therefore needed no amendment.

### 4.6 audit_log

Append-only. The application role holds `INSERT` and `SELECT` only — no `UPDATE`, no `DELETE` grant, enforced at the database level rather than by convention.

| Column             | Type        | Notes                                                                                                                                                                                                                                                                               |
|--------------------|-------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| id                 | uuid        | PK                                                                                                                                                                                                                                                                                  |
| actor_user_id      | uuid        | **No foreign key** — see the note below. NULL for anonymous actions such as a failed login on an unknown email.                                                                                                                                                                     |
| action             | text        | `user.registered`, `user.login_succeeded`, `user.login_failed`, `user.social_linked`, `token.refreshed`, `token.reuse_detected`, `token.family_revoked`, `password.reset_requested`, `password.reset_completed`, `profile.created`, `profile.updated`, `account.deletion_requested` |
| entity / entity_id | text / uuid | What was acted on                                                                                                                                                                                                                                                                   |
| metadata           | jsonb       | Changed field names and values for profile edits. **Never** a password, token, or reset code.                                                                                                                                                                                       |
| ip / user_agent    | inet / text |                                                                                                                                                                                                                                                                                     |
| created_at         | timestamptz | NOT NULL DEFAULT now()                                                                                                                                                                                                                                                              |

> **Why `actor_user_id` carries no foreign key (A-02)**
>
> Every referential action Postgres could take here needs a privilege this table deliberately withholds: `ON DELETE CASCADE` needs `DELETE`, `SET NULL` needs `UPDATE`, and even `NO ACTION` needs the check to run against a table the app role may only append to. Beyond the grants, the intent settles it — an audit row describing an account must survive that account. The column is a plain uuid, and referential integrity here is the application's job, not the database's.

### 4.7 DDL extract — this is what the T-02 migration shipped

```sql
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
  id             uuid PRIMARY KEY,
  email          citext NOT NULL UNIQUE,
  password_hash  text,
  email_verified boolean NOT NULL DEFAULT false,
  token_version  int NOT NULL DEFAULT 0,
  is_active      boolean NOT NULL DEFAULT true,
  last_login_at  timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
-- chk_credential_present was DROPPED in T-06 (migration 2b58d76b93fb).
  -- §5.4 step 5 requires a user with no password and an unverified placeholder
  -- email, which the constraint rejected. The real invariant is three-way —
  -- password, OR verified email, OR a linked identity — and Postgres cannot
  -- express it in a single-table CHECK. It now lives in social_service.py,
  -- which writes the user and identity rows in one transaction. See A.5 item 14.
);
CREATE UNIQUE INDEX uq_users_email_live ON users (email) WHERE deleted_at IS NULL;

CREATE TABLE profiles (
  user_id              uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  name                 text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 2 AND 60),
  gender               text NOT NULL CHECK (gender IN ('male','female')),
  birth_date           date NOT NULL CHECK (
                         birth_date <= current_date - INTERVAL '13 years' AND
                         birth_date >= current_date - INTERVAL '100 years'),
  height_cm            numeric(5,1) NOT NULL CHECK (height_cm BETWEEN 100 AND 250),
  weight_kg            numeric(5,2) CHECK (weight_kg BETWEEN 30 AND 300),
  goal                 text NOT NULL CHECK (goal IN ('lose','gain','maintain')),
  experience_level     text NOT NULL CHECK (experience_level IN
                         ('beginner','intermediate','advanced')),
  activity_level       text CHECK (activity_level IN
                         ('sedentary','light','moderate','high','very_high')),
  unit_system          text NOT NULL DEFAULT 'metric'
                         CHECK (unit_system IN ('metric','imperial')),
  language             text NOT NULL DEFAULT 'ar' CHECK (language IN ('ar','en')),
  onboarding_completed boolean NOT NULL DEFAULT false,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  text NOT NULL UNIQUE,
  family_id   uuid NOT NULL,
  parent_id   uuid REFERENCES refresh_tokens(id) ON DELETE SET NULL,
  expires_at  timestamptz NOT NULL,
  consumed_at timestamptz,
  revoked_at  timestamptz,
  user_agent  text,
  ip          inet,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_rt_user_active ON refresh_tokens (user_id)
  WHERE consumed_at IS NULL AND revoked_at IS NULL;
CREATE INDEX idx_rt_family ON refresh_tokens (family_id);

-- Row-level security: a second, independent barrier behind repository scoping.
-- FORCE is not optional. Postgres exempts a table's OWNER from its own policies,
-- and gymak_app both runs the migration and serves the application, so without
-- FORCE the policies below are decorative: enabled, present, and protecting nothing.
ALTER TABLE profiles       ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles       FORCE  ROW LEVEL SECURITY;
ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE refresh_tokens FORCE  ROW LEVEL SECURITY;

-- NULLIF is not cosmetic either. After a transaction ends, the reset value of
-- app.user_id is the empty string, not NULL, and ''::uuid is a hard Postgres
-- error. NULLIF makes an unset variable fail closed instead of raising.
CREATE POLICY p_profiles_owner ON profiles
  USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY p_refresh_tokens_owner ON refresh_tokens
  USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

-- T-05 addition. SELECT ... FOR UPDATE is checked against the UPDATE policy,
-- not the SELECT one, so a pre-auth lookup could not lock its own row: the
-- owner is unknown until the row is found, and the row is invisible until the
-- owner is bound. Resolved with a permissive read policy plus a two-phase
-- lookup in token_repo (unscoped peek to discover the owner, bind, then a
-- correctly scoped locking read).
CREATE POLICY p_refresh_tokens_lookup ON refresh_tokens FOR SELECT USING (true);

-- audit_log has no RLS. Its protection is the grant: INSERT and SELECT only.
-- users, user_identities and password_reset_codes have no RLS either: all three
-- are read in pre-auth flows where app.user_id does not exist yet.

-- The application must connect as a NON-superuser role, asserted at startup,
-- otherwise RLS is silently bypassed and this whole barrier is decorative.
```

> **The role split has landed (A-12, closes A.5 items 1, 11).** `gymak_migrator` owns the schema and runs Alembic (migrations `737d03a7c353`, `ae026cea6d8d`); `gymak_app` holds DML only — `SELECT`/`INSERT`/`UPDATE`/`DELETE` on the specific tables each repository actually touches, granted by the migration itself since `gymak_migrator`, as table owner, is the only role with authority to grant on them. `gymak_app` can no longer `DROP POLICY`, `ALTER TABLE`, `CREATE TABLE`, or — the gap that made `audit_log`'s append-only grant self-revocable even before this split — re-`GRANT` itself privileges back on a table it used to own. Neither role is a superuser; `app/database.py`'s startup assertion now also refuses any connection that can `CREATE` in schema `public`, so a misconfigured `DATABASE_URL` pointed at `gymak_migrator` fails closed instead of silently serving traffic with DDL privilege. See `tests/security/test_rls.py`'s "A.5 item 1" section for the tests proving each of these is refused, not merely unexercised.
>
> **FORCE is kept, deliberately, even though it is no longer load-bearing for `gymak_app`.** A non-owner is always subject to RLS regardless of `FORCE` — that attribute only ever exempted the table's *owner*. Since `gymak_app` is never the owner post-split, `FORCE` is redundant for it specifically. But `gymak_migrator` *is* the owner, and is also the one role a human might reasonably connect as directly for an ad hoc production fix; `FORCE` is what stops that connection from silently bypassing RLS too. It costs nothing and reverses cleanly on downgrade — belt-and-braces protecting against an operator mistake, not decoration.
>
> **`CREATE EXTENSION citext` no longer needs a human running SQL by hand (A.5 item 11, answers §13.2 item 8).** The original assumption that it requires a superuser was wrong for Postgres 13+: `citext` is a "trusted" extension, installable by any non-superuser role holding `CREATE` on the *database* — confirmed empirically against a real container, not assumed; the schema-level `CREATE` one might expect instead is not sufficient and fails with a different error. `gymak_migrator` holds `CREATE` on the database for exactly this reason, so `alembic upgrade head` creates the extension itself, as part of the same migration that always ran it (`ba41f8eb5985`), with no separate manual step. A fresh deployment — local or managed-host — completes with zero SQL run by hand, once the two roles themselves are provisioned (see `backend/README.md`).

## 5 · API contract

#### Conventions

- Base path `/api/v1`. A breaking change means a new path, never a silent contract change.
- JSON in, JSON out, UTF-8. Errors use `application/problem+json` per §7.2.
- Authentication is `Authorization: Bearer <access_token>`. Refresh happens only against `/auth/refresh`, never as a side effect of another call.
- Units are SI on the wire, always: kilograms and centimetres. Imperial is a client display concern.
- Times are ISO 8601 with an explicit offset; the server always returns UTC.
- Email addresses are lowercased and trimmed before any lookup or insert.

### 5.1 Endpoint catalogue

| Method | Path                       | Auth        | Purpose                                                  | Req         |
|--------|----------------------------|-------------|----------------------------------------------------------|-------------|
| POST   | /auth/register             | none        | Create an email/password account and return a token pair | P1-FR-001   |
| POST   | /auth/login                | none        | Exchange credentials for a token pair                    | P1-FR-002   |
| POST   | /auth/social/{provider}    | none        | Exchange a Firebase ID token for a Gymak token pair      | P1-FR-003/4 |
| POST   | /auth/refresh              | refresh     | Rotate the refresh token, issue a new pair               | P1-FR-005   |
| POST   | /auth/logout               | bearer      | Revoke the current token family                          | P1-FR-007   |
| POST   | /auth/logout-all           | bearer      | Revoke every family and bump token_version               | P1-FR-007   |
| POST   | /auth/password/forgot      | none        | Email a single-use reset code (format per P1-ADR-07)     | P1-FR-008   |
| POST   | /auth/password/verify-code | none        | Exchange a valid code for a reset token                  | P1-FR-008   |
| POST   | /auth/password/reset       | reset token | Set a new password, revoke all sessions                  | P1-FR-008   |
| GET    | /auth/me                   | bearer      | Current user plus onboarding state — the app's boot call | P1-FR-010   |
| POST   | /profile                   | bearer      | Complete onboarding, once                                | P1-FR-010   |
| GET    | /profile                   | bearer      | Read the profile                                         | P1-FR-011   |
| PATCH  | /profile                   | bearer      | Edit profile fields from Settings                        | P1-FR-011   |
| DELETE | /account                   | bearer      | Request account deletion                                 | P1-FR-012   |
| GET    | /health                    | none        | Liveness plus database reachability                      | —           |

### 5.2 POST /auth/register

```http
POST /api/v1/auth/register
{ "email": "nabil@example.com", "password": "correct horse battery",
  "language": "ar" }              // optional, defaults to 'ar', used for the email locale

--- 201 Created ---
{ "access_token": "eyJhbGci...", "token_type": "bearer", "expires_in": 900,
  "refresh_token": "9f3c...", "refresh_expires_in": 5184000,
  "user": { "id": "018f...", "email": "nabil@example.com",
            "onboarding_completed": false } }
```

| | |
|---|---|
| **Behaviour** | Lowercase and trim the email. If a live user already holds it, return `409 EMAIL_ALREADY_REGISTERED` — this endpoint is the one place account enumeration is accepted, because a registration form that silently succeeds on a taken email is worse for the user than the disclosure is for security. Hash the password, insert the user, issue the token pair, write `user.registered` to the audit log. |
| **Errors**    | 409 EMAIL_ALREADY_REGISTERED · 422 VALIDATION_ERROR · 429 RATE_LIMIT_EXCEEDED (with `Retry-After`) |
| **Note**      | No profile row is created here. The client sees `onboarding_completed: false` and routes into onboarding. |

### 5.3 POST /auth/login

```http
{ "email": "nabil@example.com", "password": "correct horse battery" }
--- 200 OK ---  // identical shape to register
```

| | |
|---|---|
| **Behaviour** | One generic failure for every cause: wrong password, unknown email, social-only account with no password, soft-deleted account. All return `401 INVALID_CREDENTIALS` with the same body and, as far as practical, similar timing — always run the hash verification against a dummy hash when the user is not found, so the response time does not reveal whether the email exists. |
| **Inactive**  | `is_active = false` is the one exception: `403 ACCOUNT_DISABLED`, because the user needs to know why. |
| **Audit**     | `user.login_succeeded` or `user.login_failed` (with `actor_user_id` null when the email is unknown). |

### 5.4 POST /auth/social/{provider}

```http
POST /api/v1/auth/social/google        // provider ∈ google in Phase 1; facebook deferred to Phase 2 (13.1.2)
{ "id_token": "<firebase ID token from the client SDK>" }

--- 200 OK ---
{ ...token pair..., "user": {...}, "is_new_user": true }
```

**Server algorithm — implement in exactly this order:**

1.  Verify the token with `firebase_admin.auth.verify_id_token(id_token, check_revoked=True)`. Any failure → `401 SOCIAL_TOKEN_INVALID`. Never decode it manually.
2.  Assert that the `firebase.sign_in_provider` claim matches the `{provider}` in the path. A mismatch → `401 SOCIAL_TOKEN_INVALID`. Without this check, a Google token would be accepted at the Facebook endpoint.
3.  Look up `user_identities` by `(provider, provider_uid)`. Found → that is the user; go to step 6.
4.  Not found, and the token carries a **verified** email that matches a live `users.email` → link: insert the identity row against that existing user, and audit `user.social_linked`. This is what makes "I signed up with email, now I tapped Google" work instead of creating a duplicate person.
5.  Not found and no matching email → create the user (`password_hash` NULL, `email_verified` from the provider claim) plus the identity row. If the provider returned no email at all, generate a placeholder of the form `fb_{provider_uid}@social.gymak.local`, set `email_verified = false`, and flag the account so Settings can prompt for a real address later.
6.  Issue the Gymak token pair. Return `is_new_user` so the client knows whether to route to onboarding or to home.

> **Do not trust the client's claim about who it is**
>
> The provider, the uid, and the email all come from the verified token — never from the request body. The body carries exactly one field: `id_token`.

### 5.5 POST /auth/refresh

```http
{ "refresh_token": "9f3c..." }
--- 200 OK ---  // a NEW access token and a NEW refresh token; the old one is dead
```

**Algorithm, inside one database transaction with the row locked (`SELECT ... FOR UPDATE`):**

1.  Hash the presented token, look it up. No row → `401 TOKEN_INVALID`.
2.  `consumed_at IS NOT NULL` → **reuse detected.** Revoke every token in that `family_id`, audit `token.reuse_detected` and `token.family_revoked`, return `401 TOKEN_REUSED`. The legitimate holder is forced to log in again; that is the intended, correct outcome.
3.  `revoked_at IS NOT NULL` or expired → `401 TOKEN_INVALID` / `401 TOKEN_EXPIRED`.
4.  User missing, soft-deleted, or inactive → `401 TOKEN_INVALID`.
5.  Mark consumed, insert the successor with the same `family_id` and `parent_id` set, issue a fresh access token, update `last_login_at`.

> **Client-side contract for this endpoint**
>
> The app must serialise refresh calls through a single-flight lock. Two screens each firing a refresh with the same token will make the second one look exactly like theft and log the user out. This is the most common way this design gets implemented wrong — see §9.5.

### 5.6 Password reset — the three calls

```http
POST /api/v1/auth/password/forgot
{ "email": "nabil@example.com" }
--- 202 Accepted ---
{ "message": "If an account exists for that address, a code has been sent." }
// Always 202. Same body, same latency envelope, whether or not the account exists.
// Send the mail on a background task so a slow provider cannot be used as an oracle.

POST /api/v1/auth/password/verify-code
{ "email": "nabil@example.com", "code": "K7M2QXR4" }   // 8 chars, P1-ADR-07 alphabet
--- 200 OK ---
{ "reset_token": "rt_7f2b...", "expires_in": 300 }
// Opaque, single-purpose, single-use, 5 minutes. Not a JWT, not a session token.

POST /api/v1/auth/password/reset
{ "reset_token": "rt_7f2b...", "new_password": "..." }
--- 204 No Content ---
// Sets the hash, bumps token_version, revokes every refresh family,
// consumes the code and the reset token, audits password.reset_completed,
// and sends a "your password was changed" notification email.
```

| Rule                | Value                                                                                                     |
|---------------------|-----------------------------------------------------------------------------------------------------------|
| Code format         | **Amended by P1-ADR-07.** 8 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ234567`, drawn with `secrets.choice` — never `random`. Uppercase the submitted value before comparing. (Was: 6 digits.) |
| Code storage        | **Amended by P1-ADR-07.** `HMAC-SHA256(key=RESET_CODE_PEPPER, msg=user_id ‖ code)`. The pepper is a required environment variable and is never written to the database. (Was: salted SHA-256.) |
| Code lifetime       | 10 minutes (`RESET_CODE_TTL_SECONDS`)                                                                     |
| Attempts per code   | 5, then the code is burned and returns `429 RESET_CODE_ATTEMPTS_EXCEEDED`                                 |
| Requests per email  | 3 per hour, keyed on the **submitted** address whether or not it resolves to a live account — see below   |
| Requests per IP     | 10 per hour                                                                                               |
| Comparison          | `secrets.compare_digest` on the HMAC digests, constant time                                               |
| Social-only account | Still returns 202 and still sends nothing. Do not reveal that the account has no password.                |
| Effect on sessions  | Every device is logged out. This is deliberate: a password reset is the recovery path after a compromise. |

> **The per-email rate limit must not become the enumeration oracle the 202 exists to prevent**
>
> Count the attempt against the submitted address **before** looking the user up, and increment it identically for an unknown address, a social-only account, and a live one. An implementation that only counts when the account exists turns the `429` / `202` difference into a reliable "does this email have an account" probe — which defeats §5.6's entire always-202 design more cheaply than the flow it was protecting. The `202` body, status and latency envelope are unchanged by this amendment; the only observable difference on a tripped limit is `429 RATE_LIMIT_EXCEEDED` with `Retry-After`, and it must be reachable for an address that has never registered.

**Enforcement, all of it in SQL — implement in T-07 (error codes are already defined in `app/core/errors.py`):**

| Case                              | Rule                                                                                                                                                                     | Error                                     |
|-----------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------|
| Expired code                      | `expires_at > now()` belongs in the `WHERE` clause of the lookup, not in a Python check after the row is fetched. A fetch-then-compare leaves a window where a row that the database would have rejected is still acted upon. | `422 RESET_CODE_EXPIRED`                  |
| Wrong or unknown code             | No row matched the keyed digest                                                                                                                                           | `422 RESET_CODE_INVALID`                  |
| Sixth attempt                     | `attempt_count` incremented on **every** failed verify — including a failure caused by expiry — and the code is dead once it passes the configured maximum                  | `429 RESET_CODE_ATTEMPTS_EXCEEDED`        |
| Concurrent redemption             | Set `consumed_at` in the **same** `UPDATE ... WHERE consumed_at IS NULL` that redeems the code, and treat a zero-row result as failure. Two simultaneous redemptions must leave exactly one winner; a read-then-write cannot guarantee that. | `422 RESET_CODE_INVALID`                  |
| Spent or unknown reset token      | The 5-minute token from `verify-code`, hashed at rest, single use                                                                                                         | `401 RESET_TOKEN_INVALID`                 |
| Per-email or per-IP limit tripped | See the oracle note above                                                                                                                                                | `429 RATE_LIMIT_EXCEEDED` + `Retry-After` |

### 5.7 GET /auth/me — the app's boot call

```http
--- 200 OK ---
{ "user": { "id": "018f...", "email": "nabil@example.com",
            "email_verified": true, "created_at": "2026-07-30T09:12:04Z",
            "auth_methods": ["password","google"] },
  "onboarding_completed": false,
  "profile": null }        // the full profile object once onboarding is done
```

One round trip decides the whole navigation state: no token → auth stack; token but `onboarding_completed: false` → onboarding stack; otherwise → app stack.

### 5.8 POST /profile — one-time onboarding capture

```http
POST /api/v1/profile
{ "name": "Nabil", "gender": "male", "birth_date": "2008-03-14",
  "height_cm": 178, "weight_kg": 74.5, "goal": "gain",
  "experience_level": "beginner", "activity_level": "moderate",
  "unit_system": "metric", "language": "ar" }

--- 201 Created ---
{ "profile": { ...all fields..., "onboarding_completed": true },
  "derived": { "age": 18 } }   // age is computed, never stored
```

| | |
|---|---|
| **Idempotency** | A profile already exists → `409 PROFILE_ALREADY_EXISTS`. Editing afterwards goes through `PATCH`. This is the "captured once" rule the spec asks for, enforced by the primary key rather than by application politeness. |
| **Safety**      | P1-SAF-001: if the age implied by `birth_date` is under 18 and `goal == 'lose'`, reject with `422 GOAL_NOT_PERMITTED_FOR_MINOR` and a `detail` naming `maintain` and `gain` as the permitted values. This check lives in a pure function, is unit-tested against the boundary (17 years 364 days, exactly 18), and is re-checked on every `PATCH`. |
| **Audit**       | `profile.created` |

### 5.9 PATCH /profile — the Settings surface

| Field                                                                                     | Editable     | Rule                                                                                                                                       |
|-------------------------------------------------------------------------------------------|--------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| name, height_cm, weight_kg, goal, experience_level, activity_level, unit_system, language | Yes          | Partial update; only the keys present in the body are touched                                                                              |
| gender, birth_date                                                                        | Yes, audited | Correcting a typo is legitimate. Every change is written to the audit log with the before and after value, and P1-SAF-001 is re-evaluated. |
| email                                                                                     | No           | Requires a verification flow. Deferred, deliberately, to a later phase.                                                                    |
| onboarding_completed                                                                      | No           | Server-controlled. A client sending it is ignored, not rejected.                                                                           |

```http
PATCH /api/v1/profile
{ "goal": "maintain", "unit_system": "imperial" }
--- 200 OK ---  { "profile": { ... } }
// 422 VALIDATION_ERROR if the body is empty, 404 if no profile exists yet
// (the client should be in onboarding, not in settings).
```

### 5.10 DELETE /account

```http
DELETE /api/v1/account
{ "password": "..." }   // required when password_hash is not null; omitted for social-only accounts
--- 202 Accepted ---
{ "deletion_requested_at": "2026-07-30T09:40:11Z", "purge_after_days": 30 }
```

Sets `deleted_at`, bumps `token_version`, revokes every refresh family, audits `account.deletion_requested`. The physical purge job is a later phase; the 30-day promise is recorded in the response and in the privacy copy, and nothing else in Phase 1 depends on it.

## 6 · Security requirements

### 6.1 Password hashing

| Parameter        | Value                | Note                                                                                         |
|------------------|----------------------|----------------------------------------------------------------------------------------------|
| Algorithm        | Argon2id             | Via `argon2-cffi`. Not bcrypt, not PBKDF2, never SHA-anything alone.                         |
| Memory cost      | 65536 KiB (64 MiB)   | Per SRS §2.7                                                                                 |
| Time cost        | 3 iterations         |                                                                                              |
| Parallelism      | 4                    |                                                                                              |
| Test override    | memory 8 MiB, time 1 | Only under `ENV=test`, or the suite takes minutes. Never in any other environment, and a test asserts that the production values are the default. |
| Rehash on verify | Yes                  | If `hasher.check_needs_rehash()`, transparently upgrade the stored hash on successful login. |

### 6.2 Password policy

- Minimum 8 characters, maximum 128. Length is the only composition rule.
- No forced symbols, no forced digits, no forced mixed case. Those rules produce `Password1!` and nothing safer.
- Reject the local part of the user's own email, and a denylist of common passwords. **(A-07)** The list is not to be invented or hand-written: use the top 1000 entries of SecLists — `https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/10-million-password-list-top-1000.txt` — vendored as a static asset with its source and retrieval date recorded in a comment. A fabricated list is worse than a short one, because it looks complete.
- Unicode is normalised NFKC before hashing so an Arabic or emoji password verifies consistently across devices.
- The password is never written to a log, an error message, an audit entry, or a response body. A test greps the log output of the whole suite to prove it.

### 6.3 Tokens

| Token       | Lifetime     | Form and storage                                                                                                                                                                                                                         |
|-------------|--------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Access      | 15 minutes   | JWT, EdDSA (Ed25519), with the algorithm pinned on verify. Private key from the environment, never in the repository. Claims: `sub`, `tv`, `jti`, `iat`, `exp`, `aud: "gymak-app"`. Verified on every request, including that `tv` equals the user's current `token_version`. |
| Refresh     | 60 days      | 32 random bytes, URL-safe base64. Stored as SHA-256 only. Single use.                                                                                                                                                                    |
| Reset       | 5 minutes    | Opaque random, hashed at rest, single use, accepted only by `/auth/password/reset`.                                                                                                                                                      |
| Firebase ID | provider-set | Accepted only at `/auth/social/{provider}`, verified by the admin SDK, never stored.                                                                                                                                                     |

Generate the Ed25519 keypair once with a documented command, keep the private key in the environment, and expose the public key at a `/.well-known`-style path only if a second service ever needs to verify tokens. In Phase 1 nothing does, so do not build it.

`config.py` accepts either a raw PEM or a base64-wrapped one and normalises `\n` escapes, multiline values and CRLF. **A structurally valid but cryptographically broken key still fails late** — the real `load_pem_private_key` parse belongs at startup. Tracked in §A.5.

> **Never let a key reach a log line.** `pydantic.ValidationError` embeds `input_value='...'` in its message text, so a bad key would otherwise be printed to the terminal and written to the crash log — exactly what §6.5 forbids. Settings construction raises a purpose-built `ConfigurationError` that names the offending field and never carries its value, including for pydantic's own missing-field errors.

### 6.4 Rate limits

| Endpoint                   | Limit                                 | Key                               |
|----------------------------|---------------------------------------|-----------------------------------|
| /auth/register             | 5 / hour                              | IP                                |
| /auth/login                | 10 / 15 min, then exponential backoff | IP + email, whichever trips first |
| /auth/social/*             | 20 / hour                             | IP                                |
| /auth/refresh              | 60 / hour                             | user                              |
| /auth/password/forgot      | 3 / hour per email, 10 / hour per IP  | email, IP                         |
| /auth/password/verify-code | 10 / hour                             | IP + email                        |
| /profile                   | 30 / hour                             | user                              |

Every 429 carries a `Retry-After` header. Implement behind one decorator or dependency so a limit is a single line at the route. Redis if it is already running; otherwise an in-memory fixed-window limiter is acceptable for Phase 1, with a comment marking it as single-instance only.

> **`Retry-After` is a Phase 1 requirement, not a nicety (A-06).** `RateLimited` already carries a tested `retry_after_seconds`, but the exception handler in `core/errors.py` does not yet emit the header, so §6.4, §7.3 and the §11.1 security row are all currently unmet in a way no existing test detects. T-04 owns the fix, and `app/core/errors.py` is in its file list for that reason.

### 6.5 Other required controls

- **Authorisation at the repository layer.** Every user-scoped repository function takes `user_id` as its first parameter. Route handlers never build a query.
- **Row-level security** as the second barrier, with `FORCE` enabled per §4.7, the app connecting as a non-superuser role and asserting that at startup. As of the §A.5 item 1 role split, `gymak_app` holds no DDL at all — it cannot `ALTER TABLE`, `DROP POLICY`, or `CREATE TABLE` — so the barrier is no longer self-revocable from the connection that serves the application. The startup assertion also now refuses any connection that can `CREATE` in schema `public`, closing the misconfiguration path where `DATABASE_URL` accidentally points at `gymak_migrator` instead.
- **Test that a control prevents, not that it functions.** RLS was enabled, policied, and protecting nothing for a full task because the tests only asserted that a permitted read succeeded. An RLS test that can never fail is decoration.
- **Generic 404 over 403** for another user's resource, so the API does not confirm that the record exists.
- **CORS** is closed by default and configurable. Allow only the local development origins and, later, the app's own domain. No `*`.
- **Security headers** on every response: `HSTS`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
- **Structured logging with an allowlist serialiser.** Fields never logged: `password`, `new_password`, `id_token`, `access_token`, `refresh_token`, `reset_token`, `code`, `weight_kg`, `height_cm`, `birth_date`. A careless log statement must not be able to emit them — and neither must a configuration error, per §6.3.
- **No secret in the repository.** `.env` and `.coverage` are gitignored, `.env.example` is committed with placeholder values, and the Firebase service-account JSON is provided as an environment variable or a mounted file, never committed. Secrets are never pasted into a chat window either; anything that was is already burned and must be regenerated.

## 7 · Validation and error contract

### 7.1 Field validation — shared by client and server, server authoritative

| Field            | Rule                                                                                                   | Error code                                         |
|------------------|--------------------------------------------------------------------------------------------------------|----------------------------------------------------|
| email            | RFC-shaped, ≤254 chars, lowercased and trimmed, MX not checked                                         | VALIDATION_ERROR / `email:INVALID`                 |
| password         | 8–128 chars, not in the denylist, NFKC-normalised                                                      | VALIDATION_ERROR / `password:TOO_SHORT\|TOO_COMMON` |
| name             | 2–60 chars after trimming; Arabic and Latin letters, spaces, hyphens, apostrophes; no digits, no emoji | VALIDATION_ERROR / `name:INVALID`                  |
| gender           | `male` \| `female`                                                                                     | VALIDATION_ERROR / `gender:NOT_ALLOWED`            |
| birth_date       | ISO date, age between 13 and 100, not in the future                                                    | VALIDATION_ERROR / `birth_date:OUT_OF_RANGE`       |
| height_cm        | 100–250, one decimal place                                                                             | VALIDATION_ERROR / `height_cm:OUT_OF_RANGE`        |
| weight_kg        | 30–300, two decimal places                                                                             | VALIDATION_ERROR / `weight_kg:OUT_OF_RANGE`        |
| goal             | `lose` \| `gain` \| `maintain`; `lose` blocked under 18                                                | GOAL_NOT_PERMITTED_FOR_MINOR                       |
| experience_level | `beginner` \| `intermediate` \| `advanced`                                                             | VALIDATION_ERROR                                   |
| activity_level   | five-value enum per §4.3                                                                               | VALIDATION_ERROR                                   |
| unit_system      | `metric` \| `imperial`                                                                                 | VALIDATION_ERROR                                   |
| language         | `ar` \| `en`                                                                                           | VALIDATION_ERROR                                   |
| code             | exactly 8 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ234567`, case-insensitive on input (P1-ADR-07)       | RESET_CODE_INVALID                                 |

> **Imperial input, SI storage**
>
> When `unit_system` is imperial the client collects pounds and feet/inches, converts, and sends kilograms and centimetres. The API never accepts imperial values. Round-trip the conversion in a client unit test so a user who enters 5'10" does not see 177.7 cm come back as 5'9.9".

### 7.2 Error envelope — identical shape for every failure

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/problem+json
{
  "type": "https://api.gymak.fitness/errors/goal-not-permitted-for-minor",
  "title": "This goal is not available for users under 18",
  "status": 422,
  "code": "GOAL_NOT_PERMITTED_FOR_MINOR",
  "detail": "Permitted goals for this account: maintain, gain.",
  "trace_id": "01J8XQ2M4V7K9F3B",
  "errors": [ { "field": "goal", "code": "NOT_ALLOWED" } ]
}
```

`code` is the stable string the client switches on. `title` and `detail` are for developers and are never rendered to a user — user-facing copy is localised on the device, keyed by `code`. Every response carries `trace_id`, and it is the same value that appears in the server log line.

### 7.3 Error code catalogue — the client must handle every one of these

| HTTP | code                         | When                                                                                 |
|------|------------------------------|--------------------------------------------------------------------------------------|
| 400  | MALFORMED_BODY               | Not valid JSON, or a basic type violation                                            |
| 400  | PROVIDER_NOT_SUPPORTED       | Path provider is not google — includes facebook, deferred to Phase 2 (13.1.2)         |
| 401  | INVALID_CREDENTIALS          | Login failed, for any reason                                                         |
| 401  | TOKEN_MISSING                | No Authorization header on a protected route                                         |
| 401  | TOKEN_EXPIRED                | Access token past `exp` — the client should refresh and retry once                   |
| 401  | TOKEN_INVALID                | Bad signature, wrong audience, stale `tv`, unknown refresh token                     |
| 401  | TOKEN_REUSED                 | A consumed refresh token was presented — the family is now revoked; log the user out |
| 401  | SOCIAL_TOKEN_INVALID         | Firebase verification failed or the provider claim mismatched                        |
| 401  | RESET_TOKEN_INVALID          | Reset token unknown, spent, or expired                                               |
| 403  | ACCOUNT_DISABLED             | `is_active = false`                                                                  |
| 404  | NOT_FOUND                    | Also returned for another user's resource, deliberately                              |
| 404  | PROFILE_NOT_FOUND            | Read or patch before onboarding completed                                            |
| 409  | EMAIL_ALREADY_REGISTERED     | Registration on a taken address                                                      |
| 409  | PROFILE_ALREADY_EXISTS       | Second POST /profile                                                                 |
| 409  | IDENTITY_ALREADY_LINKED      | That social identity belongs to a different Gymak user                               |
| 422  | VALIDATION_ERROR             | Field-level failure; the `errors` array is populated                                 |
| 422  | GOAL_NOT_PERMITTED_FOR_MINOR | P1-SAF-001                                                                           |
| 422  | RESET_CODE_INVALID           | Wrong or unknown code                                                                |
| 422  | RESET_CODE_EXPIRED           | Past 10 minutes                                                                      |
| 429  | RATE_LIMIT_EXCEEDED          | With `Retry-After` — see A-06                                                        |
| 429  | RESET_CODE_ATTEMPTS_EXCEEDED | Sixth wrong attempt; the code is burned. With `Retry-After`                           |
| 500  | INTERNAL_ERROR               | Never leaks a stack trace or a database message to the client                        |
| 503  | UPSTREAM_UNAVAILABLE         | Firebase or the email provider is unreachable                                        |

## 8 · Firebase configuration

Two consoles, one afternoon. Do this before T-06, and record every value in `.env.example` with placeholders.

### 8.1 Firebase console

1.  Reuse the existing project `gymak-2d4ab`. Do not create a second one.
2.  Authentication → Sign-in method → enable **Google** only. Facebook is deferred to Phase 2 (decision 13.1.2, A-15) — do not enable it now. Leave Email/Password **disabled**: our backend owns that path (P1-ADR-01).
3.  Register the Android app with package name `com.gymak.app`, and the iOS app with the matching bundle identifier. Download `google-services.json` and `GoogleService-Info.plist`.
4.  Add the SHA-1 **and** SHA-256 fingerprints of both the debug keystore and the EAS release keystore. Google Sign-In on Android fails with an opaque error when a fingerprint is missing, and it is the single most common half-day lost in this setup.
5.  Project settings → Service accounts → generate a private key. This JSON is what `firebase-admin` uses on the backend. It goes in the environment, never in git.

### 8.2 Facebook developer console — deferred to Phase 2 (decision 13.1.2, A-15)

> **Not done in Phase 1.** Decision 13.1.2 is closed: Google ships now, Facebook is held for Phase 2. This section is kept, unexecuted, as the record of what the work will be when Phase 2 picks it up — do not action it now.

1.  Create an app of type **Consumer**, add the Facebook Login product.
2.  Copy the App ID and App Secret into Firebase's Facebook provider settings.
3.  Copy Firebase's OAuth redirect URI back into Facebook → Facebook Login → Settings → Valid OAuth Redirect URIs.
4.  Request the `email` permission. Note that a Facebook account registered by phone number returns no email — the placeholder path in §5.4 step 5 exists for exactly this case, and it must be tested, not assumed.
5.  Facebook Login requires the app to be in Live mode with a privacy-policy URL before non-developer accounts can sign in. Add testers under Roles while the app is still in development.

### 8.3 Client and server wiring

```bash
# backend/.env
FIREBASE_CREDENTIALS_JSON='{"type":"service_account","project_id":"gymak-2d4ab",...}'
FIREBASE_PROJECT_ID=gymak-2d4ab

# mobile/.env — public config only, safe to ship in the bundle
EXPO_PUBLIC_FIREBASE_API_KEY=...
EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN=gymak-2d4ab.firebaseapp.com
EXPO_PUBLIC_FIREBASE_PROJECT_ID=gymak-2d4ab
EXPO_PUBLIC_FIREBASE_APP_ID=...
EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID=...
EXPO_PUBLIC_FACEBOOK_APP_ID=...
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.x:8000/api/v1
```

> **Two things that will otherwise cost a day each**
>
> **1.** Google Sign-In needs native code, so it does **not** work in Expo Go. Build a development build (`eas build --profile development`) before starting T-13. **2.** On a physical device, `localhost` is the phone, not the laptop. Use the laptop's LAN address in `EXPO_PUBLIC_API_BASE_URL` and bind uvicorn to `0.0.0.0`. The single-login-screen milestone after T-04 exists to hit this second problem early, while it is the only moving part.

## 9 · Mobile application

### 9.1 Stack

| Concern        | Choice                                                                                     | Reason                                                                                                                   |
|----------------|--------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| Framework      | Expo (managed) + React Native + TypeScript `strict`                                        | EAS hosted macOS workers remove the Mac dependency for iOS builds (SRS ADR-005)                                          |
| Navigation     | expo-router                                                                                | File-based routes make the three-stack gate (auth / onboarding / app) a directory structure instead of conditional logic |
| Server state   | TanStack Query                                                                             | Caching, retry, and request de-duplication that would otherwise be hand-written                                          |
| Session state  | Zustand, one small store                                                                   | Tokens and user identity only. Not a dumping ground for form state.                                                      |
| Token storage  | `expo-secure-store`                                                                        | Keychain / Keystore. **Never** AsyncStorage for a token.                                                                 |
| Forms          | react-hook-form + zod                                                                      | The zod schemas mirror §7.1 field-for-field                                                                              |
| HTTP           | axios with one interceptor                                                                 | Single place for the bearer header and the refresh dance                                                                 |
| i18n           | `i18n-js` + `expo-localization`                                                             | Arabic default, English second, RTL via `I18nManager`                                                                    |
| Social sign-in | `@react-native-firebase/auth` or `@react-native-google-signin` (Google only — `react-native-fbsdk-next` deferred to Phase 2, 13.1.2) | Requires a development build; not available in Expo Go                                                                   |

### 9.2 Navigation and the session gate

```text
app/_layout.tsx
  └─ providers: QueryClient, i18n, Theme, SessionProvider
     └─ on mount: read tokens from SecureStore → if present call GET /auth/me
        ├─ no token or 401                   → redirect to (auth)/welcome
        ├─ token, onboarding_completed=false → redirect to (onboarding)/step-1
        └─ token, onboarding_completed=true  → redirect to (app)/home

While that call is in flight, show the splash. Never flash the login screen at a
signed-in user — it is the single most noticeable polish bug in an auth flow.
```

### 9.3 Screen inventory

| #  | Screen               | Content and behaviour                                                                                                                                                                  |
|----|----------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1  | welcome              | Logo on sand background, one line of positioning copy, **Create account** (primary), **Log in** (secondary), then a divider and the social button (Google only — Facebook deferred to Phase 2, 13.1.2). Language toggle in the corner.      |
| 2  | register             | Email, password, confirm password, password-strength hint, terms checkbox with links, submit. Inline field errors below each input, never in an alert dialog.                          |
| 3  | login                | Email, password with a reveal toggle, "Forgot password?" link, submit, social button (Google only, per 13.1.2).                                                                        |
| 4  | forgot-password      | Email only. On 202, navigate to verify-code carrying the email. Copy states plainly that a code has been sent if the account exists.                                                   |
| 5  | verify-code          | **Eight**-box OTP input (P1-ADR-07) with auto-advance, paste support, and auto-submit on the eighth character. Uppercases as the user types; rejects characters outside the §7.1 alphabet rather than accepting and failing server-side. A visible countdown, and a resend button that is disabled until the countdown ends. |
| 6  | new-password         | New password, confirm. On success, show a confirmation and route to login — the user must sign in again, because every session was just revoked.                                       |
| 7  | onboarding step 1    | Name and gender                                                                                                                                                                        |
| 8  | onboarding step 2    | Birth date — a native date picker or three selects. Never a free-text field.                                                                                                           |
| 9  | onboarding step 3    | Height and weight, with a unit toggle that converts live                                                                                                                               |
| 10 | onboarding step 4    | Goal — three cards: lose, gain, maintain. Under 18, `lose` is disabled with a short explanation shown inline, not hidden.                                                              |
| 11 | onboarding step 5    | Experience level — three cards with one clarifying line each ("trained consistently for under 6 months")                                                                               |
| 12 | onboarding step 6    | Units and language                                                                                                                                                                     |
| 13 | onboarding review    | Everything collected, each row tappable to jump back, then one **Finish** that makes the single POST /profile call                                                                     |
| 14 | home [placeholder]   | "Welcome, {name}" and an explicit "your training plan arrives in the next phase" panel. No fake charts, no dummy workout cards.                                                        |
| 15 | settings             | Reads GET /profile, edits through PATCH. Sections: profile, preferences (units, language), account (log out, log out of all devices, delete account with a typed confirmation).        |

> **Onboarding progress is held on the device, not on the server**
>
> Steps 1–6 write to a local Zustand draft. Exactly one network call happens, on Finish. If the app is killed mid-flow the draft survives in memory for the session and the user resumes at the step they left; if the process died, they restart onboarding — acceptable for six short screens, and far simpler than six partial-write endpoints. The API's resumability guarantee is at the account level: they are still signed in, and `/auth/me` still says onboarding is incomplete.

### 9.4 States every screen must implement

| State         | Treatment                                                                                                                        |
|---------------|----------------------------------------------------------------------------------------------------------------------------------|
| Idle          | The designed state                                                                                                               |
| Submitting    | Button shows a spinner and its label, stays the same width, and is disabled. Inputs are locked. No full-screen blocking overlay. |
| Field error   | Red border on the input, error text below it, and the first failing field receives focus and is scrolled into view.              |
| Request error | An inline banner at the top of the form, localised from the `code` field, with a retry affordance where retrying makes sense.    |
| Offline       | Detected before submitting: an inline message saying there is no connection. Never a raw axios network-error string.             |
| Rate limited  | Read `Retry-After` and show a live countdown instead of a generic failure.                                                       |
| Success       | Navigate immediately. No congratulatory modal between the user and where they were going.                                        |

### 9.5 The refresh interceptor — get this exactly right

```text
1. Request interceptor attaches the access token if present.
2. On a 401 with code TOKEN_EXPIRED:
     a. If a refresh is already in flight, queue this request against that promise.
        Single-flight. One refresh call at a time, per app instance, always.
     b. Otherwise start one refresh, then replay every queued request once.
3. On a 401 with code TOKEN_REUSED or TOKEN_INVALID, or if the refresh itself fails:
     clear SecureStore, reset the session store, redirect to (auth)/welcome.
     Never retry a failed refresh. Retrying is what turns one bad token into a loop.
4. Never attempt refresh for /auth/login, /auth/register, /auth/refresh itself,
   or any /auth/password/* call.
5. Retry each original request at most once. A second 401 is a logout, not a third try.
```

### 9.6 Localisation and RTL

- Arabic is the default language; English is the alternate. Both files carry the same keys, and a missing key fails loudly in development rather than silently rendering the key name in production.
- No string literal appears in a component. Every visible word is `t('some.key')`, including button labels, error text, and accessibility labels.
- Layout uses `start`/`end`, never `left`/`right`. Icons that imply direction (back chevron, progress arrow) mirror in RTL; icons that do not (the logo, a check mark) never mirror.
- Numbers, dates, weights, and the OTP boxes stay left-to-right and use Western digits even in Arabic. This is what Arabic-speaking fitness users expect, and the OTP input in particular breaks in confusing ways otherwise.
- Switching language calls `I18nManager.forceRTL()` and requires an app reload. Say so in the UI — a silent half-flipped layout looks like a bug.
- Error copy is keyed by the API's `code`: `errors.TOKEN_REUSED`, `errors.EMAIL_ALREADY_REGISTERED`, and so on. Nothing from the API's `title` or `detail` is ever shown to a user.

## 10 · Design tokens

The full Gymak palette. Copy this into `src/theme/tokens.ts` verbatim. Do not invent a colour, do not reach for a Tailwind default, and do not hardcode a hex value anywhere in a component. The emotional split the palette is built on: **60% comfort, 25% progress, 10% strength, 5% celebration.** Rust at full saturation is reserved for the primary action and the win.

### 10.1 Rust scale — accent and strength

| 50      | 100     | 200     | 300     | 400     | 500 · core  | 600     | 700     | 800     | 900     |
|---------|---------|---------|---------|---------|-------------|---------|---------|---------|---------|
| #FBEDE6 | #F6D3C3 | #EDA98A | #E2835A | #D5642F | **#C4491F** | #A63C18 | #832E12 | #5E210D | #3B1508 |

### 10.2 Sand scale — warm neutral

| 50      | 100     | 200     | 300     | 400     | 500     | 600     | 700     | 800     | 900     | 950     |
|---------|---------|---------|---------|---------|---------|---------|---------|---------|---------|---------|
| #FFFDF8 | #FAF6EF | #F3ECE0 | #E7DDCC | #D3C7B4 | #B4A896 | #8A8175 | #5A5249 | #35302B | #211D1B | #17130F |

### 10.3 Semantic tokens

#### Light (default)

| Token              | Value                                |
|--------------------|--------------------------------------|
| bg                 | sand-100 · #FAF6EF                   |
| surface            | sand-50 · #FFFDF8                    |
| surfaceVariant     | sand-200 · #F3ECE0                   |
| card               | sand-50                              |
| input              | sand-50                              |
| border             | sand-300 · #E7DDCC                   |
| divider            | sand-200                             |
| overlay            | rgba(33,29,27,.45)                   |
| skeleton           | sand-200                             |
| primary            | rust-500 · #C4491F                   |
| primaryPressed     | rust-700 · #832E12                   |
| primaryDisabled    | rust-200 · #EDA98A                   |
| primaryContainer   | rust-50 · #FBEDE6                    |
| onPrimary          | #FFF6EF                              |
| secondary          | sand-700 · #5A5249                   |
| secondaryContainer | sand-200                             |
| textPrimary        | sand-900 · #211D1B                   |
| textSecondary      | sand-700 · #5A5249                   |
| textMuted          | sand-600 · #8A8175                   |
| textDisabled       | sand-500 · #B4A896                   |
| textInverse        | sand-50                              |
| textLink           | rust-600 · #A63C18                   |
| success            | #3B7A4E · bg #DCEBDF                 |
| warning            | #C98A2E · text #9A6410 · bg #F7E9CE  |
| error              | #B23A2E · bg #F5DCD8                 |
| info               | #3E7691 · bg #DAE7EE                 |
| shadowColor        | rgba(53,41,30,.10)                   |

#### Dark — warm charcoal, never #000

| Token              | Value                                |
|--------------------|--------------------------------------|
| bg                 | sand-900 · #211D1B                   |
| surface            | #2A2523                              |
| surfaceVariant     | #332D2A                              |
| card               | #2A2523                              |
| input              | #332D2A                              |
| border             | #403A35                              |
| divider            | #35302B                              |
| overlay            | rgba(0,0,0,.55)                      |
| skeleton           | #332D2A                              |
| primary            | rust-400 · #D5642F                   |
| primaryPressed     | #EA8A5C                              |
| primaryDisabled    | #6E463A                              |
| primaryContainer   | #4A2418                              |
| onPrimary          | #1A1310                              |
| secondary          | sand-400 · #D3C7B4                   |
| secondaryContainer | #332D2A                              |
| textPrimary        | #EDE6DA                              |
| textSecondary      | #B5AB9E                              |
| textMuted          | #8A8175                              |
| textDisabled       | #6A625A                              |
| textInverse        | sand-900                             |
| textLink           | #E8703F                              |
| success            | #6FBF87 · bg #24361F                 |
| warning            | #E0A94B · text #E8B968 · bg #3A2E17  |
| error              | #E88579 · bg #3A1F1A                 |
| info               | #79A8BE · bg #1E2E36                 |
| shadowColor        | rgba(0,0,0,.35)                      |

Also carried forward for later phases, defined now so nothing gets improvised later: `chart1..5` = #C4491F, #C98A2E, #3E7691, #3B7A4E, #B4A896 (dark: #E8703F, #E0A94B, #79A8BE, #6FBF87, #B4A896) · `ringWorkout` rust · `ringCalories` #C98A2E · `ringWeight` #3E7691 · `streak`/`prBadge` rust · `navBg` sand-50 / #2A2523 · `fab` primary · `aiCoachBg` #EDE7F0 / #2C2635 · `premiumBg` #F3E9D4 / #352C1B.

### 10.4 Type, space, radius, motion

| Role       | Size / weight             |
|------------|---------------------------|
| display    | 34 / 700, tracking −.02em |
| h1         | 28 / 700                  |
| h2         | 22 / 600                  |
| h3         | 18 / 600                  |
| body       | 16 / 400, line-height 1.5 |
| bodyStrong | 16 / 600                  |
| label      | 14 / 500                  |
| caption    | 12 / 400, textMuted       |
| stat       | 34 / 700, tabular figures |

Latin: Inter. Arabic: IBM Plex Sans Arabic or Cairo — one Arabic face, loaded once, chosen and locked in T-10. Never let the OS pick a fallback Arabic font per platform.

| Scale            | Values                                         |
|------------------|------------------------------------------------|
| space            | 4, 8, 12, 16, 20, 24, 32, 40, 48               |
| radius           | sm 8 · md 12 · lg 16 · xl 20 · pill 999        |
| screen padding   | 20 horizontal                                  |
| control height   | 52 (button and input alike)                    |
| min touch target | 48 × 48                                        |
| shadow sm        | y1 blur2 · shadowColor                         |
| shadow md        | y6 blur20 · shadowColor                        |
| motion           | fast 120ms · base 200ms · slow 320ms, ease-out |

### 10.5 Component contracts

| Component    | Props and required states                                                                                                                                                                                       |
|--------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GButton      | `variant: primary \| secondary \| ghost \| social`, `loading`, `disabled`, `fullWidth`, `icon`. Height 52, radius 12. Loading keeps the label and its width. Disabled uses `primaryDisabled`, never opacity alone. |
| GTextInput   | `label`, `error`, `secure` with a reveal toggle, `keyboardType`, `autoComplete`. Focus ring in rust; error state in `error` with the message below.                                                             |
| GOtpInput    | **8** boxes (P1-ADR-07), auto-advance, backspace to the previous box, paste distributes across boxes, auto-submit on complete, LTR even in Arabic. Alphanumeric, not digits-only: uppercase on entry, `autoCapitalize="characters"`, and silently drop characters outside the §7.1 alphabet on paste. |
| GSelectCard  | Title, optional description, `selected`, `disabled` with a reason line. Selected = rust border plus `primaryContainer` fill, not a tiny radio dot.                                                              |
| GProgressBar | `step` of `total`, animated, with an accessible "step 3 of 6" label.                                                                                                                                            |
| GScreen      | SafeArea, keyboard-avoiding, scroll-on-overflow, standard padding, optional header with a back affordance.                                                                                                      |
| GErrorBanner | Localised message from an error `code`, optional retry, dismissible.                                                                                                                                            |
| GLogo        | The mark, sized by prop, from `assets/logo.png`. Never recoloured, never stretched, minimum 24 dp clear space.                                                                                                  |

### 10.6 Accessibility floor for Phase 1

- Every touchable has an `accessibilityRole` and an `accessibilityLabel` from the translation file.
- Every touchable is at least 48 × 48, using hit-slop where the visual is smaller.
- Text contrast at 4.5:1 minimum. The listed pairings already satisfy it; a new pairing must be checked before it ships.
- Errors are announced, not only coloured — colour alone never carries meaning.
- The whole register → onboarding flow is completable with TalkBack on.
- Respect the OS text-size setting: no fixed-height text container that clips at 130% scaling.

## 11 · Testing and definition of done

### 11.1 Backend test matrix

| Level       | Must cover                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
|-------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Unit        | Argon2id hash and verify · rehash-on-verify · production Argon2 cost is the default · JWT sign, verify, expiry, wrong audience, tampered signature, stale `tv`, pinned algorithm · refresh token generation and hashing · reset-code generation: the alphabet never emits `I`, `O`, `0` or `1`, and the same code under two different peppers yields different digests · constant-time comparison · every validator in §7.1 · the P1-SAF-001 age function at its boundaries (17y 364d, exactly 18, 18y 1d) · imperial conversion round-trip |
| Integration | Register happy path · duplicate email · login success and each failure cause · refresh rotation · **refresh reuse revokes the family** · logout · logout-all invalidates access tokens through `token_version` · the full reset flow · expired code · sixth wrong attempt · concurrent double redemption leaves exactly one winner · reset revokes all sessions · social sign-in creating a user · social sign-in linking to an existing verified email · provider-claim mismatch rejected · profile create, duplicate create, read, patch · minor blocked from `lose` on both POST and PATCH · account deletion revoking access |
| Security    | Generated cross-tenant matrix: user B attempts every user-scoped endpoint with user A's identifiers and receives 404, not 403 · **RLS tests must fail when the policy is removed** — a passing RLS test that only proves a permitted read succeeds proves nothing · no endpoint returns `password_hash` · a log-capture test asserting no password, token, code, key material, or health field appears in any log line across the whole suite · rate limits return 429 with `Retry-After` · an unregistered address can still trip the per-email 429 |
| Migration   | Alembic upgrade then downgrade runs clean against a seeded database                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| Contract    | `openapi.json` regenerated and identical to the committed copy                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

Fixtures use `testcontainers` for a real PostgreSQL — SQLite would not honour `citext`, the CHECK constraints, or RLS, so testing against it would test nothing that matters here.

> **Coverage must be greenlet-aware, or the gate is measuring the wrong thing (A-08)**
>
> `coverage.py` does not follow greenlet switches, and SQLAlchemy's async layer runs on greenlets. Every line after the first database `await` was being reported as unexecuted. With `concurrency = ["thread", "greenlet"]` in `pyproject.toml` and no test changes at all, `dependencies.py` went 73% → 100% and `user_repo.py` 88% → 100%. This setting is a precondition of the §11.3 gates, not an optimisation: the T-01 and T-02 numbers recorded before it were understated.
>
> The suite uses a session-scoped event loop to avoid `Event loop is closed`. That has a cost: if flakiness appears in a later task, this is the first thing to suspect.

### 11.2 Mobile verification — manual, on a physical device

1.  Register a fresh account → land in onboarding step 1, not on home.
2.  Kill the app mid-onboarding, reopen → signed in, returned to onboarding.
3.  Complete onboarding → home shows the correct name.
4.  Force-close, reopen → straight to home, no login flash, no re-onboarding.
5.  Wait past 15 minutes (or shorten the access lifetime in a staging build) → the next call refreshes silently and succeeds.
6.  Corrupt the stored refresh token → the app logs out cleanly and lands on welcome, with no crash and no loop.
7.  Airplane mode on login → the offline message, not a raw network error.
8.  Wrong password five times → the 429 countdown renders.
9.  Full reset flow using the real email inbox.
10. Google sign-in on a fresh account, then Google sign-in again → the same account, not a duplicate.
11. Sign up by email, then sign in with Google on the same address → one account, both methods listed in `/auth/me`.
12. Switch to English, reload → LTR throughout, no clipped labels; switch back to Arabic → RTL throughout.
13. Set the birth date to age 16 → the `lose` card is disabled with a visible reason, and the server also rejects it if forced.
14. TalkBack on → the whole register-to-home path is completable.

### 11.3 Phase 1 definition of done

> **Phase 1 is complete when every one of these is true. Not before.**
>
> 1.  Every P1-FR requirement in §1.1 is implemented and demonstrated, not described. (P1-FR-004 is deferred to Phase 2 per decision 13.1.2, A-15, and is excluded from this gate.)
> 2.  Backend coverage ≥ 80% overall and ≥ 95% in `core/security.py`, `auth_service`, and `password_reset_service` — measured with greenlet concurrency enabled per A-08.
> 3.  The cross-tenant matrix passes with zero findings, and the RLS tests fail when a policy is dropped.
> 4.  The refresh-reuse test passes, and the audit log shows both `token.reuse_detected` and `token.family_revoked`.
> 5.  Alembic migrates forward and backward cleanly.
> 6.  `openapi.json` is committed and matches the code.
> 7.  No secret, key, or service-account JSON is in git history.
> 8.  All fourteen manual device checks in §11.2 pass on a real Android device.
> 9.  The nothing-out-of-scope rule in §1.2 holds: no workout, nutrition, AI, or payment code exists in the repository.
> 10. `README.md` lets a fresh clone run the backend and the app from zero in under ten minutes.
> 11. Every item in §A.5 is either closed or explicitly re-deferred with a reason.

## 12 · Task pack

Fourteen tasks in dependency order. Each block is written to be pasted into Claude Code or Cursor **on its own**, with this document available in the context. Do not paste two at once. After each one, run the tests, read the diff, and only then continue.

> **Two operational rules learned the hard way**
>
> **Never write a task prompt from memory.** Paste the actual text from this document. A T-02 prompt written from recollection produced Phase 2 tables and cost a whole task. **Never commit while the agent is running** — it sees the working tree change under it, assumes a hook, and starts second-guessing its own diff.

#### Preamble — paste once at the start of every session

```text
You are working on Gymak, Phase 1 only. GYMAK-P1-SPEC-001 v1.1 is your single source
of truth; if this document and your instinct disagree, the document wins. Ignore any
copy of this spec dated v1.0.

Hard rules:
- Implement exactly one task, the one I name. Nothing beyond it.
- Touch only the files that task lists. If you believe another file must change,
  stop and tell me why instead of changing it. Standing exception: pyproject.toml
  and tests/** are always in scope.
- Build nothing from the section 1.2 out-of-scope list, not even a stub or a TODO.
- Add no dependency outside Appendix A.2 without asking.
- If a required detail is genuinely missing from the spec, ask one specific
  question and wait. Do not invent a column, an endpoint, or a library.
- Report first what the current implementation actually does — state it explicitly
  before changing anything.
- Finish by listing: files touched, what changed, how to verify, and anything you
  deliberately did not do. Paste real output with exit codes for ruff, mypy
  --strict, and pytest. Do not commit.
```

### T-01 · Backend skeleton — **complete**

```text
Create the FastAPI skeleton for Gymak per spec section 3.

Files: backend/pyproject.toml, backend/.env.example, backend/app/main.py,
config.py, database.py, core/errors.py, core/logging.py, core/ids.py,
routers/health.py, tests/conftest.py, backend/README.md

Requirements:
- App factory in main.py, /api/v1 prefix, CORS closed except localhost dev
  origins and configurable, security headers middleware per spec 6.5.
- config.py with pydantic-settings covering every variable in Appendix A.1;
  the app must fail at startup if a required one is missing, and no error message
  may ever contain a key value (spec 6.3).
- Async SQLAlchemy 2.0 engine and session factory; a helper that sets
  app.user_id per session for RLS. The helper must refuse to run under
  AUTOCOMMIT, where set_config has no transaction to be local to.
- core/errors.py: an AppError base carrying code/status/title/detail/errors, a
  subclass per code in spec 7.3, and one exception handler that emits
  application/problem+json with a trace_id.
- core/logging.py: structured JSON logs with the redaction allowlist from 6.5.
- core/ids.py: uuid7().
- GET /api/v1/health returning status plus a real database round-trip.
- conftest.py with a testcontainers PostgreSQL fixture, a session-scoped event
  loop, a real generated Ed25519 keypair per run, and an httpx async client.
- Argon2 params reduced only when ENV=test.

Done when: pytest collects and passes a non-zero number of tests, /health returns
200 against a live database, and a deliberately raised AppError produces the exact
envelope in spec 7.2.
```

### T-02 · Schema and migration — **complete**

```text
Implement the Phase 1 data model per spec section 4, all six tables.

Files: backend/app/models/*.py, backend/alembic/**, backend/tests/unit/test_models.py

Requirements:
- SQLAlchemy 2.0 declarative models for users, user_identities, profiles,
  refresh_tokens, password_reset_codes, audit_log — matching section 4 exactly:
  every CHECK, every UNIQUE, every partial index, the citext email, UUID v7 keys
  passed from Python.
- One Alembic migration creating all of it, including the citext extension, the
  updated_at trigger, and the RLS block in 4.7 exactly as written: ENABLE and
  FORCE on profiles and refresh_tokens, an owner policy on each using the NULLIF
  guard, no RLS on the other four tables.
- A startup assertion that the database role is not a superuser.
- Grant the app role INSERT and SELECT only on audit_log, and give
  audit_log.actor_user_id no foreign key.

Do not add a column that is not in section 4. Do not create a workout, exercise,
nutrition, or subscription table.

Done when: upgrade then downgrade runs clean, a test proves each CHECK constraint
rejects an out-of-range value (height 99, age 12, unknown goal), and the RLS tests
fail if the policy is dropped.
```

### T-03 · Security primitives — **complete**

```text
Implement core/security.py per spec section 6, with tests first.

Files: backend/app/core/security.py, core/dependencies.py, core/rate_limit.py,
backend/app/repositories/user_repo.py, backend/tests/unit/test_security.py

Requirements:
- Argon2id hash/verify at the 6.1 parameters, with rehash-on-verify.
- Password policy validation per 6.2 including NFKC normalisation and the common
  password denylist.
- Ed25519 JWT sign and verify with the algorithm pinned; claims sub, tv, jti, iat,
  exp, aud per 6.3.
- Opaque token generation (32 bytes, urlsafe) plus SHA-256 hashing for refresh
  and reset tokens.
- Reset-code generation and hashing per P1-ADR-07 — NOT the superseded 6-digit,
  user-id-salted SHA-256 design. This module owns the primitive that T-07 then
  consumes, so getting it wrong here propagates: 8 characters from
  ABCDEFGHJKLMNPQRSTUVWXYZ234567 via secrets.choice, stored as HMAC-SHA256 keyed
  with RESET_CODE_PEPPER (required config, fails fast at import, never persisted),
  compared with compare_digest.
- get_current_user dependency: parse bearer, verify signature, audience, expiry,
  and that tv matches the user's current token_version; load the user; reject
  inactive or soft-deleted. user_repo gets get_by_id and nothing else yet.
- A rate-limit dependency taking a limit, a window, and a key strategy.

Tests must cover: wrong audience, expired token, tampered signature, stale tv, and
the boundary of every password rule. Also: that the same code under two different
peppers produces different digests, and that the generated alphabet never emits
I, O, 0 or 1.

For constant-time comparison, do not assert on wall-clock timing — it is flaky.
Assert on the AST that the comparison function is a single return statement
calling secrets.compare_digest with no If/For/While/Try/BoolOp/Compare inside it,
so any added length check or early return fails the test.

Done when: coverage of this module is at or above 95%, measured with
concurrency = ["thread", "greenlet"] per section 11.1.
```

### T-04 · Register and login — **next**

```text
Implement registration and login per spec 5.2 and 5.3.

Files: app/schemas/auth.py, app/repositories/user_repo.py, token_repo.py,
audit_repo.py, app/services/auth_service.py, audit_service.py,
app/routers/auth.py, app/core/errors.py,
tests/integration/test_auth_register_login.py

Requirements:
- POST /auth/register and POST /auth/login with the exact request and response
  shapes in 5.2 and 5.3.
- Emails lowercased and trimmed everywhere.
- Login returns one generic INVALID_CREDENTIALS for every failure cause, and runs
  a dummy hash verification when the user is not found so timing does not leak
  existence. is_active=false is the one exception: 403 ACCOUNT_DISABLED.
- Refresh token issued with a new family_id, stored hashed only.
- Audit user.registered, user.login_succeeded, user.login_failed.
- Rate limits per 6.4.
- core/errors.py: emit the Retry-After header on every 429. RateLimited already
  carries a tested retry_after_seconds; the handler does not yet write the
  header, so 6.4, 7.3 and the 11.1 security row are unmet today and no existing
  test catches it. This is the only change permitted in errors.py.
- Repository functions own all queries; the router builds none, and every
  user-scoped function takes user_id first.

Done when: the integration tests cover both happy paths and every failure cause,
a 429 response carries Retry-After with a correct value, and no response body
anywhere contains password_hash.
```

### T-05 · Refresh rotation and logout

```text
Implement refresh rotation, logout, and logout-all per spec 5.5.

Files: app/services/auth_service.py, app/repositories/token_repo.py,
app/routers/auth.py, tests/integration/test_token_rotation.py

Requirements:
- POST /auth/refresh implementing the 5.5 algorithm exactly, inside one
  transaction with SELECT ... FOR UPDATE on the token row.
- Reuse of a consumed token revokes the entire family, audits
  token.reuse_detected and token.family_revoked, and returns 401 TOKEN_REUSED.
- POST /auth/logout revokes the current family. POST /auth/logout-all revokes
  every family and increments token_version.
- Distinguish TOKEN_EXPIRED, TOKEN_INVALID, and TOKEN_REUSED correctly; the
  client's behaviour differs per code.

The reuse test is the important one: rotate A into B, then present A again, and
assert that B is dead too.

Done when: that test passes and the audit rows are present.
```

### T-06 · Social sign-in

```text
Implement Google sign-in per spec 5.4 and 8.3. Facebook is deferred to Phase 2
(decision 13.1.2, A-15) — do not build it.

Files: app/integrations/firebase.py, app/services/social_service.py,
app/repositories/user_repo.py, app/schemas/auth.py, app/routers/auth.py,
tests/integration/test_social_auth.py

Requirements:
- firebase-admin initialised once from FIREBASE_CREDENTIALS_JSON.
- POST /auth/social/{provider}, provider restricted to the enabled set,
  anything else 400 PROVIDER_NOT_SUPPORTED.
- Execute the six steps of 5.4 in that order, including the
  firebase.sign_in_provider claim check against the path provider.
- Link to an existing user only on a verified matching email; audit
  user.social_linked. Otherwise create the user with password_hash NULL.
- Handle a provider that returns no email using the placeholder scheme in 5.4
  step 5.
- Return is_new_user.
- Tests mock verify_id_token; never call Firebase from the suite. Cover: new
  user, returning user, link to existing email, unverified email does not link,
  provider mismatch rejected, missing email placeholder path, identity already
  attached to another user returns 409.

Done when: all seven cases pass and no request-body field other than id_token
influences the outcome.
```

### T-07 · Password reset

```text
Implement the three-call password reset per spec 5.6 and ADR-05.

Files: app/integrations/email/base.py, console.py, http_provider.py,
templates/reset_code.{ar,en}.html, app/services/password_reset_service.py,
app/repositories/reset_repo.py, app/routers/auth.py,
tests/integration/test_password_reset.py

Requirements:
- EmailSender interface with a console implementation used in dev and tests, and
  an HTTP provider implementation selected by config.
- Bilingual email template; pick the language from profiles.language, defaulting
  to Arabic. RTL, table-based inline CSS, the code large and selectable.
- forgot: always 202, identical body and latency envelope, mail dispatched on a
  background task, previous unconsumed codes marked consumed, nothing sent for an
  unknown or social-only account.
- verify-code: 5 attempts max, 10 minute expiry, constant-time comparison,
  returns a 5-minute single-use reset token.
- reset: sets the hash, bumps token_version, revokes every refresh family,
  consumes the code and the token, audits, sends a password-changed notice.
- Rate limits per 6.4.

READ P1-ADR-07 BEFORE STARTING. It amends 4.5 and 5.6 and supersedes the original
reset-code design. Do not implement 6-digit SHA-256 codes salted with user_id:
that is recoverable offline in under a second by anyone who can read the table,
and because /auth/password/forgot is unauthenticated it means takeover of
arbitrary accounts, not only accounts mid-reset. The primitive already exists in
core/security.py from T-03 — consume it, do not rewrite it. Specifically:
- Codes are 8 characters from ABCDEFGHJKLMNPQRSTUVWXYZ234567 via secrets.choice,
  uppercased on input.
- Stored as HMAC-SHA256 keyed with RESET_CODE_PEPPER, which is required config
  (Appendix A.1), fails fast at import if absent, and is never written to the DB.
- expires_at goes in the SQL WHERE clause, not a Python check after the fetch.
- attempt_count increments on every failed verify, expiry included.
- consumed_at is set in the same UPDATE ... WHERE consumed_at IS NULL that
  redeems the code; a zero-row result is a failure, so two concurrent
  redemptions leave exactly one winner.
- The per-email limit counts the submitted address before the user lookup, so
  429-vs-202 cannot be used to test whether an account exists.

Done when: tests cover expiry, the sixth attempt, reuse of a spent code, reuse of
a spent reset token, an unknown email still returning 202, and every session
being dead after a successful reset. Add: a test that a code is unrecoverable
from the stored digest without the pepper, a concurrent double-redemption test
asserting exactly one success, and a test that an unregistered address can still
trip the per-email 429.
```

### T-08 · Profile and onboarding

```text
Implement the profile endpoints per spec 5.7, 5.8, 5.9 and validation 7.1.

Files: app/schemas/profile.py, app/repositories/profile_repo.py,
app/services/profile_service.py, app/routers/profile.py,
tests/integration/test_profile.py, tests/unit/test_saf_age_goal.py

Requirements:
- GET /auth/me returning exactly the 5.7 shape, including auth_methods and
  onboarding_completed.
- POST /profile: one-time, 409 PROFILE_ALREADY_EXISTS on a second call, sets
  onboarding_completed true, audits profile.created.
- GET /profile, and PATCH /profile honouring the editable/immutable table in 5.9,
  ignoring onboarding_completed if sent, auditing before and after values for
  gender and birth_date.
- P1-SAF-001 as a pure function, unit-tested at its boundaries, enforced on both
  POST and PATCH, returning 422 GOAL_NOT_PERMITTED_FOR_MINOR with the permitted
  goals in detail.
- Every repository function takes user_id first.

Done when: the integration tests pass and the profile of another user is
unreachable through any of these routes.
```

### T-09 · Account deletion, hardening, contract

```text
Close out the backend: deletion, the cross-tenant matrix, and the OpenAPI export.

Files: app/routers/account.py, app/services/auth_service.py,
tests/security/test_cross_tenant.py, tests/security/test_no_secret_logging.py,
scripts/export_openapi.py, backend/openapi.json, backend/README.md

Requirements:
- DELETE /account per 5.10: password required when one exists, sets deleted_at,
  bumps token_version, revokes every family, audits.
- A cross-tenant test that enumerates the route table and, for every user-scoped
  route, attempts it as user B with user A's identifiers, asserting 404.
- A log-capture test asserting that no password, token, reset code, key material,
  birth date, height, or weight appears in any log line produced by the full
  suite.
- scripts/export_openapi.py writing openapi.json, plus a test that fails if the
  committed file differs from the generated one.
- Add ruff format --check to the gate alongside ruff check, and format the
  repository once in a commit that changes nothing else. The project currently
  gates on lint only, so the codebase is not format-consistent.
- README: setup, migrations, running tests, and every environment variable.

Done when: the coverage gates in 11.3 are met with greenlet concurrency enabled
and every item in that list except the mobile ones is true.
```

### T-10 · Mobile scaffold, theme, i18n

```text
Create the Expo application shell per spec 9.1, 9.2, 9.6 and section 10.

Files: mobile/package.json, app.json, tsconfig.json, .env.example,
app/_layout.tsx, src/theme/tokens.ts, typography.ts, useTheme.ts,
src/i18n/index.ts, ar.json, en.json, assets/logo.png

Requirements:
- Expo + TypeScript strict + expo-router. Three route groups: (auth),
  (onboarding), (app), each with a placeholder screen for now.
- tokens.ts holding the complete section 10 palette, light and dark, plus space,
  radius, typography, and motion scales. No hex value anywhere else in the app,
  ever.
- useTheme following the OS colour scheme.
- i18n with ar as default and en second, identical keys in both, and a
  development-mode warning on a missing key. Arabic strings can be placeholders I
  will replace, but every key must exist.
- RTL via I18nManager; layout written with start/end only.
- Providers wired in _layout.tsx: QueryClient, i18n, theme.

Done when: the app boots on a device in both languages with correct direction,
and grep finds no hardcoded hex or user-facing string outside the theme and
translation files.
```

### T-11 · Component library

```text
Build the eight primitives in spec 10.5, to the contracts and states in 9.4
and the accessibility floor in 10.6.

Files: mobile/src/components/GButton.tsx, GTextInput.tsx, GOtpInput.tsx,
GSelectCard.tsx, GProgressBar.tsx, GScreen.tsx, GErrorBanner.tsx, GLogo.tsx,
index.ts, and app/(app)/_dev-gallery.tsx

Requirements:
- Every component reads from the theme; zero literal colours or sizes.
- Every variant and state from 10.5 exists and is visibly distinct.
- 48dp minimum targets, accessibilityRole and accessibilityLabel on everything
  touchable, error text announced and not colour-only.
- GOtpInput: eight boxes, alphanumeric not digits-only, uppercase on entry,
  characters outside the 7.1 alphabet dropped on paste, auto-advance, backspace
  to previous, paste distribution, auto-submit on the eighth character, forced
  LTR.
- A dev-only gallery screen rendering every component in every state, so I can
  review them all at once. Mark it clearly as dev-only.

Done when: the gallery renders correctly in light, dark, Arabic, and English.
```

### T-12 · API client and session

```text
Implement the API layer and session handling per spec 9.1, 9.2 and 9.5.

Files: mobile/src/api/client.ts, auth.ts, profile.ts, errors.ts,
src/auth/storage.ts, session.ts, useSession.ts, src/validation/schemas.ts,
app/_layout.tsx

Requirements:
- axios instance from EXPO_PUBLIC_API_BASE_URL, attaching the bearer token.
- Tokens stored only in expo-secure-store. AsyncStorage must not appear anywhere
  in this diff.
- The refresh interceptor implementing all five rules of 9.5, with a real
  single-flight lock and a queue that replays each request at most once.
- errors.ts mapping every code in 7.3 to a translation key; an unrecognised code
  falls back to a generic message and is logged.
- Zustand session store: tokens, user, onboardingCompleted, and the actions
  signIn, signOut, hydrate.
- The boot sequence of 9.2, showing the splash until /auth/me resolves so a
  signed-in user never sees the login screen flash.
- zod schemas mirroring the 7.1 field rules exactly, including the imperial
  conversion helpers with a round-trip test.

Done when: manual checks 5 and 6 in 11.2 both pass — silent refresh works, and a
corrupted refresh token produces a clean logout with no loop.
```

### T-13 · Auth screens

```text
Build the six auth screens, numbers 1 to 6 in spec 9.3.

Files: mobile/app/(auth)/welcome.tsx, login.tsx, register.tsx,
forgot-password.tsx, verify-code.tsx, new-password.tsx, _layout.tsx,
src/auth/firebase.ts

Requirements:
- Content and behaviour exactly as described in the 9.3 table, using only T-11
  primitives.
- Every state in 9.4: submitting, field error with focus on the first failure,
  request-error banner localised from the code, offline detection before submit,
  a Retry-After countdown on 429, and immediate navigation on success.
- Social buttons calling the Firebase client SDK, then posting the ID token to
  /auth/social/{provider}; is_new_user decides onboarding versus home.
- verify-code: countdown, resend disabled until it ends, auto-submit on the
  eighth character, uppercase normalisation, ambiguous characters rejected on
  paste per P1-ADR-07.
- new-password success routes to login with a message explaining that all devices
  were signed out.

Note: social sign-in needs a development build, not Expo Go. Tell me if I need to
run a new build before this can be tested.

Done when: manual checks 1, 7, 8, 9, 10, and 11 in 11.2 pass on a device.
```

### T-14 · Onboarding, home, settings

```text
Build screens 7 to 15 in spec 9.3: onboarding, home placeholder, settings.

Files: mobile/app/(onboarding)/_layout.tsx, step-1..step-6.tsx, review.tsx,
app/(app)/home.tsx, settings.tsx, src/onboarding/draft.ts

Requirements:
- Six steps plus review, with GProgressBar showing "step n of 6" and a back
  affordance that preserves entered values.
- A local Zustand draft; exactly one network call, POST /profile, on Finish.
- Step 3 unit toggle converting live, sending SI only.
- Step 4 disables the lose card for users under 18, with the reason shown inline
  rather than the card hidden, and handles the server's 422 as well.
- Review lists every value with a tap-to-edit jump back to its step.
- Home: name greeting and an honest "training plan arrives next phase" panel. No
  fake data, no placeholder charts, no dummy workout cards.
- Settings: GET /profile, PATCH on save, plus log out, log out of all devices,
  and delete account behind a typed confirmation.

Done when: manual checks 2, 3, 4, 12, 13, and 14 in 11.2 pass, and Phase 1's
definition of done in 11.3 is fully satisfied.
```

## 13 · Decisions to confirm

### 13.1 Open

| Question                             | Context and recommendation                                                                                                                                                                                                                                                                                                                                                                                                                                       |
|--------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **1. `weight_kg` and `activity_level` in onboarding?** | **Resolved: yes.** Both are needed by every calorie calculation in the SRS (Mifflin-St Jeor → TDEE), and asking later means interrupting a user who already believes onboarding is finished. Both columns shipped in T-02 and the `[confirm]` markers are removed from §4.3. |

### 13.2 Decided unless overruled

| Question                                    | Answer applied                                                                                                                                                                                                                                                            |
|---------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 2. Is Facebook login worth Phase 1?         | **Resolved (A-15): no — Google ships in Phase 1, Facebook is held for Phase 2.** Facebook costs a second developer console, App Review with a published privacy policy, a Live-mode requirement, and the no-email-returned edge case, weighed against a market where Google covers the large majority of sign-ins. Four of those five items are not code, and one of them — App Review — waits on Meta's review queue rather than on this team. The `user_identities.provider` CHECK already allows `'facebook'` and `/auth/social/{provider}` already takes it as a path value, so shipping it later is configuration plus one button, not a redesign or a migration. P1-FR-004 moves to Phase 2 (§1.1), `react-native-fbsdk-next` stays out of Appendix A.2, and §8.2 is kept as the record of the console work for when Phase 2 picks it up. |
| 3. Firebase's role                          | Identity broker for social sign-in only; no Firestore. See P1-ADR-01, which is the single most consequential assumption in this document — read it before starting.                                                                                                       |
| 4. Email provider                           | Resend for the developer experience, Brevo if a free tier matters more. Either sits behind the ADR-05 interface, so the choice can change in one file. Sending domain: `gymak.fitness`, with SPF, DKIM, and DMARC configured before T-07 or the codes will land in spam. |
| 5. Minimum age                              | 13 to hold an account, 18 to select a weight-loss goal. Consistent with SRS SAF-007 and with app-store expectations.                                                                                                                                                      |
| 6. Gender options                           | `male` and `female` only, because the field exists to select a metabolic formula, not to describe identity. The onboarding copy should say so in one short line, which is both honest and better received than an unexplained binary.                                     |
| 7. Default language                         | Arabic, with the device locale respected on first launch if it is English.                                                                                                                                                                                                |
| 8. Hosting                                  | Local Docker Compose for Phase 1, staging after T-09. Railway or Fly.io with managed Postgres, per the SRS deployment baseline. **Answered concretely (A.5 items 1, 6, 11):** a managed host must let an initial admin role create two non-superuser roles — `gymak_migrator` (`CONNECT, CREATE` on the database; `CREATE, USAGE` on schema `public`) and `gymak_app` (`CONNECT` on the database; `USAGE` only on schema `public`) — with the exact grants in `backend/README.md`. Nothing more: `CREATE EXTENSION citext` does not need superuser on Postgres 13+ (`gymak_migrator`'s database-level `CREATE` is sufficient, confirmed empirically), so `alembic upgrade head` completes with no DDL run by hand on the operator's behalf. A provider that can create those two roles qualifies; one that only hands out a single superuser-equivalent role, or forbids creating additional roles at all, is disqualified. Do not spend time on production infrastructure until the auth flow works end to end on a device. |
| 9. Email verification for password signups  | Deferred. The account works unverified in Phase 1; the column exists and is set correctly for social sign-ins, so turning verification on later is a flow addition, not a migration.                                                                                       |

## Appendix A

### A.1 Environment variables

```bash
# backend/.env.example
ENV=development                       # development | test | staging | production
DATABASE_URL=postgresql+asyncpg://gymak_app:pass@localhost:5432/gymak
                                      # A.5 item 1: gymak_app is DML-only. The application
                                      # never reads MIGRATOR_DATABASE_URL below.
MIGRATOR_DATABASE_URL=postgresql+asyncpg://gymak_migrator:pass@localhost:5432/gymak
                                      # REQUIRED for `alembic upgrade`/`downgrade` only (read by
                                      # alembic/env.py, never by the application). gymak_migrator
                                      # owns the schema and is the only role that can CREATE
                                      # TABLE, ALTER TABLE, or CREATE EXTENSION citext.
JWT_PRIVATE_KEY_PEM=                  # Ed25519 private key, PEM, base64 if multiline is awkward
JWT_PUBLIC_KEY_PEM=
JWT_AUDIENCE=gymak-app
ACCESS_TOKEN_TTL_SECONDS=900
REFRESH_TOKEN_TTL_SECONDS=5184000
RESET_CODE_TTL_SECONDS=600
RESET_TOKEN_TTL_SECONDS=300
RESET_CODE_PEPPER=                    # REQUIRED (P1-ADR-07). HMAC key for reset-code hashing.
                                      # No default — the app must fail at import if it is missing,
                                      # exactly like JWT_PRIVATE_KEY_PEM, so a deployment can never
                                      # silently fall back to an unkeyed hash. Never stored in the
                                      # database. Generate with: python -c "import secrets;
                                      # print(secrets.token_urlsafe(32))"
                                      # Rotating it invalidates every outstanding reset code.
ARGON2_MEMORY_KIB=65536
ARGON2_TIME_COST=3
ARGON2_PARALLELISM=4
FIREBASE_PROJECT_ID=gymak-2d4ab
FIREBASE_CREDENTIALS_JSON=            # service account JSON, one line
EMAIL_BACKEND=console                 # console | http
EMAIL_API_KEY=
EMAIL_FROM="Gymak <no-reply@gymak.fitness>"
REDIS_URL=                            # optional in Phase 1
CORS_ORIGINS=http://localhost:8081,http://localhost:19006
LOG_LEVEL=INFO

# mobile/.env.example  — public values only
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.10:8000/api/v1
EXPO_PUBLIC_FIREBASE_API_KEY=
EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN=gymak-2d4ab.firebaseapp.com
EXPO_PUBLIC_FIREBASE_PROJECT_ID=gymak-2d4ab
EXPO_PUBLIC_FIREBASE_APP_ID=
EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID=
EXPO_PUBLIC_FACEBOOK_APP_ID=
```

Both key variables accept a raw PEM or a base64-wrapped one, with `\n` escapes, multiline values and CRLF normalised. An empty string is rejected, and the error names the field and distinguishes "not base64" from "base64 but contains no PEM" — without ever printing the value.

### A.2 Permitted dependencies

#### Backend

fastapi · uvicorn[standard] · pydantic · pydantic-settings · sqlalchemy[asyncio] · asyncpg · alembic · argon2-cffi · pyjwt[crypto] (or python-jose) · cryptography · uuid6 · firebase-admin · httpx · python-multipart · structlog · slowapi or a hand-rolled limiter · redis (optional) · **dev:** pytest · pytest-asyncio · pytest-cov · testcontainers[postgresql] · ruff · mypy

#### Mobile

expo · expo-router · react-native · typescript · @tanstack/react-query · zustand · axios · react-hook-form · zod · expo-secure-store · expo-localization · i18n-js · @react-native-firebase/app · @react-native-firebase/auth · @react-native-google-signin/google-signin · react-native-safe-area-context · @react-native-community/datetimepicker

`react-native-fbsdk-next` is deferred to Phase 2 alongside Facebook sign-in (decision 13.1.2, A-15) and is not added now.

Nothing else without asking. In particular: no UI kit, no component library, no state-management framework beyond Zustand, and no ORM other than SQLAlchemy.

### A.3 Deliberately deferred — the answer is "next phase", not "never"

| | | | |
|---|---|---|---|
| Email verification for password signups | Phase 2                         | Active-sessions screen               | Phase 2 (the data is already captured)            |
| Apple Sign-In                           | Before the first iOS submission | Physical purge job                   | Phase 2                                           |
| Change email flow                       | Phase 2                         | Two-factor authentication            | Unscheduled                                       |
| Offline mutation queue                  | Phase 3, with session logging   | Push notifications / FCM             | Phase 4                                           |
| Avatar upload                           | Unscheduled                     | Injuries, dietary pattern, allergens | Phase 3 and 4, with the modules that consume them |
| Facebook sign-in (P1-FR-004)            | Phase 2 (decision 13.1.2, A-15) |                                       |                                                    |

### A.4 Glossary

| | |
|---|---|
| **Token family**         | A rotation chain of refresh tokens sharing one `family_id`. One family is one device session; revoking the family signs that device out. |
| **Reuse detection**      | Presenting an already-consumed refresh token. Treated as theft: the whole family dies immediately. |
| **Pepper**               | A secret key held outside the database and mixed into a hash. Unlike a salt, it is not stored beside the value it protects, so reading the table is not enough to attack the hash. |
| **token_version**        | A counter on the user row, mirrored in every access token. Incrementing it invalidates every outstanding access token at once without a database read on the hot path. |
| **Onboarding completed** | A profile row exists with every required field satisfied. The single flag the client uses to choose its navigation stack. |
| **Repository scoping**   | Every data-access function takes `user_id` as its first parameter, so a route handler cannot construct an unscoped query even by accident. |
| **RLS**                  | PostgreSQL row-level security. The second, independent barrier behind repository scoping. Requires a non-superuser role, and `FORCE`, to be effective. |
| **Problem+json**         | The single error envelope in §7.2. `code` is the contract; `title` and `detail` are for developers only. |

### A.5 Carried-forward technical debt (A-10)

Recorded here so it stops living only in chat history. Each item has an owning task. §11.3 item 11 requires every one of these to be closed or explicitly re-deferred before Phase 1 baselines at v1.3.

| # | Item                                                                                                                                                                                                 | Owner | Severity |
|---|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------|----------|
| 1 | **Role split — closed.** `gymak_app` held `GRANT ALL ON SCHEMA public`, so it could revoke its own RLS (`DROP POLICY`, `ALTER TABLE ... NO FORCE`) and, since it owned every table, could re-`GRANT` itself `UPDATE`/`DELETE` on `audit_log` regardless of any prior `REVOKE`. Split into `gymak_migrator` (owner, runs Alembic — migrations `737d03a7c353`, `ae026cea6d8d`) and `gymak_app` (DML only, granted per-table by the migration). `FORCE` is kept as belt-and-braces protecting `gymak_migrator` itself from an ad hoc connection, not as the barrier for `gymak_app` — see §4.7's amendment. `app/database.py`'s startup assertion now also refuses any connection that can `CREATE` in schema `public`. Verified in `tests/security/test_rls.py`: `gymak_app` cannot `CREATE TABLE`, `ALTER TABLE`, `DROP POLICY`, disable `FORCE`, or `UPDATE`/`DELETE` `audit_log` — each asserted as a real, caught failure. | T-09  | Closed |
| 2 | **Password denylist.** The vendored list has 313 entries, not the ~1000 §6.2 asks for. Replace with the SecLists top-1000 file named in §6.2 — one static-asset change, no code change.                 | T-09  | Low      |
| 3 | **Real key parse at startup.** `config.py` normalises and shape-checks the PEM but does not call `load_pem_private_key`, so a structurally valid, cryptographically broken key still fails at first sign. | T-09  | Medium   |
| 4 | **`ruff format`.** The gate runs `ruff check` only, so formatting drifts and the agent occasionally reformats unrelated files as a side effect. Add `--check` to the gate and format once.               | T-09  | Low      |
| 5 | **Session-scoped event loop.** Chosen to avoid `Event loop is closed`. No flakiness appeared through T-04. Still the first thing to suspect if any appears. | — | Watch |
| 6 | **Managed-host compatibility — closed.** Answered concretely by the role split (item 1) and item 11: a managed host only needs to let an initial admin/superuser role create two non-superuser roles (`gymak_migrator`, `gymak_app`) with the grants in `backend/README.md` — it does not need to hand out superuser access to either, and does not need to run any DDL on the operator's behalf, since `gymak_migrator` holds enough privilege (`CREATE` on the database) to run `CREATE EXTENSION citext` itself. See §13.2 item 8. | T-09  | Closed   |
| 7 | **`onboarding_completed` is hardcoded false** in the register and login responses. Correct today, because nothing touches `profiles` yet — and wrong the moment something does: `/auth/me` will report false for a fully onboarded user and the client will route them back into onboarding. No test will fail when it breaks. | T-08 | **Medium** |
| 8 | **Login exponential backoff — closed.** §6.4 asks for backoff after 10 attempts per 15 minutes; `rate_limit.py` implemented fixed windows only, so tripping the limit only ever meant "wait out the rest of the 15-minute window," never an escalating penalty. `_InMemoryFixedWindow` now tracks a separate per-bucket violation streak (`bucket -> (streak, locked_until)`), consulted only for scopes named in `_ESCALATED_SCOPES` (`{"auth.login"}` today). Each violation while a lock is still active — including the one that first trips the base limit — doubles the delay from a 30-second base, capped at one hour, and `Retry-After` reports that escalated delay rather than the window's time-to-boundary. Keyed identically to the base limit: `auth.py`'s two `enforce()` calls (`ip_key`, then `key_for_email`) are unchanged — `enforce()` decides whether to escalate from `scope` alone, so the call sites needed no edit, and "whichever trips first" (§6.4) still governs which bucket's streak advances. `test_login_backoff_escalates_retry_after_beyond_the_window_remainder` proves the growth (30s → 60s → 120s on three consecutive post-trip attempts); `test_login_backoff_state_is_isolated_per_bucket` proves one bucket's escalation does not bleed into another's. | T-09c | Closed |
| 9 | **`set_rls_user` in pre-auth flows — closed.** Three call sites bound `app.user_id` by hand before a pre-auth write to the FORCE-RLS `refresh_tokens` table: `auth_service._issue_session` (register, login, and social sign-in via reuse), `auth_service.refresh` (after its peek discovers the owning user), and `password_reset_service.reset`. Each called `set_rls_user` directly. All three now go through one new helper, `database.bind_pre_auth_rls_user` — a thin async function, not a context manager, since nothing needs to unbind early (the value is transaction-scoped until commit or rollback either way) and a function is a drop-in replacement at each call site with no reindentation. It changes nothing about what any of the three call sites do, only which name they call to do it. `social_service.sign_in` was checked and needs no change: it reuses `_issue_session` rather than binding a fourth time. | T-09c | Closed |
| 10 | **Nothing exercises the real ASGI startup path.** The suite drives the app through httpx inside `conftest`, so uvicorn was never run from T-01 through T-04 — and an import-time `asyncio.run()` in `database.py` meant the application could not start under uvicorn for four consecutive tasks while every test stayed green. Fixed in T-04b by moving the privilege assertion into a lifespan handler. The standing rule that replaces it: after every backend task, start uvicorn and curl `/api/v1/health` before committing. | — | **Standing** |
| 12 | **`refresh_tokens` SELECT is fully open — re-deferred, not closed.** Migration `6b18a9095bb4` (§4.7, §5.5) widened `refresh_tokens`' SELECT policy to `USING (true)` so `/auth/refresh` can look up a token by hash before `app.user_id` is knowable, because `SELECT ... FOR UPDATE` is checked against the UPDATE policy, not the SELECT one — the owner is unknown until the row is found, and the row was invisible until the owner was bound. The read barrier on this table is therefore repository scoping alone (every `token_repo` function takes the relevant id as an argument): RLS still governs INSERT/UPDATE/DELETE (proved in `test_rls.py`), but any row is SELECT-able by any bound identity or none, so a query that forgot to filter by hash or user_id would not be caught by the database. A narrower alternative was considered and declined: a `SECURITY DEFINER` function that looks up by hash under an elevated role and returns only what `/auth/refresh` needs, keeping the owner-only SELECT policy intact for every other path. Declined because the table holds only token hashes, user agents and IPs — none of it is the kind of data (profile fields, health data) RLS in this spec exists to protect at the row level — so the added surface (a `SECURITY DEFINER` function, its own privilege boundary to review) was judged not worth trading for a barrier this table's contents do not need. §11.3 item 11 accepts a re-deferral with a reason; this is that reason. | T-09c | Re-deferred |
| 13 | **RLS tests coupled fixture setup to the mechanism under test — closed.** `tests/security/test_rls.py`'s fixture helper inserted each test's user and profile rows through the same app-role connection and the same owner policy the test then went on to exercise, so a broken *or missing* policy could fail the test at `flush()` during setup instead of at the assertion that names the actual guarantee — exactly the "fixture is not testing the policy, it is testing the fixture" failure mode. Restructured so every fixture row is seeded over a superuser connection (`superuser_database_url`, already in `conftest.py` for the startup-privilege tests), which bypasses RLS unconditionally regardless of policy state — setup can no longer fail because of anything RLS-related. The `gymak_app` / `db_session` connection is now used only for the read, update, or insert each test is actually about. Added `test_dropping_the_owner_policy_makes_the_barrier_provably_load_bearing`, which drops `p_profiles_owner` on `profiles` and installs a deliberately permissive stand-in (`USING (true)`) rather than leaving zero policies — Postgres's documented default-deny for a table with RLS enabled and no policies at all would hide *every* row, including the legitimate owner's own, which would not demonstrate the claim this test exists to prove; the permissive stand-in is what actually reproduces "the ownership check is gone," matching the historical T-01b bug class (a policy present but not restricting anything) rather than a policy absent. It asserts a cross-tenant read that every other test in the file relies on being blocked now succeeds, then restores the original policy in a `finally` block and confirms the same read is blocked again — proving §11.1's "RLS tests must fail when the policy is removed" and §11.3 item 3 against a real, reversed run, not by inspection. No RLS test errors during setup after this change. | T-09c | Closed |
| 11 | **The migration needs privileges the application must not have — closed.** The premise turned out to be wrong: `CREATE EXTENSION citext` does **not** require a superuser on Postgres 13+ — `citext` is a "trusted" extension, installable by any non-superuser role holding `CREATE` on the *database* (confirmed empirically against a real container, not assumed — the schema-level `CREATE` one might expect instead is insufficient and fails with a different error). `gymak_migrator` (item 1) holds exactly that, so `alembic upgrade head` runs `CREATE EXTENSION citext` itself with no manual `psql` step, locally or anywhere else. This answers §13.2 item 8 concretely: a managed host only needs to let you create two non-superuser roles with the grants in `backend/README.md`; it does not need to hand out superuser access, and it does not need a separate DDL path run on the operator's behalf. | T-09 | Closed |
| 14 | **`chk_credential_present` replaced at the database layer — closed.** A CHECK permitting the `@social.gymak.local` placeholder domain was considered and rejected: it can only narrow by shape (email suffix), never verify the thing that actually matters, because CHECK constraints still cannot reference `user_identities`. Migration `ae026cea6d8d` instead adds a `DEFERRABLE INITIALLY DEFERRED` constraint trigger (`trg_users_credential_present`) enforcing the real three-way invariant — password, OR verified email, OR a linked identity — at COMMIT, which only became a real barrier rather than a self-revocable one once `gymak_app` stopped owning `users` (item 1): before the split it could simply `DROP TRIGGER` on its own table. Gap (a) is closed: `tests/unit/test_models.py::test_credential_present_trigger_rejects_orphan_user_at_commit` proves an orphaned row is rejected at commit, and `test_credential_present_trigger_allows_placeholder_account_with_identity` proves the legitimate §5.4 step 5 case still commits. Gap (b) is closed by replacing the test that asserted the barrier's *absence* with the two above. | T-09 | Closed |
| 14(a) | **The dummy-hash branch had no test forcing it — closed.** §5.3 requires `auth_service.login` to run a dummy Argon2 verification when the user is not found, so response time does not leak whether an address is registered. The code path (`_DUMMY_PASSWORD_HASH`, computed once at import) predates this item; nothing previously proved it actually executes rather than being dead code a refactor could silently remove. Not a timing assertion — flaky, same reasoning T-03 gives for its `compare_digest` test — but a structural one: `test_login_with_a_never_registered_email_runs_the_dummy_hash_verifier_once` (`tests/integration/test_auth_register_login.py`) monkeypatches `auth_service.verify_password` with a spy that delegates to the real function, submits a login for an email that has never registered, and asserts the spy was called exactly once, with `_DUMMY_PASSWORD_HASH` as the `password_hash` argument. | T-09c | Closed |
| 15 | **`firebase.py` initialises the SDK at import time.** The same shape as the `database.py` defect T-04b fixed, minus the event-loop crash: importing `app.main` now requires a valid service-account JSON, so `scripts/export_openapi.py` and any CLI that imports the app will fail without one. Move the initialisation into the lifespan handler beside the privilege assertion. | T-09 | Medium |
| 16 | **Firebase misconfiguration is reported to the client as a bad token — closed.** `social_service.py` caught `Exception` broadly around `firebase.verify_id_token`, so an uninitialised SDK — a deployment problem, not a client one — returned `401 SOCIAL_TOKEN_INVALID`, indistinguishable from a genuinely invalid token. The catch is now split: `RuntimeError` (firebase.py's own signal that `init_firebase()` never ran or ran with no credentials — see its docstring), `firebase_admin.auth.CertificateFetchError` (cannot fetch Google's signing certs), and `firebase_admin.exceptions.UnavailableError` (the `check_revoked=True` revocation check, §5.4 step 1, cannot reach Google) are caught first and raise `UpstreamUnavailableError` — §7.3's `503 UPSTREAM_UNAVAILABLE`. Every other failure (bad signature, expired, revoked, wrong project, malformed input, ...) still falls through to the original broad `except Exception` and stays `401 SOCIAL_TOKEN_INVALID`. Both paths are tested in `tests/integration/test_social_auth.py`: `test_uninitialised_admin_sdk_returns_upstream_unavailable_not_social_token_invalid`, `test_certificate_fetch_failure_returns_upstream_unavailable`, `test_revocation_check_unavailable_returns_upstream_unavailable`, alongside the pre-existing `test_firebase_verification_failure_returns_social_token_invalid` proving the 401 path is unchanged. `tests/integration/test_firebase_lazy_init.py`'s own control for A.5 item 15 asserted only `status_code < 500`, written when this endpoint's actual response for a missing credential was 401; updated to assert the now-correct `503 UPSTREAM_UNAVAILABLE` specifically, since that is what a misconfigured deployment must report. | T-09c | Closed |
| 17 | **`mypy --strict` fails on `tests/`.** 30 errors across five integration test files, all pre-existing. 28 are three mechanical patterns from a copy-pasted helper shape repeated per file rather than shared: 14 `no-untyped-def`, 8 bare `-> dict` instead of `dict[str, Any]`, 6 `no-any-return` from `response.json()` leaking `Any`. The other 2 are `in` against `AppError.detail`, typed `str \| None`, without narrowing. The documented gate is scoped to `app` until these are closed, so the type checker currently covers less than it appears to. One afternoon of mechanical work, and the shared helper the five files each reimplemented is worth extracting while doing it. | T-09c | Medium |

---

**End of GYMAK-P1-SPEC-001 v1.2** · Phase 1 only: authentication, session management, and one-time profile capture. Nothing in §1.2 gets built. When §11.3 is fully satisfied, baseline this document at v1.3 with whatever reality changed, and only then open Phase 2.