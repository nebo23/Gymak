# Gymak — Phase 2 Build Specification

> **Document ID** GYMAK-P2-SPEC-001 · **Version** 2.0 · **Date** 13 August 2026
> **Owner** Nabil — sole developer · **Phase** 2 of N — training plan, workout logging, body-weight tracking, dashboard
> **Stack** unchanged from Phase 1 — FastAPI · PostgreSQL · Firebase Auth (social sign-in only) · React Native (Expo)
> **Builds on** GYMAK-P1-SPEC-001 v1.3 (`docs/PHASE-1-SPEC.md`)
> **Status** Not started. Phase 1 is code-complete; §0.4 lists what must be true before T-15 begins.
>
> **This file is the single source of truth for Phase 2.** Phase 1's document remains authoritative
> for everything it covers — auth, tokens, the profile, the error envelope, the design tokens — and
> this document never contradicts it. Where Phase 2 needs to change a Phase 1 rule, it says so
> explicitly and names the section it amends. Build nothing from the §1.2 out-of-scope list.
> Execute one task from §12 at a time, touching only the files that task names.

### What Phase 2 is for, in one paragraph

After Phase 1 a user can create an account, sign in, and describe their body. That is an account,
not a product — the home screen says so out loud: _"your training plan arrives in the next phase."_
Phase 2 is that sentence coming true. It gives the user a plan to follow, a screen to log the work
against while they are standing in the gym holding a phone with sweaty hands, a record of what they
lifted last time, and an honest picture of their body weight moving over time. Nothing in this
phase is decorative: every number shown to the user is one the user themselves put into the
database, or is arithmetic over those numbers that the user could redo by hand.

---

## 0 · How to use this document

### 0.1 Reading order

- **0** — This section: rules of engagement, entry conditions, what Phase 1 left behind
- **1** — Phase 2 scope — what ships, what is explicitly deferred
- **2** — Architecture decisions (P2-ADR-01 … 09)
- **3** — Repository layout — what is added to the Phase 1 tree
- **4** — Data model — seven new tables, one altered column, full DDL and RLS
- **5** — API contract — every new endpoint, request, response, error
- **6** — The plan generator — the one piece of real domain logic in this phase
- **7** — Validation rules and the Phase 2 error codes
- **8** — Mobile application — navigation, screens, states
- **9** — Design — what is reused, what is new, what is forbidden
- **10** — Testing requirements and the Phase 2 definition of done
- **11** — Carried-forward debt from Phase 1
- **12** — Task pack — ordered, copy-paste prompts T-15 … T-31
- **13** — Decisions Nabil must confirm
- **A** — Appendix — environment variables, dependencies, seed data, glossary

### 0.2 Rules of engagement for the coding agent

> **These are Phase 1 §0.2's rules, unchanged, because they worked. They override any instinct
> to be helpful beyond the task.**
>
> 1.  **One task at a time.** Execute exactly one task from §12. Do not start the next task, do not "also fix" an adjacent file, do not refactor code you were not asked about.
> 2.  **Named files only.** Each task lists the files it may create or modify. **Standing exception:** `backend/pyproject.toml`, `backend/tests/**`, `mobile/src/i18n/*.json` and `mobile/app/(app)/_dev-gallery.tsx` are always in scope — a task that cannot adjust its own test configuration will delete a test instead, and a task that cannot add a translation key will hardcode a string.
> 3.  **No scope invention.** If a feature is not in §1.1, it does not get built, stubbed, or scaffolded — not nutrition, not AI, not payments, not push.
> 4.  **Ask, don't assume.** If a required detail is genuinely absent from this document, stop and ask one specific question. Do not invent a schema column, an endpoint, an exercise, or a library.
> 5.  **No new dependencies** beyond Phase 1 Appendix A.2 plus §A.2 below, without asking first.
> 6.  **Report before changing.** State what the current implementation actually does before you modify it.
> 7.  **Every task ends with its tests passing** and the diff summarised in plain language: files touched, what changed, what to verify manually, and what you deliberately did not do. Paste real command output with exit codes — `ruff check`, `ruff format --check`, `mypy --strict .`, `pytest`.
> 8.  **The device rule from Phase 1 stands.** After every backend task, start uvicorn and reach the new endpoint from the phone before committing. A green suite is not evidence that the application runs — Phase 1 proved that twice (§A.5 items 10 and 11).

### 0.3 The three steps this document covers

| Step       | Deliverable                                                                                          | Tasks       | Done when                                                        |
| ---------- | ---------------------------------------------------------------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| **Step 1** | Backend data layer: schema, the seeded exercise library, the plan generator                          | T-15 … T-17 | A profile can be turned into a stored, readable weekly plan      |
| **Step 2** | Backend logging layer: sessions, sets, body weight, records, the dashboard aggregate                 | T-18 … T-22 | A full workout can be started, logged, finished and read back    |
| **Step 3** | React Native client: tab shell, dashboard, plan, the active-workout screen, history, weight, library | T-23 … T-30 | A real device completes a whole workout end to end, offline-free |
| **Step 4** | Engineering infrastructure: a mobile runner that can render, generated API types, CI, Docker             | T-32 … T-35 | Every gate above runs on a pull request instead of from memory   |

Steps 1 to 3 run in order. Do not begin step 3 while any step-1 or step-2 test is red.
Step 4 depends on none of them and blocks none of them: it changes no backend logic and
no screen. T-31 sits outside the steps — it is optional, and §13.1 decision 3 recommends
deferring it to Phase 3.

### 0.4 Entry conditions — do not start T-15 until every one of these is true

1. Phase 1's §11.3 definition of done holds. In particular: the cross-tenant matrix is green and the RLS tests still fail when a policy is dropped.
2. `alembic upgrade head` runs clean on a fresh database, and `downgrade` back to base runs clean too.
3. The mobile app installs on a physical device and completes register → onboarding → home.
4. §11 of _this_ document — the Phase 1 carry-over list — has been read, and each item is either fixed or consciously accepted. Two of them (the hardcoded LAN IP in `eas.json`, the untracked `mobile/android/`) will bite during Phase 2 if they are left alone.
5. Decisions §13.1 are answered. The plan generator cannot be written while decision 1 is open.

---

## 1 · Phase 2 scope

### 1.1 In scope — build exactly this

| ID         | Requirement                                                                                                 | Layer     |
| ---------- | ----------------------------------------------------------------------------------------------------------- | --------- |
| P2-FR-001  | A seeded, read-only exercise library, bilingual, filterable by muscle group and equipment                   | API + app |
| P2-FR-002  | Generate a weekly training plan deterministically from the Phase 1 profile plus a days-per-week choice      | API       |
| P2-FR-003  | Read the current plan: its week structure, each day's exercises, and each exercise's set and rep targets    | API + app |
| P2-FR-004  | Regenerate the plan when the profile changes materially, keeping the previous plan's history intact         | API + app |
| P2-FR-005  | Start a workout session from a plan day, or an empty session with no plan behind it                         | API + app |
| P2-FR-006  | Log a set — reps, weight, optional RPE, warm-up flag — and edit or delete it while the session is open      | API + app |
| P2-FR-007  | Finish a session, or abandon it; the server computes duration and total volume                              | API + app |
| P2-FR-008  | Read workout history, and read one past session in full detail                                              | API + app |
| P2-FR-009  | Log body weight, one entry per calendar day, editable and deletable                                         | API + app |
| P2-FR-010  | See body weight over time as a line, with a seven-day moving average                                        | API + app |
| P2-FR-011  | Derived personal records per exercise: heaviest set, best estimated one-rep max, best volume in a session   | API + app |
| P2-FR-012  | A dashboard: the next workout, the current streak, this week's completion, the weight trend, recent records | API + app |
| P2-FR-013  | A rest timer between sets, running on the device                                                            | App       |
| P2-FR-014  | Bottom tab navigation replacing Phase 1's single-screen app stack                                           | App       |
| P2-FR-015  | Sign in or register with Facebook, brokered through Firebase Auth — the Phase 1 P1-FR-004 carry-over        | API + app |
| P2-SAF-002 | A user under 18 never receives a calorie-deficit or weight-loss framing anywhere in the plan or dashboard   | API + app |
| P2-SAF-003 | A beginner's generated plan never exceeds the volume ceiling in §6.4, whatever the goal                     | API       |
| P2-SAF-004 | Every screen that displays training advice carries the one-line medical disclaimer in §8.6                  | App       |

### 1.2 Out of scope — do not build, stub, or scaffold

> **Anything below appearing in a Phase 2 pull request is a defect. This list is longer than
> Phase 1's, not shorter — the temptation grows as the app starts to look real.**
>
> - **Nutrition of any kind** — calorie targets, TDEE display, macros, food search, meal logging. The profile already carries everything a TDEE needs, and that is exactly why the temptation exists. Phase 3.
> - **Any LLM call, RAG pipeline, or AI coach surface.** The plan generator is a pure function with a lookup table (P2-ADR-01). If a task's output contains a prompt string, it is wrong.
> - Subscriptions, receipt validation, paywalls, "premium" gating — `premiumBg` exists as a token and stays unused.
> - Push notifications, FCM wiring, workout reminders.
> - Progress photos, body measurements beyond weight, body-fat estimation.
> - Apple Health / Google Fit / wearable import.
> - Apple Sign-In (Phase 3, with the first iOS build).
> - Offline mutation queue. Phase 2 logging is online-only; see P2-ADR-08 for what happens on a dropped connection mid-workout, which is a UX problem this phase does solve, not a sync problem it does not.
> - Social features: friends, sharing, leaderboards, comments.
> - Custom user-created exercises, or user edits to the library. Read-only, seeded (P2-ADR-02).
> - Video or animated exercise demonstrations. A text instruction and a static illustration slot only.
> - Supersets, drop sets, EMOM/AMRAP, tempo prescription. Straight sets only in Phase 2.
> - Cardio, mobility, or class-style sessions. Resistance training only.
> - Plan editing by the user — swapping an exercise, adding a day. Read-only plan in Phase 2; §13.1 decision 4 records the argument for Phase 3.
> - The physical purge job for deleted accounts (still Phase 3, carried from Phase 1 §A.3).

### 1.3 Non-functional targets that apply now

| ID        | Target                                                                                                            | Verified by                                   |
| --------- | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| P2-NFR-01 | p95 under 400 ms for every endpoint, including `GET /dashboard` with 12 months of history seeded                  | A seeded-load timing test in the suite        |
| P2-NFR-02 | Logging a set completes in under 250 ms p95 from tap to persisted, on a LAN connection                            | Manual timing on device, recorded in the task |
| P2-NFR-03 | No user can read or write another user's plan, session, set, or weight entry through any endpoint                 | The Phase 1 cross-tenant matrix, extended     |
| P2-NFR-04 | Backend line coverage stays ≥ 80% overall, and ≥ 95% in the plan generator and the metrics module                 | pytest-cov gate, greenlet-aware               |
| P2-NFR-05 | The active-workout screen never loses a logged set to a navigation, a background, or a rotation                   | Manual device checklist §10.2 items 5–8       |
| P2-NFR-06 | Every new interactive element is ≥ 48 dp, labelled, and meets WCAG AA contrast, in both themes and both languages | Manual audit against Phase 1 §10.6            |
| P2-NFR-07 | The generated OpenAPI document is committed and matches the code                                                  | Schema drift check, unchanged from Phase 1    |
| P2-NFR-08 | The dashboard renders its full skeleton in under 100 ms and never shows a spinner over an already-loaded value    | Manual device check                           |

---

## 2 · Architecture decisions

Nine decisions. They are settled, and recorded so the agent does not relitigate them mid-build.
Phase 1's P1-ADR-01 … 07 all still hold and are not repeated here.

### P2-ADR-01 · The plan generator is a deterministic pure function, not a model

|                 |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Decision**    | `services/plan_generator.py` exposes one pure function: profile fields plus a days-per-week integer in, a fully-specified plan structure out. No I/O, no randomness, no network, no LLM. Same input, same output, forever — and a `generator_version` integer is stored on every generated plan so a future change to the rules is traceable in the data.                                                                                                                                                                                                                                                                              |
| **Why**         | Three reasons, in order of weight. **(1) Safety.** This function decides how much load a possibly-16-year-old beginner is told to lift. A deterministic table can be reviewed line by line by a human who knows training; a model's output cannot. **(2) Testability.** Golden-file tests over the full input space (3 experience levels × 3 goals × 5 activity levels × 5 day counts = 225 combinations) are trivial for a pure function and impossible for a stochastic one. **(3) Honesty.** Phase 1's home screen promised "nothing made up." A plan assembled from a reviewed table keeps that promise; a generated one does not. |
| **Consequence** | The plan is less personalised than a marketing page would like. That is the correct trade for Phase 2. Personalisation that adapts to logged performance is a Phase 4 concern and will have real data to work with by then, which it does not today.                                                                                                                                                                                                                                                                                                                                                                                   |
| **Boundary**    | The function may not import anything from `models/`, `repositories/`, or `routers/`. It takes primitives and returns a dataclass. A test that needs a database to test the generator means the boundary has been broken.                                                                                                                                                                                                                                                                                                                                                                                                               |

### P2-ADR-02 · The exercise library is seeded data owned by a migration, not user content

|                 |                                                                                                                                                                                                                                                                                                                                           |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Decision**    | Exercises live in a table populated by an Alembic data migration from a committed JSON file, `backend/app/data/exercises.json`. No endpoint creates, edits, or deletes an exercise. The mobile app never caches the list to disk beyond TanStack Query's normal in-memory cache.                                                          |
| **Why**         | A library of ~60 movements is reference data with a slow change rate and a correctness requirement — a wrong muscle group or a wrong equipment tag produces a wrong plan. Putting it in a reviewed file under version control means a change to it is a diff someone reads, not a row someone typed into production at midnight.          |
| **Bilingual**   | `name_en`/`name_ar` and `instructions_en`/`instructions_ar` are columns on the row, not a separate translation table. Two languages are settled (Phase 1 §13.2 item 7) and a join table for a fixed pair of columns is complexity with no payer. If a third language is ever added, that is the migration that introduces the join table. |
| **Soft delete** | `is_active`. A removed exercise must not vanish from a session logged three months ago, so rows are never deleted — they are deactivated and stop appearing in the library listing while remaining resolvable by id.                                                                                                                      |

### P2-ADR-03 · A workout session is a small state machine with exactly one active session per user

|                 |                                                                                                                                                                                                                                                                                                                      |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **States**      | `in_progress` → `completed` \| `abandoned`. No other transitions. A completed or abandoned session is immutable: its sets can no longer be added, edited, or deleted.                                                                                                                                                |
| **Uniqueness**  | A partial unique index enforces at most one `in_progress` session per user, in the database, not in the service. Starting a second one returns `409 SESSION_ALREADY_ACTIVE` carrying the existing session's id, so the client can offer "resume" rather than failing blankly.                                        |
| **Why**         | The alternative — many concurrent sessions — sounds more flexible and is a bug factory: the app has one "log a set" button and no way to ask which session it belongs to. The single-active rule is what the interface already assumes, so the database should assert it.                                            |
| **Abandonment** | There is no automatic timeout in Phase 2. A session left open for three days stays open until the user finishes or abandons it, and the app shows a "you have a workout in progress since Tuesday" banner. An auto-abandon job invents a policy nobody has decided; §13.1 decision 5 records it as an open question. |

