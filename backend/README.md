
# Gymak backend

FastAPI + PostgreSQL. Firebase Auth is used only to verify Google/Facebook sign-in; it is never
a second datastore (see `docs/PHASE-1-SPEC.md`, P1-ADR-01). This README covers what exists after
T-01: the application skeleton and `/api/v1/health`. It will grow with each task in the spec's
task pack — see T-09 for the full setup/migrations/environment-variable documentation.

## Task scope rules

Each task in the spec's task pack (§12) names the exact files it may touch; touching anything
else is a failure of that task. One standing amendment, in force from T-01b onward:
**`pyproject.toml` and everything under `backend/tests/` are always in scope, for every task,
even when a task's file list doesn't name them.** Every other file still requires an explicit
name in that task's file list before it can be created, renamed, or modified.

## Prerequisites

- Python 3.12+
- Docker Desktop (or another Docker engine) running locally.

  Docker is needed for two *separate* things, and passing tests does not imply the second one
  is set up: `pytest` starts its own disposable PostgreSQL container via `testcontainers` and
  destroys it when the run ends, so a developer whose tests pass can still have no database to
  run the app against. Running `uvicorn` locally needs its own **permanent** container — set up
  in step 1 below.

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -e ".[dev]"
copy .env.example .env            # Windows; `cp` on macOS/Linux
```

Fill in `.env` with real values before running the app outside of tests — at minimum
`DATABASE_URL` and, once later tasks need them, `JWT_PRIVATE_KEY_PEM` / `JWT_PUBLIC_KEY_PEM` and
`FIREBASE_CREDENTIALS_JSON`. Nothing in `.env` is ever committed; only `.env.example` is.

## Running locally (Windows)

Do these in order the first time. Each step exists because skipping it fails in a way that
looks like a different problem than it is.

### 1. Start a permanent Postgres container

`testcontainers` (used by `pytest`) only exists for the duration of a test run — it is not a
database you can point `uvicorn` at. Create a container that stays up across sessions instead.
Port 5432 may already be taken by another local Postgres install; check first:

```bash
netstat -ano | findstr :5432
```

If that prints anything, use 5433 (and update `DATABASE_URL` accordingly) instead of 5432:

```bash
docker run -d --name gymak-db -p 5433:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=gymak postgres:16
```

In later sessions the container already exists, so just start it again:

```bash
docker start gymak-db
```

### 2. Create the two roles

**A.5 items 1 and 11 are closed as of this version**: the migrator and application roles are
split. `gymak_migrator` owns the schema and runs Alembic; `gymak_app` is DML-only and serves
the application. Neither is a PostgreSQL superuser, or any role holding `BYPASSRLS` — both
attributes silently bypass every row-level security policy, which would leave the `profiles`
and `refresh_tokens` barriers in §4.7 purely decorative while still appearing to work.
`app/database.py`'s startup assertion refuses to serve the app against either attribute, and
now also refuses a connection that can `CREATE` anything in schema `public` — the exact
capability that would let a connection be `gymak_migrator` instead of `gymak_app` by mistake.
This is also why both roles must be created separately from `POSTGRES_USER` above: that user
is a superuser by default.

There is no local `psql` client on a fresh machine, so run it inside the container instead:

```bash
docker exec gymak-db psql -U postgres -d gymak -c "CREATE ROLE gymak_migrator LOGIN PASSWORD '<choose-one>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; GRANT CONNECT, CREATE ON DATABASE gymak TO gymak_migrator; GRANT CREATE, USAGE ON SCHEMA public TO gymak_migrator;"
docker exec gymak-db psql -U postgres -d gymak -c "CREATE ROLE gymak_app LOGIN PASSWORD '<choose-a-different-one>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; GRANT CONNECT ON DATABASE gymak TO gymak_app; GRANT USAGE ON SCHEMA public TO gymak_app;"
```

Point `MIGRATOR_DATABASE_URL` in `.env` at `gymak_migrator`, and `DATABASE_URL` at `gymak_app`.
`gymak_migrator` creates — and therefore owns — every table when the migrations run, which is
why the migration still sets `FORCE ROW LEVEL SECURITY` on `profiles` and `refresh_tokens`
rather than merely `ENABLE`: Postgres exempts a table's owner from its own policies, and
`gymak_migrator`, unlike `gymak_app` today, is a role a human might reasonably connect as
directly for an ad hoc fix — `FORCE` is what stops that connection from silently bypassing RLS
too. `gymak_app` itself is never the owner of anything post-split, so `FORCE` is redundant for
it specifically; it is belt-and-braces for the owner role, not decorative.

`gymak_app`'s actual data access — `SELECT`/`INSERT`/`UPDATE`/`DELETE` on specific tables — is
granted by the migration itself (`737d03a7c353`), not by the command above, because by the
time that migration runs, `gymak_migrator` is the table owner and the only role with authority
to grant on those tables. This command only grants what the bootstrap superuser (`postgres`),
not `gymak_migrator`, has authority over: schema- and database-level access.

### 3. Run the migrations

```bash
alembic upgrade head
```

No manual `CREATE EXTENSION citext` step is needed. `CREATE EXTENSION citext` does **not**
require a superuser on Postgres 13+ — `citext` is a "trusted" extension, installable by any
non-superuser role holding `CREATE` on the *database* (confirmed empirically against a real
container; the schema-level `CREATE` alone is not enough and fails with a different error).
`gymak_migrator` holds exactly that, so `alembic upgrade head` creates the extension itself as
part of the first migration — a fresh deployment completes with zero SQL run by hand, which is
also the answer to spec §13.2 item 8: a managed host only needs to let you create two
non-superuser roles with the grants in step 2 above; it does not need to hand out superuser
access or run any DDL for you.

`tests/conftest.py` provisions both roles automatically for each test session, so steps 2–3
above are only needed for a real local or staging database.

### 4. Run the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is not optional: the default binds to `127.0.0.1` only, and no other device —
including a phone on the same network — can ever reach it, no matter what firewall rules or
IP address you use.

`GET http://localhost:8000/api/v1/health` returns `{"status": "ok", "database": "reachable"}`
once Postgres at `DATABASE_URL` is reachable.

