from typing import Protocol

from app.gold_dataset import GoldDataset
from app.models import DocumentArtifact, DocumentStructure, Section


class DocumentStructureRepository(Protocol):
    def get_document_structure(self, paper_id: str) -> DocumentStructure | None: ...


class DocumentStructureService:
    def __init__(
        self,
        dataset: GoldDataset,
        repository: DocumentStructureRepository | None = None,
    ) -> None:
        self.dataset = dataset
        self.repository = repository

    def get(self, paper_id: str, backend: str = "gold") -> DocumentStructure | None:
        if backend == "gold":
            return self.get_gold_snapshot(paper_id)
        if backend == "mysql":
            if self.repository is None:
                raise RuntimeError("MySQL document backend is not configured")
            parsed = self.repository.get_document_structure(paper_id)
            if parsed is not None and parsed.source == "parsed_pdf":
                return parsed
            return self.get_gold_snapshot(paper_id)
        raise ValueError(f"unsupported document structure backend: {backend}")

    def get_gold_snapshot(self, paper_id: str) -> DocumentStructure | None:
        record = self.dataset.get(paper_id)
        if record is None:
            return None
        sections: list[Section] = []
        seen_sections: set[str] = set()
        for anchor in record.evidence:
            if anchor.kind == "section" and anchor.label not in seen_sections:
                seen_sections.add(anchor.label)
                sections.append(
                    Section(
                        id=f"sec-{len(sections) + 1}",
                        title=anchor.label,
                        level=1,
                        page_start=None,
                        page_end=None,
                    )
                )
        artifacts = [
            DocumentArtifact(
                id=item.id,
                artifact_type=item.artifact_type,
                label=item.label,
                caption=None,
                page=None,
            )
            for item in record.artifacts
        ]
        return DocumentStructure(
            paper_id=paper_id,
            source="gold_snapshot",
            sections=sections,
            artifacts=artifacts,
            references=[],
            evidence=[],
            warnings=[
                "This is a semantic Gold snapshot, not a parsed PDF layout.",
                "Missing page, caption, bbox and body-reference fields are intentionally null.",
            ],
        )
