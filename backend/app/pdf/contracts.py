from typing import Literal

from pydantic import BaseModel, Field


class ParsedSection(BaseModel):
    id: str
    title: str
    level: int = Field(ge=1)
    page_start: int
    page_end: int


class ParsedArtifact(BaseModel):
    id: str
    artifact_type: Literal["figure", "table"]
    label: str
    caption: str
    page: int
    bbox: list[float] | None = None
    markdown: str | None = None


class ParsedReference(BaseModel):
    id: str
    artifact_id: str
    text: str
    page: int


class ParsedDocument(BaseModel):
    parser_name: str
    parser_version: str
    file_sha256: str
    sections: list[ParsedSection]
    artifacts: list[ParsedArtifact]
    references: list[ParsedReference]
    warnings: list[str] = []


class PersistenceRight(BaseModel):
    basis: Literal["open_full_text", "user_private_copy", "institution_authorized"]
    confirmed_by: str = Field(min_length=1)
    note: str = ""

