# Gymak — Phase 2 Build Specification

> **Document ID** GYMAK-P2-SPEC-001 · **Version** 1.0 · **Date** 26 August 2026
> **Owner** Nabil — sole developer · **Phase** 2 of N — workout domain, offline logging, UX rebuild
> **Stack** FastAPI · PostgreSQL · Firebase Auth (social broker) · React Native (Expo) · SQLite (client)
> **Derives from** AIFC-SRS-TDD-001 v1.0 (Vol. 1, 3, 4, 5, 6) · GYMAK-P1-SPEC-001 v1.3 · Gymak Color System
> **Extends** GYMAK-P1-SPEC-001 v1.3 — does not supersede it, except where §0.4 lists an explicit amendment
> **Progress** T-15 next. T-01 … T-14 complete (Phase 1 backend + mobile shipped).
>
> **This file is the single source of truth for Phase 2.** Phase 1's spec remains the source of
> truth for everything it covers — auth, session management, profile capture, the error catalogue,
> and the design tokens. Where the two documents disagree, §0.4 below names which one wins and why.
>
> Execute one task from §8 at a time, touching only the files that task names.

---

## 0 · How to use this document

### 0.1 Reading order

- **1** — Phase 2 scope — what ships, what stays deferred
- **2** — Architecture decisions (P2-ADR-08 … 14) — porting strategy, offline model, rules-engine authority
- **3** — The UX contract — the CTA budget, the screen inventory, and the rework rules **(read this before any UI task)**
- **4** — Data model additions — new tables, constraints, RLS
- **5** — API contract additions — every new endpoint
- **6** — Offline and sync contract — the client SQLite schema and the outbox protocol
- **7** — Design system additions — new primitives, icons, motion
- **8** — Task pack — ordered, copy-paste prompts T-15 … T-37
- **9** — Testing requirements and Phase 2 definition of done
- **10** — Decisions Nabil must confirm
- **A** — Appendix — dependencies, porting notes, glossary additions

### 0.2 Rules of engagement for the coding agent

> **These rules override any instinct to be helpful beyond the task. They are Phase 1's rules,
> carried forward unchanged, plus two additions marked NEW.**
>
> 1. **One task at a time.** Execute exactly one task from §8. Do not start the next task, do not
>    "also fix" an adjacent file, do not refactor code you were not asked about.
> 2. **Named files only.** Each task lists the files it may create or modify. Touching any other
>    file is a failure of the task, even if the change is an improvement. **Standing exception:**
>    `pyproject.toml`, `package.json` and `tests/**` are always in scope, because a task that
>    cannot adjust its own test configuration will delete a test instead.
> 3. **No scope invention.** If a feature is not in §1's "in scope" list, it does not get built,
>    stubbed, or scaffolded — not nutrition, not AI, not payments, not social feeds.
> 4. **Ask, don't assume.** If a required detail is genuinely absent from this document, stop and
>    ask one specific question. Do not invent a schema column, an endpoint, or a library.
> 5. **No new dependencies** beyond Appendix A.2 without asking first.
> 6. **Report before changing.** State what the current implementation actually does before you
>    modify it.
> 7. **Every task ends with its tests passing** and the diff summarised in plain language: files
>    touched, what changed, what to verify manually, and what you deliberately did not do. Paste
>    real command output with exit codes — `ruff`, `mypy --strict`, `pytest`, `jest`, `tsc`.
> 8. **NEW — Never copy a file from GymTK.** See P2-ADR-08. GymTK is a design reference you read;
>    it is not a source tree you copy from. Every file you write is written against Gymak's own
>    conventions. If you find yourself pasting, you have misread this rule.
> 9. **NEW — The CTA budget in §3.2 is a gate, not a guideline.** A UI task whose screen exceeds
>    its budget has failed, the same way a task with a red test has failed. There is a structural
>    test that enforces this; do not weaken it to make a screen pass.

### 0.3 The steps this document covers

| Step       | Deliverable                                                                                    | Tasks       | Done when                                                        |
|------------|------------------------------------------------------------------------------------------------|-------------|------------------------------------------------------------------|
| **Step 4** | Foundation repair: CI, containers, a mobile test harness that can render components, generated API types | T-15 … T-18 | CI green on a pull request; a component test renders and asserts   |
| **Step 5** | UX rebuild: app shell, onboarding compression, CTA reduction, settings restructure              | T-19 … T-22 | Every screen inside its §3.2 budget; onboarding completes in ≤ 8 taps |
| **Step 6** | Backend domain: exercises, goals, body metrics, rules engine, programmes, sessions, sync        | T-23 … T-29 | All new endpoints green; cross-tenant matrix extended and passing |
| **Step 7** | Mobile domain: local database, sync engine, exercise library, programme builder, session logging, dashboard | T-30 … T-35 | A real device logs a full session in airplane mode and syncs on reconnect |
| **Step 8** | Store readiness: Apple Sign-In, accessibility pass                                              | T-36 … T-37 | App Store sign-in requirement met; session flow operable with VoiceOver and TalkBack |

Steps run in order. Step 5 deliberately precedes Steps 6 and 7: the domain screens are the bulk of
the app's surface, and building them on the current shell would multiply the UX debt this phase
exists to clear.

### 0.4 Amendments to GYMAK-P1-SPEC-001 v1.3

Phase 1's spec stays authoritative except for these seven points. Each is a deliberate reversal
with a stated reason, not drift.

| ID   | P1 section              | Amendment                                                                                                                                                                                                                                                                        |
|------|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **P2-A-01** | §1.2 out-of-scope     | "Offline mutation queue (auth and onboarding are online-only operations)" is **reversed for domain data**. Session logging is offline-first from T-30 onward (P2-ADR-09). Auth and onboarding remain online-only exactly as P1 specified — the reversal covers programmes, sessions, set logs, and body metrics only. |
| **P2-A-02** | §1.2 out-of-scope     | "Exercise library, programmes, workout sessions, set logging" and "Progress photos, charts, analytics, dashboards" move **in scope** — that is what this phase is. Nutrition, AI, push notifications, subscriptions, and Health/Fit integration stay out.                          |
| **P2-A-03** | §9.3 screen list      | The onboarding screen inventory is **replaced** by §3.3 of this document: seven screens (six steps + review) become three. P1 §9.3 screens 8–14 no longer describe what ships.                                                                                                     |
| **P2-A-04** | §9.3 screen 14 (home) | The home placeholder is replaced by a real dashboard (T-35). P1's "no fake data, no placeholder charts" rule is **kept and strengthened**: the dashboard renders empty states until real logged data exists, never sample data.                                                     |
| **P2-A-05** | §1.2 out-of-scope     | Apple Sign-In moves **in scope** (T-36). P1 deferred it to "Phase 3 of the roadmap, when the iOS build ships". The App Store requires it wherever third-party sign-in is offered, so it blocks any submission, not just an iOS-specific one.                                        |
| **P2-A-06** | Appendix A.2          | The dependency list is extended by Appendix A.2 of this document. Nothing is removed.                                                                                                                                                                                             |
| **P2-A-07** | §11 testing           | Mobile testing moves from `vitest` to `jest-expo` + `@testing-library/react-native` (T-16). `vitest` cannot render React Native components, which is why Phase 1 shipped 16 screens behind a single test file.                                                                     |

### 0.5 Housekeeping that must happen first

Two facts about the repository are wrong today and will mislead any agent that reads it:

1. **`docs/PHASE-1-SPEC.md` §0.3's build-status table says `T-10 | Next`.** T-10 through T-14 are
   all committed. T-15 (below) updates that table as its first action.
2. **Superseded copies of the Phase 1 spec exist outside the repository** as `v1.0` and `v1.2`
   PDFs. v1.3 §0's own words: *"If two versions of this document are reachable by a coding agent,
   the single-source-of-truth rule is already broken."* Delete them. They describe a reset-code
   format `P1-ADR-07` rejected and a Facebook sign-in that `A-15` deferred.

---

## 1 · Phase 2 scope

### 1.1 In scope — build exactly this

