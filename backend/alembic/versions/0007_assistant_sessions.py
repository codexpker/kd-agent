"""Add persistent assistant sessions, messages and tool-run provenance.

Revision ID: 0007_assistant_sessions
Revises: 0006_experiment_run_manifests
Create Date: 2026-07-22

This is a new reconstruction migration, not a recovered historical revision.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_assistant_sessions"
down_revision: str | None = "0006_experiment_run_manifests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_sessions",
        sa.Column("session_id", sa.String(length=191), nullable=False),
        sa.Column("trace_id", sa.String(length=191), nullable=False),
        sa.Column("paper_id", sa.String(length=191), nullable=False),
        sa.Column("backend", sa.String(length=16), nullable=False),
        sa.Column("provider_status", sa.String(length=16), nullable=False),
        sa.Column("provider_name", sa.String(length=255), nullable=False),
        sa.Column("model_label", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("storage", sa.String(length=32), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.paper_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("trace_id", name="uq_assistant_sessions_trace_id"),
    )
    op.create_index(
        "ix_assistant_sessions_paper_updated",
        "assistant_sessions",
        ["paper_id", "updated_at"],
    )

    op.create_table(
        "assistant_messages",
        sa.Column("message_id", sa.String(length=191), nullable=False),
        sa.Column("session_id", sa.String(length=191), nullable=False),
        sa.Column("message_order", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["assistant_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint(
            "session_id", "message_order", name="uq_assistant_messages_session_order"
        ),
    )
    op.create_index(
        "ix_assistant_messages_session_id", "assistant_messages", ["session_id"]
    )

    op.create_table(
        "assistant_tool_runs",
        sa.Column("run_id", sa.String(length=191), nullable=False),
        sa.Column("session_id", sa.String(length=191), nullable=False),
        sa.Column("run_order", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["assistant_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint(
            "session_id", "run_order", name="uq_assistant_tool_runs_session_order"
        ),
    )
    op.create_index(
        "ix_assistant_tool_runs_session_id", "assistant_tool_runs", ["session_id"]
    )

    op.create_table(
        "assistant_message_evidence",
        sa.Column("message_id", sa.String(length=191), nullable=False),
        sa.Column("evidence_id", sa.String(length=191), nullable=False),
        sa.Column("evidence_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"], ["assistant_messages.message_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("message_id", "evidence_id"),
    )
    op.create_table(
        "assistant_tool_run_evidence",
        sa.Column("run_id", sa.String(length=191), nullable=False),
        sa.Column("evidence_id", sa.String(length=191), nullable=False),
        sa.Column("evidence_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["assistant_tool_runs.run_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id", "evidence_id"),
    )
    op.create_table(
        "assistant_message_tool_runs",
        sa.Column("message_id", sa.String(length=191), nullable=False),
        sa.Column("run_id", sa.String(length=191), nullable=False),
        sa.Column("run_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"], ["assistant_messages.message_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["assistant_tool_runs.run_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("message_id", "run_id"),
    )


def downgrade() -> None:
    op.drop_table("assistant_message_tool_runs")
    op.drop_table("assistant_tool_run_evidence")
    op.drop_table("assistant_message_evidence")
    op.drop_index(
        "ix_assistant_tool_runs_session_id", table_name="assistant_tool_runs"
    )
    op.drop_table("assistant_tool_runs")
    op.drop_index(
        "ix_assistant_messages_session_id", table_name="assistant_messages"
    )
    op.drop_table("assistant_messages")
    op.drop_index(
        "ix_assistant_sessions_paper_updated", table_name="assistant_sessions"
    )
    op.drop_table("assistant_sessions")
