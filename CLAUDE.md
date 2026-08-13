# Gymak

**Phase 2 in progress.** Read `docs/PHASE-2-SPEC.md` before any work — it is the single
source of truth for this phase. `docs/PHASE-1-SPEC.md` stays authoritative for everything
Phase 1 covers: auth, tokens, the profile, the error envelope, the design tokens. If a
document and your instinct disagree, the document wins.

- Execute **one task at a time** from §12, and touch **only** the files that task names.
  Standing exception: `backend/pyproject.toml`, `backend/tests/**`, `mobile/src/i18n/*.json`,
  `mobile/app/(app)/_dev-gallery.tsx`.
- Never build anything from §1.2 out-of-scope — not a stub, not a TODO. No nutrition, no
  calorie or TDEE display, **no LLM call of any kind**.
- No dependency outside Phase 1 Appendix A.2 plus Phase 2 §A.2 without asking.
- Missing detail? Ask one specific question and wait. Do not invent a column, an endpoint,
  an exercise, or a library.
- Say what the current code actually does before you change it.
- Backend gate, every task: `ruff check` · `ruff format --check` · `mypy --strict .` · `pytest`.
  Mobile gate: `npm run typecheck` · `npm run test`. Paste real output with exit codes.
- After a backend task, start uvicorn and reach the endpoint from the phone before
  committing. A green suite is not evidence that the application runs.
- Mobile rules that are never negotiable: no hex literal in a component, no bare
  user-visible string, `start`/`end` never `left`/`right`, every touchable ≥ 48 dp with a
  translated `accessibilityLabel`, and `ar.json`/`en.json` keep identical key sets.