| ID | Requirement | Source | Layer |
|----|-------------|--------|-------|
| P2-FR-020 | Serve an exercise library with search, filtering by muscle group / equipment / movement pattern, and per-exercise instructions | SRS FR-018, FR-019 | API + app |
| P2-FR-021 | Create, edit, and archive a training programme entirely by hand — days, ordered items, sets, reps, load, rest | SRS FR-026 | API + app |
| P2-FR-022 | Generate a multi-week programme from profile, goal, and experience level using the deterministic rules engine | SRS FR-020 | API |
| P2-FR-023 | Attach an explicit progression rule to every programme item | SRS FR-021 | API |
| P2-FR-024 | Prescribe conservative starting loads for users with no lift history | SRS FR-022 | API |
| P2-FR-025 | Exclude movement patterns contraindicated by declared injuries | SRS FR-023 | API |
| P2-FR-026 | Substitute an exercise for an equivalent within the same programme | SRS FR-024 | API + app |
| P2-FR-027 | Expose full programme structure including weekly volume and intensity summaries | SRS FR-025 | API + app |
| P2-FR-030 | Start, pause, resume, and complete a workout session | SRS FR-030 | API + app |
| P2-FR-031 | Log weight, repetitions, and RPE per set | SRS FR-031 | API + app |
| P2-FR-032 | Run an automatic rest timer between sets | SRS FR-032 | App |
| P2-FR-033 | Operate the full session flow offline and sync on reconnect | SRS FR-033, NFR-011 | App + API |
| P2-FR-034 | Record session-level notes and perceived effort | SRS FR-034 | API + app |
| P2-FR-040 | Create, update, and archive goals with a target and a date | SRS FR-014 | API + app |
| P2-FR-050 | Record body weight and body measurements over time | SRS FR-050 | API + app |
| P2-FR-052 | Compute and chart estimated one-repetition maximum per exercise | SRS FR-052 | API + app |
| P2-FR-053 | Chart weekly training volume per muscle group | SRS FR-053 | API + app |
| P2-FR-062 | Propose a deload when accumulated fatigue criteria are met | SRS FR-062 | API + app |
| P2-FR-002 | Sign in or register with Apple | SRS FR-002 | API + app |
| P2-SAF-002 | A generated or manually built programme never exceeds the weekly hard-set landmark for the user's training status | SRS SAF | API |
| P2-SAF-003 | A prescribed starting load for a user with no history never exceeds the conservative calibration bound | SRS SAF | API |
| P2-UX-001 | Every screen stays inside the CTA budget in §3.2 | This document | App |

### 1.2 Out of scope — do not build, stub, or scaffold

Anything below appearing in a Phase 2 pull request is a defect.

| Out of scope | Why, and where it lands |
|--------------|--------------------------|
| Nutrition targets, food search, meal logging, meal plans | SRS Phase 6 equivalent. Needs the USDA corpus and its own safety floors. |
| Any LLM call, RAG pipeline, assistant surface, or plan explanation | SRS Phase 7. The rules engine is the sole author of every number this phase ships (P2-ADR-10). |
| Weekly adaptation review, plan adjustment approval | SRS Phase 8. Depends on the AI platform. Note: **deload proposal is in scope** — it is pure rules-engine output and needs no AI. |
| Push notifications and FCM wiring | SRS Phase 10. |
| Subscriptions, receipt validation, paywalls | SRS Phase 10. |
| Apple Health / Google Fit integration | SRS Phase 10. |
| Progress photographs | Needs encryption at rest and signed URLs; a security surface of its own. |
| Social feed, following, leaderboards | Explicitly out of scope for v1.0 in the SRS §1.5. |
| Apple Watch / WearOS companion | Real competitive gap, real cost. Its own phase. |
| Barcode scanning | Belongs with nutrition. |
| Data export | SRS Phase 9. |

### 1.3 Non-functional targets that apply now

Phase 1's P1-NFR-01 … P1-NFR-08 all still apply. These are additional.

| ID | Target | Verified by |
|----|--------|-------------|
| P2-NFR-01 | The full session-logging flow works with the device in airplane mode, and every mutation reaches the server on reconnect | Offline integration test plus a manual airplane-mode device run |
| P2-NFR-02 | Exercise library search returns in under 300 ms p95 against the full 873-row corpus | Load test against a seeded database |
| P2-NFR-03 | No sync batch can write a row owned by another user, regardless of what the payload claims | Extended cross-tenant matrix, plus a payload-identity-injection test |
| P2-NFR-04 | Every screen satisfies the CTA budget in §3.2 | Structural test over `mobile/app/**` |
| P2-NFR-05 | Onboarding completes in 8 taps or fewer from the first step to the dashboard, excluding text entry | Counted in a navigation test |
| P2-NFR-06 | Mobile line coverage at or above 70%, and at or above 90% in `src/db`, `src/sync`, and `src/validation` | `jest --coverage` gate |
| P2-NFR-07 | The rules engine is pure: no module under `app/rules/` imports a database session, an HTTP client, or the clock | Import-boundary test |
| P2-NFR-08 | Cold app start below 2.5 s on a mid-range Android device | Manual timing on a real device, recorded in the task report |

---

## 2 · Architecture decisions

These seven decisions are settled. They are recorded so the agent does not relitigate them
mid-build, and so a future reader understands why the code looks the way it does.

### P2-ADR-08 · GymTK is a design reference, never a source tree

**Decision.** Every file in this phase is written fresh, against Gymak's own conventions. Reading
GymTK to understand *what* a module must do and *which algorithm* it implements is expected and
encouraged. Copying a file, a class, or a component from it is forbidden.

**Why.** This is not a stylistic preference — the two stacks are materially incompatible, and a
paste would not compile, let alone fit:

| Concern | Gymak | GymTK |
|---------|-------|-------|
| Mobile navigation | `expo-router` (file-based, `app/` directory) | React Navigation v7 (imperative navigators) |
| Mobile styling | `StyleSheet` + semantic tokens from `src/theme/tokens.ts` | NativeWind v4 (Tailwind classes) |
| Mobile tests | `vitest` → `jest-expo` (T-16) | `jest-expo` |
| Backend layout | Layered: `routers/` → `services/` → `repositories/` → `models/` | Vertical slices: `src/gymtk/<domain>/{router,service,repository,models}.py` |
| Backend package | `app` | `src/gymtk` |
| Social auth | Firebase Admin as identity broker (P1-ADR-01) | Direct OIDC discovery, no Firebase |
| Rate limiting | In-process | Redis |
| i18n | Arabic + English, RTL-aware | English only |

A paste from either mobile tree into the other produces a file that references a navigator that
does not exist, a `className` prop nothing reads, and a token module at a different path.

**Consequence.** Task prompts in §8 name the *behaviour* to build and the *algorithm* to
implement. Where GymTK's implementation is worth reading, the task says so and names the file.
The agent reads it, understands it, closes it, and writes Gymak's version.

**Open question.** §10 decision 1 asks whether GymTK is even the same owner's work. If it is not,
this ADR is also the licensing answer: nothing is copied, so nothing is licensed.

### P2-ADR-09 · Domain data is offline-first; auth and onboarding stay online-only

**Decision.** Programmes, sessions, set logs, and body metrics are written to a local SQLite
database first and drained to the server through an outbox queue. Registration, login, token
refresh, password reset, and the one-time profile capture remain online-only, exactly as Phase 1
built them.

**Why.** The core use case is a person in a gym basement with no signal, logging five sets between
rests. An app that loses that data is not a tracker. But an auth flow that pretends to work
offline is worse than one that says "you need a connection to sign in" — it cannot verify a
password locally, and queuing a registration produces an account that may collide on the server.
The split is not a compromise; the two halves have genuinely different requirements.

**Shape.** Local SQLite holds draft rows plus a monotonic `outbox` table. A drain loop claims
pending rows, posts them in batches of at most 100 to `POST /api/v1/sync`, and marks each
`applied`, `rejected`, or `superseded` from the response. Backoff is exponential; the drain is
single-flight; connectivity changes and app foregrounding both trigger it.

**Consequence.** Every domain mutation has two write paths and one read path. The server is
authoritative on conflict, and the client never invents an id the server has not seen — see §6.3.

### P2-ADR-10 · The rules engine is the sole author of every prescribed number

**Decision.** Every set count, repetition target, load, rest interval, and deload decision this
phase produces comes from a pure, deterministic function in `app/rules/`. No LLM is called. No
number is hard-coded in a router or a service.

**Why.** Three reasons, in order of weight. First, safety: a prescribed load is a number that can
injure someone, and a function you can unit-test at its boundaries is the only kind of author you
can hold to a safety floor. Second, the SRS makes this the product's differentiator — published
2026 reviews of AI fitness apps report fabricated citations and advice that is accurate but not
comprehensive, and "the numbers come from rules, not from a model" is a claim the competition
cannot make. Third, offline: a rules engine runs when the network does not.

**Consequence.** When the AI phase arrives, the LLM proposes and the engine validates and clamps.
The engine is never removed and never becomes a fallback — it stays the generator of record.
Building it as pure functions now is what makes that possible later.

### P2-ADR-11 · The CTA budget is enforced by a test

**Decision.** §3.2's limits are checked by a structural test over `mobile/app/**`, run in CI. A
screen that exceeds its budget fails the build.

