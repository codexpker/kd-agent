"""Create the reconstructed R2 storage baseline.

Revision ID: 0001_reconstructed
Revises:
Create Date: 2026-07-19
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_reconstructed"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("paper_id", sa.String(length=191), nullable=False),
        sa.Column("dataset_version", sa.String(length=191), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("venue", sa.String(length=255), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("annotation_status", sa.String(length=32), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("deconstruction", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("paper_id"),
    )
    op.create_index("ix_papers_dataset_version", "papers", ["dataset_version"], unique=False)
    op.create_table(
        "document_structures",
        sa.Column("paper_id", sa.String(length=191), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("parser_name", sa.String(length=255), nullable=True),
        sa.Column("parser_version", sa.String(length=255), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("structure", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.paper_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("paper_id"),
    )
    op.create_table(
        "graph_sync_states",
        sa.Column("paper_id", sa.String(length=191), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.paper_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("paper_id"),
    )


def downgrade() -> None:
    op.drop_table("graph_sync_states")
    op.drop_table("document_structures")
    op.drop_index("ix_papers_dataset_version", table_name="papers")
    op.drop_table("papers")
