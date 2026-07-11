from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Checkpoint a SQLite WAL before backup.")
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    database = args.database.resolve(strict=True)
    with sqlite3.connect(database) as connection:
        row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != 0:
        raise RuntimeError(f"SQLite WAL checkpoint did not complete: {row!r}")
    if integrity is None or integrity[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {integrity!r}")
    print(f"Checkpointed {database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
