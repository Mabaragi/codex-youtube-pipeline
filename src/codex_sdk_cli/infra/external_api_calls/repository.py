from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import override

from codex_sdk_cli.domains.external_api_calls.exceptions import (
    ExternalApiCallPersistenceError,
)
from codex_sdk_cli.domains.external_api_calls.ports import (
    ExternalApiCallCreate,
    ExternalApiCallRecord,
    ExternalApiCallRepositoryPort,
    JsonObject,
    ValidationStatus,
)
from codex_sdk_cli.infra.database.base import Base


class ExternalApiCallModel(Base):
    __tablename__ = "external_api_calls"
    __table_args__ = (
        CheckConstraint(
            "duration_ms >= 0",
            name="external_api_calls_duration_ms_non_negative",
        ),
        CheckConstraint(
            "quota_cost IS NULL OR quota_cost >= 0",
            name="external_api_calls_quota_cost_non_negative",
        ),
        CheckConstraint(
            "response_status_code IS NULL OR response_status_code >= 100",
            name="external_api_calls_status_code_min",
        ),
        CheckConstraint(
            "validation_status IN ('not_validated', 'valid', 'invalid')",
            name="external_api_calls_validation_status_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    operation: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    request_method: Mapped[str] = mapped_column(String(16), nullable=False)
    request_url: Mapped[str] = mapped_column(Text, nullable=False)
    request_params: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    request_body: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    response_storage_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response_storage_object_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SqlAlchemyExternalApiCallRepository(ExternalApiCallRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_external_api_call(
        self,
        record: ExternalApiCallCreate,
    ) -> ExternalApiCallRecord:
        try:
            model = ExternalApiCallModel(
                provider=record.provider,
                operation=record.operation,
                request_method=record.request_method,
                request_url=record.request_url,
                request_params=record.request_params,
                request_body=record.request_body,
                response_status_code=record.response_status_code,
                response_headers=record.response_headers,
                response_storage_bucket=record.response_storage_bucket,
                response_storage_object_name=record.response_storage_object_name,
                response_storage_uri=record.response_storage_uri,
                response_sha256=record.response_sha256,
                schema_name=record.schema_name,
                schema_version=record.schema_version,
                validation_status=record.validation_status,
                validation_error=record.validation_error,
                duration_ms=record.duration_ms,
                quota_cost=record.quota_cost,
            )
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise ExternalApiCallPersistenceError(
                "External API call metadata persistence failed."
            ) from exc


def _record(model: ExternalApiCallModel) -> ExternalApiCallRecord:
    return ExternalApiCallRecord(
        id=model.id,
        provider=model.provider,
        operation=model.operation,
        request_method=model.request_method,
        request_url=model.request_url,
        request_params=model.request_params,
        request_body=model.request_body,
        response_status_code=model.response_status_code,
        response_headers=model.response_headers,
        response_storage_bucket=model.response_storage_bucket,
        response_storage_object_name=model.response_storage_object_name,
        response_storage_uri=model.response_storage_uri,
        response_sha256=model.response_sha256,
        schema_name=model.schema_name,
        schema_version=model.schema_version,
        validation_status=_validation_status(model.validation_status),
        validation_error=model.validation_error,
        duration_ms=model.duration_ms,
        quota_cost=model.quota_cost,
        created_at=model.created_at,
    )


def _validation_status(value: str) -> ValidationStatus:
    if value == "valid":
        return "valid"
    if value == "invalid":
        return "invalid"
    return "not_validated"