**Why.** Every UI guideline that lives only in a document gets violated within three sprints, and
the violation is always locally reasonable — one more button, on one screen, for one good reason.
The current settings screen carries twenty interactive elements in a single flat scroll; nobody
decided that, it accumulated. A number in a test does not accumulate.

**Consequence.** Adding a control to a full screen forces a design decision instead of an
accretion. The test's failure message names the screen, its count, and its budget.

### P2-ADR-12 · The exercise corpus is seeded from the public-domain source, not vendored

**Decision.** The 873-exercise corpus comes from `yuhonas/free-exercise-db` (public domain), fetched
by a seed script that caches its download under `backend/data/`, and is loaded into the `exercises`
table by an idempotent seeder. The JSON is not committed to the repository, and it is not taken
from GymTK.

**Why.** Public domain means no licence obligation, so the only question is provenance hygiene:
fetching from the upstream source and caching it is auditable, and a re-run against a newer
upstream is a diff rather than an archaeology exercise. Vendoring 873 records into git makes every
future refresh a large, unreviewable commit.

**Consequence.** `backend/data/` is gitignored. A fresh clone runs the seed script once. CI seeds a
small fixture subset, not the full corpus, so integration tests stay fast.

### P2-ADR-13 · Units and language are derived, not asked

**Decision.** Measurement units default from the active locale — Arabic and every non-US English
locale get metric, `en-US` gets imperial — and are changed in settings, not during onboarding.
Language is chosen once on the welcome screen and changed in settings.

**Why.** Phase 1's onboarding spends an entire screen (step 6) and three taps asking two questions
the device already answers. A unit system is a display preference with a correct default and a
trivial reversal; it is not a fact about the user that needs capturing before they can use the app.
Asking it in onboarding is the clearest single instance of the problem this phase's UX rework
exists to fix.

**Consequence.** Step 6 is deleted, not merged. Height and weight fields carry a small inline unit
toggle for the user whose device locale is wrong for them, and that toggle writes the same
preference the settings screen does.

### P2-ADR-14 · An icon system ships before any new screen

**Decision.** `lucide-react-native` is added as a dependency in T-18, and every navigational and
state-bearing surface built from T-19 onward uses it. No new screen ships icon-free.

**Why.** The application currently contains one image — `assets/logo.png` — and zero icons. This is
the single largest reason the interface reads as unfinished rather than minimal: a bottom tab bar
without icons is not a design choice, an empty state without an illustration is a blank screen, and
a list row without a chevron does not look tappable. Adding icons after the domain screens exist
means touching every one of them twice.

**Consequence.** Lucide's stroke-based 24×24 grid inherits `currentColor`, so icons take their
colour from the same semantic tokens text does, and no icon carries a hex literal — the rule
`src/theme/tokens.ts` already states for every other visual value.

---

## 3 · The UX contract

**Read this section before any task numbered T-19 through T-22, and before adding any screen in
Steps 6 and 7.**

### 3.1 What is actually wrong today

Measured from the shipped code, not from impression. Counts are interactive elements per screen —
`GButton` plus `GSelectCard` plus `Pressable`.

| Screen | Interactive elements | The specific problem |
|--------|---------------------:|----------------------|
| `(app)/settings.tsx` | **20** | Six buttons, thirteen selection cards, and eight inputs in one flat scroll. Every profile field is simultaneously visible and editable, so nothing has priority and the destructive account-deletion control sits in the same visual plane as a units toggle. |
| `(onboarding)/step-6.tsx` | 5 | An entire screen asking for units and language — two preferences with correct defaults (P2-ADR-13). |
| `(auth)/welcome.tsx` | 4 | Four competing calls to action with no hierarchy: Create account, Log in, Continue with Google, and a language toggle rendered as a ghost button in the corner. |
| `(auth)/login.tsx` | 4 | Submit, forgot-password, Google, and a back affordance, plus a conditional reset notice. |
| `(onboarding)/step-4.tsx`, `step-5.tsx` | 4 each | One question per screen. Three option cards and a Continue button. |
| `(onboarding)/step-1.tsx`, `step-3.tsx` | 3 each | `step-3` spends two of its three on a metric/imperial toggle rendered as full-width selection cards. |
| `(onboarding)/review.tsx` | 2 visible, **7 targets** | Six edit links, each navigating to a separate screen and back, plus submit. |
| `(app)/home.tsx` | 1 | A greeting and a panel stating that the training plan arrives in a later phase. |

Three structural problems follow from that table:

1. **Onboarding is seven screens for eight fields.** Minimum sixteen taps plus text entry, across
   six "Continue" buttons and a review pass. Two of those screens (`step-3`'s unit toggle,
   `step-6` entirely) ask questions the device already answers.
2. **Settings is a single flat form.** Twenty controls with no grouping, no navigation, and no
   separation between a preference and an irreversible action.
3. **There is no application shell.** No bottom tab bar, no persistent navigation. Every screen is
   reached by pushing onto a stack from the one before it. There is nowhere to put a Train tab, a
   Progress tab, or a Profile tab, which is where the entirety of Steps 6 and 7 needs to land.

And one presentational problem that amplifies all three: **the application has no icons**. See
P2-ADR-14.

### 3.2 The CTA budget

These are the limits T-19 through T-22 must bring every screen inside, and every screen built in
Steps 6 and 7 must satisfy on first commit. `interactive elements` counts `GButton`, `GSelectCard`,
`Pressable`, and any new primitive that responds to a tap. It does not count text inputs, because a
form field is not a call to action.

| Rule | Limit | Applies to |
|------|-------|------------|
| **B-1** | **At most one** `variant="primary"` button per screen | Every screen without exception. A screen with two primary actions has not decided what it is for. |
| **B-2** | **At most 5** interactive elements per screen | Every screen except the three exemptions below |
| **B-3** | **At most 3** interactive elements above the fold | Every screen except list screens |
| **B-4** | Secondary actions are **text links**, not buttons | Every screen. "Log in", "Forgot password?", "Skip" are links. |
| **B-5** | A destructive action is **never on the same screen** as a routine one | Account deletion, discarding a draft, ending a session early |
| **B-6** | **No screen may exist** whose only content is one question and a Continue button | Onboarding, and any future wizard |

**Exemptions, and only these three:**

- **List screens** (exercise library, programme day list, session history) are exempt from B-2 and
  B-3 for their list rows only. Their chrome — headers, filters, floating actions — still counts,
  and still obeys B-1 and B-2.
- **Settings group screens** are exempt from B-2 up to a limit of eight rows, because a list of
  navigational rows is a menu, not a set of competing actions. Each row must navigate or open a
  sheet; a row that toggles state in place counts against the budget normally.
- **The active session screen** is exempt from B-2, and only that screen. Logging a set is a
  repeated action under time pressure, and every control on it serves that one job. It still obeys
  B-1, B-5, and B-6.

**Enforcement.** T-19 adds `mobile/src/__tests__/ctaBudget.test.ts`, which parses every file under
`mobile/app/**` that default-exports a component, counts its interactive elements, and asserts the
budget. Exemptions live in an explicit allowlist inside that test file, each with a one-line reason.
Adding a screen to the allowlist without a reason is a failed task.

### 3.3 The new onboarding: seven screens to three

Replaces P1 §9.3 screens 8–14 (amendment P2-A-03).

| New screen | Title (en / ar) | Fields | Interactive elements | Replaces |
|-----------|------------------|--------|---------------------:|----------|
| **1. About you** | "About you" / "عنك" | Name, gender, birth date | 4 — two gender cards, a date field, one primary Continue | old step-1 + step-2 |
| **2. Your body** | "Your body" / "جسمك" | Height, weight, with an inline unit toggle | 3 — inline unit toggle, one primary Continue, one "Why do we ask?" link | old step-3 |
| **3. Your goal** | "Your goal" / "هدفك" | Goal type, experience level | 5 — three goal cards, an experience segmented control, one primary "Start training" | old step-4 + step-5 + step-6 + review |

**Tap count:** 8 maximum, excluding text entry — gender (1), date (1), continue (1), unit toggle
only if the default is wrong (0 typical), continue (1), goal (1), experience (1), start (1). That
is P2-NFR-05's target, down from sixteen.

**The review screen is deleted.** With three screens, everything the user entered is at most two
back-taps away, and the summary it existed to provide now lives on the profile screen where it is
useful more than once. The `POST /profile` call fires from screen 3's primary action.

**What survives unchanged from Phase 1:**

- **Resumability.** `src/onboarding/draft.ts` still persists a draft after every step and restores
  to the furthest completed screen. T-20 migrates its shape from six step-keys to three; a draft
  written by the old shape is discarded, not migrated, because no production user exists yet.
- **P1-SAF-001.** A user under 18 cannot select a weight-loss goal. The rule, its client-side
  disabled state with a visible reason, and its server-side enforcement on both profile writes are
  all unchanged. It now sits on screen 3.
