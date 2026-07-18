from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from codex_sdk_cli.infra.database.base import NAMING_CONVENTION


class CatalogBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