### P2-ADR-04 · Sets store absolute values; derived numbers are computed on read

|                                    |                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Stored**                         | `reps` (integer), `weight_kg` (numeric), `rpe` (numeric, optional), `is_warmup` (boolean). Nothing else about the set's performance.                                                                                                                                                                                                                                                                                                                |
| **Computed on read, never stored** | Estimated one-rep max (Epley: `weight × (1 + reps/30)`), set volume (`reps × weight`), session volume (the sum over non-warm-up sets), and every personal record.                                                                                                                                                                                                                                                                                   |
| **Why**                            | A stored derived value is a value that can disagree with its inputs. Phase 1 already made this choice once — `age` is computed from `birth_date` and never stored (§5.8) — and the reasoning is identical here, with more arithmetic at stake. The formula also _will_ change: Epley is a reasonable default and Brzycki is a defensible alternative, and switching a computed formula is a code change while switching a stored one is a backfill. |
| **Performance**                    | If the dashboard aggregate becomes slow with real data, the answer is an index or a materialised view with an explicit refresh, decided against a measurement — not a denormalised column added pre-emptively. P2-NFR-01 is the trigger, and it is tested with seeded volume rather than guessed at.                                                                                                                                                |
| **Warm-up sets**                   | Excluded from volume, from records, and from "sets completed" counts. Included in the session detail view, because the user logged them and hiding a user's own data is worse than a slightly noisier screen.                                                                                                                                                                                                                                       |

### P2-ADR-05 · Personal records are a query, not a table

A `records` table would need to be recalculated whenever a set is edited or deleted, whenever a
session is abandoned, and whenever an exercise is deactivated — three write paths that must all
remember to do it, and one forgotten path means the app displays a record the user never set.
Records are therefore a read-time aggregation over `workout_sets`, expressed once in
`repositories/metrics_repo.py`. If P2-NFR-01 fails on a real dataset, the fix is the indexes named
in §4.9, and only if those are insufficient does a materialised view get considered — with its
refresh path specified in the task that adds it.

### P2-ADR-06 · Body weight is a log, and `profiles.weight_kg` becomes its cached head

|                                        |                                                                                                                                                                                                                                                                                                                                                                                                |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Decision**                           | `body_weight_entries` holds one row per user per calendar day. `profiles.weight_kg` — which Phase 1 already ships and every plan calculation reads — is kept in sync with the most recent entry, written in the same transaction as the entry itself.                                                                                                                                          |
| **Why not drop `profiles.weight_kg`?** | Because Phase 1's onboarding writes it before any log entry exists, `GET /profile` returns it, and the Settings screen edits it. Removing it is a migration plus a client change plus a semantic argument, in exchange for removing one line of transactional bookkeeping. Not worth it.                                                                                                       |
| **Two writers, one truth**             | Writing a body-weight entry updates `profiles.weight_kg` if — and only if — the entry is the newest one for that user. Editing `weight_kg` through `PATCH /profile` (Phase 1 §5.9) **also** upserts today's body-weight entry, so the two surfaces cannot diverge. Both directions are integration-tested; this is the single most likely place for a Phase 2 data bug and deserves the tests. |
| **One per day**                        | `UNIQUE (user_id, measured_on)`. A second entry for the same date is an upsert, not an error — the user stepped on the scale twice, and the later reading is the one they meant.                                                                                                                                                                                                               |

### P2-ADR-07 · One dashboard endpoint, computed server-side

`GET /dashboard` returns everything the home screen renders, in one round trip. The alternative —
the client calling six endpoints and assembling them — means six loading states, six failure modes,
and a home screen whose correctness depends on the client's arithmetic. It also means the streak
would be computed in the client's timezone, which is exactly the bug §4.2's `timezone` column
exists to prevent. The endpoint is allowed to be the slowest in the API; P2-NFR-01 bounds it.

### P2-ADR-08 · Set logging is online-only, and the interface is honest about it

Phase 1 §1.2 deferred the offline mutation queue to Phase 3, and that stands. But "no offline
queue" must not mean "the user loses their session when the gym's wifi drops." Phase 2's answer is
narrower and shippable: each set is `POST`ed the moment it is logged; a failure leaves the set
visibly marked as unsent with a retry affordance, the set stays on screen, and the session is not
navigable away from until every set is either sent or explicitly discarded by the user. The queue
is in-memory and dies with the process — which is the honest limit, and is stated in §8.5 rather
than hidden.

### P2-ADR-09 · Every new table gets RLS with `FORCE` on day one, and `exercises` is the single exception

Phase 1 learned this the hard way (§A.5 items 1 and 13). Every user-owned table added in this
phase — `programs`, `program_days`, `program_exercises`, `workout_sessions`, `workout_sets`,
`body_weight_entries` — gets `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`, and an owner
policy in the same migration that creates it, not in a follow-up. `exercises` is public reference
data with no `user_id`: it gets `SELECT` granted to `gymak_app` and no policy, and the security
test asserts that this is deliberate rather than forgotten.

`workout_sets` has no `user_id` column of its own — it hangs off `workout_sessions`. Its policy
therefore reads through the parent (`EXISTS (SELECT 1 FROM workout_sessions s WHERE s.id =
workout_sets.session_id AND s.user_id = current_app_user())`), and the cross-tenant test must
prove that a set belonging to another user's session is invisible, not merely that the session is.

---

## 3 · Repository layout

Additions only. Everything from Phase 1 §3 stays exactly where it is, and the layering rule —
routers may not import models, services may not import HTTP objects, repositories are the only
place a query is written — is unchanged and still enforced by review.

```text
backend/app/
├── data/
│   └── exercises.json              # NEW · the seeded library (P2-ADR-02), ~60 movements
├── models/
│   ├── exercise.py                 # NEW
│   ├── program.py                  # NEW · Program, ProgramDay, ProgramExercise
│   ├── workout.py                  # NEW · WorkoutSession, WorkoutSet
│   └── body_weight.py              # NEW
├── schemas/
│   ├── exercise.py  program.py  workout.py  metrics.py    # NEW
├── repositories/
│   ├── exercise_repo.py  program_repo.py                  # NEW
│   ├── workout_repo.py  body_weight_repo.py               # NEW
│   └── metrics_repo.py             # NEW · records + dashboard aggregation (P2-ADR-05)
├── services/
│   ├── plan_generator.py           # NEW · the pure function (P2-ADR-01), imports nothing local
│   ├── program_service.py  workout_service.py             # NEW
│   ├── body_weight_service.py  dashboard_service.py       # NEW
│   └── metrics.py                  # NEW · e1RM, volume, streak — pure arithmetic, no I/O
└── routers/
    ├── exercises.py  program.py  workouts.py              # NEW
    └── body_weight.py  dashboard.py                       # NEW

mobile/
├── app/(app)/
│   ├── _layout.tsx                 # CHANGED · becomes a Tabs layout (P2-FR-014)
│   ├── index.tsx                   # NEW · dashboard, replaces home.tsx
│   ├── plan/index.tsx  plan/[dayId].tsx                   # NEW
│   ├── workout/active.tsx  workout/[id].tsx               # NEW
│   ├── history.tsx                 # NEW
│   ├── progress.tsx                # NEW · weight log + chart
│   ├── exercises/index.tsx  exercises/[id].tsx            # NEW
│   └── settings.tsx                # UNCHANGED, moves under the Settings tab
└── src/
    ├── api/       exercises.ts  program.ts  workouts.ts   # NEW
    │              bodyWeight.ts  dashboard.ts             # NEW
    ├── components/ GCard.tsx  GStat.tsx  GChip.tsx        # NEW
    │               GEmptyState.tsx  GSkeleton.tsx         # NEW
    │               GListRow.tsx  GNumberField.tsx         # NEW
    │               GRestTimer.tsx  GLineChart.tsx  GSheet.tsx   # NEW
    └── workout/   activeSession.ts                        # NEW · the in-memory send queue (P2-ADR-08)
```

> **`home.tsx` is deleted, not left behind.** Phase 1's placeholder home exists to say "the plan
> arrives next phase." Once the plan arrives, that screen is a lie. T-24 deletes it in the same
> commit that adds the dashboard.

---

## 4 · Data model

