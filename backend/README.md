
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

### 2. Create the application role

The app will not run as a PostgreSQL superuser, or as any role holding `BYPASSRLS`. Both
silently bypass every row-level security policy, which would leave the `profiles` and
`refresh_tokens` barriers in §4.7 purely decorative while still appearing to work.
`app/database.py` queries `pg_roles` for the connected role at import time and raises if
either attribute is set, rather than letting the app come up with RLS quietly disabled. This is
also why the role must be created separately from `POSTGRES_USER` above: that user is a
superuser by default and the startup assertion refuses to serve as one.

There is no local `psql` client on a fresh machine, so run it inside the container instead:

```bash
docker exec gymak-db psql -U postgres -d gymak -c "CREATE ROLE gymak_app LOGIN PASSWORD '<choose-one>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; GRANT ALL PRIVILEGES ON DATABASE gymak TO gymak_app; GRANT ALL PRIVILEGES ON SCHEMA public TO gymak_app;"
```

Point `DATABASE_URL` in `.env` at this role, not at `postgres`. One role both migrates and
serves the app, so it **owns** these tables — which is why the migration sets
`FORCE ROW LEVEL SECURITY` and not merely `ENABLE`: Postgres exempts a table's owner from its
own policies, and without `FORCE` every policy is a no-op for exactly this role.

### 3. Create the `citext` extension

`CREATE EXTENSION citext` requires a superuser, and `gymak_app` cannot create extensions —
so it must be created by the `postgres` role, once, before `alembic upgrade head` runs:

```bash
docker exec gymak-db psql -U postgres -d gymak -c "CREATE EXTENSION IF NOT EXISTS citext;"
```

This manual step only exists because the migrator and application roles are not yet split
(spec Appendix A.5 items 1 and 11 — item 1 is the role split, item 11 is this exact gap, tracked
as High severity, owned by T-09). Once that split lands, `gymak_migrator` can own extension
creation and this step goes away.

### 4. Run the migrations

```bash
alembic upgrade head
```

`tests/conftest.py` provisions an equivalent role and extension automatically for each test
session, so steps 2–4 above are only needed for a real local or staging database.

### 5. Run the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is not optional: the default binds to `127.0.0.1` only, and no other device —
including a phone on the same network — can ever reach it, no matter what firewall rules or
IP address you use.

`GET http://localhost:8000/api/v1/health` returns `{"status": "ok", "database": "reachable"}`
once Postgres at `DATABASE_URL` is reachable.

### 6. Make it reachable from a phone

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

### 7. Find the LAN IP

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
