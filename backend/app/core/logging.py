from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog

from app.config import settings

# Spec 6.5: fields a careless log statement must never be able to emit. T-22 (spec
# 10.1's security row) adds "reps" and "notes" -- workout_sets.reps and
# workout_sessions.notes (session notes, spec 5.8) -- alongside weight_kg: no current
# call site logs any of the three (see tests/security/test_no_secret_logging.py's
# module docstring), but the allowlist is what stops a future one from leaking them
# by accident, the same defence-in-depth reasoning weight_kg/height_cm/birth_date
# were already added under.
_REDACTED_KEYS = {
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
_REDACTED_VALUE = "[REDACTED]"


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def _redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _REDACTED_VALUE if key.lower() in _REDACTED_KEYS else _redact_value(val)
        for key, val in mapping.items()
    }


def redact_sensitive_fields(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """A structlog processor: an allowlist serialiser by exclusion, applied to every log line."""
    for key, value in list(event_dict.items()):
        event_dict[key] = _REDACTED_VALUE if key.lower() in _REDACTED_KEYS else _redact_value(value)
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=settings.LOG_LEVEL)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_sensitive_fields,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.LOG_LEVEL)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