- **Progress indication.** `GProgressBar` stays, now showing three segments rather than six.
- **Every validation rule and error code** in P1 §7.

### 3.4 The new settings: one flat form to five groups

Replaces the current `(app)/settings.tsx` in T-22.

The screen becomes a list of navigational rows. Each row shows its group's title, a one-line
summary of the current values, and a chevron; tapping it opens a bottom sheet containing only that
group's fields and a single Save button.

| Group | Rows shown in the summary | Fields inside the sheet |
|-------|---------------------------|-------------------------|
| **You** | Name, gender, age | `name`, `gender`, `birth_date` |
| **Body** | Height, weight | `height_cm`, `weight_kg` |
| **Goal** | Current goal | `goal`, with P1-SAF-001's disabled state |
| **Training** | Experience level | `experience_level` |
| **Preferences** | Language, units, theme | `locale`, `unit_system`, `theme_preference` |

Below the five rows, separated by a full-width divider and a section heading, sit the account
actions: **Log out** (secondary), and **Delete account** (destructive, and per B-5 it opens a
confirmation screen of its own rather than revealing an inline confirmation field as it does now).

That is five rows plus two account actions — inside the eight-row settings exemption in §3.2.

**Read before building:** GymTK solves this same problem with a group-descriptor module and a
shared edit sheet. Its approach — descriptors that name their own validation schema so the client
cannot drift from the server's constraints — is worth understanding before you write Gymak's
version. Per P2-ADR-08, read it, then write ours: `mobile/src/screens/profile/editGroups.ts` and
`ProfileEditSheet.tsx` in the GymTK tree.

### 3.5 The new auth surface

| Screen | Now | After T-21 |
|--------|-----|------------|
| **Welcome** | 4 CTAs: Create account (primary), Log in (secondary), Continue with Google (social), language toggle (ghost button) | 3: **Continue with Apple** and **Continue with Google** at the top, one primary **Create account**, and "Already have an account? **Log in**" as a text link (B-4). The language toggle becomes a small icon button in the header, not a labelled ghost button. |
| **Login** | 4 | 3: one primary Submit, "Forgot password?" as a text link, social buttons collapsed to a single row |
| **Register** | 3 | 3, unchanged — already inside budget |

**The language switch must stop showing an Alert.** Today, switching language raises
`Alert.alert(t("auth.language.reloadTitle"), …)` asking the user to restart the app, because
flipping `I18nManager.isRTL` requires a native reload. Telling a user to kill and reopen your app
is a defect, not a message. T-21 replaces it with `expo-updates`' `reloadAsync()`, applying the
change immediately behind a brief loading state. If `expo-updates` is unavailable in a bare
development build, the fallback is to apply the locale without the RTL flip until next launch —
never a dialog instructing the user to do the work themselves.

### 3.6 The application shell

T-19 introduces a bottom tab bar. Four tabs, each with a Lucide icon and a label:

| Tab | Icon | Contains | Ships in |
|-----|------|----------|----------|
| **Home** | `Home` | Dashboard: today's session, active programme summary, recent body-weight trend | T-35 |
| **Train** | `Dumbbell` | Programme list → programme overview → active session; exercise library | T-32, T-33, T-34 |
| **Progress** | `TrendingUp` | e1RM chart per exercise, weekly volume per muscle group, body-weight trend | T-35 |
| **Profile** | `User` | Settings groups from §3.4 | T-22 |

Until a tab's content ships, it renders an `EmptyState` naming what will appear there and carrying
**no call to action** — a button that navigates nowhere is worse than no button. This is P1's
"no fake data" rule (P2-A-04) applied to navigation.

### 3.7 Copy rules

Every string is bilingual from the moment it is written — a screen that ships with an English
string and an Arabic `TODO` is an unfinished screen. Both `src/i18n/en.json` and `src/i18n/ar.json`
gain the key in the same commit.

- **Buttons say what happens.** "Start training", not "Continue" where it completes onboarding.
  "Log this set", not "Submit".
- **Errors say what went wrong and what to do.** No apologies. Phase 1's error catalogue (§7)
  already provides the codes; new codes follow its conventions.
- **Empty states name what will fill them.** "Your programmes will appear here once you build one."
- **Offline is not an error.** "You're offline. Your sets are saved on this device and will sync
  when you're back." Neutral colours, never the error token.
- **Numbers are tabular.** Any digit that appears in a column uses the `stat` role from
  `src/theme/typography.ts`, which already sets `fontVariant: ["tabular-nums"]`.

---

## 4 · Data model additions

All new tables follow the conventions Phase 1 established in P1 §4: `uuid7` primary keys via
`app/core/ids.py`, `created_at`/`updated_at` with `timezone(True)`, `FORCE ROW LEVEL SECURITY` with
a `NULLIF` guard on the user-scoped policy, owned by `gymak_migrator` and granted to `gymak_app`,
and a matching downgrade in every migration.

### 4.1 New tables

| Table | Owner scope | Purpose | Key columns |
|-------|-------------|---------|-------------|
| `exercises` | **Global, not user-scoped** | The 873-row corpus | `id`, `name` (unique, citext), `force`, `level`, `mechanic`, `equipment`, `primary_muscles[]`, `secondary_muscles[]`, `movement_pattern`, `instructions[]` |
| `goals` | User | Target and date per goal | `id`, `user_id`, `goal_type`, `target_value`, `target_date`, `status`, `archived_at` |
| `programs` | User | A multi-week training plan | `id`, `user_id`, `name`, `weeks`, `days_per_week`, `split_type`, `source` (`manual` \| `generated`), `status`, `active` |
| `program_days` | User (via program) | One day within a programme | `id`, `program_id`, `day_index`, `name`, `target_muscle_groups[]` |
| `program_items` | User (via day) | One prescribed exercise | `id`, `program_day_id`, `exercise_id`, `order_index`, `sets`, `rep_min`, `rep_max`, `load_kg`, `rest_seconds`, `progression_rule` |
| `workout_sessions` | User | One execution of one programme day | `id`, `user_id`, `program_day_id`, `started_at`, `completed_at`, `status`, `notes`, `session_rpe`, `client_id` |
| `set_logs` | User (via session) | One performed set | `id`, `session_id`, `exercise_id`, `set_index`, `weight_kg`, `reps`, `rpe`, `logged_at`, `client_id` |
| `body_metrics` | User | Weight and measurements over time | `id`, `user_id`, `metric_type`, `value`, `unit`, `recorded_at`, `client_id` |

### 4.2 Constraints that must be in the database, not in Python

Phase 1 established the rule that an invariant enforced only in a service is not enforced. These
follow it.

- `program_items.sets` between 1 and 10; `rep_min` ≤ `rep_max`; both between 1 and 50.
- `program_items.load_kg` ≥ 0 and ≤ 500. `rest_seconds` between 0 and 900.
- `set_logs.reps` between 0 and 100. `weight_kg` ≥ 0 and ≤ 500. `rpe` between 1 and 10, nullable.
- `workout_sessions.completed_at` is null unless `status = 'completed'`, enforced by a `CHECK`.
- **A partial unique index** on `programs (user_id) WHERE active` — one active programme per user,
  enforced by the database, not by a read-then-write in a service.
- **`client_id` is unique per user** on `workout_sessions`, `set_logs`, and `body_metrics`. This is
  the idempotency key the sync protocol depends on; see §6.3.
- `exercises.name` unique, case-insensitive, so a re-seed cannot duplicate the corpus.

### 4.3 RLS

Every user-scoped table gets `FORCE ROW LEVEL SECURITY` and a policy matching Phase 1's shape.
Tables owned through a parent (`program_days`, `program_items`, `set_logs`) are scoped by a
subquery to their owning row's `user_id`, never by a duplicated `user_id` column — a denormalised
owner column is a second thing that can disagree with the first.

`exercises` is global reference data: `gymak_app` gets `SELECT` only, and no `INSERT`, `UPDATE`, or
`DELETE`. Only the seeder, running as `gymak_migrator`, writes it.

---

## 5 · API contract additions

Conventions are Phase 1's (P1 §5): `/api/v1` prefix, the same error envelope, the same error codes
where they apply, `ConfigDict(extra="forbid")` on every request model, and `mypy --strict`.