Seven new tables, one altered table. Every timestamp is `timestamptz` in UTC; every date the user
thinks of as a calendar day (`measured_on`, the streak's day boundaries) is a `date` resolved in
the user's timezone, per §4.2. Every table gets `created_at`; every mutable table gets `updated_at`
maintained by the existing trigger.

### 4.1 exercises

| Column             | Type        | Constraints                                                                                                                | Notes                                                                                                                            |
| ------------------ | ----------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| id                 | uuid        | PK                                                                                                                         | UUID v7, but **stable across environments** — the seed file carries the id so a session logged in staging resolves in production |
| slug               | text        | UNIQUE, NOT NULL                                                                                                           | `barbell-back-squat`. The human-readable key the seed file and the generator refer to                                            |
| name_en / name_ar  | text        | NOT NULL                                                                                                                   | Both required — a missing Arabic name is a shipped bug, not a fallback                                                           |
| primary_muscle     | text        | CHECK IN (§4.1a)                                                                                                           | Exactly one                                                                                                                      |
| secondary_muscles  | text[]      | NOT NULL DEFAULT '{}'                                                                                                      | Zero or more from the same vocabulary                                                                                            |
| equipment          | text        | CHECK IN ('barbell','dumbbell','machine','cable','bodyweight','kettlebell','band')                                         | Drives the "what does this gym have" filter                                                                                      |
| movement_pattern   | text        | CHECK IN ('squat','hinge','horizontal_push','vertical_push','horizontal_pull','vertical_pull','lunge','carry','isolation') | The generator selects by pattern, not by name                                                                                    |
| is_compound        | boolean     | NOT NULL                                                                                                                   | Compounds are ordered first within a day (§6.3)                                                                                  |
| difficulty         | text        | CHECK IN ('beginner','intermediate','advanced')                                                                            | The minimum experience level this movement is offered at                                                                         |
| instructions_en/ar | text        | NOT NULL                                                                                                                   | Two to four sentences. Cues, not paragraphs.                                                                                     |
| is_active          | boolean     | NOT NULL DEFAULT true                                                                                                      | P2-ADR-02's soft delete                                                                                                          |
| created_at         | timestamptz | NOT NULL DEFAULT now()                                                                                                     |                                                                                                                                  |

**§4.1a — the muscle vocabulary, closed set:** `chest`, `back`, `lats`, `traps`, `front_delts`,
`side_delts`, `rear_delts`, `biceps`, `triceps`, `forearms`, `quads`, `hamstrings`, `glutes`,
`calves`, `abs`, `obliques`, `lower_back`. Seventeen values. Adding an eighteenth is a migration
plus a translation key plus a review of every generator rule that filters on muscles — not a
casual change.

### 4.2 profiles — one added column

| Column   | Type | Constraints                     | Notes                                            |
| -------- | ---- | ------------------------------- | ------------------------------------------------ |
| timezone | text | NOT NULL DEFAULT 'Africa/Cairo' | IANA name. **New in Phase 2, and load-bearing.** |

> **Why a timezone column is not optional**
>
> The streak in P2-FR-012 asks "did the user train yesterday?" — a question with no answer until
> "yesterday" is defined. Computing it in UTC breaks for every user east or west of it: a workout
> logged at 01:00 Cairo time lands on the previous UTC day, and a user who trains late every
> evening would see their streak reset at random. Computing it in the client's timezone means the
> server and the client disagree, and the number changes when the user flies. The column is
> written at onboarding from `expo-localization`'s `getCalendars()[0].timeZone`, is editable in
> Settings, and every day-boundary calculation in this phase resolves through it. The default
> exists only for the rows Phase 1 already created; a client that omits it on new writes is a bug
> the test suite catches.
>
> This is an amendment to Phase 1 §4.3 and §5.9 — `timezone` joins the editable field list.
>
> **Ownership, so it does not fall between tasks:** T-15 creates the column. **T-18** adds the
> ORM attribute and the `PATCH /profile` editable-field wiring, because T-18 is the first
> consumer — `workout_sessions.local_date` cannot be computed without it — not T-20. **T-23**
> sends the device zone from the client. A task that needs the value and finds it unwired
> should stop and say so rather than reading a default.

### 4.3 programs

| Column            | Type        | Constraints                                           | Notes                                                                             |
| ----------------- | ----------- | ----------------------------------------------------- | --------------------------------------------------------------------------------- |
| id                | uuid        | PK                                                    |                                                                                   |
| user_id           | uuid        | FK users(id) ON DELETE CASCADE, NOT NULL              |                                                                                   |
| days_per_week     | int         | CHECK BETWEEN 2 AND 6                                 | The one input the user gives beyond the profile                                   |
| split_type        | text        | CHECK IN ('full_body','upper_lower','push_pull_legs') | Chosen by the generator from `days_per_week`, stored so the app can name the plan |
| goal              | text        | CHECK IN ('lose','gain','maintain')                   | Snapshot of the profile at generation time                                        |
| experience_level  | text        | CHECK IN ('beginner','intermediate','advanced')       | Snapshot                                                                          |
| generator_version | int         | NOT NULL                                              | P2-ADR-01. Bumped whenever a generator rule changes.                              |
| is_current        | boolean     | NOT NULL DEFAULT true                                 | Exactly one true per user, enforced by a partial unique index                     |
| created_at        | timestamptz | NOT NULL DEFAULT now()                                |                                                                                   |
| superseded_at     | timestamptz | NULL                                                  | Set when a regeneration replaces this plan                                        |

**Snapshots, not joins.** `goal` and `experience_level` are copied onto the program rather than read
from the profile at display time, because a user who changes their goal in Settings has not
retroactively changed the plan they followed for six weeks. The dashboard compares the two and
offers a regeneration when they diverge — which is P2-FR-004, and is a prompt, never automatic.

**Old programs are kept.** Regeneration sets `is_current = false` and `superseded_at = now()` on the
previous row. Sessions logged against its days keep resolving.

### 4.4 program_days

| Column        | Type   | Constraints                                           | Notes                                                                                                                         |
| ------------- | ------ | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| id            | uuid   | PK                                                    |                                                                                                                               |
| program_id    | uuid   | FK programs(id) ON DELETE CASCADE, NOT NULL           |                                                                                                                               |
| day_index     | int    | CHECK BETWEEN 1 AND 6, UNIQUE (program_id, day_index) | Ordinal within the week, not a weekday. The user trains on their own days.                                                    |
| label_key     | text   | NOT NULL                                              | An i18n key, not a translated string — `plan.day.upper`, `plan.day.push`. The server never sends display text (Phase 1 §9.6). |
| focus_muscles | text[] | NOT NULL                                              | For the day card's subtitle chips                                                                                             |

> **`day_index`, not `weekday`.** Assigning "Monday = Upper" forces a schedule the user did not
> choose and makes a missed Monday look like a failure. Days are an ordered list the user works
> through; the streak counts sessions, not calendar adherence.

### 4.5 program_exercises

| Column                            | Type | Constraints                                     | Notes                                                                                                                                            |
| --------------------------------- | ---- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| id                                | uuid | PK                                              |                                                                                                                                                  |
| program_day_id                    | uuid | FK program_days(id) ON DELETE CASCADE, NOT NULL |                                                                                                                                                  |
| exercise_id                       | uuid | FK exercises(id) ON DELETE RESTRICT, NOT NULL   | `RESTRICT`, not `CASCADE` — P2-ADR-02 says exercises are never deleted, and this constraint is what makes that a guarantee rather than a promise |
| position                          | int  | NOT NULL, UNIQUE (program_day_id, position)     | Compounds first (§6.3)                                                                                                                           |
| target_sets                       | int  | CHECK BETWEEN 1 AND 8                           |                                                                                                                                                  |
| target_reps_min / target_reps_max | int  | CHECK 1 ≤ min ≤ max ≤ 30                        | A range, shown as "8–12"                                                                                                                         |
| rest_seconds                      | int  | CHECK BETWEEN 30 AND 300                        | Seeds the rest timer (P2-FR-013)                                                                                                                 |

### 4.6 workout_sessions

| Column           | Type         | Constraints                                      | Notes                                                                                                                                                          |
| ---------------- | ------------ | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| id               | uuid         | PK                                               |                                                                                                                                                                |
| user_id          | uuid         | FK users(id) ON DELETE CASCADE, NOT NULL         |                                                                                                                                                                |
| program_day_id   | uuid         | FK program_days(id) ON DELETE SET NULL, NULL     | NULL for an empty session (P2-FR-005). `SET NULL` so deleting an old program never deletes history                                                             |
| status           | text         | CHECK IN ('in_progress','completed','abandoned') | P2-ADR-03                                                                                                                                                      |
| started_at       | timestamptz  | NOT NULL DEFAULT now()                           | Server clock, never the client's                                                                                                                               |
| ended_at         | timestamptz  | NULL                                             | Set on finish or abandon                                                                                                                                       |
| duration_seconds | int          | NULL                                             | Computed server-side at finish, stored because `ended_at - started_at` overstates a session the user paused for an hour — see §5.8                             |
| total_volume_kg  | numeric(9,2) | NULL                                             | Computed at finish over non-warm-up sets. Stored here **only**, as a finish-time snapshot; live volume during a session is computed on read (P2-ADR-04)        |
| notes            | text         | NULL, ≤ 500 chars                                |                                                                                                                                                                |
| local_date       | date         | NOT NULL                                         | `started_at` resolved into the user's §4.2 timezone at insert. This is the column the streak groups by, so the streak never re-derives a timezone at read time |

**Partial unique index:** `CREATE UNIQUE INDEX ux_one_active_session ON workout_sessions (user_id)
WHERE status = 'in_progress';` — P2-ADR-03, enforced by the database.

### 4.7 workout_sets

| Column      | Type         | Constraints                                           | Notes                                                                      |
| ----------- | ------------ | ----------------------------------------------------- | -------------------------------------------------------------------------- |
| id          | uuid         | PK                                                    |                                                                            |
| session_id  | uuid         | FK workout_sessions(id) ON DELETE CASCADE, NOT NULL   | No `user_id` — ownership reads through the parent (P2-ADR-09)              |
| exercise_id | uuid         | FK exercises(id) ON DELETE RESTRICT, NOT NULL         |                                                                            |
| set_index   | int          | NOT NULL, UNIQUE (session_id, exercise_id, set_index) | 1-based, per exercise within the session                                   |
| reps        | int          | CHECK BETWEEN 1 AND 100                               |                                                                            |
| weight_kg   | numeric(6,2) | CHECK BETWEEN 0 AND 500                               | Zero is legitimate — a bodyweight movement                                 |
| rpe         | numeric(3,1) | NULL, CHECK BETWEEN 5 AND 10                          | Optional. A user who does not know what RPE is never sees the field (§8.4) |
| is_warmup   | boolean      | NOT NULL DEFAULT false                                | P2-ADR-04                                                                  |
| logged_at   | timestamptz  | NOT NULL DEFAULT now()                                | Server clock. Drives the rest timer's "time since last set"                |

### 4.8 body_weight_entries

| Column                  | Type         | Constraints                              | Notes                                                     |
| ----------------------- | ------------ | ---------------------------------------- | --------------------------------------------------------- |
| id                      | uuid         | PK                                       |                                                           |
| user_id                 | uuid         | FK users(id) ON DELETE CASCADE, NOT NULL |                                                           |
| measured_on             | date         | NOT NULL, UNIQUE (user_id, measured_on)  | The user's local calendar day (§4.2). Never in the future |
| weight_kg               | numeric(5,2) | CHECK BETWEEN 30 AND 300                 | The same range as `profiles.weight_kg`, deliberately      |
| note                    | text         | NULL, ≤ 200 chars                        |                                                           |
| created_at / updated_at | timestamptz  | NOT NULL                                 |                                                           |

### 4.9 Indexes — named, because P2-ADR-05 depends on them

```sql
CREATE INDEX ix_sessions_user_status      ON workout_sessions (user_id, status);
CREATE INDEX ix_sessions_user_local_date  ON workout_sessions (user_id, local_date DESC);
CREATE INDEX ix_sets_session              ON workout_sets (session_id);
CREATE INDEX ix_sets_exercise             ON workout_sets (exercise_id) WHERE is_warmup = false;
CREATE INDEX ix_bodyweight_user_date      ON body_weight_entries (user_id, measured_on DESC);
CREATE INDEX ix_program_days_program      ON program_days (program_id, day_index);
```

The records query joins `workout_sets` to `workout_sessions` filtered by `user_id` and
`status = 'completed'`, grouped by `exercise_id`. `ix_sets_exercise` is partial because warm-up
sets can never set a record and excluding them shrinks the index that matters.

### 4.10 RLS — the pattern every new table follows

```sql
ALTER TABLE workout_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE workout_sessions FORCE  ROW LEVEL SECURITY;
CREATE POLICY p_workout_sessions_owner ON workout_sessions
  USING      (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

-- workout_sets owns no user_id; it reads through its parent (P2-ADR-09)
ALTER TABLE workout_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE workout_sets FORCE  ROW LEVEL SECURITY;
CREATE POLICY p_workout_sets_owner ON workout_sets
  USING (EXISTS (SELECT 1 FROM workout_sessions s
                 WHERE s.id = workout_sets.session_id
                   AND s.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid))
  WITH CHECK (EXISTS (SELECT 1 FROM workout_sessions s
                 WHERE s.id = workout_sets.session_id
                   AND s.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid));

-- exercises is public reference data: SELECT to gymak_app, no policy, no RLS (P2-ADR-09)
GRANT SELECT ON exercises TO gymak_app;
```

The `NULLIF(..., '')` guard is Phase 1's (§4.7, A-02) and is not re-invented here. Grants for
`gymak_app` are issued by the migration, per Phase 1's role split (§A.5 item 1) — `gymak_app`
cannot grant itself anything.

---

## 5 · API contract

Conventions are Phase 1 §5's, unchanged: `/api/v1`, problem+json errors, SI units on the wire,
bearer auth, ISO 8601 UTC timestamps.

### 5.1 Endpoint catalogue

| Method | Path                         | Auth   | Purpose                                          | Req       |
| ------ | ---------------------------- | ------ | ------------------------------------------------ | --------- |
| GET    | /exercises                   | bearer | List the library, filtered and paginated         | P2-FR-001 |
| GET    | /exercises/{id}              | bearer | One exercise in full                             | P2-FR-001 |
| POST   | /program/generate            | bearer | Generate (or regenerate) the current plan        | P2-FR-002 |
| GET    | /program                     | bearer | The current plan with its days                   | P2-FR-003 |
| GET    | /program/days/{day_id}       | bearer | One day with its exercises and targets           | P2-FR-003 |
| POST   | /workouts                    | bearer | Start a session                                  | P2-FR-005 |
| GET    | /workouts/active             | bearer | The in-progress session, or 204                  | P2-FR-005 |
| POST   | /workouts/{id}/sets          | bearer | Log a set                                        | P2-FR-006 |
| PATCH  | /workouts/{id}/sets/{set_id} | bearer | Correct a set                                    | P2-FR-006 |
| DELETE | /workouts/{id}/sets/{set_id} | bearer | Remove a set                                     | P2-FR-006 |
| POST   | /workouts/{id}/finish        | bearer | Complete the session                             | P2-FR-007 |
| POST   | /workouts/{id}/abandon       | bearer | Abandon the session                              | P2-FR-007 |
| GET    | /workouts                    | bearer | History, paginated, newest first                 | P2-FR-008 |
| GET    | /workouts/{id}               | bearer | One session in full                              | P2-FR-008 |
| PUT    | /body-weight                 | bearer | Upsert one calendar day's entry                  | P2-FR-009 |
| GET    | /body-weight                 | bearer | Entries in a date range, plus the moving average | P2-FR-010 |
| DELETE | /body-weight/{measured_on}   | bearer | Remove one day's entry                           | P2-FR-009 |
| GET    | /records                     | bearer | Personal records, all exercises or one           | P2-FR-011 |
| GET    | /dashboard                   | bearer | Everything the home screen needs, in one call    | P2-FR-012 |

Every one of these requires a completed profile. A request from an account with
`onboarding_completed = false` returns `409 PROFILE_REQUIRED` — not `404`, because the resource is
not missing, the precondition is.

### 5.2 GET /exercises

```http
GET /api/v1/exercises?muscle=chest&equipment=barbell&q=press&limit=50&cursor=...

--- 200 OK ---
{ "items": [
    { "id": "018f...", "slug": "barbell-bench-press",
      "name": "Barbell bench press",          // resolved to the caller's profile language
      "primary_muscle": "chest",
      "secondary_muscles": ["triceps","front_delts"],
      "equipment": "barbell", "movement_pattern": "horizontal_push",
      "is_compound": true, "difficulty": "beginner" } ],
  "next_cursor": null }
```

`name` is resolved server-side from the profile's `language`, because the library is the one place
the server holds display text and shipping both columns to the client doubles the payload for no
gain. **This is the single exception to Phase 1 §9.6's "the server never sends display text" rule,
and it is deliberate**: the alternative is 60 exercise names in each of two locale files,
maintained by hand, drifting from the seed file. Everything else — labels, errors, day names —
stays keyed. `GET /exercises/{id}` additionally returns `instructions`.

Filters combine with AND. `q` matches either language's name, case- and diacritic-insensitively.
`is_active = false` rows never appear here, but `GET /exercises/{id}` resolves them.

> **"Diacritic-insensitive" means something different in Arabic, and `unaccent` does not deliver it.**
>
> T-16 implemented this with the `unaccent` extension, whose default rules file is built for Latin,
> Greek and Cyrillic — it strips `é` to `e` and leaves Arabic untouched. And Arabic's real search
> problems are not diacritics anyway: alef variants (`أ إ آ` against `ا`), yeh (`ي` against `ى`),
> teh marbuta (`ة` against `ه`), and the definite article, so that a user typing `صدر` finds
> nothing named `الصدر`. Harakat are the least of it, because almost nobody types them.
>
> The fix is a small normalisation applied identically to the stored name and the query — fold the
> alef and yeh variants, drop harakat and tatweel, and match as a substring — not another
> extension. Verify with three real queries before calling Arabic search done: `صدر`, `بنش`,
> and `اسكوات` typed with a plain alef.

**Path parameters that are not valid UUIDs return the resource's own 404**, not FastAPI's default
422 — a malformed id and an unknown id are indistinguishable to the caller, which is §6.5's
generic-failure rule applied one level earlier. T-16 set this precedent on `GET /exercises/{id}`;
every `{id}` route in T-18, T-19 and T-21 follows it, so the API does not answer "that id is
well-formed but not yours" for some routes and "that is not an id" for others.

### 5.3 POST /program/generate

```http
POST /api/v1/program/generate
{ "days_per_week": 4 }

--- 201 Created ---
{ "program": { "id": "018f...", "days_per_week": 4, "split_type": "upper_lower",
                "goal": "gain", "experience_level": "beginner",
                "generator_version": 1, "created_at": "...",
                "days": [ { "id": "018f...", "day_index": 1,
                            "label_key": "plan.day.upper",
                            "focus_muscles": ["chest","back","front_delts"],
                            "exercise_count": 5 } ] } }
```

|                  |                                                                                                                                                                                                                                                                                                                     |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Precondition** | A completed profile. Otherwise `409 PROFILE_REQUIRED`.                                                                                                                                                                                                                                                              |
| **Regeneration** | Calling it again supersedes the current plan (§4.3). It never fails with a conflict — regenerating is a normal action, not an error. An `in_progress` session blocks it with `409 SESSION_ACTIVE_BLOCKS_REGENERATION`: replacing the plan under a running workout would orphan the day the user is halfway through. |
| **Safety**       | P2-SAF-003 is enforced inside the generator, and asserted again by the service before persisting — a belt-and-braces check that costs one comparison and would have caught a whole class of table-editing mistake.                                                                                                  |
| **Audit**        | `program.generated`, with `days_per_week`, `split_type`, and `generator_version` in the metadata. Never the exercise list — the audit log is not a copy of the plan.                                                                                                                                                |
| **Rate limit**   | 10 / hour per user. Regeneration is cheap but not free, and a loop in a client should not be able to write 500 programs.                                                                                                                                                                                            |

### 5.4 GET /program

Returns the current program with its days, exactly as §5.3's response shape. `404 PROGRAM_NOT_FOUND`
when the user has never generated one — the app routes to the "build my plan" screen on that code.

Includes a `stale` object when the profile has diverged from the program's snapshot:

```json
"stale": { "reason": "goal_changed", "from": "gain", "to": "lose" }
```

`null` when they agree. The dashboard renders it as a prompt (P2-FR-004); it is never acted on
automatically.

### 5.5 GET /program/days/{day_id}

```http
--- 200 OK ---
{ "day": { "id": "018f...", "day_index": 1, "label_key": "plan.day.upper",
           "exercises": [
             { "id": "018f...", "position": 1,
               "exercise": { "id": "...", "slug": "barbell-bench-press",
                             "name": "Barbell bench press", "equipment": "barbell",
                             "primary_muscle": "chest" },
               "target_sets": 4, "target_reps_min": 6, "target_reps_max": 8,
               "rest_seconds": 150,
               "last_performance": { "session_id": "...", "local_date": "2026-08-09",
                                     "best_set": { "reps": 8, "weight_kg": 60 } } } ] } }
```

`last_performance` is the single most useful thing on this screen and the reason the day endpoint
is separate from the program endpoint: it is per-exercise, requires a join against history, and
would make the plan overview slow for no benefit. `null` if the exercise has never been logged.

### 5.6 POST /workouts

```http
POST /api/v1/workouts
{ "program_day_id": "018f..." }      // omit entirely for an empty session

--- 201 Created ---
{ "session": { "id": "018f...", "status": "in_progress",
               "started_at": "2026-08-13T17:02:11Z", "local_date": "2026-08-13",
               "program_day_id": "018f...", "sets": [] } }
```

`409 SESSION_ALREADY_ACTIVE` when one is open, with `detail` carrying the active session's id so the
client offers _Resume_ / _Discard and start new_ rather than a dead end. `404 NOT_FOUND` if the
`program_day_id` belongs to another user's program — generic, per Phase 1 §6.5.

### 5.7 POST /workouts/{id}/sets · PATCH · DELETE

```http
POST /api/v1/workouts/018f.../sets
{ "exercise_id": "018f...", "reps": 8, "weight_kg": 60, "rpe": 8, "is_warmup": false }

--- 201 Created ---
{ "set": { "id": "018f...", "exercise_id": "018f...", "set_index": 3,
           "reps": 8, "weight_kg": 60, "rpe": 8, "is_warmup": false,
           "logged_at": "2026-08-13T17:14:02Z",
           "derived": { "volume_kg": 480, "e1rm_kg": 76 } },
  "session_totals": { "sets": 7, "volume_kg": 2840 },
  "is_record": { "kind": "e1rm", "previous": 74.5 } }        // null when it is not
```

|                   |                                                                                                                                                                                                                                       |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`set_index`**   | Assigned by the server, never sent by the client. The next integer for that exercise within that session. A client-assigned index is a race the moment a retry duplicates a request.                                                  |
| **Session state** | `409 SESSION_NOT_ACTIVE` on a completed or abandoned session (P2-ADR-03).                                                                                                                                                             |
| **`is_record`**   | Computed against the user's history _excluding this session's other sets_, so a new personal best is announced once, not on every subsequent heavier set in the same workout. The celebration is the app's; the fact is the server's. |
| **PATCH**         | Any of `reps`, `weight_kg`, `rpe`, `is_warmup`. Not `exercise_id` — that is a delete and a re-log, and pretending otherwise makes `set_index` meaningless.                                                                            |
| **DELETE**        | `204`. Remaining sets are **not** re-indexed: gaps in `set_index` are harmless, and renumbering rows the user did not touch is a surprising write.                                                                                    |
| **Rate limit**    | 300 / hour per user. A long session is ~60 sets; the limit is generous on purpose, because hitting it mid-workout would be the worst possible failure.                                                                                |

### 5.8 POST /workouts/{id}/finish · abandon

```http
POST /api/v1/workouts/018f.../finish
{ "notes": "left shoulder felt tight on the last set" }    // optional

--- 200 OK ---
{ "session": { "id": "...", "status": "completed",
               "started_at": "...", "ended_at": "...",
               "duration_seconds": 3720, "total_volume_kg": 8420,
               "set_count": 18, "exercise_count": 5 },
  "records_set": [ { "exercise_id": "...", "kind": "e1rm", "value": 102.5 } ] }
```

**`duration_seconds` is `last_logged_at − started_at`, not `ended_at − started_at`.** A user who
finishes their last set and then forgets to press Finish until the next morning did not train for
fourteen hours, and a history screen that says they did is worse than useless. If the session has
no sets, duration is zero.

`POST /abandon` sets `status = 'abandoned'`, `ended_at`, and computes nothing. An abandoned session
keeps its sets — the user logged them and they happened — but it is excluded from the streak, from
volume totals, and from records. `409 SESSION_NOT_ACTIVE` if it is already finished.

A `finish` on a session with **zero** sets returns `422 EMPTY_SESSION` and suggests abandoning
instead. Recording a completed workout with nothing in it corrupts the streak, which is the one
number in this app the user will actually care about defending.

### 5.9 GET /workouts · GET /workouts/{id}

History is cursor-paginated, newest first, and returns summaries only — id, `local_date`, status,
duration, volume, set count, and the program day's `label_key`. Optional `from` / `to` date filters
and a `status` filter.

`GET /workouts/{id}` returns the session with every set, grouped by exercise in `position` order for
a plan-backed session and in first-logged order for an empty one, each set carrying its `derived`
block.

### 5.10 Body weight

```http
PUT /api/v1/body-weight
{ "measured_on": "2026-08-13", "weight_kg": 73.4, "note": null }
--- 200 OK ---
{ "entry": { ... }, "profile_weight_updated": true }

GET /api/v1/body-weight?from=2026-05-13&to=2026-08-13
--- 200 OK ---
{ "entries": [ { "measured_on": "2026-08-13", "weight_kg": 73.4 } ],
  "moving_average_7d": [ { "measured_on": "2026-08-13", "weight_kg": 73.8 } ],
  "summary": { "first": 76.1, "latest": 73.4, "change_kg": -2.7, "entry_count": 41 } }
```

|                              |                                                                                                                                                                                                                                                                                |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Upsert**                   | `PUT`, not `POST`, and same-day writes replace (P2-ADR-06).                                                                                                                                                                                                                    |
| **`profile_weight_updated`** | True when this entry was the newest and therefore updated `profiles.weight_kg`. The client uses it to invalidate its profile cache — and it makes the P2-ADR-06 coupling visible in the contract rather than hidden in a service.                                              |
| **Future dates**             | `422 VALIDATION_ERROR` / `measured_on:IN_FUTURE`. Resolved against the user's timezone, so a user in Cairo at 01:00 can log "today" without the UTC server calling it tomorrow.                                                                                                |
| **Moving average**           | Seven-day trailing, computed only where at least three entries exist in the window, because a two-point "average" is a line between two dots pretending to be a trend. Days with no entry are not interpolated — the array is sparse, and the chart draws gaps as gaps (§9.3). |
| **Range default**            | 90 days when `from`/`to` are omitted. Maximum span 730 days.                                                                                                                                                                                                                   |

### 5.11 GET /records

```http
GET /api/v1/records?exercise_id=018f...     // omit for all exercises

--- 200 OK ---
{ "records": [
    { "exercise": { "id": "...", "slug": "barbell-back-squat", "name": "Barbell back squat" },
      "heaviest_set":   { "weight_kg": 110, "reps": 3, "session_id": "...", "local_date": "2026-08-02" },
      "best_e1rm":      { "value_kg": 121, "weight_kg": 110, "reps": 3, "local_date": "2026-08-02" },
      "best_session_volume": { "volume_kg": 4200, "session_id": "...", "local_date": "2026-07-19" },
      "total_sets": 84 } ] }
```

Warm-up sets and non-`completed` sessions are excluded everywhere (P2-ADR-04, §5.8). Exercises the
user has never performed are omitted entirely rather than returned with nulls.

### 5.12 GET /dashboard

```http
--- 200 OK ---
{ "greeting_name": "Nabil",
  "active_session": null,                       // or a summary, so the app can offer Resume
  "next_workout": { "program_day_id": "...", "day_index": 2, "label_key": "plan.day.lower",
                    "exercise_count": 5, "estimated_minutes": 55 },
  "streak": { "current_days": 4, "longest_days": 11, "last_workout_local_date": "2026-08-12" },
  "this_week": { "completed": 2, "target": 4, "local_week_start": "2026-08-10" },
  "weight": { "latest_kg": 73.4, "measured_on": "2026-08-13",
              "change_30d_kg": -1.2, "sparkline": [ /* {measured_on, weight_kg} */ ] },
  "recent_records": [ { "exercise_name": "Barbell back squat", "kind": "e1rm",
                        "value": 121, "local_date": "2026-08-02" } ],
  "program_stale": null,
  "disclaimer_key": "common.medicalDisclaimer" }
```

|                         |                                                                                                                                                                                                                                                                                                                  |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`next_workout`**      | The day after the most recently completed one, wrapping at `days_per_week`. Never a calendar prescription (§4.4). `null` if no program exists — the client shows the "build my plan" call to action.                                                                                                             |
| **`streak`**            | Consecutive **calendar days with at least one completed session**, in the user's timezone, counted backwards from today. Today not yet trained does **not** break it; yesterday untrained does. The boundary cases are specified in §10.1 and are the single most test-worthy piece of arithmetic in this phase. |
| **`estimated_minutes`** | `Σ target_sets × (rest_seconds + 40)`, rounded to five minutes. A crude model, stated as crude, and better than no expectation at all. It is arithmetic over stored targets — not a prediction.                                                                                                                  |
| **Empty state**         | A brand-new user with no program, no sessions and no weight entries gets a well-formed response with nulls and zeros, never a 404. The dashboard must render from it without a single conditional crash, and there is a test that asserts exactly this shape.                                                    |

---

## 6 · The plan generator

This is the only real domain logic in Phase 2. It lives in `services/plan_generator.py`, imports
nothing from the rest of the application, and is a pure function (P2-ADR-01).

### 6.1 Signature

```python
@dataclass(frozen=True)
class PlanInput:
    experience_level: Literal["beginner", "intermediate", "advanced"]
    goal: Literal["lose", "gain", "maintain"]
    activity_level: Literal["sedentary", "light", "moderate", "high", "very_high"]
    days_per_week: int          # 2..6
    age: int                    # for P2-SAF-002/003
    available_exercise_slugs: frozenset[str]

def generate_plan(spec: PlanInput) -> GeneratedPlan: ...
```

`available_exercise_slugs` is passed in rather than queried, which is what keeps the function pure
and lets a test drive it with a five-exercise library. If a rule asks for a movement pattern the
library cannot satisfy, the generator raises `PlanGenerationError` naming the pattern — it never
silently produces a shorter day.

### 6.2 Split selection

| days_per_week | split_type       | Day labels                                       |
| ------------- | ---------------- | ------------------------------------------------ |
| 2             | `full_body`      | Full body A, Full body B                         |
| 3             | `full_body`      | Full body A, B, C                                |
| 4             | `upper_lower`    | Upper A, Lower A, Upper B, Lower B               |
| 5             | `upper_lower`    | Upper A, Lower A, Upper B, Lower B, Arms & delts |
| 6             | `push_pull_legs` | Push A, Pull A, Legs A, Push B, Pull B, Legs B   |

Beginners are capped at **4** days regardless of what they ask for: a beginner who requests 6 gets a
4-day plan and the response's `notes_key` explains why (`plan.notes.beginnerCappedDays`). This is
P2-SAF-003's first mechanism, and it is a cap, not a rejection — a request for more days is not an
error, it is over-eagerness the plan quietly corrects.

### 6.3 Day composition

Each day is built by filling an ordered list of movement-pattern slots, then choosing the
highest-priority available exercise for each slot that the user's experience level permits
(`exercises.difficulty <= experience_level`), preferring compounds.

**Ordering within a day is fixed:** compound movements first, in the slot order below, then
isolation. This is not a style preference — a fatigued lifter under a heavy barbell is the risk
this ordering exists to reduce.

| Day type     | Slots, in order                                                                                            |
| ------------ | ---------------------------------------------------------------------------------------------------------- | -------------------------------- |
| Full body    | squat · horizontal_push · horizontal_pull · hinge · isolation(abs)                                         |
| Upper        | horizontal_push · vertical_pull · vertical_push · horizontal_pull · isolation(biceps) · isolation(triceps) |
| Lower        | squat · hinge · lunge · isolation(calves) · isolation(abs)                                                 |
| Push         | horizontal_push · vertical_push · isolation(side_delts) · isolation(triceps)                               |
| Pull         | vertical_pull · horizontal_pull · isolation(rear_delts) · isolation(biceps)                                |
| Legs         | squat · hinge · lunge · isolation(calves)                                                                  |
| Arms & delts | isolation(side_delts) · isolation(rear_delts) · isolation(biceps) · isolation(triceps) · isolation(abs)    | the 5-day split's fifth day only |

The A/B variants of a day use the second-priority exercise for each slot where one exists, so a
4-day plan is not the same two workouts twice.

> **Why the 5-day split has no full-body day — a defect T-17 found and this document caused.**
>
> The original 5-day split was Upper A · Lower A · **Full body** · Upper B · Lower B. Every seeded
> squat and lunge movement carries `quads` as its primary muscle, so Lower A, Lower B and the
> full-body day between them gave quads five compound slots in one week: 25 sets at advanced/gain
> against a ceiling of 22, and 20 at intermediate/gain against 18. §6.2 and §6.4 were written
> separately and never checked against each other.
>
> The generator did the right thing — it raised `PlanGenerationError` rather than shipping an
> over-volume week — but the user-visible result was a `422` instead of a plan, for one of the most
> ordinary requests this app will ever get: five days a week, trying to gain muscle.
>
> The fifth day is now an isolation-only Arms & delts day. That removes the third quad exposure
> entirely, adds no compound systemic load, and services the two muscle groups the upper/lower
> split under-serves. It is also what a large share of real five-day programmes actually do.
> **Any change to this table is a `generator_version` bump** (P2-ADR-01), and the version is stored
> on every program precisely so this correction is traceable in the data.

### 6.4 Sets, reps and rest — the table P2-SAF-003 enforces

> **⚠️ This table has not been reviewed by anyone who trains, and T-17 shipped against it anyway.**
>
> It was drafted from conventional programming ranges and is internally consistent, but conventional
> is not the same as verified, and no lifter has read it. It ships because blocking the whole phase
> on one review was the worse trade — not because the numbers are confirmed.
>
> **The gate this creates:** the app must not reach anyone other than Nabil until someone who trains
> has read this table and either signed it off or corrected it. That is a release condition, recorded
> here and in §10.3 item 14, not a suggestion. `generator_version` exists precisely so a correction
> is traceable: bump it, regenerate, and every program carries the version that produced it.
>
> The two numbers most worth a second opinion: the beginner ceiling of **12 sets per muscle per
> week**, and the advanced ceiling of **22**.

| experience   | goal             | Compound sets × reps | Isolation sets × reps | Rest (compound / isolation) | Ceiling: sets per muscle per week |
| ------------ | ---------------- | -------------------- | --------------------- | --------------------------- | --------------------------------- |
| beginner     | any              | 3 × 8–12             | 2 × 10–15             | 120 s / 60 s                | **12**                            |
| intermediate | gain             | 4 × 6–10             | 3 × 10–15             | 150 s / 75 s                | 18                                |
| intermediate | lose \| maintain | 3 × 8–12             | 3 × 12–15             | 90 s / 60 s                 | 16                                |
| advanced     | gain             | 5 × 4–8              | 3 × 8–12              | 180 s / 90 s                | 22                                |
| advanced     | lose \| maintain | 4 × 6–10             | 3 × 12–15             | 120 s / 75 s                | 20                                |

`activity_level` adjusts rest only — `sedentary`/`light` add 15 seconds to every rest interval,
`high`/`very_high` subtract 15, floored at 30 and capped at 300 (§4.5). It does **not** change set
counts: conflating daily activity with training capacity is the kind of plausible-sounding rule
that has no support, and inventing it would break P2-ADR-01's "reviewable by a human who knows
training" premise.

**The ceiling is checked, not assumed.** After composing the week, the generator counts sets per
primary muscle across all days and asserts each is at or under the ceiling. Exceeding it is a
`PlanGenerationError`, which is a bug in the table or in §6.3's slots — and it is a unit test over all 225 input
combinations, not a runtime hope.

### 6.5 P2-SAF-002 — minors

If `age < 18`:

- `goal == 'lose'` cannot reach the generator at all: Phase 1's P1-SAF-001 already blocks it at the
  profile layer, on both `POST` and `PATCH`. The generator asserts it anyway and raises if it sees
  it, because a safety check that exists in exactly one place is one refactor away from existing in
  none.
- The plan's `notes_key` list never includes a deficit or weight-loss key.
- `GET /dashboard` omits `weight.change_30d_kg` framing keys that imply a target direction. The
  weight chart itself still renders — a 16-year-old may legitimately track their weight; what they
  do not get is the app telling them which way it should go.

---

## 7 · Validation and error contract

Phase 1 §7.2's envelope is unchanged. `code` is the stable string the client switches on; `title`
and `detail` are never rendered to a user.

### 7.1 New field validation

| Field            | Rule                                                                      | Error code                                      |
| ---------------- | ------------------------------------------------------------------------- | ----------------------------------------------- |
| days_per_week    | integer 2–6                                                               | VALIDATION_ERROR / `days_per_week:OUT_OF_RANGE` |
| reps             | integer 1–100                                                             | VALIDATION_ERROR / `reps:OUT_OF_RANGE`          |
| weight_kg (set)  | 0–500, two decimals                                                       | VALIDATION_ERROR / `weight_kg:OUT_OF_RANGE`     |
| rpe              | 5–10 in steps of 0.5, or absent                                           | VALIDATION_ERROR / `rpe:OUT_OF_RANGE`           |
| measured_on      | ISO date, not in the future in the user's timezone, not before 2000-01-01 | VALIDATION_ERROR / `measured_on:IN_FUTURE`      |
| weight_kg (body) | 30–300, two decimals — the same range as the profile                      | VALIDATION_ERROR / `weight_kg:OUT_OF_RANGE`     |
| notes            | ≤ 500 chars, trimmed                                                      | VALIDATION_ERROR / `notes:TOO_LONG`             |
| timezone         | a valid IANA name (`zoneinfo.available_timezones()`)                      | VALIDATION_ERROR / `timezone:INVALID`           |

### 7.2 New error codes — the client must handle every one

| HTTP | code                               | When                                                                                                                    |
| ---- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| 404  | PROGRAM_NOT_FOUND                  | No program generated yet                                                                                                |
| 404  | SESSION_NOT_FOUND                  | Unknown session, or another user's — generic, per Phase 1 §6.5                                                          |
| 404  | SET_NOT_FOUND                      | Unknown set, or not in this session                                                                                     |
| 404  | EXERCISE_NOT_FOUND                 | Unknown exercise id                                                                                                     |
| 409  | PROFILE_REQUIRED                   | Any Phase 2 endpoint before onboarding completes                                                                        |
| 409  | SESSION_ALREADY_ACTIVE             | Starting a second session; `detail` carries the active id                                                               |
| 409  | SESSION_NOT_ACTIVE                 | Writing to, finishing, or abandoning a closed session                                                                   |
| 409  | SESSION_ACTIVE_BLOCKS_REGENERATION | Regenerating the plan with a workout in progress                                                                        |
| 422  | EMPTY_SESSION                      | Finishing a session with zero sets                                                                                      |
| 422  | PLAN_GENERATION_FAILED             | The library cannot satisfy a required movement pattern — a seed-data bug, surfaced honestly rather than as a short plan |
| 429  | RATE_LIMIT_EXCEEDED                | With `Retry-After`, as Phase 1                                                                                          |

Every code gets an `errors.<CODE>` entry in **both** `ar.json` and `en.json` in the same task that
introduces it. A code with no Arabic string is an incomplete task.

### 7.3 New rate limits

| Endpoint           | Limit      | Key  |
| ------------------ | ---------- | ---- |
| /program/generate  | 10 / hour  | user |
| /workouts (POST)   | 20 / hour  | user |
| /workouts/\*/sets  | 300 / hour | user |
| /body-weight (PUT) | 30 / hour  | user |
| /dashboard         | 120 / hour | user |
| /exercises         | 120 / hour | user |

---

## 8 · Mobile application

### 8.1 Navigation — the shell changes

Phase 1's `(app)` group holds two screens behind a stack. Phase 2 replaces it with four bottom tabs
(P2-FR-014). The `(auth)` and `(onboarding)` groups and the session gate in `app/_layout.tsx` are
**unchanged** — do not touch them.

```text
(app)/_layout.tsx  → Tabs
  ├── index          Home       · the dashboard
  ├── plan           Plan       · program overview → day detail
  ├── progress       Progress   · weight log, chart, records
  └── settings       Settings   · unchanged from Phase 1

Presented outside the tabs, as full-screen routes:
  workout/active     the active session — tabs hidden, back guarded by a confirm
  workout/[id]       a past session, read-only
  exercises/index    the library, reachable from plan and from the active session
  exercises/[id]
```

Tab icons come from the same hand-drawn approach `GTextInput`'s eye icon already uses, or from
`@expo/vector-icons` **if** it resolves inside the installed `expo` package — check before
assuming, and add no new dependency either way (Phase 1 A.2).

The tab bar mirrors under RTL automatically; the tab **order** does not change, because a tab bar is
a spatial arrangement, not a reading sequence, and users navigate it by position.

### 8.2 Screen inventory

| #   | Screen           | Content and behaviour                                                                                                                                                                                                                                    |
| --- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 16  | dashboard        | One `GET /dashboard`. Greeting, resume-session banner when one is active, next-workout card with a primary Start button, streak, this-week ring, weight sparkline, recent records, the stale-plan prompt. Every block has a skeleton and an empty state. |
| 17  | plan overview    | The week as day cards: label, focus chips, exercise count, estimated minutes. A "regenerate" action behind a confirm. Empty state → the days-per-week picker → `POST /program/generate`.                                                                 |
| 18  | plan day detail  | The ordered exercise list with targets and `last_performance`. Tapping an exercise opens the library detail. One primary Start this workout button.                                                                                                      |
| 19  | active workout   | **The screen this phase lives or dies on.** See §8.3.                                                                                                                                                                                                    |
| 20  | session detail   | A completed session, read-only: duration, volume, per-exercise sets, records set, notes.                                                                                                                                                                 |
| 21  | history          | Infinite list of session summaries grouped by month. Empty state points at the plan.                                                                                                                                                                     |
| 22  | progress         | Weight chart with 30/90/365 range chips, the moving-average line, a log-today button, an editable entry list, and the records list below.                                                                                                                |
| 23  | exercise library | Searchable, filterable list. Muscle and equipment filters as chips.                                                                                                                                                                                      |
| 24  | exercise detail  | Name, muscles, equipment, instructions, and this user's record for it.                                                                                                                                                                                   |

### 8.3 The active-workout screen — requirements, not suggestions

This screen is used one-handed, sweating, between sets, sometimes with a 90-second timer running.
It gets its own section because a merely acceptable version of it makes the whole app feel bad.

1. **The current exercise is always visible without scrolling**, along with its target (`4 × 6–8`),
   its rest time, and what the user did last time. Everything else may scroll.
2. **Logging a set is at most two taps from resting state** when the values are unchanged from the
   previous set — which is the overwhelmingly common case. The weight and reps fields pre-fill from
   the user's previous set of that exercise in this session, or from `last_performance` for the
   first set.
3. **Number entry is a `GNumberField`, not a raw keyboard.** Steppers (± 2.5 kg, ± 1 rep) with a
   tap-to-type fallback. `keyboardType="decimal-pad"`. The field never loses focus to a re-render.
4. **The rest timer starts automatically** when a set is logged, seeded from the exercise's
   `rest_seconds`, and is visible from anywhere on the screen. It is pausable and skippable. It
   keeps running while the app is backgrounded — it is wall-clock arithmetic against a stored
   timestamp, never a `setInterval` that a suspended JS thread will silently freeze.
5. **A logged set appears instantly** (optimistic), marked as unsent until the server confirms it
   (P2-ADR-08). A failed send shows a retry chip on that set, and never a modal.
6. **Navigating away is guarded.** The back gesture and the tab bar are blocked while a session is
   in progress; leaving requires Finish or Abandon, both behind a confirm. The one exception is the
   exercise-library route, which is pushed over the top and returns.
7. **Rotation and background do not lose state**, because state lives in `src/workout/activeSession.ts`
   and the server, never only in a component.
8. **Finish shows a summary before it commits**: duration, volume, sets, and any records set.

### 8.4 Progressive disclosure — RPE and warm-up sets

RPE is off by default. A first-time user sees reps and weight, nothing else. A "log more" toggle in
Settings turns on the RPE field and the warm-up checkbox. The API accepts both from the first day
regardless; this is a client-side default, not a capability gate. A beginner asked to rate a set's
perceived exertion before they know what a set feels like will enter noise, and noise in the data is
worse than an absent column.

### 8.5 States every screen must implement

Phase 1 §9.4's table applies unchanged — idle, submitting, field error, request error, offline, rate
limited, success — and Phase 2 adds three:

| State      | Treatment                                                                                                                                                                                                                                |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Empty      | Never a blank screen and never a spinner that resolves to nothing. Each empty state names the one action that fills it: no program → "build my plan"; no history → "start your first workout"; no weight entries → "log today's weight". |
| Skeleton   | The dashboard and the plan render their layout as `GSkeleton` blocks on first load, not a centred spinner. Cached data is never replaced by a skeleton on refetch (P2-NFR-08).                                                           |
| Unsent set | A set that has not been confirmed by the server shows a subtle unsent marker and a retry affordance on that row (P2-ADR-08). The session cannot be finished while any set is unsent — Finish offers "retry all" or "discard unsent".     |

### 8.6 Copy and safety

- **The disclaimer.** Every screen that shows training prescription — plan overview, day detail,
  active workout — carries one line, from `common.medicalDisclaimer`, keyed and translated:
  _"Gymak is not medical advice. Stop if something hurts, and talk to a doctor before starting a new
  programme."_ Not a modal, not a one-time dismissal. One quiet line (P2-SAF-004).
- **No invented numbers, still.** Phase 1's home screen promised nothing made up. If a value cannot
  be computed from what the user logged, the screen says so — "not enough data yet" — rather than
  showing a zero that looks like a measurement.
- **No streak guilt.** A broken streak is stated, never scolded. No flame animations, no "you lost
  your streak!" — the number resets and the copy stays neutral.

---

## 9 · Design

### 9.1 Everything comes from Phase 1 §10, which already anticipated this phase

Phase 1's token file is not merely reusable here — it was written for this. §10.3's trailing
paragraph already defines `chart1..5`, `ringWorkout`, `ringCalories`, `ringWeight`, `streak`,
`prBadge`, `navBg`, and `fab`, "defined now so nothing gets improvised later." Phase 2 is when they
get used. `src/theme/tokens.ts` already carries every one of them.

**No new colour may be added to `tokens.ts` in this phase.** If a screen seems to need one, it needs
an existing one used differently. `aiCoachBg` and `premiumBg` stay unused — they belong to phases
that have not happened.

The rules that governed Phase 1 governs Phase 2 unchanged: no hex literal in a component, no bare
string in the UI, `start`/`end` never `left`/`right`, every touchable ≥ 48 dp with a translated
`accessibilityLabel`, 4.5:1 contrast minimum, and no fixed-height text container that clips at 130%
font scaling.

### 9.2 New component contracts

| Component    | Props and required states                                                                                                                                                                           |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GCard        | `title?`, `subtitle?`, `onPress?`, `footer?`. Surface background, `radius.lg`, `shadowSm`. Pressable variant gets a pressed state, not just opacity.                                                |
| GStat        | `label`, `value`, `unit?`, `delta?`, `tone: neutral \| positive \| negative`. Value uses the `stat` type role (34/700, tabular figures). Tone never carries meaning alone — a delta shows its sign. |
| GChip        | `label`, `selected`, `onPress`, `disabled`. Filter and range chips. Selected = rust border + `primaryContainer`, matching `GSelectCard`.                                                            |
| GEmptyState  | `titleKey`, `bodyKey`, `actionLabelKey?`, `onAction?`. Never renders raw text.                                                                                                                      |
| GSkeleton    | `width`, `height`, `radius?`. `skeleton` token, a subtle pulse honouring `prefers-reduced-motion`.                                                                                                  |
| GListRow     | `title`, `subtitle?`, `trailing?`, `onPress?`. The history and entry-list primitive. Min height 56.                                                                                                 |
| GNumberField | `value`, `onChange`, `step`, `min`, `max`, `unit`, `precision`. Stepper buttons ≥ 48 dp, tap-to-type, holds focus across re-renders (§8.3.3).                                                       |
| GRestTimer   | `seconds`, `onComplete`, `onSkip`, `paused`. Wall-clock based (§8.3.4). Announces completion to screen readers; optional haptic, never a sound by default.                                          |
| GLineChart   | `series`, `xAccessor`, `yAccessor`, `range`. See §9.3.                                                                                                                                              |
| GSheet       | `visible`, `onClose`, `children`. Bottom sheet for the exercise picker and the log-weight form. Focus-trapped, dismissible, `overlay` token behind.                                                 |

### 9.3 The chart, specifically

One chart type in Phase 2: a line. Weight over time, with the moving average as a second line.

- **Built from `react-native-svg`** — an Expo-managed dependency — and nothing else. No charting
  library (§A.2). A line chart is a path, two axes, and some labels; a library brings a theming
  system that will fight `tokens.ts`.
- **Colours:** the raw series is `chart3` (the blue already assigned to `ringWeight`), the moving
  average is `chart1` (rust). Two series, two hues, distinguishable in greyscale by weight — the
  average line is thicker.
- **Gaps are gaps.** Days with no entry are not interpolated across (§5.10). A straight line through
  a two-week hole is a claim about weight the user never made.
- **Axes are honest.** The y-axis does not start at zero — for body weight that would flatten every
  real change into a straight line — but the visible range is labelled at both ends so the reader
  can see the scale. This is the one place a truncated axis is correct, and it is stated here so it
  is a decision rather than an accident.
- **Accessible:** the chart carries an `accessibilityLabel` summarising the trend in words
  ("weight, 41 entries, from 76.1 to 73.4 kilograms over 90 days"), and the same numbers appear in
  the `summary` row beneath it. Nobody has to read a picture to get the information.
- **Empty and sparse states:** fewer than two entries renders `GEmptyState`, not an axis with one
  dot.

---

## 10 · Testing and definition of done

### 10.1 Backend test matrix

| Level       | Must cover                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit        | **The generator over all 225 input combinations** (every `days_per_week` from 2 to 6, none excluded — the exclusion T-17 needed is what surfaced the §6.3 defect), asserting: the §6.4 volume ceiling holds for every one, no day is short a slot, compounds precede isolation, beginners never exceed 4 days, A/B variants differ, and a minor never receives a `lose` plan · determinism (the same input twice is byte-identical) · e1RM at boundaries (1 rep = the weight itself; 30 reps) · volume excludes warm-ups · **the streak function**: trained today, trained yesterday not today, gap of exactly one day, gap of two, a session at 23:59 local, a session at 00:01 local, a DST transition, a user who changes timezone mid-streak · the 7-day moving average with fewer than three points in window · `measured_on` future-date resolution across timezones      |
| Integration | Program generate → read → regenerate supersedes → history intact · generate blocked by an active session · session start → log → edit → delete → finish, with totals correct at each step · a second start returns 409 with the active id · finishing an empty session returns 422 · abandoning keeps sets but leaves them out of records and streak · `set_index` assignment under two concurrent POSTs for the same exercise · duration uses the last set, not `ended_at` · body-weight upsert replaces same-day and updates `profiles.weight_kg` · **`PATCH /profile` weight upserts today's entry** (both directions of P2-ADR-06) · deleting the newest weight entry rolls `profiles.weight_kg` back to the next newest · dashboard on a brand-new account returns the empty shape without error · every Phase 2 endpoint returns 409 `PROFILE_REQUIRED` before onboarding |
| Security    | The Phase 1 cross-tenant matrix **regenerated to include every new route**, asserting 404 · a set belonging to another user's session is invisible even when its own id is known (P2-ADR-09's parent-policy path, tested directly) · **the new RLS policies fail the test when dropped**, per Phase 1 §11.1 — a passing RLS test that only proves a permitted read succeeds proves nothing · `exercises` is readable by any authenticated user and writable by none · no endpoint returns another user's `notes` · the log-capture test extended: no `weight_kg`, no `reps`, no session notes in any log line                                                                                                                                                                                                                                                                   |
| Performance | `GET /dashboard` and `GET /workouts` under P2-NFR-01 against a seeded account with 12 months of sessions (≈150 sessions, ≈2,700 sets) and 365 weight entries. The seed helper is committed, so the number is reproducible rather than anecdotal                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Migration   | Upgrade and downgrade clean against a seeded database, three cycles · the exercise seed is idempotent — running the data migration twice does not duplicate rows · downgrade does not orphan sessions                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Contract    | `openapi.json` regenerated and identical to the committed copy                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

