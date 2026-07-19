"""Add normalized parsed-PDF layout facts and rights provenance.

Revision ID: 0003_reconstructed_pdf_layout
Revises: 0002_reconstructed_authority
Create Date: 2026-07-20

This revision stores hashes and structured layout facts only. It has no PDF binary,
filesystem path, or full-document text column.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_reconstructed_pdf_layout"
down_revision: str | None = "0002_reconstructed_authority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pdf_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("paper_id", sa.String(length=191), nullable=False),
        sa.Column("paper_source_id", sa.Integer(), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("rights_basis", sa.String(length=32), nullable=False),
        sa.Column("rights_confirmed_by", sa.String(length=255), nullable=False),
        sa.Column("rights_note", sa.Text(), nullable=False),
        sa.Column("rights_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.paper_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["paper_source_id"], ["paper_sources.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "paper_id", "file_sha256", name="uq_pdf_sources_paper_file"
        ),
    )
    op.create_index("ix_pdf_sources_file_sha256", "pdf_sources", ["file_sha256"])
    op.create_table(
        "pdf_parse_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pdf_source_id", sa.Integer(), nullable=False),
        sa.Column("parser_name", sa.String(length=255), nullable=False),
        sa.Column("parser_version", sa.String(length=255), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pdf_source_id"], ["pdf_sources.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pdf_source_id",
            "parser_name",
            "parser_version",
            "content_sha256",
            name="uq_pdf_runs_source_parser_content",
        ),
    )
    op.create_index(
        "ix_pdf_parse_runs_source_status",
        "pdf_parse_runs",
        ["pdf_source_id", "status"],
    )
    op.create_table(
        "pdf_sections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parse_run_id", sa.Integer(), nullable=False),
        sa.Column("local_id", sa.String(length=191), nullable=False),
        sa.Column("section_order", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("heading_bbox", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parse_run_id"], ["pdf_parse_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parse_run_id", "local_id", name="uq_pdf_sections_run_local"
        ),
        sa.UniqueConstraint(
            "parse_run_id", "section_order", name="uq_pdf_sections_run_order"
        ),
    )
    op.create_table(
        "pdf_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parse_run_id", sa.Integer(), nullable=False),
        sa.Column("local_id", sa.String(length=191), nullable=False),
        sa.Column("artifact_order", sa.Integer(), nullable=False),
        sa.Column("artifact_type", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("caption_bbox", sa.JSON(), nullable=True),
        sa.Column("table_markdown", sa.Text(), nullable=True),
        sa.Column("table_data", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parse_run_id"], ["pdf_parse_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parse_run_id", "local_id", name="uq_pdf_artifacts_run_local"
        ),
        sa.UniqueConstraint(
            "parse_run_id", "artifact_order", name="uq_pdf_artifacts_run_order"
        ),
    )
    op.create_table(
        "pdf_body_references",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parse_run_id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("local_id", sa.String(length=191), nullable=False),
        sa.Column("reference_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["pdf_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parse_run_id"], ["pdf_parse_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parse_run_id", "local_id", name="uq_pdf_references_run_local"
        ),
        sa.UniqueConstraint(
            "parse_run_id", "reference_order", name="uq_pdf_references_run_order"
        ),
    )


def downgrade() -> None:
    op.drop_table("pdf_body_references")
    op.drop_table("pdf_artifacts")
    op.drop_table("pdf_sections")
    op.drop_index("ix_pdf_parse_runs_source_status", table_name="pdf_parse_runs")
    op.drop_table("pdf_parse_runs")
    op.drop_index("ix_pdf_sources_file_sha256", table_name="pdf_sources")
    op.drop_table("pdf_sources")
