"""Export the frozen API contract (ADR 0020).

    uv run python -m app.api.openapi        # make openapi: writes docs/api/openapi.json

A test fails when the live schema and the committed file differ: a change to the contract is a
reviewed change to that file.
"""

import json
import sys
from pathlib import Path
from typing import Any

from app.api.main import app
from app.config import REPO_ROOT

OPENAPI_FILE = REPO_ROOT / "docs" / "api" / "openapi.json"


def document() -> str:
    spec: dict[str, Any] = app.openapi()
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    target = Path(argv[0]) if argv else OPENAPI_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document(), encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