> **The streak is the highest-risk arithmetic in this phase.** It combines a user-configurable
> timezone, calendar-day boundaries, DST, and a "today does not break it, yesterday does" rule that
> is easy to state and easy to get off by one. It is also the number a user will notice being wrong
> immediately, and the one they will feel cheated by. Nine explicit cases are listed above; write
> them before writing the function.

### 10.2 Mobile verification — manual, on a physical device

1. Fresh account, complete onboarding → dashboard shows the empty state with "build my plan", no crash, no zeros pretending to be data.
2. Generate a 4-day plan → four day cards, each with focus chips and an exercise count.
3. Open day 1 → exercises in order, compounds first, targets shown, `last_performance` absent on the first ever run.
4. Start the workout → the active screen opens, tabs are hidden, back is guarded.
5. Log a set → it appears instantly, the rest timer starts, `session_totals` update.
6. **Background the app for 60 seconds mid-rest, return** → the timer shows the correct remaining time, not a frozen one.
7. **Rotate the device mid-session** → no set is lost, the current exercise is unchanged.
8. **Turn wifi off, log two sets, turn it back on** → both sets show as unsent, then send on retry; Finish is blocked until they do.
9. Log a heavier set than any before → the record is announced once, not on every subsequent set.
10. Finish → the summary shows duration matching the actual training time, not the wall clock since Start.
11. Reopen the app → the dashboard streak reads 1, this-week shows 1 of 4.
12. Log body weight for today, then again with a different number → one entry, the second value, and Settings shows the new weight.
13. Change weight in Settings → the Progress chart shows today's point at the new value.
14. **Switch to English, reload** → every Phase 2 screen is LTR with no clipped labels and no leftover Arabic; switch back → RTL throughout, including the chart's axis labels.
15. Set the device font size to 130% → the active-workout screen still fits, nothing clips, the number fields are still usable.
16. Dark mode across every new screen → no invisible text, no white flash on navigation.
17. TalkBack on → a full set can be logged, and the rest timer announces completion.
18. A 16-year-old account (birth date set accordingly) → no weight-loss framing anywhere on the dashboard or in the plan; the weight chart still renders.

