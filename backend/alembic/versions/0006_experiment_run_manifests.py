"""Add versioned experiment run manifests.

Revision ID: 0006_experiment_run_manifests
Revises: 0005_experiment_artifact_plans
Create Date: 2026-07-20

This is a new reconstruction migration, not a recovered historical revision.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_experiment_run_manifests"
down_revision: str | None = "0005_experiment_artifact_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_run_manifest_versions",
        sa.Column("run_revision_id", sa.String(length=191), nullable=False),
        sa.Column("run_id", sa.String(length=191), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_run_revision_id", sa.String(length=191), nullable=True),
        sa.Column("plan_revision_id", sa.String(length=191), nullable=False),
        sa.Column("experiment_id", sa.String(length=191), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("run_configuration_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_provenance", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("data_sha256", sa.String(length=64), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supersedes_run_revision_id"],
            ["experiment_run_manifest_versions.run_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_revision_id"],
            ["experiment_plan_versions.plan_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_revision_id"),
        sa.UniqueConstraint(
            "run_id",
            "revision",
            name="uq_experiment_run_manifests_run_revision",
        ),
    )
    op.create_index(
        "ix_experiment_run_manifests_project_run",
        "experiment_run_manifest_versions",
        ["project_id", "run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_experiment_run_manifests_project_run",
        table_name="experiment_run_manifest_versions",
    )
    op.drop_table("experiment_run_manifest_versions")
