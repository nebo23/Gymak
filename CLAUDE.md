# Gymak

Phase 1 is complete (T-01 … T-14). **Phase 2 is in progress.**

Read `docs/PHASE-2-SPEC.md` before any work. It is the single source of truth for Phase 2 and
lists its own task pack in §8. Execute one task at a time; touch only the files that task names.

`docs/PHASE-1-SPEC.md` remains the source of truth for everything Phase 1 covers — auth, session
management, profile capture, the error catalogue, and the design tokens in its §10. Where the two
disagree, `PHASE-2-SPEC.md` §0.4 names which one wins and why; nothing else in Phase 1's spec is
overridden.

Never build anything from `PHASE-2-SPEC.md` §1.2's out-of-scope list.

Before any UI work, read `PHASE-2-SPEC.md` §3 — the CTA budget in §3.2 is enforced by a test, not
a guideline. Never copy a file from the GymTK repository; see P2-ADR-08.
