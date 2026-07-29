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
- Docker Desktop (or another Docker engine) running locally — the test suite starts a real
  PostgreSQL container via `testcontainers`; nothing is mocked or run against SQLite.

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

## Running the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`GET http://localhost:8000/api/v1/health` returns `{"status": "ok", "database": "reachable"}`
once Postgres at `DATABASE_URL` is reachable.

## Running tests

```bash
pytest
```

`tests/conftest.py` starts a disposable PostgreSQL container per test session (Docker must be
running) and points the app at it before any application code is imported, so a missing
`DATABASE_URL` — or any other required environment variable — fails the same way it would in a
real deployment. Coverage is reported on every run; the 80%/95% gates in spec §11.3 are enforced
starting T-09, once the modules they cover exist.
