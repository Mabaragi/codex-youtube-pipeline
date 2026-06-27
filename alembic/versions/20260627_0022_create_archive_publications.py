"""Create archive publication tables."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0022"
down_revision: str | Sequence[str] | None = "20260627_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "archive_video_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("source_timeline_composition_id", sa.Integer(), nullable=False),
        sa.Column("source_timeline_task_id", sa.Integer(), nullable=False),
        sa.Column("source_micro_event_task_id", sa.Integer(), nullable=False),
        sa.Column("publish_task_id", sa.Integer(), nullable=False),
        sa.Column("publish_job_id", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.Column("variant", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("block_count", sa.Integer(), nullable=False),
        sa.Column("episode_count", sa.Integer(), nullable=False),
        sa.Column("topic_cluster_count", sa.Integer(), nullable=False),
        sa.Column("review_flag_count", sa.Integer(), nullable=False),
        sa.Column("micro_event_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("schema_version >= 1", name="archive_video_artifacts_schema_min"),
        sa.CheckConstraint("byte_size >= 1", name="archive_video_artifacts_byte_size_min"),
        sa.CheckConstraint("block_count >= 0", name="archive_video_artifacts_block_count_min"),
        sa.CheckConstraint("episode_count >= 0", name="archive_video_artifacts_episode_count_min"),
        sa.CheckConstraint(
            "topic_cluster_count >= 0", name="archive_video_artifacts_topic_cluster_count_min"
        ),
        sa.CheckConstraint(
            "review_flag_count >= 0", name="archive_video_artifacts_review_flag_count_min"
        ),
        sa.CheckConstraint(
            "micro_event_count >= 0", name="archive_video_artifacts_micro_event_count_min"
        ),
        sa.ForeignKeyConstraint(["publish_job_id"], ["pipeline_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["publish_task_id"], ["video_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_micro_event_task_id"], ["video_tasks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_timeline_composition_id"], ["timeline_compositions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_timeline_task_id"], ["video_tasks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_archive_video_artifacts_environment_version",
        "archive_video_artifacts",
        ["environment", "schema_version", "version"],
    )
    op.create_index(
        "ix_archive_video_artifacts_publish_job",
        "archive_video_artifacts",
        ["publish_job_id"],
    )
    op.create_index(
        "ix_archive_video_artifacts_publish_task",
        "archive_video_artifacts",
        ["publish_task_id"],
    )
    op.create_index(
        "ix_archive_video_artifacts_source_timeline_task",
        "archive_video_artifacts",
        ["source_timeline_task_id"],
    )
    op.create_index(
        "ix_archive_video_artifacts_video_env_variant",
        "archive_video_artifacts",
        ["video_id", "environment", "variant", "created_at"],
    )

    op.create_table(
        "archive_index_publications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("pointer_key", sa.Text(), nullable=False),
        sa.Column("index_key", sa.Text(), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("video_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("schema_version >= 1", name="archive_index_schema_min"),
        sa.CheckConstraint("byte_size >= 1", name="archive_index_byte_size_min"),
        sa.CheckConstraint("video_count >= 0", name="archive_index_video_count_min"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_archive_index_publications_environment_created",
        "archive_index_publications",
        ["environment", "created_at", "id"],
    )
    op.create_index(
        "ix_archive_index_publications_environment_version",
        "archive_index_publications",
        ["environment", "schema_version", "version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_archive_index_publications_environment_version",
        table_name="archive_index_publications",
    )
    op.drop_index(
        "ix_archive_index_publications_environment_created",
        table_name="archive_index_publications",
    )
    op.drop_table("archive_index_publications")
    op.drop_index(
        "ix_archive_video_artifacts_video_env_variant",
        table_name="archive_video_artifacts",
    )
    op.drop_index(
        "ix_archive_video_artifacts_source_timeline_task",
        table_name="archive_video_artifacts",
    )
    op.drop_index(
        "ix_archive_video_artifacts_publish_task",
        table_name="archive_video_artifacts",
    )
    op.drop_index(
        "ix_archive_video_artifacts_publish_job",
        table_name="archive_video_artifacts",
    )
    op.drop_index(
        "ix_archive_video_artifacts_environment_version",
        table_name="archive_video_artifacts",
    )
    op.drop_table("archive_video_artifacts")
