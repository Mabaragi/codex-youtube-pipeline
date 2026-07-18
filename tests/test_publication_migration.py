from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner

from codex_sdk_cli.cli import main
from codex_sdk_cli.domains.archive_publish.ports import (
    ArchivePublicCatalogVideoRow,
    ArchiveVideoArtifactRecord,
)
from codex_sdk_cli.domains.publication.ports import (
    PublicationCatalogContext,
    PublicationCatalogRowVerification,
    PublicationObjectLocation,
    PublicationObjectStat,
)
from codex_sdk_cli.infra.archive_publish.repository import (
    ArchiveIndexPublicationModel,
    ArchiveVideoArtifactModel,
)
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.publication.factory import PublicationConnectionFactory
from codex_sdk_cli.infra.publication.legacy_connections import (
    import_legacy_publication_connections,
)
from codex_sdk_cli.infra.publication.migration import (
    PublicationDataMigrator,
    PublicationMigrationMode,
    PublicationMigrationRequest,
    PublicationMigrationSourceError,
    _ensure_immutable_object,
    _index_membership,
    _legacy_artifact_build_key,
    _read_legacy_source_object,
)
from codex_sdk_cli.infra.publication.projection import build_destination_index
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.videos.repository import VideoModel
from codex_sdk_cli.settings import CliSettings


def test_legacy_connection_import_is_previewable_and_idempotent(tmp_path: Path) -> None:
    registry_path = tmp_path / "publish-connections.json"
    settings = CliSettings(
        archive_publish_r2_endpoint="https://objects.example.test",
        archive_publish_r2_access_key="ACCESS",
        archive_publish_r2_secret_key="SECRET",
        archive_publish_r2_bucket="archive",
        archive_publish_public_base_url="https://cdn.example.test",
        archive_publish_dev_r2_bucket="archive-dev",
        archive_publish_dev_public_base_url="https://dev-cdn.example.test",
        archive_public_catalog_sync_url="https://catalog.example.test/upsert",
        archive_public_catalog_sync_token="TOKEN",
    )

    preview = import_legacy_publication_connections(
        settings,
        path=registry_path,
        apply=False,
    )
    assert preview.added == (
        "legacy-dev-remote-object",
        "legacy-remote-catalog",
        "legacy-remote-object",
    )
    assert preview.written is False
    assert not registry_path.exists()

    applied = import_legacy_publication_connections(
        settings,
        path=registry_path,
        apply=True,
    )
    repeated = import_legacy_publication_connections(
        settings,
        path=registry_path,
        apply=True,
    )

    assert applied.written is True
    assert repeated.written is False
    assert repeated.retained == (
        "legacy-dev-remote-object",
        "legacy-remote-catalog",
        "legacy-remote-object",
    )
    payload = registry_path.read_text(encoding="utf-8")
    assert "ACCESS" in payload
    assert "SECRET" in payload
    assert "TOKEN" in payload


