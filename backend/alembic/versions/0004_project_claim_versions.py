"""Add versioned Project Claims and editable evidence diagnoses.

Revision ID: 0004_project_claim_versions
Revises: 0003_reconstructed_pdf_layout
Create Date: 2026-07-20

This is a new reconstruction migration, not a recovered historical revision.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_project_claim_versions"
down_revision: str | None = "0003_reconstructed_pdf_layout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_claim_versions",
        sa.Column("claim_version_id", sa.String(length=191), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("claim_id", sa.String(length=191), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_claim_version_id", sa.String(length=191), nullable=True),
        sa.Column("research_question", sa.Text(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("proposed_method", sa.Text(), nullable=False),
        sa.Column("target_scenario", sa.Text(), nullable=False),
        sa.Column("existing_results", sa.JSON(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supersedes_claim_version_id"],
            ["project_claim_versions.claim_version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("claim_version_id"),
        sa.UniqueConstraint(
            "project_id",
            "version",
            name="uq_project_claim_versions_project_version",
        ),
    )
    op.create_index(
        "ix_project_claim_versions_claim_id",
        "project_claim_versions",
        ["claim_id"],
    )
    op.create_table(
        "evidence_diagnosis_versions",
        sa.Column("diagnosis_id", sa.String(length=191), nullable=False),
        sa.Column("claim_version_id", sa.String(length=191), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("planner_version", sa.String(length=64), nullable=False),
        sa.Column("language_organizer", sa.String(length=64), nullable=False),
        sa.Column("diagnosis", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["project_claim_versions.claim_version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("diagnosis_id"),
        sa.UniqueConstraint(
            "claim_version_id",
            "revision",
            name="uq_evidence_diagnoses_claim_revision",
        ),
    )


def downgrade() -> None:
    op.drop_table("evidence_diagnosis_versions")
    op.drop_index(
        "ix_project_claim_versions_claim_id",
        table_name="project_claim_versions",
    )
    op.drop_table("project_claim_versions")
