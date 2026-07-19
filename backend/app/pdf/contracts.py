import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _validate_bbox(value: list[float] | None) -> list[float] | None:
    if value is None:
        return None
    if len(value) != 4 or not all(math.isfinite(item) for item in value):
        raise ValueError("bbox must contain four finite coordinates")
    if value[2] < value[0] or value[3] < value[1]:
        raise ValueError("bbox maximum coordinates must not precede minimum coordinates")
    return value


class ParsedSection(BaseModel):
    id: str
    title: str
    level: int = Field(ge=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    heading_bbox: list[float] | None = None

    _bbox = field_validator("heading_bbox")(_validate_bbox)

    @model_validator(mode="after")
    def validate_page_range(self) -> "ParsedSection":
        if self.page_end < self.page_start:
            raise ValueError("section page_end must not precede page_start")
        return self


class ParsedArtifact(BaseModel):
    id: str
    artifact_type: Literal["figure", "table"]
    label: str
    caption: str
    page: int = Field(ge=1)
    bbox: list[float] | None = None
    caption_bbox: list[float] | None = None
    markdown: str | None = None
    table_data: list[list[str]] | None = None

    _bbox = field_validator("bbox")(_validate_bbox)
    _caption_bbox = field_validator("caption_bbox")(_validate_bbox)

    @model_validator(mode="after")
    def validate_table_fields(self) -> "ParsedArtifact":
        if self.artifact_type != "table" and (
            self.markdown is not None or self.table_data is not None
        ):
            raise ValueError("structured table fields are only valid for table artifacts")
        return self


class ParsedReference(BaseModel):
    id: str
    artifact_id: str
    text: str
    page: int = Field(ge=1)
    bbox: list[float] | None = None

    _bbox = field_validator("bbox")(_validate_bbox)


class ParsedDocument(BaseModel):
    parser_name: str
    parser_version: str
    file_sha256: str
    page_count: int = Field(ge=1)
    sections: list[ParsedSection]
    artifacts: list[ParsedArtifact]
    references: list[ParsedReference]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_layout_graph(self) -> "ParsedDocument":
        if len(self.file_sha256) != 64:
            raise ValueError("file_sha256 must contain 64 hexadecimal characters")
        try:
            int(self.file_sha256, 16)
        except ValueError as exc:
            raise ValueError("file_sha256 must contain 64 hexadecimal characters") from exc
        section_ids = [item.id for item in self.sections]
        artifact_ids = [item.id for item in self.artifacts]
        reference_ids = [item.id for item in self.references]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("duplicate parsed section id")
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("duplicate parsed artifact id")
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("duplicate parsed reference id")
        unknown_artifacts = {
            item.artifact_id for item in self.references
        } - set(artifact_ids)
        if unknown_artifacts:
            raise ValueError(f"unknown parsed artifact ids: {sorted(unknown_artifacts)}")
        pages = [
            *(item.page_end for item in self.sections),
            *(item.page for item in self.artifacts),
            *(item.page for item in self.references),
        ]
        if any(page > self.page_count for page in pages):
            raise ValueError("parsed layout page exceeds page_count")
        return self


class PersistenceRight(BaseModel):
    basis: Literal["open_full_text", "user_private_copy", "institution_authorized"]
    confirmed_by: str = Field(min_length=1)
    note: str = ""
