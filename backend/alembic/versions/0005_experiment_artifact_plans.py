"""Add versioned Project Claim experiment and artifact plans.

Revision ID: 0005_experiment_artifact_plans
Revises: 0004_project_claim_versions
Create Date: 2026-07-20

This is a new reconstruction migration, not a recovered historical revision.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_experiment_artifact_plans"
down_revision: str | None = "0004_project_claim_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_plan_versions",
        sa.Column("plan_revision_id", sa.String(length=191), nullable=False),
        sa.Column("plan_id", sa.String(length=191), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_plan_revision_id", sa.String(length=191), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("planner_version", sa.String(length=64), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supersedes_plan_revision_id"],
            ["experiment_plan_versions.plan_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("plan_revision_id"),
        sa.UniqueConstraint(
            "project_id",
            "revision",
            name="uq_experiment_plans_project_revision",
        ),
    )
    op.create_index(
        "ix_experiment_plan_versions_plan_id",
        "experiment_plan_versions",
        ["plan_id"],
    )
    op.create_table(
        "experiment_plan_claim_links",
        sa.Column("plan_revision_id", sa.String(length=191), nullable=False),
        sa.Column("experiment_id", sa.String(length=191), nullable=False),
        sa.Column("claim_version_id", sa.String(length=191), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_revision_id"],
            ["experiment_plan_versions.plan_revision_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["project_claim_versions.claim_version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("plan_revision_id", "experiment_id", "claim_version_id"),
    )
    op.create_table(
        "artifact_plan_claim_links",
        sa.Column("plan_revision_id", sa.String(length=191), nullable=False),
        sa.Column("artifact_id", sa.String(length=191), nullable=False),
        sa.Column("claim_version_id", sa.String(length=191), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_revision_id"],
            ["experiment_plan_versions.plan_revision_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["project_claim_versions.claim_version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("plan_revision_id", "artifact_id", "claim_version_id"),
    )


def downgrade() -> None:
    op.drop_table("artifact_plan_claim_links")
    op.drop_table("experiment_plan_claim_links")
    op.drop_index(
        "ix_experiment_plan_versions_plan_id",
        table_name="experiment_plan_versions",
    )
    op.drop_table("experiment_plan_versions")
