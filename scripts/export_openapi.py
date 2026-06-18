from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "ops-ui" / "openapi" / "codex-api.openapi.json"


def main() -> None:
    args = _parse_args()
    schema = _openapi_schema()
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path

    if args.check:
        if not output_path.is_file():
            raise SystemExit(f"{output_path.relative_to(REPO_ROOT)} is missing.")
        current = output_path.read_text(encoding="utf-8")
        if current != rendered:
            raise SystemExit(
                f"{output_path.relative_to(REPO_ROOT)} is stale. "
                "Run `uv run python scripts/export_openapi.py`."
            )
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export FastAPI OpenAPI schema JSON.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH.relative_to(REPO_ROOT)),
        help="Output path relative to the repository root.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check that the committed OpenAPI schema is current.",
    )
    return parser.parse_args()


def _openapi_schema() -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from codex_sdk_cli.api.main import app

    return app.openapi()


if __name__ == "__main__":
    main()
