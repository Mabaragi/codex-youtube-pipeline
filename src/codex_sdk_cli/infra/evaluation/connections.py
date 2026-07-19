from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy.engine import make_url


class EvaluationDatabaseConnection(BaseModel):
    kind: str = Field(pattern=r"^sql_database$")
    database_url: SecretStr = Field(alias="databaseUrl")
    echo: bool = False

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def validated_url(self) -> str:
        value = self.database_url.get_secret_value()
        url = make_url(value)
        if url.get_backend_name() != "postgresql":
            raise ValueError("Evaluation database URL must use PostgreSQL.")
        if url.database != "codex_model_evaluations":
            raise ValueError("Evaluation database URL must target 'codex_model_evaluations'.")
        return value


class EvaluationObjectConnection(BaseModel):
    kind: str = Field(pattern=r"^s3_compatible_object$")
    endpoint: str = Field(min_length=1)
    access_key: SecretStr = Field(alias="accessKey")
    secret_key: SecretStr = Field(alias="secretKey")
    bucket: str = Field(pattern=r"^model-evaluations$")
    secure: bool = False
    region: str = "auto"

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvaluationConnections(BaseModel):
    version: int = Field(default=1, ge=1, le=1)
    database: EvaluationDatabaseConnection
    object_store: EvaluationObjectConnection = Field(alias="objectStore")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("Unsupported evaluation connection registry version.")
        return value

    @classmethod
    def from_file(cls, path: Path) -> EvaluationConnections:
        if not path.is_file():
            raise ValueError(f"Evaluation connection registry not found: {path}")
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
