"""§11.3 item 6: the committed OpenAPI document must match the code.

`scripts/export_openapi.py` is the single source of truth for how the document is
generated; this test re-runs exactly that logic and fails if `backend/openapi.json`
does not match byte-for-byte, so a route or schema change that isn't followed by
re-running the export script is caught here rather than by a client against a stale
spec.
"""

from __future__ import annotations

from pathlib import Path

from scripts.export_openapi import OPENAPI_PATH, generate


def test_committed_openapi_json_matches_the_generated_schema() -> None:
    committed = Path(OPENAPI_PATH).read_text(encoding="utf-8")
    assert committed == generate(), (
        "backend/openapi.json is out of date -- run `python scripts/export_openapi.py` "
        "from backend/ and commit the result."
    )