def test_publication_migration_cli_writes_dry_run_report_without_default_runner(
    tmp_path: Path,
) -> None:
    requests: list[PublicationMigrationRequest] = []

    async def runner(
        settings: CliSettings,
        request: PublicationMigrationRequest,
    ) -> dict[str, object]:
        del settings
        requests.append(request)
        return {"version": 1, "mode": "dry-run", "mutated": False, "ok": True}

    result = CliRunner().invoke(
        main,
        [
            "publication",
            "migrate",
            "--mode",
            "dry-run",
            "--report-dir",
            str(tmp_path),
        ],
        obj={"publication_migration_runner": runner},
    )

    assert result.exit_code == 0, result.output
    assert len(requests) == 1
    assert requests[0].mode == "dry-run"
    assert requests[0].mutates is False
    assert requests[0].expected_history_count == 416
    reports = list(tmp_path.glob("publication-migration-*-dry-run.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["ok"] is True


def test_immutable_copy_reuses_matching_bytes_and_rejects_mismatch() -> None:
    store = MemoryObjectStore()

    first = asyncio.run(
        _ensure_immutable_object(store, object_key="artifact.json", payload=b"good")
    )
    second = asyncio.run(
        _ensure_immutable_object(store, object_key="artifact.json", payload=b"good")
    )

    assert first is True
    assert second is False
    assert store.put_count == 1
    try:
        asyncio.run(
            _ensure_immutable_object(
                store,
                object_key="artifact.json",
                payload=b"different",
            )
        )
    except ValueError as exc:
        assert "size mismatch" in str(exc)
    else:
        raise AssertionError("immutable mismatch must fail")


def test_legacy_source_only_treats_explicit_missing_stat_as_absent() -> None:
    missing = MemoryObjectStore()
    assert (
        asyncio.run(
            _read_legacy_source_object(
                missing,
                object_key="missing.json",
                object_kind="artifact",
            )
        )
        is None
    )

    stat_failure = FaultingMemoryObjectStore(fail_stat=True)
    with pytest.raises(PublicationMigrationSourceError, match="stat failed"):
        asyncio.run(
            _read_legacy_source_object(
                stat_failure,
                object_key="artifact.json",
                object_kind="artifact",
            )
        )

    read_failure = FaultingMemoryObjectStore(fail_read=True)
    read_failure.objects["artifact.json"] = b"{}"
    with pytest.raises(PublicationMigrationSourceError, match="read failed"):
        asyncio.run(
            _read_legacy_source_object(
                read_failure,
                object_key="artifact.json",
                object_kind="artifact",
            )
        )


def test_legacy_build_key_is_unique_when_artifact_content_is_deduplicated() -> None:
    sha256 = "a" * 64

    assert _legacy_artifact_build_key(1, sha256) != _legacy_artifact_build_key(2, sha256)


def test_index_membership_and_local_projection_are_deterministic() -> None:
    artifact = _artifact()
    index = {
        "videos": [
            {
                "timelineVariants": [
                    {"url": artifact.public_url},
                    {"url": "https://example.test/orphan.json"},
                ]
            }
        ]
    }
    artifact_ids, missing = _index_membership(
        index,
        artifacts_by_url={artifact.public_url: artifact.id},
    )
    generated_at = "2026-07-18T01:30:00Z"
    first = build_destination_index(
        artifacts=((artifact, {"youtubeVideoId": "yt-1", "video": {}}, "local.json"),),
        key_prefix="archive",
        public_url=lambda key: f"https://local.test/{key}",
        environment="prod",
        schema_version=1,
        version="v1",
        generated_at=generated_at,
    )
    second = build_destination_index(
        artifacts=((artifact, {"youtubeVideoId": "yt-1", "video": {}}, "local.json"),),
        key_prefix="archive",
        public_url=lambda key: f"https://local.test/{key}",
        environment="prod",
        schema_version=1,
        version="v1",
        generated_at=generated_at,
    )

    assert artifact_ids == (artifact.id,)
    assert missing == ("https://example.test/orphan.json",)
    assert first.payload_bytes == second.payload_bytes
    assert first.pointer_payload_bytes == second.pointer_payload_bytes


def test_dry_run_with_empty_migrated_database_is_read_only(
    migrated_database_path: Path,
) -> None:
    stores = {
        "legacy-remote-object": MemoryObjectStore(),
        "local-public-object": MemoryObjectStore(),
        "local-artifact-store": MemoryObjectStore(),
        "local-publication-staging": MemoryObjectStore(),
    }
    stores["legacy-remote-object"].objects["archive/channels/prod.json"] = (
        b'{"currentIndexUrl":"https://remote.test/archive/index.json"}'
    )
    factory = cast(PublicationConnectionFactory, MemoryConnectionFactory(stores))
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"

    report = asyncio.run(_dry_run_empty_database(database_url, factory))

    assert report["ok"] is True
    assert report["mutated"] is False
    artifact_report = cast(dict[str, object], report["artifacts"])
    assert artifact_report["total"] == 0
    assert stores["local-artifact-store"].put_count == 0
    assert stores["local-publication-staging"].put_count == 0
    assert stores["local-public-object"].put_count == 0


@pytest.mark.parametrize("mode", ["apply", "resume", "verify"])
def test_completion_modes_require_source_manifest(
    migrated_database_path: Path,
    mode: PublicationMigrationMode,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    factory = cast(PublicationConnectionFactory, MemoryConnectionFactory({}))

    with pytest.raises(ValueError, match="--source-manifest is required"):
        asyncio.run(_run_without_manifest(database_url, factory, mode))


async def _run_without_manifest(
    database_url: str,
    factory: PublicationConnectionFactory,
    mode: PublicationMigrationMode,
) -> None:
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await PublicationDataMigrator(
                session=session,
                connections=factory,
                artifact_store_ref="local-artifact-store",
                staging_store_ref="local-publication-staging",
            ).run(PublicationMigrationRequest(mode=mode))
    finally:
        await engine.dispose()


async def _dry_run_empty_database(
    database_url: str,
    factory: PublicationConnectionFactory,
) -> dict[str, object]:
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            return await PublicationDataMigrator(
                session=session,
                connections=factory,
                artifact_store_ref="local-artifact-store",
                staging_store_ref="local-publication-staging",
            ).run(
                PublicationMigrationRequest(
                    mode="dry-run",
                    expected_artifact_count=0,
                    expected_ready_count=0,
                    expected_unavailable_count=0,
                    expected_latest_count=0,
                    expected_history_count=None,
                )
            )
    finally:
        await engine.dispose()


def test_apply_and_resume_copy_once_and_reuse_checkpoints(
    migrated_database_path: Path,
) -> None:
    stores = {
        "legacy-remote-object": MemoryObjectStore("remote"),
        "local-public-object": MemoryObjectStore("local-public"),
        "local-artifact-store": MemoryObjectStore("canonical"),
        "local-publication-staging": MemoryObjectStore("staging"),
    }
    catalog = MemoryCatalogPublisher()
    factory = cast(
        PublicationConnectionFactory,
        MemoryConnectionFactory(
            stores,
            catalogs={"local-public-catalog": catalog},
        ),
    )
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    manifest_path = migrated_database_path.with_suffix(".manifest.json")

    dry_report, apply_report, resume_report, verify_report = asyncio.run(
        _seed_apply_and_resume(database_url, factory, stores, catalog, manifest_path)
    )

    assert dry_report["ok"] is True, json.dumps(dry_report, indent=2)
    assert apply_report["ok"] is True, json.dumps(apply_report, indent=2)
    assert resume_report["ok"] is True, json.dumps(resume_report, indent=2)
    assert verify_report["ok"] is True, json.dumps(verify_report, indent=2)
    assert len(catalog.rows) == 1
    assert set(catalog.rows) == {2}
    assert catalog.upsert_count == 2
    assert stores["local-artifact-store"].put_count == 2
    assert stores["local-public-object"].put_count == 5
    assert stores["local-publication-staging"].put_count == 7
    for report in (dry_report, apply_report, resume_report, verify_report):
        latest_report = cast(dict[str, object], report["latest"])
        assert latest_report["artifactIds"] == [2]
    for report in (apply_report, resume_report, verify_report):
        catalog_report = cast(dict[str, object], report["catalog"])
        assert catalog_report["remoteCheckpointed"] == 2
    apply_catalog_report = cast(dict[str, object], apply_report["catalog"])
    assert apply_catalog_report["remoteImported"] == 1
    assert apply_catalog_report["localReplayed"] == 1
    resume_catalog_report = cast(dict[str, object], resume_report["catalog"])
    assert resume_catalog_report["localReplayed"] == 1
    verify_catalog_report = cast(dict[str, object], verify_report["catalog"])
    assert verify_catalog_report["localRowsFound"] == 1
    assert verify_catalog_report["localRowsMatched"] == 1
    manifest_report = cast(dict[str, object], verify_report["sourceManifest"])
    assert manifest_report["historyIndexCount"] == 2
    assert manifest_report["historyPreservedCount"] == 2
    assert manifest_report["orphanIndexCount"] == 1
    assert manifest_report["orphanPointerCount"] == 1
    assert manifest_report["orphanTimelineCount"] == 1
    assert manifest_report["complete"] is True


def test_current_remote_membership_mismatch_blocks_local_pointer_write(
    migrated_database_path: Path,
) -> None:
    stores = {
        "legacy-remote-object": MemoryObjectStore("remote"),
        "local-public-object": MemoryObjectStore("local-public"),
        "local-artifact-store": MemoryObjectStore("canonical"),
        "local-publication-staging": MemoryObjectStore("staging"),
    }
    catalog = MemoryCatalogPublisher()
    factory = cast(
        PublicationConnectionFactory,
        MemoryConnectionFactory(stores, catalogs={"local-public-catalog": catalog}),
    )
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    manifest_path = migrated_database_path.with_suffix(".manifest.json")

    reports = asyncio.run(
        _seed_apply_and_resume(
            database_url,
            factory,
            stores,
            catalog,
            manifest_path,
            current_membership_artifact_id=1,
            remove_catalog_row_before_resume=False,
        )
    )

    for report in reports:
        blockers = cast(list[dict[str, object]], report["blockers"])
        assert "remote_pointer_membership_differs_from_latest_selection" in {
            str(item["code"]) for item in blockers
        }
    assert "archive/channels/prod.json" not in stores["local-public-object"].objects


def test_verify_blocks_corrupt_available_historical_local_index(
    migrated_database_path: Path,
) -> None:
    stores = {
        "legacy-remote-object": MemoryObjectStore("remote"),
        "local-public-object": MemoryObjectStore("local-public"),
        "local-artifact-store": MemoryObjectStore("canonical"),
        "local-publication-staging": MemoryObjectStore("staging"),
    }
    catalog = MemoryCatalogPublisher()
    factory = cast(
        PublicationConnectionFactory,
        MemoryConnectionFactory(stores, catalogs={"local-public-catalog": catalog}),
    )
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    manifest_path = migrated_database_path.with_suffix(".manifest.json")

    _, apply_report, resume_report, verify_report = asyncio.run(
        _seed_apply_and_resume(
            database_url,
            factory,
            stores,
            catalog,
            manifest_path,
            corrupt_history_before_verify=True,
        )
    )

    assert apply_report["ok"] is True
    assert resume_report["ok"] is True
    assert verify_report["ok"] is False
    blockers = cast(list[dict[str, object]], verify_report["blockers"])
    assert "legacy_local_index_object_mismatch" in {str(item["code"]) for item in blockers}


async def _seed_apply_and_resume(
    database_url: str,
    factory: PublicationConnectionFactory,
    stores: dict[str, MemoryObjectStore],
    catalog: MemoryCatalogPublisher,
    manifest_path: Path,
    *,
    current_membership_artifact_id: int = 2,
    remove_catalog_row_before_resume: bool = True,
    corrupt_history_before_verify: bool = False,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    timeline_payload = _timeline_payload()
    timeline_bytes = _json_payload(timeline_payload)
    timeline_sha = hashlib.sha256(timeline_bytes).hexdigest()
    latest_timeline_payload = _timeline_payload(
        video_id=2,
        youtube_video_id="yt-2",
        title="Latest video",
    )
    latest_timeline_bytes = _json_payload(latest_timeline_payload)
    latest_timeline_sha = hashlib.sha256(latest_timeline_bytes).hexdigest()
    remote = stores["legacy-remote-object"]
    timeline_key = "archive/archive/v1/videos/1/timeline.v1.control.json"
    timeline_url = remote.public_url(timeline_key)
    latest_timeline_key = "archive/archive/v1/videos/2/timeline.v1.control.json"
    latest_timeline_url = remote.public_url(latest_timeline_key)
    current_timeline_url = (
        timeline_url if current_membership_artifact_id == 1 else latest_timeline_url
    )
    index_key = "archive/archive/v1/index.index-v1.json"
    index_payload: dict[str, object] = {
        "schemaVersion": 1,
        "environment": "prod",
        "generatedAt": "2026-07-18T01:30:00Z",
        "version": "index-v1",
        "videos": [
            {
                "id": current_membership_artifact_id,
                "timelineVariants": [
                    {
                        "key": "control",
                        "url": current_timeline_url,
                        "version": "v1",
                    }
                ],
            }
        ],
    }
    index_bytes = _json_payload(index_payload)
    pointer_key = "archive/channels/prod.json"
    pointer_bytes = _json_payload(
        {
            "currentIndexUrl": remote.public_url(index_key),
            "currentIndexVersion": "index-v1",
        }
    )
    orphan_index_key = "archive/archive/v1/index.orphan.json"
    orphan_index_bytes = _json_payload(
        {
            "schemaVersion": 1,
            "environment": "prod",
            "generatedAt": "2026-07-17T01:30:00Z",
            "version": "orphan",
            "videos": [],
        }
    )
    orphan_pointer_key = "archive/channels/old-prod.json"
    orphan_pointer_bytes = _json_payload(
        {
            "currentIndexUrl": remote.public_url(orphan_index_key),
            "currentIndexVersion": "orphan",
        }
    )
    orphan_timeline_key = "archive/archive/v1/videos/404/timeline.v1.control.json"
    remote.objects.update(
        {
            timeline_key: timeline_bytes,
            latest_timeline_key: latest_timeline_bytes,
            index_key: index_bytes,
            pointer_key: pointer_bytes,
            orphan_index_key: orphan_index_bytes,
            orphan_pointer_key: orphan_pointer_bytes,
            orphan_timeline_key: b"{}",
        }
    )
    manifest_path.write_text(
        json.dumps({"objects": sorted(remote.objects)}),
        encoding="utf-8",
    )
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            session.add_all(
                [
                    StreamerModel(id=1, name="Streamer", publish_profile_id=1),
                    ChannelModel(
                        id=1,
                        streamer_id=1,
                        handle="@streamer",
                        name="Channel",
                        youtube_channel_id="UC_TEST",
                        uploads_playlist_id="UU_TEST",
                    ),
                    VideoModel(
                        id=1,
                        channel_id=1,
                        youtube_video_id="yt-1",
                        title="Video",
                        description="",
                        published_at=datetime(2026, 7, 18, 1, 0, tzinfo=UTC),
                        duration="PT1H",
                        is_embeddable=True,
                    ),
                    VideoModel(
                        id=2,
                        channel_id=1,
                        youtube_video_id="yt-2",
                        title="Latest video",
                        description="",
                        published_at=datetime(2026, 7, 18, 2, 0, tzinfo=UTC),
                        duration="PT30M",
                        is_embeddable=True,
                    ),
                    ArchiveVideoArtifactModel(
                        id=1,
                        video_id=1,
                        source_timeline_composition_id=1,
                        source_timeline_task_id=1,
                        source_micro_event_task_id=1,
                        publish_task_id=1,
                        publish_job_id=1,
                        environment="prod",
                        variant="control",
                        schema_version=1,
                        version="v1",
                        object_key=timeline_key,
                        public_url=timeline_url,
                        sha256=timeline_sha,
                        byte_size=len(timeline_bytes),
                        block_count=0,
                        episode_count=0,
                        topic_cluster_count=0,
                        review_flag_count=0,
                        micro_event_count=0,
                        public_catalog_synced_at=datetime(2026, 7, 18, 1, 30, tzinfo=UTC),
                    ),
                    ArchiveVideoArtifactModel(
                        id=2,
                        video_id=2,
                        source_timeline_composition_id=2,
                        source_timeline_task_id=2,
                        source_micro_event_task_id=2,
                        publish_task_id=2,
                        publish_job_id=2,
                        environment="prod",
                        variant="control",
                        schema_version=1,
                        version="v1",
                        object_key=latest_timeline_key,
                        public_url=latest_timeline_url,
                        sha256=latest_timeline_sha,
                        byte_size=len(latest_timeline_bytes),
                        block_count=0,
                        episode_count=0,
                        topic_cluster_count=0,
                        review_flag_count=0,
                        micro_event_count=0,
                        public_catalog_synced_at=None,
                    ),
                    ArchiveVideoArtifactModel(
                        id=3,
                        video_id=2,
                        source_timeline_composition_id=3,
                        source_timeline_task_id=3,
                        source_micro_event_task_id=3,
                        publish_task_id=3,
                        publish_job_id=3,
                        environment="prod",
                        variant="control",
                        schema_version=1,
                        version="v2",
                        object_key=("archive/archive/v1/videos/2/timeline.v2.control.json"),
                        public_url=(
                            "memory://remote/archive/archive/v1/videos/2/timeline.v2.control.json"
                        ),
                        sha256="f" * 64,
                        byte_size=2,
                        block_count=0,
                        episode_count=0,
                        topic_cluster_count=0,
                        review_flag_count=0,
                        micro_event_count=0,
                        public_catalog_synced_at=None,
                    ),
                    ArchiveIndexPublicationModel(
                        id=1,
                        environment="prod",
                        schema_version=1,
                        version="index-v1",
                        pointer_key=pointer_key,
                        index_key=index_key,
                        public_url=remote.public_url(index_key),
                        sha256=hashlib.sha256(index_bytes).hexdigest(),
                        byte_size=len(index_bytes),
                        video_count=1,
                    ),
                    ArchiveIndexPublicationModel(
                        id=2,
                        environment="prod",
                        schema_version=1,
                        version="missing-index",
                        pointer_key=pointer_key,
                        index_key="archive/archive/v1/index.missing.json",
                        public_url=remote.public_url("archive/archive/v1/index.missing.json"),
                        sha256="0" * 64,
                        byte_size=2,
                        video_count=0,
                    ),
                ]
            )
            await session.commit()
        dry_request = PublicationMigrationRequest(
            mode="dry-run",
            expected_artifact_count=3,
            expected_ready_count=2,
            expected_unavailable_count=1,
            expected_latest_count=1,
            expected_history_count=2,
            latest_limit=1,
            source_manifest=manifest_path,
        )
        async with session_factory() as session:
            dry_report = await PublicationDataMigrator(
                session=session,
                connections=factory,
                artifact_store_ref="local-artifact-store",
                staging_store_ref="local-publication-staging",
            ).run(dry_request)
        request = PublicationMigrationRequest(
            mode="apply",
            expected_artifact_count=3,
            expected_ready_count=2,
            expected_unavailable_count=1,
            expected_latest_count=1,
            expected_history_count=2,
            latest_limit=1,
            source_manifest=manifest_path,
        )
        async with session_factory() as session:
            apply_report = await PublicationDataMigrator(
                session=session,
                connections=factory,
                artifact_store_ref="local-artifact-store",
                staging_store_ref="local-publication-staging",
            ).run(request)
        if remove_catalog_row_before_resume:
            assert catalog.rows.pop(2, None) is not None
        async with session_factory() as session:
            resume_report = await PublicationDataMigrator(
                session=session,
                connections=factory,
                artifact_store_ref="local-artifact-store",
                staging_store_ref="local-publication-staging",
            ).run(
                PublicationMigrationRequest(
                    mode="resume",
                    expected_artifact_count=3,
                    expected_ready_count=2,
                    expected_unavailable_count=1,
                    expected_latest_count=1,
                    expected_history_count=2,
                    latest_limit=1,
                    source_manifest=manifest_path,
                )
            )
        if corrupt_history_before_verify:
            stores["local-public-object"].objects["archive/archive/v1/index.index-v1.json"] = (
                b"corrupt-history"
            )
        async with session_factory() as session:
            verify_report = await PublicationDataMigrator(
                session=session,
                connections=factory,
                artifact_store_ref="local-artifact-store",
                staging_store_ref="local-publication-staging",
            ).run(
                PublicationMigrationRequest(
                    mode="verify",
                    expected_artifact_count=3,
                    expected_ready_count=2,
                    expected_unavailable_count=1,
                    expected_latest_count=1,
                    expected_history_count=2,
                    latest_limit=1,
                    source_manifest=manifest_path,
                )
            )
        return dry_report, apply_report, resume_report, verify_report
    finally:
        await engine.dispose()


class MemoryObjectStore:
    def __init__(self, name: str = "bucket") -> None:
        self.name = name
        self.objects: dict[str, bytes] = {}
        self.put_count = 0

    def public_url(self, object_key: str) -> str:
        return f"memory://{self.name}/{object_key}"

    async def put_bytes(
        self,
        *,
        object_key: str,
        payload: bytes,
        content_type: str = "application/octet-stream",
        cache_control: str | None = None,
    ) -> PublicationObjectLocation:
        del content_type, cache_control
        self.put_count += 1
        self.objects[object_key] = payload
        return PublicationObjectLocation(
            bucket=self.name,
            object_key=object_key,
            public_url=self.public_url(object_key),
        )

    async def get_bytes(self, *, object_key: str) -> bytes:
        return self.objects[object_key]

    async def stat_object(self, *, object_key: str) -> PublicationObjectStat | None:
        payload = self.objects.get(object_key)
        if payload is None:
            return None
        return PublicationObjectStat(
            bucket=self.name,
            object_key=object_key,
            byte_size=len(payload),
            etag=None,
            last_modified=None,
        )


class FaultingMemoryObjectStore(MemoryObjectStore):
    def __init__(self, *, fail_stat: bool = False, fail_read: bool = False) -> None:
        super().__init__()
        self._fail_stat = fail_stat
        self._fail_read = fail_read

    async def get_bytes(self, *, object_key: str) -> bytes:
        if self._fail_read:
            raise PermissionError("read denied")
        return await super().get_bytes(object_key=object_key)

    async def stat_object(self, *, object_key: str) -> PublicationObjectStat | None:
        if self._fail_stat:
            raise ConnectionError("stat unavailable")
        return await super().stat_object(object_key=object_key)


class MemoryConnectionFactory:
    def __init__(
        self,
        stores: dict[str, MemoryObjectStore],
        *,
        catalogs: dict[str, MemoryCatalogPublisher] | None = None,
    ) -> None:
        self._stores = stores
        self._catalogs = catalogs or {}

    def object_store(self, connection_ref: str) -> MemoryObjectStore:
        return self._stores[connection_ref]

    def catalog_publisher(self, connection_ref: str) -> MemoryCatalogPublisher:
        return self._catalogs[connection_ref]

    def catalog_verifier(self, connection_ref: str) -> MemoryCatalogPublisher:
        return self._catalogs[connection_ref]


class MemoryCatalogPublisher:
    def __init__(self) -> None:
        self.rows: dict[int, ArchivePublicCatalogVideoRow] = {}
        self.upsert_count = 0

    async def upsert_video(
        self,
        context: PublicationCatalogContext,
        row: ArchivePublicCatalogVideoRow,
    ) -> None:
        del context
        self.upsert_count += 1
        self.rows[row.video_id] = row

    async def verify_video(
        self,
        context: PublicationCatalogContext,
        row: ArchivePublicCatalogVideoRow,
    ) -> PublicationCatalogRowVerification:
        del context
        actual = self.rows.get(row.video_id)
        matches = actual is not None and _stable_catalog_row(actual) == _stable_catalog_row(row)
        return PublicationCatalogRowVerification(
            exists=actual is not None,
            matches=matches,
            detail=None if matches else "memory_projection_mismatch",
        )


def _stable_catalog_row(row: ArchivePublicCatalogVideoRow) -> ArchivePublicCatalogVideoRow:
    timeline_index = row.timeline_index
    if timeline_index is not None:
        timeline_index = replace(timeline_index, updated_at="")
    return replace(row, updated_at="", timeline_index=timeline_index)


def _timeline_payload(
    *,
    video_id: int = 1,
    youtube_video_id: str = "yt-1",
    title: str = "Video",
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "environment": "prod",
        "youtubeVideoId": youtube_video_id,
        "video": {
            "id": video_id,
            "title": title,
            "streamer": {"id": 1, "name": "Streamer"},
            "channel": {
                "id": 1,
                "name": "Channel",
                "handle": "@streamer",
                "youtubeChannelId": "UC_TEST",
            },
            "publishedAt": "2026-07-18T01:00:00Z",
            "duration": "PT1H",
            "isEmbeddable": True,
        },
        "blocks": [],
        "episodes": [],
        "topicClusters": [],
    }


def _json_payload(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _artifact() -> ArchiveVideoArtifactRecord:
    now = datetime(2026, 7, 18, 1, 30, tzinfo=UTC)
    return ArchiveVideoArtifactRecord(
        id=7,
        video_id=71,
        source_timeline_composition_id=1,
        source_timeline_task_id=2,
        source_micro_event_task_id=3,
        publish_task_id=4,
        publish_job_id=5,
        environment="prod",
        variant="control",
        schema_version=1,
        version="v1",
        object_key="archive/timeline.json",
        public_url="https://remote.test/archive/timeline.json",
        sha256="0" * 64,
        byte_size=2,
        block_count=0,
        episode_count=0,
        topic_cluster_count=0,
        review_flag_count=0,
        micro_event_count=0,
        build_key=None,
        artifact_status="pending",
        artifact_store_ref=None,
        artifact_key=None,
        unavailable_code=None,
        unavailable_detail=None,
        public_catalog_synced_at=now,
        public_catalog_sync_error=None,
        created_at=now,
        updated_at=now,
    )
