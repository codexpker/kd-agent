from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PaperRow(Base):
    __tablename__ = "papers"
    __table_args__ = (Index("ix_papers_dataset_version", "dataset_version"),)

    paper_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(191), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    venue: Mapped[str] = mapped_column(String(255), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    annotation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    deconstruction: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperSourceRow(Base):
    __tablename__ = "paper_sources"
    __table_args__ = (
        UniqueConstraint("paper_id", "source_key", name="uq_paper_sources_paper_key"),
        Index("ix_paper_sources_external_id", "external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(
        String(191), ForeignKey("papers.paper_id", ondelete="CASCADE"), nullable=False
    )
    source_key: Mapped[str] = mapped_column(String(191), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(255))
    license_name: Mapped[str | None] = mapped_column(String(255))
    access_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GoldDatasetVersionRow(Base):
    __tablename__ = "gold_dataset_versions"

    dataset_version: Mapped[str] = mapped_column(String(191), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaperGoldRecordRow(Base):
    __tablename__ = "paper_gold_records"
    __table_args__ = (
        UniqueConstraint(
            "paper_id", "dataset_version", name="uq_paper_gold_records_paper_dataset"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(
        String(191), ForeignKey("papers.paper_id", ondelete="CASCADE"), nullable=False
    )
    dataset_version: Mapped[str] = mapped_column(
        String(191),
        ForeignKey("gold_dataset_versions.dataset_version", ondelete="RESTRICT"),
        nullable=False,
    )
    annotation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NarrativeMoveRow(Base):
    __tablename__ = "narrative_moves"
    __table_args__ = (
        UniqueConstraint("gold_record_id", "local_id", name="uq_narrative_moves_record_local"),
        UniqueConstraint("gold_record_id", "move_order", name="uq_narrative_moves_record_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gold_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_gold_records.id", ondelete="CASCADE"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(String(191), nullable=False)
    move_order: Mapped[int] = mapped_column(Integer, nullable=False)
    move: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)


class ClaimRow(Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("gold_record_id", "local_id", name="uq_claims_record_local"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gold_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_gold_records.id", ondelete="CASCADE"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(String(191), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)


class ExperimentIntentRow(Base):
    __tablename__ = "experiment_intents"
    __table_args__ = (
        UniqueConstraint(
            "gold_record_id", "local_id", name="uq_experiment_intents_record_local"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gold_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_gold_records.id", ondelete="CASCADE"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(String(191), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    design_reason: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class ArtifactRoleRow(Base):
    __tablename__ = "artifact_roles"
    __table_args__ = (
        UniqueConstraint("gold_record_id", "local_id", name="uq_artifact_roles_record_local"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gold_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_gold_records.id", ondelete="CASCADE"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(String(191), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    why_here: Mapped[str] = mapped_column(Text, nullable=False)


class EvidenceAnchorRow(Base):
    __tablename__ = "evidence_anchors"
    __table_args__ = (
        UniqueConstraint("gold_record_id", "local_id", name="uq_evidence_anchors_record_local"),
        Index("ix_evidence_anchors_kind", "kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gold_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_gold_records.id", ondelete="CASCADE"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(String(191), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)


class PaperLimitationRow(Base):
    __tablename__ = "paper_limitations"
    __table_args__ = (
        UniqueConstraint(
            "gold_record_id", "limitation_order", name="uq_paper_limitations_record_order"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gold_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_gold_records.id", ondelete="CASCADE"), nullable=False
    )
    limitation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)


class NarrativeMoveEvidenceRow(Base):
    __tablename__ = "narrative_move_evidence"

    narrative_move_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("narrative_moves.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_anchor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evidence_anchors.id", ondelete="CASCADE"), primary_key=True
    )


class ClaimEvidenceRow(Base):
    __tablename__ = "claim_evidence"

    claim_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_anchor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evidence_anchors.id", ondelete="CASCADE"), primary_key=True
    )


class ExperimentIntentClaimRow(Base):
    __tablename__ = "experiment_intent_claims"

    experiment_intent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiment_intents.id", ondelete="CASCADE"), primary_key=True
    )
    claim_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True
    )


class ExperimentIntentEvidenceRow(Base):
    __tablename__ = "experiment_intent_evidence"

    experiment_intent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiment_intents.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_anchor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evidence_anchors.id", ondelete="CASCADE"), primary_key=True
    )


class ArtifactRoleClaimRow(Base):
    __tablename__ = "artifact_role_claims"

    artifact_role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artifact_roles.id", ondelete="CASCADE"), primary_key=True
    )
    claim_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True
    )


class ArtifactRoleEvidenceRow(Base):
    __tablename__ = "artifact_role_evidence"

    artifact_role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artifact_roles.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_anchor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evidence_anchors.id", ondelete="CASCADE"), primary_key=True
    )


class PdfSourceRow(Base):
    __tablename__ = "pdf_sources"
    __table_args__ = (
        UniqueConstraint("paper_id", "file_sha256", name="uq_pdf_sources_paper_file"),
        Index("ix_pdf_sources_file_sha256", "file_sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(
        String(191), ForeignKey("papers.paper_id", ondelete="CASCADE"), nullable=False
    )
    paper_source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("paper_sources.id", ondelete="SET NULL")
    )
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rights_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    rights_confirmed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    rights_note: Mapped[str] = mapped_column(Text, nullable=False)
    rights_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PdfParseRunRow(Base):
    __tablename__ = "pdf_parse_runs"
    __table_args__ = (
        UniqueConstraint(
            "pdf_source_id",
            "parser_name",
            "parser_version",
            "content_sha256",
            name="uq_pdf_runs_source_parser_content",
        ),
        Index("ix_pdf_parse_runs_source_status", "pdf_source_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pdf_source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pdf_sources.id", ondelete="CASCADE"), nullable=False
    )
    parser_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(255), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PdfSectionRow(Base):
    __tablename__ = "pdf_sections"
    __table_args__ = (
        UniqueConstraint("parse_run_id", "local_id", name="uq_pdf_sections_run_local"),
        UniqueConstraint("parse_run_id", "section_order", name="uq_pdf_sections_run_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parse_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pdf_parse_runs.id", ondelete="CASCADE"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(String(191), nullable=False)
    section_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_bbox: Mapped[list[float] | None] = mapped_column(JSON)


class PdfArtifactRow(Base):
    __tablename__ = "pdf_artifacts"
    __table_args__ = (
        UniqueConstraint("parse_run_id", "local_id", name="uq_pdf_artifacts_run_local"),
        UniqueConstraint("parse_run_id", "artifact_order", name="uq_pdf_artifacts_run_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parse_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pdf_parse_runs.id", ondelete="CASCADE"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(String(191), nullable=False)
    artifact_order: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[list[float] | None] = mapped_column(JSON)
    caption_bbox: Mapped[list[float] | None] = mapped_column(JSON)
    table_markdown: Mapped[str | None] = mapped_column(Text)
    table_data: Mapped[list[list[str]] | None] = mapped_column(JSON)


class PdfBodyReferenceRow(Base):
    __tablename__ = "pdf_body_references"
    __table_args__ = (
        UniqueConstraint(
            "parse_run_id", "local_id", name="uq_pdf_references_run_local"
        ),
        UniqueConstraint(
            "parse_run_id", "reference_order", name="uq_pdf_references_run_order"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parse_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pdf_parse_runs.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pdf_artifacts.id", ondelete="CASCADE"), nullable=False
    )
    local_id: Mapped[str] = mapped_column(String(191), nullable=False)
    reference_order: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[list[float] | None] = mapped_column(JSON)


class DocumentStructureRow(Base):
    __tablename__ = "document_structures"

    paper_id: Mapped[str] = mapped_column(
        String(191), ForeignKey("papers.paper_id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    parser_name: Mapped[str | None] = mapped_column(String(255))
    parser_version: Mapped[str | None] = mapped_column(String(255))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    structure: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GraphSyncStateRow(Base):
    __tablename__ = "graph_sync_states"

    paper_id: Mapped[str] = mapped_column(
        String(191), ForeignKey("papers.paper_id", ondelete="CASCADE"), primary_key=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectClaimVersionRow(Base):
    __tablename__ = "project_claim_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "version", name="uq_project_claim_versions_project_version"
        ),
        Index("ix_project_claim_versions_claim_id", "claim_id"),
    )

    claim_version_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_id: Mapped[str] = mapped_column(String(191), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_claim_version_id: Mapped[str | None] = mapped_column(
        String(191), ForeignKey("project_claim_versions.claim_version_id", ondelete="RESTRICT")
    )
    research_question: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_method: Mapped[str] = mapped_column(Text, nullable=False)
    target_scenario: Mapped[str] = mapped_column(Text, nullable=False)
    existing_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceDiagnosisVersionRow(Base):
    __tablename__ = "evidence_diagnosis_versions"
    __table_args__ = (
        UniqueConstraint(
            "claim_version_id",
            "revision",
            name="uq_evidence_diagnoses_claim_revision",
        ),
    )

    diagnosis_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    claim_version_id: Mapped[str] = mapped_column(
        String(191),
        ForeignKey("project_claim_versions.claim_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    planner_version: Mapped[str] = mapped_column(String(64), nullable=False)
    language_organizer: Mapped[str] = mapped_column(String(64), nullable=False)
    diagnosis: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentPlanVersionRow(Base):
    __tablename__ = "experiment_plan_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "revision", name="uq_experiment_plans_project_revision"
        ),
    )

    plan_revision_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_plan_revision_id: Mapped[str | None] = mapped_column(
        String(191),
        ForeignKey("experiment_plan_versions.plan_revision_id", ondelete="RESTRICT"),
    )
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    planner_version: Mapped[str] = mapped_column(String(64), nullable=False)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentPlanClaimLinkRow(Base):
    __tablename__ = "experiment_plan_claim_links"

    plan_revision_id: Mapped[str] = mapped_column(
        String(191),
        ForeignKey("experiment_plan_versions.plan_revision_id", ondelete="CASCADE"),
        primary_key=True,
    )
    experiment_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    claim_version_id: Mapped[str] = mapped_column(
        String(191),
        ForeignKey("project_claim_versions.claim_version_id", ondelete="RESTRICT"),
        primary_key=True,
    )


class ArtifactPlanClaimLinkRow(Base):
    __tablename__ = "artifact_plan_claim_links"

    plan_revision_id: Mapped[str] = mapped_column(
        String(191),
        ForeignKey("experiment_plan_versions.plan_revision_id", ondelete="CASCADE"),
        primary_key=True,
    )
    artifact_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    claim_version_id: Mapped[str] = mapped_column(
        String(191),
        ForeignKey("project_claim_versions.claim_version_id", ondelete="RESTRICT"),
        primary_key=True,
    )