### 10.3 Phase 2 definition of done

> **Phase 2 is complete when every one of these is true. Not before.**
>
> 1.  Every P2-FR requirement in §1.1 is implemented and demonstrated on a device, not described.
> 2.  Backend coverage ≥ 80% overall, ≥ 95% in `plan_generator.py` and `services/metrics.py`.
> 3.  The regenerated cross-tenant matrix covers every Phase 2 route and passes with zero findings.
> 4.  Every new RLS policy fails its test when dropped — including `workout_sets`' parent-policy path.
> 5.  The generator's 225-combination test passes with no day count excluded, and the volume ceiling holds in every one.
> 6.  The nine streak cases in §10.1 all pass.
> 7.  Alembic migrates forward and backward cleanly, and the exercise seed is idempotent.
> 8.  `openapi.json` is committed and matches the code.
> 9.  All eighteen manual device checks in §10.2 pass on a real Android device.
> 10. The §1.2 out-of-scope rule holds: no nutrition, AI, payment, or push code exists in the repository. Grep for it before claiming this.
> 11. `mobile/app/(app)/home.tsx` is deleted — the "next phase" placeholder cannot survive the phase it promised.
> 12. Every item in §11 is closed or explicitly re-deferred with a reason.
> 13. `README.md` describes running Phase 2 from a fresh clone, including seeding the exercise library.
> 14. **Someone who trains has read the §6.4 table and signed it off or corrected it.** T-17 shipped
>     against an unreviewed table; this is the gate that closes that. Phase 2 may be feature-complete
>     without it, but the app does not go to a single user outside Nabil until it is done.

