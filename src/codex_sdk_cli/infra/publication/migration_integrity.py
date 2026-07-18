from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.application.publication_config.ports import (
    ResolvedObjectBinding,
    ResolvedPublishRoute,
)
from codex_sdk_cli.domains.publication.exceptions import PublicationObjectStoreError
from codex_sdk_cli.infra.archive_publish.checkpoints import (
    ArchivePublicationModel,
    SqlAlchemyArchivePublicationCheckpointRepository,
)
from codex_sdk_cli.infra.archive_publish.repository import ArchiveIndexPublicationModel
from codex_sdk_cli.infra.publication.factory import PublicationConnectionFactory


@dataclass(frozen=True, slots=True)
class MigrationIntegrityIssue:
    code: str
    detail: dict[str, object]


@dataclass(frozen=True, slots=True)
class CurrentRemoteMembershipVerification:
    current_index_url: str | None
    remote_artifact_ids: tuple[int, ...]
    matches: bool
    issue: MigrationIntegrityIssue | None = None


@dataclass(frozen=True, slots=True)
class HistoricalLocalIndexVerification:
    checkpoint_count: int
    verified_count: int
    issues: tuple[MigrationIntegrityIssue, ...]


def validate_current_remote_membership(
    *,
    expected_latest_count: int | None,
    current_index_url: str | None,
    historical_memberships: dict[str, tuple[int, ...]],
    latest_ids: tuple[int, ...],
) -> CurrentRemoteMembershipVerification:
    if not latest_ids and expected_latest_count == 0:
        return CurrentRemoteMembershipVerification(
            current_index_url=current_index_url,
            remote_artifact_ids=(),
            matches=True,
        )
    if current_index_url is None:
        return CurrentRemoteMembershipVerification(
            current_index_url=None,
            remote_artifact_ids=(),
            matches=False,
            issue=MigrationIntegrityIssue(
                code="remote_pointer_current_index_missing",
                detail={},
            ),
        )
    remote_ids = historical_memberships.get(current_index_url)
    if remote_ids is None:
        return CurrentRemoteMembershipVerification(
            current_index_url=current_index_url,
            remote_artifact_ids=(),
            matches=False,
            issue=MigrationIntegrityIssue(
                code="remote_pointer_index_membership_unavailable",
                detail={"currentIndexUrl": current_index_url},
            ),
        )
    matches = remote_ids == latest_ids
    return CurrentRemoteMembershipVerification(
        current_index_url=current_index_url,
        remote_artifact_ids=remote_ids,
        matches=matches,
        issue=(
            None
            if matches
            else MigrationIntegrityIssue(
                code="remote_pointer_membership_differs_from_latest_selection",
                detail={
                    "currentIndexUrl": current_index_url,
                    "remoteArtifactIds": list(remote_ids),
                    "latestArtifactIds": list(latest_ids),
                },
            )
        ),
    )


async def verify_available_historical_local_indexes(
    *,
    session: AsyncSession,
    checkpoints: SqlAlchemyArchivePublicationCheckpointRepository,
    connections: PublicationConnectionFactory,
    route: ResolvedPublishRoute,
    primary: ResolvedObjectBinding,
    index_models: list[ArchiveIndexPublicationModel],
) -> HistoricalLocalIndexVerification:
    expected_ids = {item.id for item in index_models}
    publications = (
        (
            await session.scalars(
                select(ArchivePublicationModel).where(
                    ArchivePublicationModel.route_id == route.route_id,
                    ArchivePublicationModel.legacy_index_publication_id.in_(expected_ids),
                )
            )
        ).all()
        if expected_ids
        else []
    )
    by_legacy_id = {
        item.legacy_index_publication_id: item
        for item in publications
        if item.legacy_index_publication_id is not None
    }
    issues: list[MigrationIntegrityIssue] = []
    if len(by_legacy_id) != len(expected_ids):
        issues.append(
            MigrationIntegrityIssue(
                code="legacy_index_checkpoint_count_mismatch",
                detail={"expected": len(expected_ids), "actual": len(by_legacy_id)},
            )
        )
    verified_count = 0
    for index_model in index_models:
        publication = by_legacy_id.get(index_model.id)
        if publication is None or publication.status == "unavailable":
            continue
        deliveries = await checkpoints.list_publication_deliveries(publication.id)
        for binding in route.object_bindings:
            if binding.id == primary.id:
                continue
            delivery = next(
                (item for item in deliveries if item.object_binding_id == binding.id),
                None,
            )
            common: dict[str, object] = {
                "indexPublicationId": index_model.id,
                "bindingId": binding.id,
            }
            if (
                delivery is None
                or delivery.status not in {"ready", "published"}
                or delivery.index_object_key is None
                or delivery.index_sha256 is None
                or delivery.index_byte_size is None
            ):
                issues.append(
                    MigrationIntegrityIssue(
                        code="legacy_local_index_delivery_incomplete",
                        detail=common,
                    )
                )
                continue
            store = connections.object_store(binding.connection_ref)
            try:
                stat = await store.stat_object(object_key=delivery.index_object_key)
                payload = (
                    await store.get_bytes(object_key=delivery.index_object_key)
                    if stat is not None
                    else None
                )
            except (KeyError, OSError, PublicationObjectStoreError) as exc:
                issues.append(
                    MigrationIntegrityIssue(
                        code="legacy_local_index_verification_failed",
                        detail={**common, "detail": str(exc)},
                    )
                )
                continue
            if stat is None or payload is None:
                issues.append(
                    MigrationIntegrityIssue(
                        code="legacy_local_index_object_missing",
                        detail={**common, "objectKey": delivery.index_object_key},
                    )
                )
                continue
            actual_sha256 = hashlib.sha256(payload).hexdigest()
            if (
                stat.byte_size != delivery.index_byte_size
                or len(payload) != delivery.index_byte_size
                or actual_sha256 != delivery.index_sha256
            ):
                issues.append(
                    MigrationIntegrityIssue(
                        code="legacy_local_index_object_mismatch",
                        detail={
                            **common,
                            "objectKey": delivery.index_object_key,
                            "expectedSha256": delivery.index_sha256,
                            "actualSha256": actual_sha256,
                            "expectedBytes": delivery.index_byte_size,
                            "actualBytes": len(payload),
                        },
                    )
                )
                continue
            verified_count += 1
    return HistoricalLocalIndexVerification(
        checkpoint_count=len(by_legacy_id),
        verified_count=verified_count,
        issues=tuple(issues),
    )
