"""Shared typing helper for integration tests (A.5 item 17).

httpx's ``Response.json()`` is typed ``Any``, so five integration test files had each
independently re-implemented an "assert status, then parse" helper with a bare ``dict``
return annotation -- the exact ``type-arg`` / ``no-any-return`` pattern ``mypy --strict``
flags. One helper, used everywhere, means the fix lives in one place instead of five.
"""

from __future__ import annotations

from typing import Any

from httpx import Response

JSONDict = dict[str, Any]


def json_body(response: Response) -> JSONDict:
    body: JSONDict = response.json()
    return body


# §11.1's log-capture test needs every line the WHOLE suite printed, accumulated by an
# autouse fixture in conftest.py. It lives here, not in conftest.py itself, because
# pytest's own conftest-loading mechanism imports that file under the bare module name
# "conftest" (confirmed empirically: `sys.modules` holds both "conftest" and
# "tests.conftest" as two DISTINCT module objects when anything does `from
# tests.conftest import x`), so a list defined there and a list imported via
# `tests.conftest` from elsewhere are two different objects -- the fixture would
# faithfully fill one while every test read the other, which stayed empty forever.
# tests/support.py has no such special-cased loading path, so `tests.support` resolves
# to exactly one module everywhere it is imported, and this list is genuinely shared.
ALL_CAPTURED_OUTPUT: list[str] = []
