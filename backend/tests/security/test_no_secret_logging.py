"""§6.5, §11.1: a log-capture test asserting no password, token, reset code, or key
material appears in any log line produced by the whole suite -- the assertion is about
VALUES, not field names (structured logs legitimately emit `trace_id` and request paths
by name; that is fine and expected, per this task's own instruction).

Two independent checks:

1. `test_no_known_secret_value_appears_anywhere_in_the_captured_output` -- every line
   captured across the whole run (`tests/support.ALL_CAPTURED_OUTPUT`, filled by an
   autouse fixture in conftest.py and pinned to run last by that same file's
   `pytest_collection_modifyitems`, so "the whole suite" really means all of it) is
   scanned for a handful of
   concrete, KNOWN secret values that exist for the duration of this run: the shared
   test password literal every integration test file registers accounts with, the JWT
   private key, and the reset-code pepper (P1-ADR-07's "key material" -- if this ever
   appeared anywhere, every outstanding reset code becomes recoverable offline). None
   of these may appear anywhere in the captured output, full stop -- this is the check
   that would catch a `logger.info(f"login failed for {password}")`-shaped bug, which a
   field-name allowlist cannot: the secret is inlined into the message text, not
   carried under a key the redactor could recognise.

2. `test_every_structured_log_record_redacts_the_allowlisted_fields` -- every captured
   line that is itself a structured log record (parses as JSON with the
   `event`/`level`/`timestamp` shape structlog's `JSONRenderer` produces -- see
   app/core/logging.py) is checked field-by-field: none of §6.5's named fields
   (password, new_password, id_token, access_token, refresh_token, reset_token, code,
   weight_kg, height_cm, birth_date) may hold anything other than the redactor's own
   "[REDACTED]" sentinel, or be absent. This is the field-name-keyed half of the
   control, proven end-to-end against real captured output rather than by reading
   redact_sensitive_fields' source and trusting it.

Deliberately out of scope: app/integrations/email/console.py's raw `print()` of the
"sent" email body. P1-ADR-05's console backend exists specifically so a developer (and
this suite) can read a password-reset code off the terminal in place of a real inbox --
the code reaching that output is the feature working as designed, not a log leak, and
is a completely different channel from the structured `logger.info("email_dispatched",
...)` call two lines above it in that same function, which correctly omits the code
(see console.py). A reset-code value is therefore not in check #1's must-never-appear-
anywhere list; it is instead covered the same way every other allowlisted field is, by
check #2, which only ever inspects genuine structured log records.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config import settings
from tests.support import ALL_CAPTURED_OUTPUT

# §6.5's own list, verbatim (app/core/logging.py's _REDACTED_KEYS) -- kept as an
# independent copy rather than an import, so this test still catches a redactor that
# was edited to drop one of these keys, instead of silently checking fewer of them.
# T-22 (spec 10.1's security row: "no weight_kg, no reps, no session notes in any log
# line the suite produces") adds "reps" and "notes" -- workout_sets.reps and
# workout_sessions.notes -- matching the two new keys added to the real allowlist.
_MUST_BE_REDACTED_FIELDS = {
    "password",
    "new_password",
    "id_token",
    "access_token",
    "refresh_token",
    "reset_token",
    "code",
    "weight_kg",
    "height_cm",
    "birth_date",
    "reps",
    "notes",
}
_REDACTED_SENTINEL = "[REDACTED]"

# The literal every integration test file registers accounts with (grepped across
# tests/integration/*.py and tests/security/test_cross_tenant.py: all define the
# identical `_PASSWORD = "correct horse battery"`; test_password_reset.py adds this
# second one for its new-password step).
_KNOWN_TEST_PASSWORDS = ("correct horse battery", "a different horse battery")


def _known_key_material() -> list[str]:
    """Concrete secret values live for this run, sourced from app.config.settings
    itself -- the same object the application logs from -- rather than re-derived, so
    this stays correct if conftest.py's key-generation ever changes shape.
    """
    values = [settings.JWT_PRIVATE_KEY_PEM, settings.RESET_CODE_PEPPER]
    # A PEM's header/footer ("-----BEGIN PRIVATE KEY-----") is generic enough that
    # matching it would prove nothing; the base64 body is what must never leak.
    body_lines = [
        line
        for line in settings.JWT_PRIVATE_KEY_PEM.splitlines()
        if line and not line.startswith("-----")
    ]
    if body_lines:
        values.append(body_lines[0])
    return [value for value in values if value]


def test_no_known_secret_value_appears_anywhere_in_the_captured_output() -> None:
    assert ALL_CAPTURED_OUTPUT, (
        "no output was captured at all -- tests/conftest.py's accumulation fixture or "
        "the collection-order pin may be broken, which would make this test vacuous"
    )
    haystack = "\n".join(ALL_CAPTURED_OUTPUT)
    for secret in (*_KNOWN_TEST_PASSWORDS, *_known_key_material()):
        assert secret not in haystack, (
            f"a known secret value ({secret[:12]!r}...) appeared verbatim in captured "
            "output -- something logged (or printed) a raw value instead of going "
            "through the redaction allowlist."
        )


def _iter_structured_log_records() -> list[dict[str, Any]]:
    """Only lines that are genuinely a structlog record -- not pytest's own summary,
    not coverage's report table, not app/integrations/email/console.py's plain-text
    email dump (see this module's docstring for why that one is out of scope).
    """
    records: list[dict[str, Any]] = []
    for line in ALL_CAPTURED_OUTPUT:
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and {"event", "level", "timestamp"} <= parsed.keys():
            records.append(parsed)
    return records


def _unredacted_fields(path: str, mapping: dict[str, Any]) -> list[str]:
    failures = []
    for key, value in mapping.items():
        if key.lower() in _MUST_BE_REDACTED_FIELDS and value != _REDACTED_SENTINEL:
            failures.append(f"{path}.{key} = {value!r}")
        if isinstance(value, dict):
            failures.extend(_unredacted_fields(f"{path}.{key}", value))
    return failures


def test_every_structured_log_record_redacts_the_allowlisted_fields() -> None:
    records = _iter_structured_log_records()
    assert records, (
        "no structured log records were captured -- the accumulation mechanism in "
        "tests/conftest.py may be broken, which would make this test vacuous"
    )
    failures: list[str] = []
    for index, record in enumerate(records):
        failures.extend(_unredacted_fields(f"record[{index}]", record))
    assert not failures, "unredacted sensitive field(s) in captured log output:\n" + "\n".join(
        failures
    )


def test_the_redactor_is_actually_exercised_by_a_real_log_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A positive control for the test above, and the more important of the two.

    Grepping app/ turns up exactly three real `logger.*` call sites in the whole
    application (main.py's request_handled, email/console.py's email_dispatched,
    errors.py's unhandled_error) and none of them passes a field named `password`,
    `code`, or any other §6.5 name -- so nothing in today's application code has ever
    actually asked the redactor to redact anything. The test above proving no violation
    was *found* in captured output therefore proves nothing about whether the redactor
    *works*; it would pass identically if `redact_sensitive_fields` were deleted
    outright. This is exactly the failure mode this task's own instruction for RLS
    warns about ("a passing RLS test that only proves a permitted read succeeds proves
    nothing") applied to logging: a control must be shown to prevent something, not
    merely observed to have not (yet) been asked to.

    This drives the real structlog pipeline (`app.core.logging`, the exact one
    `main.py`'s `create_app()` configures) with every §6.5 field set to a distinguishing
    sentinel value neither of the two secret-shaped test values above would accidentally
    match, and asserts none of them survive into the rendered line.
    """
    from app.core.logging import configure_logging, get_logger

    configure_logging()
    logger = get_logger("test_no_secret_logging")
    sentinel_values = {
        field: f"UNREDACTED-{field.upper()}-SENTINEL" for field in _MUST_BE_REDACTED_FIELDS
    }
    logger.info("synthetic_redaction_probe", **sentinel_values)

    captured = capsys.readouterr()
    for field, value in sentinel_values.items():
        assert value not in captured.out, (
            f"redact_sensitive_fields failed to redact {field!r}: the raw sentinel "
            f"value leaked into the log line -- {captured.out!r}"
        )
