# syntax=docker/dockerfile:1

# Gymak backend. Two stages: the first resolves and installs dependencies, the
# second carries only what is needed to run. Splitting them keeps the build
# toolchain (gcc, headers) out of the shipped image, which both shrinks it and
# removes a compiler from anything an attacker reaches.

# Python 3.12 to match pyproject's `requires-python = ">=3.12"` and mypy's
# `python_version = "3.12"` exactly. Pinned to the minor, not `:3-slim`, so a
# future 3.13 base cannot silently change behaviour the type checker was
# configured against.
FROM python:3.12-slim AS builder

# Bytecode in the image would be written for a path layout the final stage may
# not share; PYTHONUNBUFFERED keeps container logs in real order.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# argon2-cffi and asyncpg both build native extensions; cryptography needs a
# Rust-free wheel path but still wants libffi headers when one is unavailable
# for the platform. Installed here and NOT carried into the final stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Dependency metadata first, on its own layer: `docker build` reuses it on every
# rebuild where only application code changed, which is nearly every rebuild.
COPY pyproject.toml ./
# The package itself needs its source present to build a wheel (hatchling reads
# `packages = ["app"]`), so app/ comes before the install rather than after.
COPY app ./app

# --prefix, not a virtualenv: a venv records absolute paths and its own
# interpreter, which do not survive being copied between stages. A prefix tree
# is relocatable, and PYTHONPATH in the final stage points at it.
RUN pip install --prefix=/install .


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/install/lib/python3.12/site-packages \
    PATH=/install/bin:$PATH

# libpq is NOT installed: asyncpg speaks the wire protocol directly and does not
# link against libpq, unlike psycopg2. Adding it would be cargo-culted weight.
# tzdata likewise is not an OS package here -- pyproject already depends on the
# `tzdata` PyPI distribution precisely because slim images ship no system zone
# database (see its own comment there), so `ZoneInfo(profile.timezone)` works
# without apt.

# A non-root user with no login shell. The app never writes to its own tree, so
# nothing needs to be owned by it beyond read access.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 gymak

WORKDIR /app

COPY --from=builder /install /install
COPY --chown=gymak:gymak app ./app
COPY --chown=gymak:gymak alembic ./alembic
COPY --chown=gymak:gymak alembic.ini ./
COPY --chown=gymak:gymak scripts ./scripts

USER gymak

EXPOSE 8000

# HEALTHCHECK hits GET /api/v1/health -- the one route that answers without a
# token. `python -c` rather than curl: curl is not in the slim image, and adding
# it for a healthcheck is a package more than this needs.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

# No --reload: that is a development flag and it watches the filesystem, which
# costs CPU in a container that never changes on disk. Migrations are NOT run
# here -- `alembic upgrade head` connects as gymak_migrator and the application
# connects as gymak_app (A.5 item 1); baking the upgrade into the app's own
# entrypoint would either hand the app the migrator's credentials or fail.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
