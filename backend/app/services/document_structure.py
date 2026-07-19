from app.gold_dataset import GoldDataset
from app.models import DocumentArtifact, DocumentStructure, Section


class DocumentStructureService:
    def __init__(self, dataset: GoldDataset) -> None:
        self.dataset = dataset

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
                        page_start=anchor.page,
                        page_end=anchor.page,
                    )
                )
        artifacts = [
            DocumentArtifact(
                id=item.id,
                artifact_type=item.artifact_type,
                label=item.label,
                caption=None,
                page=next(
                    (anchor.page for anchor in record.evidence if anchor.id in item.evidence_ids),
                    None,
                ),
            )
            for item in record.artifacts
        ]
        return DocumentStructure(
            paper_id=paper_id,
            source="gold_snapshot",
            sections=sections,
            artifacts=artifacts,
            references=[],
            evidence=record.evidence,
            warnings=[
                "This is a semantic Gold snapshot, not a parsed PDF layout.",
                "Missing page, caption, bbox and body-reference fields are intentionally null.",
            ],
        )