---

## 11 · Carried-forward debt from Phase 1

Found during Phase 1's device work and its final review. Each needs an owner in Phase 2 or an
explicit re-deferral (§10.3 item 12).

| #   | Item                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Owner | Severity |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- | -------- |
| 1   | **`eas.json` hardcodes a LAN IP.** `EXPO_PUBLIC_API_BASE_URL` is `http://192.168.1.3:8000/api/v1`, committed to git, on the development and preview profiles. It breaks the moment the router hands out a different address, and it is in a public-ish file. Move to `eas env:create` or a tunnel.                                                                                                                                                                                                                                                                                                                                                                                     | T-15  | Medium   |
| 2   | **`production` has no `EXPO_PUBLIC_API_BASE_URL`.** A production build passes CI and fails at runtime on `client.ts`'s own guard. Harmless today because nothing ships to production; a trap the first time something does.                                                                                                                                                                                                                                                                                                                                                                                                                                                            | T-15  | Low      |
| 3   | **`mobile/android/` is untracked and un-gitignored.** A generated native project with a live `debug.keystore` sitting in the working tree, in neither state. A careless `git add .` commits a keystore. Decide: bare workflow (commit it, minus the keystore) or managed (gitignore it).                                                                                                                                                                                                                                                                                                                                                                                               | T-15  | **High** |
| 4   | **`.env.example` and `eas.json` disagree** on the API host (`.10` vs `.3`). One of them is wrong for every reader.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | T-15  | Low      |
| 5   | **The local debug keystore's SHA-1 was unregistered**, which is what made Google sign-in fail with `DEVELOPER_ERROR`. Fixed by registering `5e8f1606…` in Firebase. Record it: any new machine, or a regenerated debug keystore, reintroduces it. Document the `keytool` check in `mobile/README.md`.                                                                                                                                                                                                                                                                                                                                                                                  | T-15  | Medium   |
| 6   | **The `GErrorBanner` dismiss glyph hardcodes `fontSize: 16` / `lineHeight: 20`** instead of a type role. Small, but it is the first hardcoded type value in a codebase whose entire premise is that there are none.                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | T-23  | Low      |
| 7   | **Overlapping hit-slop in `GErrorBanner`** when retry and dismiss are both present: `gap: space[2]` with 14 dp of slop each side means the touch targets overlap. Widen the gap.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | T-23  | Low      |
| 8   | **No `mobile/README.md`.** The backend has one; the app does not. Phase 2's §10.3 item 13 needs it, and today's build session — JDK, `ANDROID_HOME`, `local.properties`, disk space, `keytool` — is exactly its content.                                                                                                                                                                                                                                                                                                                                                                                                                                                               | T-30  | Medium   |
| 9   | **A second PostgreSQL extension now exists.** T-16's seed migration installs `unaccent` alongside Phase 1's `citext`. It is trusted on PG13+, so `gymak_migrator` can install it without a superuser and the role split is unaffected — but Phase 1 §13.2 item 8's hosting criterion **(b)** was written against one extension: "`citext` is not blocked by the provider's own extension allowlist". That criterion now covers two, and both must be checked before committing to a managed host. Amend §13.2 item 8 when a host is actually chosen. Separately, see §5.2's note: `unaccent` may not be earning its place at all, in which case the cheapest resolution is to drop it. | T-22  | Medium   |
| 10  | Phase 1 §A.5 items **5** (session-scoped event loop), **10** (nothing exercises the real ASGI startup path — standing rule), **12** (`refresh_tokens` SELECT is open, re-deferred), and **18** (`_penalise` escalates per request, not per window trip) carry forward unchanged. Item 18 becomes more likely to bite as the app gets more screens that retry.                                                                                                                                                                                                                                                                                                                          | —     | Watch    |

---

## 12 · Task pack

Twenty-one tasks in dependency order. Each block is written to be pasted **on its own**, with this
document available in the context. Do not paste two at once.

> **The two operational rules from Phase 1 still apply.** Never write a task prompt from memory —
> paste the actual text from this document; a T-02 prompt written from recollection produced Phase 2
> tables and cost a whole task. Never commit while the agent is running.

#### Preamble — paste once at the start of every session

```text
You are working on Gymak, Phase 2 only. docs/PHASE-2-SPEC.md is your single source
of truth for this phase; docs/PHASE-1-SPEC.md remains authoritative for everything
Phase 1 covers (auth, tokens, the profile, the error envelope, the design tokens).
If a document and your instinct disagree, the document wins.

Hard rules:
- Implement exactly one task, the one I name. Nothing beyond it.
- Touch only the files that task lists. If you believe another file must change,
  stop and tell me why instead of changing it. Standing exception:
  backend/pyproject.toml, backend/tests/**, mobile/src/i18n/*.json and
  mobile/app/(app)/_dev-gallery.tsx are always in scope.
- Build nothing from the section 1.2 out-of-scope list, not even a stub or a TODO.
  In particular: no nutrition, no calorie or TDEE display, no LLM call of any kind.
- Add no dependency outside Phase 1 Appendix A.2 plus Phase 2 A.2 without asking.
- If a required detail is genuinely missing from the spec, ask one specific
  question and wait. Do not invent a column, an endpoint, an exercise, or a library.
- Report first what the current implementation actually does — state it explicitly
  before changing anything.
- Finish by listing: files touched, what changed, how to verify, and anything you
  deliberately did not do. Paste real output with exit codes for ruff check,
  ruff format --check, mypy --strict . and pytest. Do not commit.
```

### T-15 · Phase 2 schema, migration, and the Phase 1 carry-over cleanup

```text
Create the Phase 2 schema per spec section 4, and close carry-over items 1 to 5 in
section 11.

Files: backend/alembic/versions/<new>_phase_2_schema.py, backend/app/models/
exercise.py, program.py, workout.py, body_weight.py, backend/app/models/__init__.py,
mobile/eas.json, mobile/.env.example, mobile/.gitignore (new if needed),
backend/tests/unit/test_models.py, backend/tests/security/test_rls.py

Requirements:
- Seven tables exactly as specified in 4.1 and 4.3 to 4.8, plus the profiles.timezone
  column in 4.2 with its default.
- Every CHECK constraint, every UNIQUE, and the partial unique index
  ux_one_active_session from 4.6.
- The indexes in 4.9, verbatim.
- RLS per 4.10 on all six user-owned tables: ENABLE, FORCE, and an owner policy in
  this same migration. workout_sets uses the parent-EXISTS policy. exercises gets
  SELECT granted to gymak_app and no policy.
- Per-table grants for gymak_app issued by the migration, per the Phase 1 role split.
- Downgrade drops everything cleanly and is tested three cycles.
- Carry-over: move the API base URL out of eas.json (item 1), decide and document
  the mobile/android/ tracking question (item 3 - propose, do not silently pick),
  reconcile .env.example with eas.json (item 4), and add the keytool SHA-1 check to
  a comment in eas.json or .env.example (item 5).

Done when: alembic upgrade head then downgrade base runs clean three times, the RLS
tests prove each new policy is load-bearing by dropping it and observing a
cross-tenant read succeed, and gymak_app is proven unable to CREATE, ALTER or DROP
POLICY on any new table.
```

### T-16 · Exercise library — seed data and the read endpoints

```text
Seed the exercise library and expose it, per spec 4.1, 5.2 and P2-ADR-02.

Files: backend/app/data/exercises.json, backend/alembic/versions/<new>_seed_
exercises.py, backend/app/repositories/exercise_repo.py, backend/app/schemas/
exercise.py, backend/app/routers/exercises.py, backend/app/main.py,
backend/tests/integration/test_exercises.py

Requirements:
- exercises.json holds at least 50 movements covering every movement_pattern in 4.1
  and every equipment value, each with a stable UUID v7 id, both names, both
  instruction texts, and correct muscle tagging. Compound and isolation both
  represented for every major muscle. Get the tagging right - a wrong primary_muscle
  produces a wrong plan.
- The data migration is idempotent: running it twice inserts nothing the second time
  and updates nothing silently.
- GET /exercises with muscle, equipment and q filters, cursor pagination, name
  resolved to the caller's profile language per 5.2.
- GET /exercises/{id} adds instructions and resolves inactive rows.
- 409 PROFILE_REQUIRED before onboarding completes.
- Rate limit 120/hour per user.

Done when: the seed runs twice with no duplicates, filters combine with AND, an
Arabic-language profile receives Arabic names, and the cross-tenant matrix has no
new findings.
```

### T-17 · The plan generator and the program endpoints

```text
Implement the plan generator and POST /program/generate, GET /program,
GET /program/days/{day_id}, per spec section 6 and 5.3 to 5.5.

Files: backend/app/services/plan_generator.py, backend/app/services/program_service.py,
backend/app/repositories/program_repo.py, backend/app/schemas/program.py,
backend/app/routers/program.py, backend/app/main.py, backend/tests/unit/
test_plan_generator.py, backend/tests/integration/test_program.py

Requirements:
- plan_generator.py is a pure function per P2-ADR-01: it imports nothing from models,
  repositories or routers, takes the PlanInput dataclass in 6.1 and returns a
  dataclass. No I/O, no randomness, no network.
- Split selection per 6.2, including the beginner 4-day cap with its notes_key.
- Day composition per 6.3: fixed slot order, compounds before isolation, A/B
  variants using the second-priority exercise where one exists.
- Sets, reps and rest per the 6.4 table. activity_level adjusts rest only.
- The volume ceiling in 6.4 is asserted after composition; exceeding it raises
  PlanGenerationError.
- P2-SAF-002 per 6.5, asserted in the generator even though P1-SAF-001 already
  blocks it upstream.
- Regeneration supersedes rather than replaces (4.3), and is blocked by an active
  session with 409 SESSION_ACTIVE_BLOCKS_REGENERATION.
- GET /program returns the stale object in 5.4 when the profile has diverged.
- GET /program/days/{id} includes last_performance per 5.5.
- Audit program.generated with days_per_week, split_type, generator_version only.

Done when: a unit test drives all 225 input combinations and asserts the ceiling,
slot completeness, ordering, the beginner cap, A/B difference and determinism; and
the integration tests prove supersede-not-replace with history intact.
```

### T-18 · Workout session lifecycle