| Method | Path | Purpose | Ships in |
|--------|------|---------|----------|
| `GET` | `/exercises` | Search and filter the corpus. Query: `q`, `muscle`, `equipment`, `pattern`, `level`, `limit`, `cursor` | T-23 |
| `GET` | `/exercises/{id}` | One exercise with full instructions | T-23 |
| `GET` | `/goals` | List the user's goals | T-24 |
| `POST` | `/goals` | Create a goal | T-24 |
| `PATCH` | `/goals/{id}` | Update or archive a goal | T-24 |
| `GET` | `/body-metrics` | List, filterable by `metric_type` and date range | T-24 |
| `POST` | `/body-metrics` | Record a measurement | T-24 |
| `GET` | `/programs` | List the user's programmes | T-26 |
| `POST` | `/programs` | Create a programme by hand | T-26 |
| `GET` | `/programs/{id}` | Full structure, including volume and intensity summaries (P2-FR-027) | T-26 |
| `PATCH` | `/programs/{id}` | Rename, archive, activate | T-26 |
| `POST` | `/programs/{id}/days` | Add a day | T-26 |
| `PATCH` | `/programs/{id}/days/{day_id}` | Edit or reorder a day | T-26 |
| `POST` | `/programs/{id}/days/{day_id}/items` | Add a prescribed exercise | T-26 |
| `PATCH` | `/programs/{id}/days/{day_id}/items/{item_id}` | Edit a prescribed exercise | T-26 |
| `POST` | `/programs/generate` | Generate from profile, goal, and experience (P2-FR-022) | T-27 |
| `GET` | `/programs/items/{item_id}/substitutes` | Equivalent exercises for one item | T-27 |
| `POST` | `/programs/items/{item_id}/substitute` | Apply a substitution | T-27 |
| `GET` | `/programs/{id}/deload-status` | Whether deload criteria are met, and why | T-27 |
| `POST` | `/programs/{id}/apply-deload` | Apply the deload prescription | T-27 |
| `POST` | `/sessions` | Start a session against a programme day | T-28 |
| `GET` | `/sessions/active` | The in-progress session, if any | T-28 |
| `GET` | `/sessions/{id}` | One session with its set logs | T-28 |
| `PATCH` | `/sessions/{id}` | Pause, resume, add notes or session RPE | T-28 |
| `POST` | `/sessions/{id}/complete` | Complete a session | T-28 |
| `POST` | `/sessions/{id}/sets` | Log a set | T-28 |
| `PATCH` | `/sessions/{id}/sets/{set_id}` | Correct a logged set | T-28 |
| `POST` | `/sync` | Drain a client outbox batch | T-29 |
| `POST` | `/auth/social/apple` | Apple sign-in, via the existing provider route | T-36 |

`openapi.json` is regenerated and committed with every task that changes a route. Phase 1's drift
check (`tests/unit/test_openapi_contract.py`) already fails the build if it is not.

---

## 6 · Offline and sync contract

### 6.1 Client database

SQLite via `expo-sqlite`, migrated by a versioned migration runner in `mobile/src/db/migrations.ts`.
Tables: `outbox`, plus a `_draft` table mirroring each syncable entity — `program_draft`,
`program_day_draft`, `program_item_draft`, `workout_session_draft`, `set_log_draft`,
`body_metric_draft` — and `exercises_cache` for the corpus.

### 6.2 The outbox

| Column | Purpose |
|--------|---------|
| `sequence` | Monotonic integer, the drain order. Never reused. |
| `entity_type` | One of the eight syncable types |
| `entity_client_id` | The client-generated uuid7 this row mutates |
| `op` | `upsert` this phase. `complete` and `delete` arrive with their entities. |
| `payload` | JSON, already in the server's snake_case wire shape |
| `status` | `pending` \| `applied` \| `rejected` \| `superseded` |
| `attempts`, `last_attempt_at`, `last_error` | Backoff bookkeeping |

**The payload is serialised once, at write time, into the exact wire shape** — never converted
again on the way out. A second conversion point is how a client drifts from the contract test that
guards the first one. A contract test asserts every serialiser's output key set against the
committed `backend/openapi.json`.

**No payload value is ever logged.** Weight, body measurements, and injuries are health data. The
outbox and sync modules contain no logging call of any kind, and Phase 1's
`tests/security/test_no_secret_logging.py` is extended to cover the new fields.

### 6.3 The protocol

1. The client generates a `client_id` (uuid7) for every new entity, before it ever reaches the
   network.
2. The drain claims at most 100 pending rows in `sequence` order and posts them as one batch.
3. The server applies each item idempotently, keyed on `(user_id, client_id)`. A repeat of an
   already-applied item returns `applied` again — it does not create a second row.
4. **The owner of every entity is the bearer token's subject, always.** A payload that names a
   `user_id` or an `id` is rejected outright, not silently overridden. This is P2-NFR-03, and it
   has its own test.
5. The response returns a per-item status. `applied` marks the local row synced. `rejected` carries
   an error code and surfaces to the user. `superseded` means a newer mutation for the same entity
   already landed; the local row is dropped without an error.
6. Backoff is exponential with jitter. The drain is single-flight — a second trigger while one is
   in flight is a no-op, not a queued second drain.

### 6.4 What is deliberately not built

- **No conflict resolution UI.** Last write wins, server-authoritative, because a single user on a
  small number of devices does not generate real conflicts and a merge interface for a problem that
  does not occur is pure cost.
- **No background sync.** Draining happens on foreground, on connectivity change, and on explicit
  user action. A background task is an OS-permission surface and a battery conversation this phase
  does not need.
- **No pull sync.** The server never pushes changes to the client this phase. The client reads
  through normal `GET` endpoints and caches. Bidirectional sync arrives when a second device does.

---

## 7 · Design system additions

Phase 1 shipped eight primitives and a complete token set. §10 of the Phase 1 spec — the palette,
the type scale, spacing, radius, motion — is unchanged and remains authoritative. `src/theme/tokens.ts`
already defines `chart1` … `chart5`, `ringWorkout`, `ringCalories`, `ringWeight`, `streak`,
`prBadge`, `fab`, and `navBg` for exactly this phase; use them rather than adding tokens.

### 7.1 New primitives (T-18)

| Primitive | Purpose | Notes |
|-----------|---------|-------|
| `GCard` | The surface every list row and summary block sits on | Uses `card`, `border`, `shadowSm` |
| `GChip` | Filter and tag affordance | Exercise filters, muscle groups |
| `GSheet` | Bottom sheet | Settings groups, exercise substitution, filters |
| `GBadge` | Status marker | Programme `active`, session `in progress`, PR marker |
| `GEmptyState` | Named empty surface with an icon | Carries **no CTA** unless the destination exists |
| `GErrorState` | Full-screen error with a retry | Distinct from `GErrorBanner`, which stays inline |
| `GOfflineBanner` | Thin persistent top banner | Neutral tokens, never `error`. No dismiss control. |
| `GSkeleton` | Shape-matching loading placeholder | Never a bare spinner on a screen with known structure |
| `GSegmented` | Segmented control | Replaces the two-card pattern currently used for binary choices |
| `GStepIndicator` | Three-segment onboarding progress | Replaces `GProgressBar`'s use in onboarding |
| `GStat` | A number with a label and optional trend | Dashboard and progress tiles |
| `GRestTimer` | Countdown with haptic completion | Active session only |

Every primitive is theme-aware through `useTheme()`, carries no hex literal, meets the 48 dp
minimum touch target from P1 §10.6, and ships with a test that renders it in both themes and both
locales.

### 7.2 Icons (P2-ADR-14)

`lucide-react-native`, added in T-18. Icons inherit `currentColor` from the surrounding text
colour token. An icon is never the only label on a control — every icon-only button carries an
`accessibilityLabel`, which P1-NFR-08 already requires.

### 7.3 Charts

`react-native-svg` plus `victory-native` for the two charts P2-FR-052 and P2-FR-053 require. Chart
colours come from `chart1` … `chart5`, which are already defined for both themes. No chart renders
sample data — an empty chart renders `GEmptyState`.

---

## 8 · Task pack

Each task is a copy-paste prompt. Execute one at a time. The **Files** list is exhaustive: touching
anything else is a failed task, subject only to the standing exception in §0.2 rule 2.

---

### Step 4 · Foundation repair

#### T-15 · CI pipeline, containers, and spec housekeeping

**Goal.** Every gate this project already has runs automatically on a pull request, and a fresh
clone can start a database without reading a README.

**Do.**
1. Update `docs/PHASE-1-SPEC.md` §0.3's build-status table: T-10 through T-14 are Done, with a
   one-line note each. Add a v1.4 amendment row recording that this Phase 2 spec now exists and
   what §0.4 of it amends.
2. Add `.github/workflows/pr.yml` with four jobs: lint and typecheck (`ruff check`,
   `ruff format --check`, `mypy --strict app tests`), backend unit tests with the coverage gate,
   backend integration tests (testcontainers PostgreSQL), and mobile (`tsc --noEmit`).
3. Add `docker-compose.yml` at the repository root with PostgreSQL 16, and `backend/Dockerfile`.
4. Add `backend/.dockerignore`.

