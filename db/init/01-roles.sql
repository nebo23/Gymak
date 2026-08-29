-- The two-role split (Appendix A.5 item 1), run once when the data directory is
-- first created. Byte-for-byte the same grants as backend/README.md step 2 and
-- backend/tests/conftest.py's _provision_roles, which is the point: a developer's
-- local database, a CI container and the test fixtures must not diverge, or a
-- privilege bug reproduces in exactly one of the three.
--
-- NOSUPERUSER and NOBYPASSRLS are the two attributes that matter. Either one
-- bypasses row-level security entirely, regardless of policy, and app/database.py
-- refuses to serve the application against a connection holding them.

CREATE ROLE gymak_migrator LOGIN PASSWORD 'gymak_migrator_dev_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

-- CREATE on the DATABASE, not merely on schema public: that is specifically what
-- `CREATE EXTENSION citext` checks for a non-superuser installing a "trusted"
-- extension on Postgres 13+. Schema-level CREATE alone fails with a different
-- error ("Must have CREATE privilege on current database..."), from inside the
-- first Alembic migration, which is a confusing place to learn this.
GRANT CONNECT, CREATE ON DATABASE gymak TO gymak_migrator;
GRANT CREATE, USAGE ON SCHEMA public TO gymak_migrator;

CREATE ROLE gymak_app LOGIN PASSWORD 'gymak_app_dev_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

-- USAGE, never CREATE: gymak_app may not create anything, anywhere. Its actual
-- data access (SELECT/INSERT/UPDATE/DELETE on specific tables) is granted by
-- migration 737d03a7c353, not here -- by the time that migration runs,
-- gymak_migrator owns those tables and is the only role able to grant on them.
GRANT CONNECT ON DATABASE gymak TO gymak_app;
GRANT USAGE ON SCHEMA public TO gymak_app;