```text
Implement session start, active, finish and abandon, per spec 5.6, 5.8 and P2-ADR-03.

Files: backend/app/services/workout_service.py, backend/app/repositories/
workout_repo.py, backend/app/schemas/workout.py, backend/app/routers/workouts.py,
backend/app/services/metrics.py, backend/app/main.py, backend/app/models/profile.py,
backend/app/schemas/profile.py, backend/app/services/profile_service.py,
backend/tests/unit/test_metrics.py, backend/tests/integration/test_workout_sessions.py

Requirements:
- FIRST, wire up profiles.timezone, which T-15 created at the database level only
  (see the ownership note under 4.2): add the ORM attribute, add it to the
  PATCH /profile editable-field list with the 7.1 IANA validation, and return it
  from GET /profile and /auth/me's profile object. Nothing else in this task works
  without it.
- POST /workouts with an optional program_day_id; local_date resolved through the
  profile timezone at insert (4.6).
- The one-active-session rule is enforced by the database index, and the 409 carries
  the active session's id in detail.
- GET /workouts/active returns the session or 204.
- finish computes duration as last_logged_at minus started_at, not ended_at minus
  started_at (5.8), and total_volume_kg over non-warm-up sets only.
- finish on a session with zero sets returns 422 EMPTY_SESSION.
- abandon keeps sets, computes nothing, and excludes the session from streak, volume
  and records.
- metrics.py holds e1RM (Epley), set volume and session volume as pure functions.

Done when: the integration tests cover every transition and every rejected
transition, and a session whose last set was logged at 18:40 but finished at 09:00
the next morning reports its real duration.
```

### T-19 · Set logging

```text
Implement POST, PATCH and DELETE for sets, per spec 5.7.

Files: backend/app/services/workout_service.py, backend/app/repositories/
workout_repo.py, backend/app/repositories/metrics_repo.py, backend/app/schemas/
workout.py, backend/app/routers/workouts.py, backend/tests/integration/
test_workout_sets.py

Requirements:
- set_index is assigned server-side as the next integer for that exercise in that
  session. Never accepted from the client.
- The response carries derived volume and e1RM, session_totals, and is_record
  computed against history excluding this session's other sets (5.7).
- PATCH accepts reps, weight_kg, rpe and is_warmup only - never exercise_id.
- DELETE returns 204 and does not re-index the remaining sets.
- 409 SESSION_NOT_ACTIVE on a closed session; 404 SET_NOT_FOUND for a set in
  another session, generic per Phase 1 6.5.
- Rate limit 300/hour per user.
- A set in another user's session is invisible even with its id - test the
  P2-ADR-09 parent policy directly.

Done when: two concurrent POSTs for the same exercise produce set_index 1 and 2 with
no duplicate, and is_record fires once for a new best rather than on every heavier
set that follows it in the same session.
```

### T-20 · Body-weight log

```text
Implement PUT, GET and DELETE for body weight, per spec 5.10 and P2-ADR-06.

Files: backend/app/services/body_weight_service.py, backend/app/repositories/
body_weight_repo.py, backend/app/schemas/metrics.py, backend/app/routers/
body_weight.py, backend/app/services/profile_service.py, backend/app/main.py,
backend/tests/integration/test_body_weight.py

Requirements:
- PUT upserts on (user_id, measured_on) and updates profiles.weight_kg when the
  entry is the newest, in the same transaction, returning profile_weight_updated.
- PATCH /profile's weight_kg also upserts today's body-weight entry - both
  directions of P2-ADR-06, both tested.
- Deleting the newest entry rolls profiles.weight_kg back to the next newest, or
  leaves it unchanged when no entry remains.
- measured_on is rejected as future relative to the user's timezone, not UTC.
- GET returns entries, the sparse 7-day moving average computed only where at least
  three entries fall in the window, and the summary block. Default range 90 days,
  maximum 730.

Done when: the two-writer coupling is proven in both directions, and a user in
Africa/Cairo at 01:00 local can log today without a future-date rejection.
```

### T-21 · Records and the dashboard aggregate

```text
Implement GET /records and GET /dashboard, per spec 5.11, 5.12 and P2-ADR-05/07.

Files: backend/app/repositories/metrics_repo.py, backend/app/services/
dashboard_service.py, backend/app/services/metrics.py, backend/app/schemas/
metrics.py, backend/app/routers/dashboard.py, backend/app/main.py,
backend/tests/unit/test_streak.py, backend/tests/integration/test_dashboard.py

Requirements:
- Records are a read-time aggregation (P2-ADR-05), excluding warm-ups and any
  session that is not completed.
- The streak counts consecutive local calendar days with at least one completed
  session, in the profile timezone. Today untrained does not break it; yesterday
  untrained does.
- Write the nine streak cases in 10.1 as tests BEFORE writing the streak function.
- next_workout follows the most recently completed day, wrapping at days_per_week.
- estimated_minutes per 5.12, rounded to five minutes.
- A brand-new account returns the full empty shape with nulls and zeros, never a
  404, and there is a test asserting that exact shape.
- P2-SAF-002: under 18, omit every weight-direction framing key while still
  returning the weight data.

Done when: all nine streak cases pass including the DST transition and the
timezone change, and the empty-account dashboard test asserts the complete shape.
```

### T-22 · Phase 2 backend hardening and contract

```text
Close the Phase 2 backend per spec 10.1 and 10.3 items 2 to 8.

Files: backend/tests/security/test_cross_tenant.py, backend/tests/security/
test_rls.py, backend/tests/security/test_no_secret_logging.py, backend/tests/
performance/test_seeded_load.py, backend/tests/support.py, backend/openapi.json,
backend/scripts/export_openapi.py, backend/README.md, backend/pyproject.toml

Requirements:
- Regenerate the cross-tenant matrix so it enumerates every Phase 2 route.
- Extend the log-capture test: no weight_kg, no reps, no session notes in any log
  line the suite produces.
- Add the seeded-load test in 10.1 with a committed seed helper: 150 sessions,
  2700 sets, 365 weight entries, asserting P2-NFR-01 for /dashboard and /workouts.
- Regenerate and commit openapi.json.
- Coverage gates: 80 percent overall, 95 percent in plan_generator.py and
  services/metrics.py.
- README covers seeding the exercise library from a fresh clone.

Done when: the whole gate is green - ruff check, ruff format --check,
mypy --strict ., pytest with coverage - and paste the real output.
```

### T-23 · Mobile tab shell and the new component library

```text
Replace the (app) stack with tabs and add the Phase 2 primitives, per spec 8.1, 9.2
and carry-over items 6 and 7 in section 11.

Files: mobile/app/(app)/_layout.tsx, mobile/src/components/GCard.tsx, GStat.tsx,
GChip.tsx, GEmptyState.tsx, GSkeleton.tsx, GListRow.tsx, GNumberField.tsx,
GSheet.tsx, mobile/src/components/index.ts, mobile/src/components/GErrorBanner.tsx,
mobile/app/(app)/_dev-gallery.tsx, mobile/app/(app)/settings.tsx,
mobile/src/api/profile.ts, mobile/src/i18n/ar.json, en.json

Requirements:
- Four tabs per 8.1: index, plan, progress, settings. The (auth) and (onboarding)
  groups and app/_layout.tsx's session gate are NOT touched.
- Send the device timezone (see the ownership note under 4.2): read
  expo-localization's getCalendars()[0].timeZone and PATCH it to /profile on first
  app open when the stored value still equals the server default, so every existing
  Phase 1 account gets a real zone without re-onboarding. Add it as an editable
  field in Settings too. The streak in T-21 and T-24 is wrong for most users until
  this lands.
- Each component to its 9.2 contract. No hex literal, no bare string, start/end
  never left/right, every touchable at least 48 dp with a translated
  accessibilityLabel.
- No new colour in tokens.ts. Use chart1..5, ringWorkout, streak, prBadge, navBg
  and fab, which Phase 1 10.3 already defined for this phase.
- Carry-over 6: replace GErrorBanner's hardcoded dismiss fontSize/lineHeight with a
  type role. Carry-over 7: widen the action gap so the hit-slops stop overlapping.
- Every new component rendered in _dev-gallery in each of its states.

Done when: npm run typecheck and npm run test pass, the gallery shows every
component in light, dark, Arabic and English, and the tab bar is usable at 130
percent font scale.
```

### T-24 · Dashboard screen

```text
Build the dashboard and delete the Phase 1 placeholder, per spec 5.12, 8.2 screen 16
and 8.5.

Files: mobile/app/(app)/index.tsx, mobile/app/(app)/home.tsx (DELETE),
mobile/src/api/dashboard.ts, mobile/src/i18n/ar.json, en.json

Requirements:
- One GET /dashboard call through TanStack Query.
- Every block from 5.12: greeting, resume banner, next workout, streak, this week,
  weight sparkline, recent records, stale-plan prompt, disclaimer line.
- Skeleton on first load, never a spinner replacing already-loaded data (P2-NFR-08).
- The empty state for a brand-new account: no zeros pretending to be measurements,
  one clear action - build my plan.
- home.tsx is deleted in this commit. The next-phase placeholder cannot survive the
  phase it promised (10.3 item 11).

Done when: a fresh account and a 12-week-old account both render correctly, and
device checks 1 and 11 in 10.2 pass.
```

### T-25 · Plan screens

```text
Build the program overview and day detail, per spec 8.2 screens 17 and 18.

Files: mobile/app/(app)/plan/index.tsx, mobile/app/(app)/plan/[dayId].tsx,
mobile/src/api/program.ts, mobile/src/i18n/ar.json, en.json

Requirements:
- Overview: day cards with label (from label_key, translated on the device), focus
  chips, exercise count, estimated minutes. Regenerate behind a confirm.
- Empty state to the days-per-week picker to POST /program/generate.
- Day detail: ordered exercises with targets and last_performance; one primary
  Start this workout button.
- The medical disclaimer line on both screens (P2-SAF-004).
- Handle 409 SESSION_ACTIVE_BLOCKS_REGENERATION with a message pointing at the
  active session, not a generic banner.

Done when: device checks 2 and 3 in 10.2 pass, and every string comes from i18n.
```

### T-26 · The active-workout screen

```text
Build the active workout screen, per spec 8.3, 8.4, 8.5 and P2-ADR-08. This is the
screen the phase lives or dies on - read 8.3 in full before starting.

Files: mobile/app/(app)/workout/active.tsx, mobile/src/workout/activeSession.ts,
mobile/src/components/GRestTimer.tsx, mobile/src/api/workouts.ts,
mobile/src/components/index.ts, mobile/app/(app)/_dev-gallery.tsx,
mobile/src/i18n/ar.json, en.json

Requirements:
- All eight numbered requirements in 8.3, each one testable on a device.
- The rest timer is wall-clock arithmetic against a stored timestamp, never a
  setInterval that a backgrounded JS thread freezes.
- Optimistic set rows with an unsent marker and a per-row retry (P2-ADR-08). Finish
  is blocked while any set is unsent, offering retry all or discard unsent.
- RPE and warm-up are hidden behind the 8.4 disclosure toggle.
- Navigation is guarded: back and the tab bar are blocked until Finish or Abandon,
  both behind a confirm. The exercise library is the one permitted push.
- Session state lives in activeSession.ts, never only in a component - it must
  survive rotation and backgrounding.

Done when: device checks 4 through 10 in 10.2 all pass, including backgrounding
mid-rest and logging two sets with wifi off.
```

### T-27 · History and session detail

```text
Build the history list and the read-only session detail, per spec 8.2 screens 20
and 21.

Files: mobile/app/(app)/history.tsx, mobile/app/(app)/workout/[id].tsx,
mobile/src/api/workouts.ts, mobile/src/i18n/ar.json, en.json

Requirements:
- Infinite cursor-paginated list grouped by month, newest first.
- Session detail: duration, volume, per-exercise sets in position order, records
  set, notes. Warm-up sets shown but visually distinguished (P2-ADR-04).
- Empty state pointing at the plan.

Done when: 150 seeded sessions scroll smoothly and an abandoned session is clearly
marked as such.
```

### T-28 · Progress — weight log, chart and records

```text
Build the progress tab, per spec 5.10, 5.11, 8.2 screen 22 and 9.3.

Files: mobile/app/(app)/progress.tsx, mobile/src/components/GLineChart.tsx,
mobile/src/api/bodyWeight.ts, mobile/src/components/index.ts,
mobile/app/(app)/_dev-gallery.tsx, mobile/src/i18n/ar.json, en.json

Requirements:
- GLineChart built from react-native-svg only, to every rule in 9.3: chart3 for the
  raw series, chart1 for the moving average, gaps drawn as gaps, a labelled
  non-zero-based y-axis, a summarising accessibilityLabel, GEmptyState below two
  entries.
- Range chips for 30, 90 and 365 days.
- Log-today in a GSheet; the entry list is editable and deletable.
- The records list below the chart.
- Axis labels stay LTR with Western digits in Arabic, per Phase 1 9.6.

Done when: device checks 12, 13 and 14 in 10.2 pass, and a 41-entry 90-day series
renders with its gaps visible rather than interpolated.
```

### T-29 · Exercise library screens

```text
Build the library list, detail, and the in-workout picker, per spec 8.2 screens 23
and 24.

Files: mobile/app/(app)/exercises/index.tsx, mobile/app/(app)/exercises/[id].tsx,
mobile/src/api/exercises.ts, mobile/src/i18n/ar.json, en.json

Requirements:
- Searchable, filterable list with muscle and equipment chips; debounced query.
- Detail: name, muscles, equipment, instructions, and this user's record for it.
- The same list, in a GSheet, is the exercise picker for an empty session.
- Names and instructions come from the API already resolved to the profile language
  (5.2) - do not add them to the locale files.

Done when: search works in both languages, and picking an exercise mid-session
returns to the active screen with that exercise selected.
```

### T-30 · Phase 2 polish, i18n and accessibility sweep, mobile README

```text
Close the mobile side per spec 10.2 and 10.3, and write mobile/README.md
(carry-over item 8 in section 11).

Files: mobile/README.md, any Phase 2 screen needing a fix found by the sweep,
mobile/src/i18n/ar.json, en.json

Requirements:
- Walk all eighteen device checks in 10.2 and fix what fails.
- Key-parity check between ar.json and en.json - identical key sets, zero
  differences.
- Grep every Phase 2 file for a hex literal, a bare user-visible string, and
  left/right in a layout style. Zero findings.
- 130 percent font scale on every new screen; dark mode on every new screen;
  TalkBack through a full logged set.
- mobile/README.md covers a fresh clone to a running app: JDK 17 and JAVA_HOME,
  ANDROID_HOME and local.properties, the keytool SHA-1 check against
  google-services.json, disk-space requirements for a local build, and when to use
  eas build instead.

Done when: all eighteen checks pass and you paste the list with a result against
each one.
```

### T-31 · Facebook sign-in — the Phase 1 carry-over (optional, see §13.1 decision 3)