### 5. Make it reachable from a phone

Two things are required on Windows, both in an **elevated** PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Gymak dev 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
Set-NetConnectionProfile -InterfaceAlias "<Wi-Fi adapter>" -NetworkCategory Private
```

A network categorised **Public** blocks all inbound traffic regardless of the firewall rule
above, so both are needed together — the rule alone is not sufficient. Check the current
category with:

```powershell
Get-NetConnectionProfile
```

### 6. Find the LAN IP

```bash
ipconfig
```

Use the current IPv4 address of the **Wi-Fi adapter** — ignore any VirtualBox, WSL, Hyper-V, or
VPN adapters listed alongside it; only the real Wi-Fi adapter has a Default Gateway set.

The laptop's LAN IP changes whenever the DHCP lease renews. A stale IP produces a timeout that
is indistinguishable from a broken backend, and this will bite again once
`EXPO_PUBLIC_API_BASE_URL` is set to point the mobile app at this machine. A DHCP reservation
for this machine on the router is the durable fix; re-running `ipconfig` is the workaround.

## Verify it actually runs

```bash
curl http://127.0.0.1:8000/api/v1/health          # the app starts
```

```text
open http://<LAN-IP>:8000/api/v1/health on a phone  # it is reachable
```

Both checks are required, not just one. A defect that made the app unable to start under
`uvicorn` at all (import-time `asyncio.run()` in `database.py`) survived four tasks and 196
passing tests, because the suite only ever drove the app through `httpx` inside `conftest.py`
and never started a real ASGI server (spec Appendix A.5 item 10). A green test suite proves
neither that the app starts for real nor that it's reachable from a device — only these two
manual checks do.

## Running tests

```bash
pytest
```

`tests/conftest.py` starts a disposable PostgreSQL container per test session (Docker must be
running) and points the app at it before any application code is imported, so a missing
`DATABASE_URL` — or any other required environment variable — fails the same way it would in a
real deployment. Coverage is reported on every run; the 80%/95% gates in spec §11.3 are enforced
starting T-09, once the modules they cover exist.

## Code quality gate

There is no CI config in this repository yet; this is the gate every task is expected to run
before its diff is considered done (spec rule 0.2.7), in this order:

```bash
ruff check .
ruff format --check .
mypy --strict app
pytest
```

`mypy --strict` is scoped to `app`, not the whole tree: run against `.`, it fails on `tests/`
today — 30 pre-existing annotation errors across five integration test files, tracked as A.5
item 17. The exclusion is temporary, not a decision to leave `tests/` unchecked; it is scoped
down here only so this section documents a gate that actually passes, rather than one that
looks like it covers the test suite and doesn't.

`ruff format --check` was added by A.5 item 4 — the gate previously ran `ruff check` only, so
formatting drifted between tasks and was occasionally fixed as an unrelated side effect of a
later, unrelated diff. `ruff check` and `ruff format --check` are two different tools (lint
rules vs. layout), so both are required, in either order relative to each other, but before
`mypy` and `pytest` so a formatting-only diff is never mixed into a behavioural one.

Run `ruff format .` (without `--check`) to actually reformat, rather than just report drift.