**Files.** `docs/PHASE-1-SPEC.md`, `.github/workflows/pr.yml`, `docker-compose.yml`,
`backend/Dockerfile`, `backend/.dockerignore`, `backend/README.md`.

**Done when.** A pull request runs all four jobs and they pass. `docker compose up -d` gives a
database that `alembic upgrade head` migrates cleanly. The Phase 1 status table matches the git log.

---

#### T-16 · Mobile test harness

**Goal.** A test can render a screen, press a button, and assert what happened. Today it cannot.

**Do.** Replace `vitest` with `jest-expo` and `@testing-library/react-native`. Port the one existing
test (`src/validation/schemas.test.ts`). Add `jest.config.js`, `jest.setup.js`, and mocks for
`expo-secure-store`, `expo-router`, and `@react-native-firebase/auth`. Add a render helper that
wraps a component in the theme and i18n providers and takes a locale, so every component test can
run in both `ar` and `en`.

**Files.** `mobile/package.json`, `mobile/jest.config.js`, `mobile/jest.setup.js`,
`mobile/src/test-utils/render.tsx`, `mobile/src/validation/schemas.test.ts`,
delete `mobile/vitest.config.ts`.

**Done when.** `npm test` passes. A smoke test renders `GButton` in both themes and both locales
and asserts its accessible label. Coverage reporting is configured with the P2-NFR-06 thresholds,
initially not enforced.

---

#### T-17 · Generated API types

**Goal.** The mobile client's types come from `backend/openapi.json`, so a backend rename breaks the
mobile build instead of the user's request.

**Do.** Add `openapi-typescript` as a dev dependency and an `api:generate` script. Generate
`mobile/src/api/schema.d.ts`. Rewrite `src/api/auth.ts` and `src/api/profile.ts` to take their
request and response types from the generated schema rather than hand-written interfaces. Add a
test that fails if the committed `schema.d.ts` differs from a fresh generation — the mobile mirror
of the backend's existing drift check.

**Files.** `mobile/package.json`, `mobile/src/api/schema.d.ts`, `mobile/src/api/auth.ts`,
`mobile/src/api/profile.ts`, `mobile/src/api/__tests__/schemaDrift.test.ts`.

**Done when.** `npm run api:generate` produces no diff. `tsc --noEmit` passes. Deliberately renaming
a field in `openapi.json` fails the drift test.

---

#### T-18 · Design system expansion

**Goal.** The twelve primitives in §7.1 exist, plus icons, before any screen needs them.

**Do.** Build every primitive in §7.1. Add `lucide-react-native`. Extend `_dev-gallery.tsx` to
render all of them. Each primitive gets a test rendering it in both themes and both locales.

**Files.** `mobile/src/components/G*.tsx` (twelve new), `mobile/src/components/index.ts`,
`mobile/src/components/__tests__/*.test.tsx`, `mobile/app/(app)/_dev-gallery.tsx`,
`mobile/package.json`.

**Done when.** The gallery renders all twenty primitives in both themes and both locales. No
component contains a hex literal — assert this with a structural test. Every interactive primitive
meets 48 dp.

---

### Step 5 · UX rebuild

#### T-19 · Application shell and the CTA budget test

**Goal.** A bottom tab bar exists, and §3.2's budget is enforced by a test.

**Do.** Add `mobile/app/(app)/_layout.tsx` as an `expo-router` Tabs layout with the four tabs in
§3.6, each with its Lucide icon and bilingual label. Home keeps the existing placeholder; Train and
Progress render `GEmptyState` with no CTA; Profile routes to settings. Write
`mobile/src/__tests__/ctaBudget.test.ts` per §3.2's enforcement paragraph, with the three exemptions
as an explicit allowlist.

**Files.** `mobile/app/(app)/_layout.tsx`, `mobile/app/(app)/train.tsx`,
`mobile/app/(app)/progress.tsx`, `mobile/app/(app)/profile.tsx`, `mobile/app/(app)/home.tsx`,
`mobile/src/__tests__/ctaBudget.test.ts`, `mobile/src/i18n/{ar,en}.json`.

**Done when.** The tab bar renders and navigates in both locales, with the tab order mirrored under
RTL. The budget test passes, and deliberately adding a second primary button to any screen fails it.

---

#### T-20 · Onboarding: seven screens to three

**Goal.** §3.3, exactly.

**Do.** Replace the six steps and the review screen with the three in §3.3. Migrate
`src/onboarding/draft.ts` to the three-screen shape, discarding drafts in the old shape. Replace the
two-card unit toggle with `GSegmented` inline on the height and weight fields, defaulting from
locale per P2-ADR-13. Delete the units-and-language step entirely. Move P1-SAF-001's disabled
weight-loss state onto screen 3.

**Files.** `mobile/app/(onboarding)/about-you.tsx`, `mobile/app/(onboarding)/your-body.tsx`,
`mobile/app/(onboarding)/your-goal.tsx`, `mobile/app/(onboarding)/_layout.tsx`,
`mobile/src/onboarding/draft.ts`, `mobile/src/i18n/{ar,en}.json`,
`mobile/src/onboarding/__tests__/*`, delete `mobile/app/(onboarding)/step-{1..6}.tsx` and
`review.tsx`.

**Done when.** A test walks the flow and counts 8 taps or fewer to reach the dashboard (P2-NFR-05).
Every screen is inside its budget. A 17-year-old cannot select weight loss, client-side and
server-side. An abandoned draft resumes at the right screen. Both locales render correctly, RTL
included.

---

#### T-21 · Auth CTA reduction and the language switch

**Goal.** §3.5, exactly.

**Do.** Rework welcome and login per the table in §3.5. Add `expo-updates` and replace the
reload Alert with `reloadAsync()` behind a loading state, with the documented fallback. Move the
language toggle into the header as an icon button with an `accessibilityLabel`. Add an Apple
sign-in button to the welcome screen, wired to a route that returns "not yet available" until T-36
lands the backend — **and hidden behind a feature flag until then**, because a visible button that
cannot work is worse than an absent one.

**Files.** `mobile/app/(auth)/welcome.tsx`, `mobile/app/(auth)/login.tsx`,
`mobile/src/i18n/{ar,en}.json`, `mobile/src/config/features.ts`, `mobile/package.json`,
`mobile/app/(auth)/__tests__/*`.

**Done when.** Welcome has one primary button and one text link. Switching language applies without
a dialog. Both screens inside budget. Tests cover the switch in both directions.

---

#### T-22 · Settings restructure

**Goal.** §3.4, exactly.

**Do.** Replace the flat form with five navigational rows opening `GSheet` editors. Build a
group-descriptor module where each group names its own validation schema, imported from
`src/validation/schemas.ts` and never redeclared. Move account deletion to its own confirmation
screen (B-5). Add a contract test asserting every group's emitted key set against
`backend/openapi.json`.

**Files.** `mobile/app/(app)/profile.tsx`, `mobile/app/(app)/settings/[group].tsx`,
`mobile/app/(app)/settings/delete-account.tsx`, `mobile/src/settings/editGroups.ts`,
`mobile/src/i18n/{ar,en}.json`, `mobile/src/settings/__tests__/*`,
delete `mobile/app/(app)/settings.tsx`.

**Done when.** Five rows plus two account actions. Each sheet saves independently and shows its own
errors. The contract test passes. Deleting an account still requires the password when one exists.

---

### Step 6 · Backend domain

#### T-23 · Exercise corpus

**Goal.** P2-FR-020. The library exists and is searchable.

**Do.** Migration for `exercises` per §4.1 and §4.3, including the case-insensitive unique name and
`SELECT`-only grant to `gymak_app`. A seed script per P2-ADR-12 that fetches from
`yuhonas/free-exercise-db`, caches to a gitignored `backend/data/`, maps each record to a movement
pattern, and is idempotent. `GET /exercises` and `GET /exercises/{id}` with cursor pagination.

**Files.** `backend/alembic/versions/*_exercises.py`, `backend/app/models/exercise.py`,
`backend/app/repositories/exercise_repo.py`, `backend/app/services/exercise_service.py`,
`backend/app/routers/exercises.py`, `backend/app/schemas/exercise.py`,
`backend/scripts/seed_exercises.py`, `backend/app/main.py`, `backend/openapi.json`,
`backend/tests/**`, `.gitignore`.

**Done when.** The seeder loads 873 rows and re-running changes nothing. Search by name, muscle,
equipment, and pattern all work, p95 under 300 ms (P2-NFR-02). `gymak_app` cannot write the table —
assert it.

---

#### T-24 · Goals and body metrics

**Goal.** P2-FR-040 and P2-FR-050.

**Do.** Migrations for `goals` and `body_metrics` per §4, with RLS and the `client_id` uniqueness
§6.3 needs. Five endpoints per §5.

