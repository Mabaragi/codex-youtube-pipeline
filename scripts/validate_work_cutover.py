from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from codex_sdk_cli.infra.database.work_cutover import validate_work_cutover


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a work-model candidate DB.")
    parser.add_argument("source", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    result = validate_work_cutover(
        args.source.resolve(strict=True),
        args.candidate.resolve(strict=True),
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
