"""Regenerate backend/openapi.json from the live FastAPI app (spec §11.3 item 6).

Building the schema (`app.openapi()`) only walks the route table -- it never runs the
lifespan handler, so it needs no live database and no Firebase credential, only the
same settings every other entry point requires (`.env` via pydantic-settings). Run
from `backend/`:

    python scripts/export_openapi.py

`tests/unit/test_openapi_contract.py` fails the suite if the committed file drifts
from what this script would write, so a route or schema change that isn't followed by
re-running this script is caught in CI, not discovered by a client against a stale spec.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

OPENAPI_PATH = _BACKEND_ROOT / "openapi.json"


def generate() -> str:
    from app.main import app

    schema = app.openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> None:
    OPENAPI_PATH.write_text(generate(), encoding="utf-8", newline="\n")
    print(f"Wrote {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
