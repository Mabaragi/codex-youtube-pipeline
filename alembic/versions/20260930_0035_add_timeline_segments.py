"""Add immutable segment classification results and publication provenance."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260930_0035"
down_revision = "20260718_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "segment_classifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "work_item_id",
            sa.Integer(),
            sa.ForeignKey("work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "work_attempt_id",
            sa.Integer(),
            sa.ForeignKey("work_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "video_id",
            sa.Integer(),
            sa.ForeignKey("videos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "composition_id",
            sa.Integer(),
            sa.ForeignKey("timeline_compositions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_timeline_work_item_id",
            sa.Integer(),
            sa.ForeignKey("work_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("taxonomy_version", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column(
            "prompt_version_id",
            sa.Integer(),
            sa.ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("prompt_body_sha256", sa.String(64), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("reasoning_effort", sa.String(32), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "work_item_id", "work_attempt_id", name="uq_segment_classifications_attempt"
        ),
    )
    op.create_index(
        "ix_segment_classifications_source",
        "segment_classifications",
        ["composition_id", "source_fingerprint"],
    )
    op.create_table(
        "timeline_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "classification_id",
            sa.Integer(),
            sa.ForeignKey("segment_classifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("start_episode_id", sa.String(64), nullable=False),
        sa.Column("end_episode_id", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("collab", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "classification_id", "segment_index", name="uq_timeline_segments_index"
        ),
        sa.CheckConstraint(
            "start_ms >= 0 AND end_ms > start_ms", name="timeline_segments_time_valid"
        ),
        sa.CheckConstraint("segment_index >= 1", name="timeline_segments_index_min"),
        sa.CheckConstraint(
            "category IN ('chat','game','sing','watch','cafe','setup','asmr','other')",
            name="timeline_segments_category_allowed",
        ),
    )
    op.create_index(
        "ix_timeline_segments_category", "timeline_segments", ["category", "classification_id"]
    )
    with op.batch_alter_table("archive_video_artifacts") as batch:
        batch.add_column(sa.Column("source_classification_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_archive_artifacts_classification",
            "segment_classifications",
            ["source_classification_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("archive_video_artifacts") as batch:
        batch.drop_constraint("fk_archive_artifacts_classification", type_="foreignkey")
        batch.drop_column("source_classification_id")
    op.drop_table("timeline_segments")
    op.drop_table("segment_classifications")