```text
Ship Facebook sign-in, closing P1-FR-004, per Phase 1 spec 5.4, 8.2 and 13.1.2.

Files: backend/app/services/social_service.py, backend/app/routers/auth.py,
mobile/src/auth/firebase.ts, mobile/app/(auth)/welcome.tsx, login.tsx,
mobile/package.json, mobile/app.json, backend/tests/integration/test_social_auth.py,
mobile/src/i18n/ar.json, en.json

Requirements:
- The backend already accepts facebook as a path value and user_identities.provider
  already allows it - no migration. Remove the PROVIDER_NOT_SUPPORTED rejection for
  facebook only.
- The no-email-returned case is expected, not an error: Phase 1 4.2 already allows
  email_at_provider to be NULL.
- react-native-fbsdk-next is added to the mobile dependency list - this is the one
  dependency Phase 2 adds beyond A.2, and Phase 1 A-15 already anticipated it.
- The console work in Phase 1 section 8.2 must be done first: it needs App Review
  with a published privacy policy, which waits on Meta's queue, not on this repo.

Done when: a Facebook account signs in on a device, and signing in with the same
verified email by Google lands on one account with both methods in /auth/me.
```

### T-32 · Merge the Arabic plural fix into the review branch

```text
Merge fix/i18n-arabic-plurals into claude/gymak-weight-tracker-review-76pvgl.

Files: none. This is a merge, not an edit.

Requirements:
- Run the mobile gate on the branch tip (657ab43) BEFORE merging, not only after.
  657ab43 landed after the gate was last run on 5b633e3, so it is unverified.
- Merge with a merge commit (--no-ff), not a fast-forward: the two commits are a
  fix and the follow-up the first one's search method could not reach, and that
  shape is worth keeping in the graph.
- Re-run the gate after the merge. A clean merge is not evidence of a green tree.
- Do not merge on a red gate. Report the output instead.

Done when: npm run typecheck and npm test are green both before and after the
merge, with the same test count, and the merge commit's message says why the fix
took two passes.
```

### T-33 · Replace vitest with jest, so a component can be rendered at all

```text
Move the mobile suite from vitest to jest-expo, and prove the harness works.

Files: mobile/package.json, mobile/jest.config.js, mobile/jest.setup.js,
mobile/src/test-utils/render.tsx, mobile/tsconfig.json, the six existing
src/**/*.test.ts files, mobile/src/components/GStat.test.tsx (new), and delete
mobile/vitest.config.ts

Dependencies (owner-approved, beyond A.2): jest, jest-expo,
@testing-library/react-native, @types/jest. Remove vitest.

Requirements:
- vitest.config.ts scoped the suite to pure functions and said so: "component/
  screen code needs React Native's runtime". 24 screens and 24 components
  therefore have zero automated coverage. jest-expo supplies that runtime.
- jest.setup.js mocks only modules that reach for a native binary:
  expo-secure-store (backed by a real Map -- useTheme and i18n both read back
  what they wrote), expo-router, expo-localization, @react-native-firebase/*,
  @react-native-google-signin. Not expo-haptics: it is not used anywhere.
- src/test-utils/render.tsx wraps in I18nProvider + ThemeProvider in the same
  order as app/_layout.tsx, and takes a REQUIRED locale. Required, because a
  harness that can only render the default locale gives a green suite that never
  reads the language most users read.
- Migrating the six existing files means deleting their `import ... from "vitest"`
  line. Nothing else. If a test fails after the move, that is a real regression
  or a missing mock -- never a reason to edit the test.
- One component test, proving the harness is real: render GStat in both locales
  and assert the streak unit inflects. Include 11, where Arabic reverts to a
  singular-looking form; a one/other "fix" passes 1 and 3 and fails there.

Done when: npm test passes with at least the 70 tests that existed before, plus
the new ones, and regressing arabicPluralCategory to one/other makes exactly the
Arabic cases fail while English stays green.
```

### T-34 · Generate the mobile API types from openapi.json

```text
Stop hand-writing mobile request and response types; generate them.

Files: mobile/package.json, mobile/src/api/schema.d.ts (generated),
mobile/src/api/*.ts, mobile/src/api/schema.drift.test.ts (new)

Dependency (owner-approved, beyond A.2): openapi-typescript (dev).

Requirements:
- An api:generate script emitting src/api/schema.d.ts from
  ../backend/openapi.json. That document is already committed and already has a
  backend drift test; nothing guarded the client side of it.
- Every request and response type in src/api/*.ts reads from the generated
  schema. Types only -- no logic changes, and every exported NAME stays the same
  so no screen is touched.
- Where the generated type is WEAKER than the hand-written one, do not alias it.
  Three response fields are bare dicts on the backend models
  (DashboardResponse.weight, DashboardResponse.program_stale,
  ProgramResponse.stale) and six profile fields are bare strings. Keep the
  precise shapes and anchor each with a type-level assertion that stops
  compiling when the backend models them properly.
- Properties carrying a server-side default come back marked required, because
  openapi-typescript emits one type per schema and cannot tell a request from a
  response. Restore those per field, not by disabling --default-non-nullable,
  which would make every defaulted response field optional.
- A test that fails when the committed schema.d.ts differs from a fresh
  generation -- the mobile twin of backend/tests/unit/test_openapi_contract.py.

Done when: npm run api:generate produces no diff, npm run typecheck is green,
and renaming a field in openapi.json fails the drift test AND, after
regenerating, fails typecheck at the real call sites.
```

### T-35 · CI and Docker

```text
Make the gate something CI runs, and make a fresh clone able to start.

Files: docker-compose.yml, db/init/01-roles.sql, backend/Dockerfile,
backend/.dockerignore, .github/workflows/pr.yml, backend/README.md

Requirements:
- docker-compose.yml with PostgreSQL 16, whose init script creates gymak_migrator
  and gymak_app with the same grants backend/README.md documents by hand and
  tests/conftest.py provisions -- all three must not diverge. No container_name:
  the older `docker run --name gymak-db` container may still exist.
- backend/Dockerfile: multi-stage, non-root, no build toolchain in the runtime
  image. .dockerignore must exclude .env -- every COPY layer is readable by
  anyone who can pull the image, and docker history shows it even after deletion.
- .github/workflows/pr.yml: lint (ruff check, ruff format --check, mypy --strict),
  backend unit, backend integration under testcontainers with the coverage gate,
  and mobile (typecheck, jest, schema.d.ts drift).
- The coverage gate belongs in whichever job can actually carry it. Measure
  before deciding: --cov-fail-under=80 is a whole-suite number.
- One more check: fail when docs/PHASE-2-SPEC.md's table-row count DROPS against
  the base commit (grep -c '^|'). Its tables have been destroyed three times
  (027517a, restored by 8486092 and again by 5249b1c). A floor, not an exact
  match -- adding rows is normal.
- Do not run migrations from the app's entrypoint: alembic connects as
  gymak_migrator and the app as gymak_app.

Done when: docker compose up -d db gives a database alembic upgrade head runs on
from a fresh volume with zero SQL typed by hand, the built image serves
GET /api/v1/health as a non-root user, and the spec-table check fails on 027517a
while passing on the restore that followed it.
```

---

## 13 · Decisions to confirm

### 13.1 Open — T-15 cannot start until 1 and 2 are answered

| #   | Question                                                                                                                                                                                                                                                                                                                                        | Recommendation                                                                                                                                                                                                                                                |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Is the §6.4 sets/reps/rest table right?** This is the one table in Phase 2 with real-world consequences, and it is the one thing in this document I cannot verify from the codebase. Review it as a lifter, not as a developer. Specifically: are the beginner volumes low enough, and is the advanced 22-sets-per-muscle ceiling defensible? | Review it before T-17. A wrong number here ships to every user.                                                                                                                                                                                               |
| 2   | **`mobile/android/` — committed or ignored?** Carry-over item 3. Committing it means the native project is reproducible and PRs show native changes, but the repository grows and the keystore needs excluding by hand. Ignoring it means `expo prebuild` regenerates it and `local.properties` must be recreated on each machine.              | **Ignore it.** The project is Expo-managed and `app.json` is the source of truth; a committed `android/` invites hand-edits that `prebuild` then silently discards. Gitignore it, and document the regeneration steps in `mobile/README.md`.                  |
| 3   | **Does Facebook sign-in (T-31) belong in Phase 2 at all?** Phase 1 deferred it here, but the blocker was never code — it is Meta's App Review queue and a published privacy policy.                                                                                                                                                             | **Defer again, to Phase 3**, unless the privacy policy already exists. Shipping the rest of Phase 2 should not wait on a review queue. Record it as deferred rather than dropping it.                                                                         |
| 4   | **Should the user be able to edit the generated plan?** Swap an exercise, add a day, change a target.                                                                                                                                                                                                                                           | **No, not in Phase 2.** It multiplies the data model (an override table), the API, and the UI, and there is no evidence yet about which parts users actually want to change. Ship the read-only plan, watch what people ask for, decide in Phase 3 with data. |
| 5   | **Should an `in_progress` session auto-abandon after some period?** P2-ADR-03 says no for now.                                                                                                                                                                                                                                                  | **No.** Pick a duration and you will be wrong for someone. The banner already makes a stale session visible and one tap resolves it. Revisit if real users actually leave sessions open.                                                                      |

### 13.2 Decided unless overruled

| #   | Question                     | Answer applied                                                                                                                                                                                                                                                        |
| --- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 6   | Estimated 1RM formula        | Epley. Simple, well known, and accurate enough in the 1–10 rep range where it will actually be used. Computed on read (P2-ADR-04), so switching to Brzycki later is a code change, not a backfill.                                                                    |
| 7   | Streak definition            | Consecutive local calendar days with at least one **completed** session. Today untrained does not break it; yesterday untrained does. Abandoned sessions do not count. Rest days therefore break a streak — which is honest, and is why the copy never scolds (§8.6). |
| 8   | Timezone source              | `expo-localization`'s `getCalendars()[0].timeZone` at onboarding, editable in Settings. Never inferred from the IP.                                                                                                                                                   |
| 9   | Exercise library size        | ~50–60 movements. Enough to build every split in §6.2 with A/B variety; small enough that every row can actually be reviewed for correct tagging. Growth is a later data migration, not a Phase 2 goal.                                                               |
| 10  | Chart library                | None. `react-native-svg` and a path (§9.3). A charting library brings a theming system that will fight `tokens.ts`, for one line chart.                                                                                                                               |
| 11  | Where the disclaimer appears | Inline on every prescription screen, always visible, never a dismissible modal (§8.6). A dismissed disclaimer is not a disclaimer.                                                                                                                                    |

---

## Appendix A

### A.1 Environment variables

No new backend variables. Phase 1's `backend/.env.example` is unchanged.

Mobile changes, all resolving carry-over items:

```bash
# mobile/.env.example — public values only
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.10:8000/api/v1
        # Declared ONCE (carry-over item 4 removed the duplicate). Point this at the
        # backend's LAN IP, not localhost — a physical device cannot reach the dev
        # machine's loopback. Add the same address to the backend's CORS_ORIGINS.
        # This value does NOT belong in eas.json (carry-over item 1): use
        # `eas env:create` so a changed router address is not a commit.
```

### A.2 Permitted dependencies — additions only

**Backend:** none. Phase 2 adds no Python dependency. If a task believes it needs one, that is a
question, not a decision.

**Mobile:** `react-native-svg` (Expo-managed, for §9.3's chart only). And, if and only if §13.1
decision 3 says Facebook ships in this phase, `react-native-fbsdk-next` — which Phase 1's A-15
already anticipated.

Nothing else. In particular: no charting library, no animation library beyond React Native's own
`Animated`, no date library (`Intl` and `zoneinfo` cover everything this phase needs), no state
manager beyond the Zustand already in use.

### A.3 The exercise seed file — shape

```json
[
  {
    "id": "01920000-0000-7000-8000-000000000001",
    "slug": "barbell-back-squat",
    "name_en": "Barbell back squat",
    "name_ar": "سكوات بالبار",
    "primary_muscle": "quads",
    "secondary_muscles": ["glutes", "hamstrings", "lower_back", "abs"],
    "equipment": "barbell",
    "movement_pattern": "squat",
    "is_compound": true,
    "difficulty": "beginner",
    "instructions_en": "Set the bar across your upper back...",
    "instructions_ar": "ضع البار على أعلى الظهر...",
    "is_active": true
  }
]
```

Ids are fixed in the file, not generated at seed time (P2-ADR-02), so the same exercise has the same
id in development, staging and production, and a session logged in one environment resolves in
another.

### A.4 Deliberately deferred — the answer is "a later phase", not "never"

|                                               |                                    |                                          |                                |
| --------------------------------------------- | ---------------------------------- | ---------------------------------------- | ------------------------------ |
| Nutrition: TDEE, macros, food logging         | Phase 3                            | Plan editing and exercise swapping       | Phase 3, per §13.1 decision 4  |
| AI coach, form feedback, adaptive programming | Phase 4                            | Progress photos and body measurements    | Phase 3                        |
| Offline mutation queue                        | Phase 3                            | Push notifications and workout reminders | Phase 4                        |
| Apple Sign-In and the first iOS build         | Phase 3                            | Supersets, drop sets, tempo prescription | Phase 3                        |
| Subscriptions and paywalls                    | Phase 4                            | Social: friends, sharing, leaderboards   | Unscheduled                    |
| Cardio and mobility sessions                  | Phase 3                            | Physical purge job for deleted accounts  | Phase 3 (carried from Phase 1) |
| Facebook sign-in                              | Phase 2 or 3, per §13.1 decision 3 | Custom user-created exercises            | Unscheduled                    |

### A.5 Glossary — Phase 2 additions

|                          |                                                                                                                                                               |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Split**                | How a training week divides the body across days. `full_body`, `upper_lower`, `push_pull_legs` (§6.2).                                                        |
| **Movement pattern**     | The mechanical category of an exercise — squat, hinge, horizontal push — which is what the generator selects on, rather than the exercise's name.             |
| **Compound / isolation** | A compound moves multiple joints (squat, bench press); an isolation moves one (bicep curl). Compounds are ordered first within a day (§6.3).                  |
| **Volume**               | Sets × reps × weight, over non-warm-up sets only. The primary progress measure in this phase.                                                                 |
| **e1RM**                 | Estimated one-rep max. Epley: `weight × (1 + reps/30)`. Computed on read, never stored (P2-ADR-04).                                                           |
| **RPE**                  | Rate of perceived exertion, 5–10. Optional, hidden by default (§8.4).                                                                                         |
| **Streak**               | Consecutive local calendar days with at least one completed session (§13.2 item 7).                                                                           |
| **Program vs. session**  | A program is the plan — what you intend to do. A session is one instance of doing it. Sessions outlive the program that produced them (§4.6's `SET NULL`).    |
| **`local_date`**         | A session's `started_at` resolved into the user's timezone at insert time, stored so day-boundary arithmetic never re-derives a timezone at read time (§4.6). |
| **Generator version**    | An integer stamped on every program recording which revision of the §6.4 rules produced it (P2-ADR-01).                                                       |

---

> **A closing note on the one rule that matters most in this phase.**
>
> Phase 1 was hard to get wrong quietly: an auth bug is a test failure or a security finding.
> Phase 2 is different. A plan with too much volume, a streak off by one, a chart that interpolates
> across a gap, a "record" the user never set — none of these fail a test that was not deliberately
> written, and all of them are the kind of wrong that a user believes for months. Every number this
> app displays is a claim it is making to someone about their own body. Write the test that could
> catch the claim being false, before writing the code that makes it.
