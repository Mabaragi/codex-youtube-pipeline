from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_sdk_cli.infra.publication.connections import (
    PublicationConnectionRegistry,
)
from codex_sdk_cli.settings import CliSettings


@dataclass(frozen=True, slots=True)
class LegacyConnectionImportResult:
    path: Path
    added: tuple[str, ...]
    retained: tuple[str, ...]
    unavailable: tuple[str, ...]
    written: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "added": list(self.added),
            "retained": list(self.retained),
            "unavailable": list(self.unavailable),
            "written": self.written,
        }


def import_legacy_publication_connections(
    settings: CliSettings,
    *,
    path: Path,
    apply: bool,
) -> LegacyConnectionImportResult:
    """Merge legacy publish settings into the private connection registry once.

    Existing connection entries always win. The function intentionally knows the
    old vendor-specific setting names so the rest of the publication domain does
    not have to.
    """
    payload = _existing_registry_payload(path)
    connections = payload.setdefault("connections", {})
    if not isinstance(connections, dict):
        raise ValueError("Publication registry 'connections' must be an object.")

    candidates, unavailable = _legacy_candidates(settings)
    added: list[str] = []
    retained: list[str] = []
    for connection_ref, connection in candidates.items():
        if connection_ref in connections:
            retained.append(connection_ref)
            continue
        connections[connection_ref] = connection
        added.append(connection_ref)

    PublicationConnectionRegistry.model_validate(payload)
    written = bool(apply and added)
    if written:
        _atomic_write_json(path, payload)
    return LegacyConnectionImportResult(
        path=path,
        added=tuple(sorted(added)),
        retained=tuple(sorted(retained)),
        unavailable=tuple(sorted(unavailable)),
        written=written,
    )


def _existing_registry_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "connections": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Publication connection registry is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("Publication connection registry must be a JSON object.")
    return value


def _legacy_candidates(
    settings: CliSettings,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    candidates: dict[str, dict[str, object]] = {}
    unavailable: list[str] = []
    production = _legacy_object_connection(
        endpoint=settings.archive_publish_r2_endpoint,
        access_key=(
            settings.archive_publish_r2_access_key.get_secret_value()
            if settings.archive_publish_r2_access_key is not None
            else None
        ),
        secret_key=(
            settings.archive_publish_r2_secret_key.get_secret_value()
            if settings.archive_publish_r2_secret_key is not None
            else None
        ),
        bucket=settings.archive_publish_r2_bucket,
        secure=settings.archive_publish_r2_secure,
        public_base_url=settings.archive_publish_public_base_url,
    )
    if production is None:
        unavailable.append("legacy-remote-object")
    else:
        candidates["legacy-remote-object"] = production

    development_access_key = (
        settings.archive_publish_dev_r2_access_key or settings.archive_publish_r2_access_key
    )
    development_secret_key = (
        settings.archive_publish_dev_r2_secret_key or settings.archive_publish_r2_secret_key
    )
    development = _legacy_object_connection(
        endpoint=(settings.archive_publish_dev_r2_endpoint or settings.archive_publish_r2_endpoint),
        access_key=(
            development_access_key.get_secret_value()
            if development_access_key is not None
            else None
        ),
        secret_key=(
            development_secret_key.get_secret_value()
            if development_secret_key is not None
            else None
        ),
        bucket=settings.archive_publish_dev_r2_bucket,
        secure=(
            settings.archive_publish_dev_r2_secure
            if settings.archive_publish_dev_r2_secure is not None
            else settings.archive_publish_r2_secure
        ),
        public_base_url=settings.archive_publish_dev_public_base_url,
    )
    if development is not None:
        candidates["legacy-dev-remote-object"] = development

    if settings.archive_public_catalog_sync_url:
        catalog: dict[str, object] = {
            "kind": "http_catalog",
            "url": settings.archive_public_catalog_sync_url,
            "timeoutSeconds": settings.archive_public_catalog_sync_timeout_seconds,
        }
        if settings.archive_public_catalog_sync_token is not None:
            catalog["token"] = settings.archive_public_catalog_sync_token.get_secret_value()
        candidates["legacy-remote-catalog"] = catalog
    else:
        unavailable.append("legacy-remote-catalog")
    return candidates, unavailable


def _legacy_object_connection(
    *,
    endpoint: str | None,
    access_key: str | None,
    secret_key: str | None,
    bucket: str | None,
    secure: bool,
    public_base_url: str | None,
) -> dict[str, object] | None:
    values = (endpoint, access_key, secret_key, bucket, public_base_url)
    if not all(values):
        return None
    return {
        "kind": "s3_compatible_object",
        "endpoint": endpoint,
        "accessKey": access_key,
        "secretKey": secret_key,
        "bucket": bucket,
        "secure": secure,
        "region": "auto",
        "publicBaseUrl": public_base_url,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