**Files.** `backend/alembic/versions/*_goals_body_metrics.py`, `backend/app/models/{goal,body_metric}.py`,
`backend/app/repositories/{goal_repo,body_metric_repo}.py`,
`backend/app/services/{goal_service,body_metric_service}.py`,
`backend/app/routers/{goals,body_metrics}.py`, `backend/app/schemas/{goal,body_metric}.py`,
`backend/app/main.py`, `backend/openapi.json`, `backend/tests/**`.

**Done when.** All five endpoints green. The cross-tenant matrix picks up the new routes
automatically and passes. Archiving a goal does not delete it.

---

#### T-25 · The rules engine

**Goal.** P2-ADR-10's pure core, before anything calls it.

**Do.** Seven pure modules under `backend/app/rules/`, none importing a session, a client, or the
clock: `epley` (estimated 1RM), `volume` (weekly hard-set landmarks by training status),
`calibration` (conservative starting load), `progression` (double-progression state machine),
`deload` (fatigue trigger and prescription), `split` (split selection by days and experience), and
`trend` (RPE and e1RM trend classification).

**Read before building:** the SRS §3.4 gives the formulas. GymTK implements the same seven — read
`backend/src/gymtk/rules_engine/` to understand the shapes, then write ours per P2-ADR-08.

**Files.** `backend/app/rules/*.py`, `backend/tests/unit/test_rules_*.py`.

**Done when.** Each module has boundary tests including the safety floors P2-SAF-002 and
P2-SAF-003. P2-NFR-07's import-boundary test passes. `mypy --strict` clean. Coverage in
`app/rules/` at or above 95%.

---

#### T-26 · Programmes, built by hand

**Goal.** P2-FR-021 and P2-FR-027. The manual baseline, before any generation.

**Do.** Migrations for `programs`, `program_days`, `program_items` per §4, including the partial
unique index enforcing one active programme. Nine CRUD endpoints per §5. `GET /programs/{id}`
returns the volume and intensity summary computed by `app/rules/volume.py`.

**Files.** `backend/alembic/versions/*_programs.py`, `backend/app/models/program.py`,
`backend/app/repositories/program_repo.py`, `backend/app/services/program_service.py`,
`backend/app/routers/programs.py`, `backend/app/schemas/program.py`, `backend/app/main.py`,
`backend/openapi.json`, `backend/tests/**`.

**Done when.** A programme can be built, edited, and archived entirely through the API with no
generation involved. Activating a second programme deactivates the first, enforced by the index.
Reordering days and items is stable.

---

#### T-27 · Generation, substitution, deload

**Goal.** P2-FR-022 … P2-FR-026, P2-FR-062.

**Do.** `POST /programs/generate` composing `split`, `volume`, and `calibration` into a full
programme; every item carries its progression rule (P2-FR-023). Injury exclusion (P2-FR-025) reads
the profile's declared restrictions and filters movement patterns. Substitution endpoints matching
on muscle group, equipment, and pattern. Deload status and application from `app/rules/deload.py`.

**Files.** `backend/app/services/{generation_service,substitution_service,deload_service}.py`,
`backend/app/routers/programs.py`, `backend/app/schemas/program.py`, `backend/openapi.json`,
`backend/tests/**`.

**Done when.** A generated programme never exceeds the volume landmark (P2-SAF-002) and never
prescribes above the calibration bound for a user with no history (P2-SAF-003) — both asserted as
property tests, not examples. An injury excludes its contraindicated patterns. Generation is
deterministic: the same input produces the same programme.

---

#### T-28 · Sessions and set logs

**Goal.** P2-FR-030, P2-FR-031, P2-FR-034.

**Do.** Migrations for `workout_sessions` and `set_logs` per §4, with the `completed_at` check and
`client_id` uniqueness. Seven endpoints per §5.

**Files.** `backend/alembic/versions/*_sessions.py`, `backend/app/models/session.py`,
`backend/app/repositories/session_repo.py`, `backend/app/services/session_service.py`,
`backend/app/routers/sessions.py`, `backend/app/schemas/session.py`, `backend/app/main.py`,
`backend/openapi.json`, `backend/tests/**`.

**Done when.** A session starts, pauses, resumes, accepts sets, and completes. Only one session is
active per user at a time. Posting the same `client_id` twice creates one row.

---

#### T-29 · The sync endpoint

**Goal.** P2-FR-033's server half, and P2-NFR-03.

**Do.** `POST /sync` per §6.3. Batch cap 100. Per-item status. Idempotency on `(user_id, client_id)`.
Ownership always from the bearer token, with a payload carrying `user_id` or `id` rejected outright.

**Files.** `backend/app/routers/sync.py`, `backend/app/schemas/sync.py`,
`backend/app/services/sync_service.py`, `backend/app/main.py`, `backend/openapi.json`,
`backend/tests/**`, `backend/tests/security/test_cross_tenant.py`.

**Done when.** A batch applies, a replayed batch is idempotent, an oversized batch is rejected, and
a batch attempting to name another user's id is rejected — each with its own test. P2-NFR-03's
test passes.

---

### Step 7 · Mobile domain

#### T-30 · Client database and outbox

**Goal.** §6.1 and §6.2.

**Do.** `expo-sqlite` connection with a versioned migration runner. The draft tables and
`exercises_cache`. The outbox with its claim, mark, and count operations. Serialisers producing the
wire shape once, with a contract test against `backend/openapi.json`.

**Files.** `mobile/src/db/{connection,migrations,schema,types,outbox}.ts`,
`mobile/src/db/drafts/*.ts`, `mobile/src/sync/payloads.ts`, `mobile/src/db/__tests__/*`,
`mobile/package.json`.

**Done when.** Migrations run forward on a fresh database and are idempotent on a migrated one.
Outbox operations are tested against a real SQLite instance. The contract test passes. No module
under `src/db/` or `src/sync/` contains a logging call — assert it.

---

#### T-31 · The sync engine

**Goal.** §6.3's client half.

**Do.** A single-flight drain loop with exponential backoff and jitter, triggered by connectivity
change and app foregrounding. A provider exposing online state and pending count for
`GOfflineBanner`.

**Files.** `mobile/src/sync/{engine,backoff,useConnectivity,SyncProvider}.tsx`,
`mobile/src/api/sync.ts`, `mobile/src/sync/__tests__/*`, `mobile/app/_layout.tsx`,
`mobile/package.json`.

**Done when.** A test drains a queue, handles each of the three statuses, backs off on failure, and
proves a second concurrent trigger is a no-op.

---

#### T-32 · Exercise library

**Goal.** P2-FR-020's client half.

**Do.** A searchable, filterable list under the Train tab, backed by `exercises_cache` so it works
offline once loaded. A filter sheet using `GChip`. A detail screen with instructions and muscles.

**Files.** `mobile/app/(app)/train/exercises.tsx`, `mobile/app/(app)/train/exercises/[id].tsx`,
`mobile/src/api/exercises.ts`, `mobile/src/db/exercisesCache.ts`, `mobile/src/i18n/{ar,en}.json`,
tests.

**Done when.** Search and filters work offline against the cache. List rows are exempt from B-2,
but the chrome is inside budget. Both locales, RTL included.

---

#### T-33 · Programme builder and overview

**Goal.** P2-FR-021, P2-FR-026, P2-FR-027's client half.

**Do.** Programme list, an overview showing days and items with the volume summary, and a builder
for adding and reordering days and items. A substitution sheet. Everything writes to the local
draft tables first and enqueues an outbox row.

**Files.** `mobile/app/(app)/train/index.tsx`, `mobile/app/(app)/train/program/[id].tsx`,
`mobile/app/(app)/train/program/builder.tsx`, `mobile/src/api/programs.ts`,
`mobile/src/i18n/{ar,en}.json`, tests.

**Done when.** A programme is built end to end in airplane mode and syncs on reconnect. Every
screen inside budget.

---

#### T-34 · Active session

**Goal.** P2-FR-030 … P2-FR-034's client half. **This is the screen the product lives or dies on.**

**Do.** A session screen listing the day's prescribed items, with per-set logging of weight, reps,
and RPE, a rest timer with haptic completion, session notes, and completion. Fully offline. The
previous session's numbers for the same exercise are shown as the default, so logging a set is a
confirmation rather than data entry.

**Files.** `mobile/app/(app)/train/session/[id].tsx`, `mobile/src/stores/activeSession.ts`,
`mobile/src/api/sessions.ts`, `mobile/src/i18n/{ar,en}.json`, tests.

**Done when.** A full session is logged in airplane mode and syncs on reconnect. Logging a set is
two taps or fewer when the prescribed numbers are correct. The rest timer survives backgrounding.
This screen uses its §3.2 exemption but still has exactly one primary action.

---

#### T-35 · Dashboard and progress

