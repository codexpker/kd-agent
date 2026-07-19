"""Add normalized MySQL authority entities for reviewed Gold records.

Revision ID: 0002_reconstructed_authority
Revises: 0001_reconstructed
Create Date: 2026-07-20

This is a new reconstruction revision. It does not represent any lost historical migration.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_reconstructed_authority"
down_revision: str | None = "0001_reconstructed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gold_dataset_versions",
        sa.Column("dataset_version", sa.String(length=191), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("dataset_version"),
    )
    op.create_table(
        "paper_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("paper_id", sa.String(length=191), nullable=False),
        sa.Column("source_key", sa.String(length=191), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("license_name", sa.String(length=255), nullable=True),
        sa.Column("access_policy", sa.String(length=32), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.paper_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paper_id", "source_key", name="uq_paper_sources_paper_key"),
    )
    op.create_index("ix_paper_sources_external_id", "paper_sources", ["external_id"])
    op.create_table(
        "paper_gold_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("paper_id", sa.String(length=191), nullable=False),
        sa.Column("dataset_version", sa.String(length=191), nullable=False),
        sa.Column("annotation_status", sa.String(length=32), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.paper_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dataset_version"],
            ["gold_dataset_versions.dataset_version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "paper_id", "dataset_version", name="uq_paper_gold_records_paper_dataset"
        ),
    )
    op.create_table(
        "narrative_moves",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gold_record_id", sa.Integer(), nullable=False),
        sa.Column("local_id", sa.String(length=191), nullable=False),
        sa.Column("move_order", sa.Integer(), nullable=False),
        sa.Column("move", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["gold_record_id"], ["paper_gold_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gold_record_id", "local_id", name="uq_narrative_moves_record_local"
        ),
        sa.UniqueConstraint(
            "gold_record_id", "move_order", name="uq_narrative_moves_record_order"
        ),
    )
    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gold_record_id", sa.Integer(), nullable=False),
        sa.Column("local_id", sa.String(length=191), nullable=False),
        sa.Column("claim_type", sa.String(length=32), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["gold_record_id"], ["paper_gold_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gold_record_id", "local_id", name="uq_claims_record_local"),
    )
    op.create_table(
        "experiment_intents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gold_record_id", sa.Integer(), nullable=False),
        sa.Column("local_id", sa.String(length=191), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("design_reason", sa.Text(), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["gold_record_id"], ["paper_gold_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gold_record_id", "local_id", name="uq_experiment_intents_record_local"
        ),
    )
    op.create_table(
        "artifact_roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gold_record_id", sa.Integer(), nullable=False),
        sa.Column("local_id", sa.String(length=191), nullable=False),
        sa.Column("artifact_type", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("why_here", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["gold_record_id"], ["paper_gold_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gold_record_id", "local_id", name="uq_artifact_roles_record_local"
        ),
    )
    op.create_table(
        "evidence_anchors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gold_record_id", sa.Integer(), nullable=False),
        sa.Column("local_id", sa.String(length=191), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["gold_record_id"], ["paper_gold_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gold_record_id", "local_id", name="uq_evidence_anchors_record_local"
        ),
    )
    op.create_index("ix_evidence_anchors_kind", "evidence_anchors", ["kind"])
    op.create_table(
        "paper_limitations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gold_record_id", sa.Integer(), nullable=False),
        sa.Column("limitation_order", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["gold_record_id"], ["paper_gold_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gold_record_id", "limitation_order", name="uq_paper_limitations_record_order"
        ),
    )
    op.create_table(
        "narrative_move_evidence",
        sa.Column("narrative_move_id", sa.Integer(), nullable=False),
        sa.Column("evidence_anchor_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["narrative_move_id"], ["narrative_moves.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_anchor_id"], ["evidence_anchors.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("narrative_move_id", "evidence_anchor_id"),
    )
    op.create_table(
        "claim_evidence",
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("evidence_anchor_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evidence_anchor_id"], ["evidence_anchors.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("claim_id", "evidence_anchor_id"),
    )
    op.create_table(
        "experiment_intent_claims",
        sa.Column("experiment_intent_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_intent_id"], ["experiment_intents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("experiment_intent_id", "claim_id"),
    )
    op.create_table(
        "experiment_intent_evidence",
        sa.Column("experiment_intent_id", sa.Integer(), nullable=False),
        sa.Column("evidence_anchor_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_intent_id"], ["experiment_intents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_anchor_id"], ["evidence_anchors.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("experiment_intent_id", "evidence_anchor_id"),
    )
    op.create_table(
        "artifact_role_claims",
        sa.Column("artifact_role_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_role_id"], ["artifact_roles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("artifact_role_id", "claim_id"),
    )
    op.create_table(
        "artifact_role_evidence",
        sa.Column("artifact_role_id", sa.Integer(), nullable=False),
        sa.Column("evidence_anchor_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_role_id"], ["artifact_roles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_anchor_id"], ["evidence_anchors.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("artifact_role_id", "evidence_anchor_id"),
    )


def downgrade() -> None:
    op.drop_table("artifact_role_evidence")
    op.drop_table("artifact_role_claims")
    op.drop_table("experiment_intent_evidence")
    op.drop_table("experiment_intent_claims")
    op.drop_table("claim_evidence")
    op.drop_table("narrative_move_evidence")
    op.drop_table("paper_limitations")
    op.drop_index("ix_evidence_anchors_kind", table_name="evidence_anchors")
    op.drop_table("evidence_anchors")
    op.drop_table("artifact_roles")
    op.drop_table("experiment_intents")
    op.drop_table("claims")
    op.drop_table("narrative_moves")
    op.drop_table("paper_gold_records")
    op.drop_index("ix_paper_sources_external_id", table_name="paper_sources")
    op.drop_table("paper_sources")
    op.drop_table("gold_dataset_versions")
