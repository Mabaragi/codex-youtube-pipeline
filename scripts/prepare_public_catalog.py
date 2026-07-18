from __future__ import annotations

import argparse
import asyncio

from codex_sdk_cli.infra.publication.catalog_database.session import (
    ensure_catalog_database,
)
from codex_sdk_cli.infra.publication.factory import PublicationConnectionFactory
from codex_sdk_cli.settings import CliSettings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the dedicated public catalog PostgreSQL database when absent."
    )
    parser.add_argument("--connection-ref", default="local-public-catalog")
    arguments = parser.parse_args()
    created = asyncio.run(_prepare(arguments.connection_ref))
    print("created" if created else "already-present-or-not-required")


async def _prepare(connection_ref: str) -> bool:
    factory = PublicationConnectionFactory.from_settings(CliSettings())
    try:
        return await ensure_catalog_database(factory.sql_catalog_database_url(connection_ref))
    finally:
        await factory.aclose()


if __name__ == "__main__":
    main()