**Goal.** P2-FR-052, P2-FR-053, and P2-A-04.

**Do.** The Home tab: today's session or the next prescribed one, active programme summary, recent
body-weight trend, and a body-metric logging sheet. The Progress tab: e1RM per exercise and weekly
volume per muscle group, both from `victory-native`. Every surface renders `GEmptyState` until real
logged data exists — **never sample data**.

**Files.** `mobile/app/(app)/home.tsx`, `mobile/app/(app)/progress.tsx`,
`mobile/src/api/bodyMetrics.ts`, `mobile/src/components/charts/*.tsx`,
`mobile/src/i18n/{ar,en}.json`, tests.

**Done when.** A new account sees empty states with no dead CTAs. An account with logged sessions
sees real charts. Chart colours come from the `chart1` … `chart5` tokens in both themes.

---

### Step 8 · Store readiness

#### T-36 · Apple Sign-In

**Goal.** P2-FR-002, amendment P2-A-05. Without this, the app cannot be submitted.

**Do.** `expo-apple-authentication` on the client. Server-side verification through the existing
`/auth/social/{provider}` route. Identity linking on a matching verified email follows P1-FR-009's
existing rule unchanged. Remove T-21's feature flag.

**Files.** `mobile/app/(auth)/welcome.tsx`, `mobile/src/auth/apple.ts`,
`backend/app/integrations/firebase.py`, `backend/app/services/auth_service.py`,
`backend/app/routers/auth.py`, `backend/openapi.json`, `mobile/app.json`, `mobile/package.json`,
tests both sides.

**Done when.** Apple sign-in completes on a real device and creates or links a Gymak user.
Apple's private-relay email addresses are handled. The button is listed above Google per store
convention.

---

#### T-37 · Accessibility and release readiness

**Goal.** P1-NFR-08 verified rather than asserted, on the screens that now exist.

**Do.** A screen-reader pass over every screen, with the active session screen as the priority
(SRS NFR-071 names it specifically). Contrast audit against P1 §10.6 in both themes. Dynamic-type
check. Cold-start timing on a mid-range Android device (P2-NFR-08). Update `backend/README.md` and
add `mobile/README.md` so a fresh clone reaches a running app on both halves.

**Files.** Any screen needing an accessibility fix, `backend/README.md`, `mobile/README.md`,
`docs/PHASE-2-SPEC.md` (status table).

**Done when.** The full session flow is operable end to end with VoiceOver and TalkBack. Every
interactive element is at least 48 dp and labelled. Cold start is recorded with a real number.

---

## 9 · Testing and Phase 2 definition of done

Phase 1's requirements (P1 §11) all still apply. These are additional.

| # | Requirement | Gate |
|---|-------------|------|
| 1 | Backend line coverage at or above 80%, and 95% in `app/rules/` and `app/services/sync_service.py` | `pytest-cov` |
| 2 | Mobile coverage at or above 70%, and 90% in `src/db`, `src/sync`, `src/validation` | `jest --coverage` |
| 3 | The cross-tenant matrix covers every new user-scoped route and passes | Generated matrix |
| 4 | No sync batch can write another user's row, however the payload is shaped | Dedicated test |
| 5 | No health value — weight, measurements, injuries — appears in any log line | Extended log-capture test |
| 6 | `openapi.json` matches the code | Existing drift check |
| 7 | Every screen inside its CTA budget | `ctaBudget.test.ts` |
| 8 | Onboarding completes in 8 taps or fewer | Navigation test |
| 9 | The rules engine imports no I/O | Import-boundary test |
| 10 | A generated programme never breaches a safety floor | Property tests |
| 11 | Every new string exists in both `ar.json` and `en.json` | Structural test |
| 12 | Every screen renders correctly in RTL | Component tests parameterised by locale |
| 13 | **A real device logs a complete workout in airplane mode and syncs on reconnect** | Manual, recorded in the T-31 and T-34 reports |
| 14 | `ruff`, `ruff format --check`, `mypy --strict`, `tsc --noEmit` all clean | CI |

Item 13 is the phase's real acceptance test. Everything else is a proxy for it.

---

## 10 · Decisions Nabil must confirm

Four questions. The first blocks nothing but changes how §8 is read; the rest block the tasks named.

1. **Is GymTK your own work?** The Phase 1 spec names the owner as Nabil; the source SRS names
   Youssef Abed; the repositories sit under different accounts (`nebo23` and `Lordiod`). P2-ADR-08
   means nothing is copied either way, so this does not block T-15 — but if the answer is no, then
   §8's "read GymTK's implementation first" instructions should be dropped, and the tasks executed
   from the SRS alone. **Blocks nothing. Answer before T-25.**

2. **What is the target platform for first release — iOS, Android, or both?** T-36's urgency and
   T-37's device testing both depend on it. Android-first would let Apple Sign-In move later; iOS
   or both makes T-36 a hard blocker. **Blocks T-36.**

3. **Does the exercise corpus need Arabic names?** `free-exercise-db` is English only. Shipping an
   Arabic interface over an English exercise library is a visible seam, and it is the one place
   where "Arabic-first" would obviously not hold. Options: ship English names with an Arabic
   description, translate the 873 names once by hand, or defer. **Blocks T-23.**

4. **Is one active programme per user the right constraint?** §4.2 enforces it in the database.
   Some users run a strength block and a conditioning block in parallel. Relaxing it later means a
   migration and a UI that must then explain which programme a session belongs to. **Blocks T-26.**

---

## Appendix A

### A.1 Environment variables added

| Variable | Where | Purpose |
|----------|-------|---------|
| `GYMAK_EXERCISE_SEED_URL` | Backend | Overrides the corpus source. Defaults to the upstream `free-exercise-db` URL. |
| `GYMAK_SYNC_MAX_BATCH` | Backend | Batch cap, default 100. Lowering it is a load-shedding control. |
| `EXPO_PUBLIC_SYNC_INTERVAL_MS` | Mobile | Drain interval floor, default 30000. |

### A.2 Dependencies added

**Backend.** None required. `hypothesis` is added as a dev dependency for T-27's property tests.

**Mobile.**

| Package | Task | Why |
|---------|------|-----|
| `jest-expo`, `@testing-library/react-native`, `jest` | T-16 | `vitest` cannot render React Native components |
| `openapi-typescript` | T-17 | Generated API types |
| `lucide-react-native` | T-18 | P2-ADR-14 |
| `react-native-svg` | T-18 | Charts and icons |
| `victory-native` | T-35 | The two required charts |
| `expo-sqlite` | T-30 | Local database |
| `@react-native-community/netinfo` | T-31 | Connectivity detection |
| `expo-updates` | T-21 | Applying a locale change without a dialog |
| `expo-apple-authentication` | T-36 | P2-FR-002 |
| `expo-haptics` | T-34 | Rest-timer completion |

`vitest` is removed in T-16.

### A.3 Where to read GymTK, per task

Subject to decision 10.1, and always under P2-ADR-08 — read to understand, then write ours.

| Task | Read | For |
|------|------|-----|
| T-22 | `mobile/src/screens/profile/editGroups.ts`, `ProfileEditSheet.tsx` | The group-descriptor pattern |
| T-25 | `backend/src/gymtk/rules_engine/` | The seven algorithms' shapes and boundaries |
| T-27 | `backend/src/gymtk/programs/generation.py` | How split, volume, and calibration compose |
| T-29 | `backend/src/gymtk/sync/schemas.py`, `service.py` | The batch contract and its identity guard |
| T-30 | `mobile/src/db/outbox.ts`, `migrations.ts` | The outbox state machine |
| T-31 | `mobile/src/sync/engine.ts`, `backoff.ts` | Single-flight drain and backoff |
| T-34 | `mobile/src/screens/train/ActiveSession.tsx` | Set-logging interaction design |

### A.4 Glossary additions

- **Programme** — a multi-week plan of days, each holding ordered prescribed exercises. Prescribed,
  not performed.
- **Session** — one execution of one programme day by one user, holding the sets actually performed.
  The distinction between programme and session is the backbone of the data model.
- **e1RM** — estimated one-repetition maximum, from the Epley formula.
- **Hard set** — a set taken close enough to failure to drive adaptation. The unit weekly volume
  landmarks are counted in.
- **Deload** — a planned reduction in volume or intensity when fatigue criteria are met.
- **Outbox** — the client-side queue of mutations awaiting sync.
- **CTA budget** — §3.2's per-screen limit on interactive elements.

---

**End of GYMAK-P2-SPEC-001 v1.0** · Phase 2: the workout domain, offline logging, and the UX
rebuild. Nothing in §1.2 gets built. Steps 4 and 5 precede Steps 6 and 7 deliberately — the shell
is fixed before the surface area triples.
