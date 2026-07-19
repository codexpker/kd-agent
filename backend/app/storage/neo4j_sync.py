from dataclasses import dataclass
from typing import Any, Protocol

from app.models import PaperDeconstruction


class Neo4jDriver(Protocol):
    def session(self) -> Any: ...


@dataclass(frozen=True)
class GraphCounts:
    papers: int
    managed_entities: int


class Neo4jSynchronizer:
    _entity_labels = ("Evidence", "Claim", "Experiment", "Artifact", "NarrativeMove")

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def ensure_schema(self) -> None:
        with self._driver.session() as session:
            session.execute_write(self._ensure_schema)

    def sync(self, record: PaperDeconstruction) -> None:
        with self._driver.session() as session:
            session.execute_write(self._sync_record, record)

    def count_managed(self, paper_id: str) -> GraphCounts:
        query = """
        MATCH (paper:Paper {paper_id: $paper_id})
        OPTIONAL MATCH (paper)-[:HAS_CLAIM|HAS_EVIDENCE|HAS_EXPERIMENT|HAS_ARTIFACT|HAS_NARRATIVE_MOVE]->(entity)
        RETURN count(DISTINCT paper) AS papers, count(DISTINCT entity) AS managed_entities
        """
        with self._driver.session() as session:
            result = session.run(query, paper_id=paper_id).single()
            return GraphCounts(papers=result["papers"], managed_entities=result["managed_entities"])

    @classmethod
    def _ensure_schema(cls, tx: Any) -> None:
        tx.run(
            "CREATE CONSTRAINT paper_id_unique IF NOT EXISTS "
            "FOR (node:Paper) REQUIRE node.paper_id IS UNIQUE"
        )
        for label in cls._entity_labels:
            constraint = f"{label.lower()}_entity_id_unique"
            tx.run(
                f"CREATE CONSTRAINT {constraint} IF NOT EXISTS "
                f"FOR (node:{label}) REQUIRE node.entity_id IS UNIQUE"
            )

    @staticmethod
    def _sync_record(tx: Any, record: PaperDeconstruction) -> None:
        paper_id = record.paper_id
        tx.run(
            """
            MERGE (paper:Paper {paper_id: $paper_id})
            SET paper.title = $title,
                paper.venue = $venue,
                paper.year = $year,
                paper.dataset_version = $dataset_version,
                paper.annotation_status = $annotation_status
            WITH paper
            OPTIONAL MATCH (paper)-[:HAS_CLAIM|HAS_EVIDENCE|HAS_EXPERIMENT|HAS_ARTIFACT|HAS_NARRATIVE_MOVE]->(managed)
            DETACH DELETE managed
            """,
            paper_id=paper_id,
            title=record.title,
            venue=record.venue,
            year=record.year,
            dataset_version=record.dataset_version,
            annotation_status=record.status,
        ).consume()

        evidence_rows = [
            {
                "entity_id": f"{paper_id}:Evidence:{item.id}",
                "local_id": item.id,
                "kind": item.kind,
                "label": item.label,
                "excerpt": item.excerpt,
                "page": item.page,
                "verified": item.verified,
            }
            for item in record.evidence
        ]
        claim_rows = [
            {
                "entity_id": f"{paper_id}:Claim:{item.id}",
                "local_id": item.id,
                "claim_type": item.claim_type,
                "statement": item.statement,
            }
            for item in record.claims
        ]
        experiment_rows = [
            {
                "entity_id": f"{paper_id}:Experiment:{item.id}",
                "local_id": item.id,
                "title": item.title,
                "question": item.question,
                "design_reason": item.design_reason,
                "variables": item.variables,
            }
            for item in record.experiment_intents
        ]
        artifact_rows = [
            {
                "entity_id": f"{paper_id}:Artifact:{item.id}",
                "local_id": item.id,
                "artifact_type": item.artifact_type,
                "label": item.label,
                "role": item.role,
                "why_here": item.why_here,
            }
            for item in record.artifacts
        ]
        narrative_rows = [
            {
                "entity_id": f"{paper_id}:NarrativeMove:{item.id}",
                "local_id": item.id,
                "move_order": item.order,
                "move": item.move,
                "purpose": item.purpose,
            }
            for item in record.narrative_moves
        ]

        Neo4jSynchronizer._merge_entities(tx, paper_id, "Evidence", "HAS_EVIDENCE", evidence_rows)
        Neo4jSynchronizer._merge_entities(tx, paper_id, "Claim", "HAS_CLAIM", claim_rows)
        Neo4jSynchronizer._merge_entities(
            tx, paper_id, "Experiment", "HAS_EXPERIMENT", experiment_rows
        )
        Neo4jSynchronizer._merge_entities(tx, paper_id, "Artifact", "HAS_ARTIFACT", artifact_rows)
        Neo4jSynchronizer._merge_entities(
            tx, paper_id, "NarrativeMove", "HAS_NARRATIVE_MOVE", narrative_rows
        )

        for label, items in (
            ("NarrativeMove", record.narrative_moves),
            ("Claim", record.claims),
            ("Experiment", record.experiment_intents),
            ("Artifact", record.artifacts),
        ):
            evidence_links = [
                {
                    "source_id": f"{paper_id}:{label}:{item.id}",
                    "target_id": f"{paper_id}:Evidence:{evidence_id}",
                }
                for item in items
                for evidence_id in item.evidence_ids
            ]
            Neo4jSynchronizer._merge_links(
                tx, label, "Evidence", "SUPPORTED_BY", evidence_links
            )

        for label, items in (
            ("Experiment", record.experiment_intents),
            ("Artifact", record.artifacts),
        ):
            claim_links = [
                {
                    "source_id": f"{paper_id}:{label}:{item.id}",
                    "target_id": f"{paper_id}:Claim:{claim_id}",
                }
                for item in items
                for claim_id in item.supports_claim_ids
            ]
            Neo4jSynchronizer._merge_links(tx, label, "Claim", "SUPPORTS", claim_links)

    @staticmethod
    def _merge_entities(
        tx: Any, paper_id: str, label: str, relationship: str, rows: list[dict[str, Any]]
    ) -> None:
        tx.run(
            f"""
            UNWIND $rows AS row
            MERGE (entity:{label} {{entity_id: row.entity_id}})
            SET entity += row
            WITH entity
            MATCH (paper:Paper {{paper_id: $paper_id}})
            MERGE (paper)-[:{relationship}]->(entity)
            """,
            paper_id=paper_id,
            rows=rows,
        ).consume()

    @staticmethod
    def _merge_links(
        tx: Any,
        source_label: str,
        target_label: str,
        relationship: str,
        rows: list[dict[str, str]],
    ) -> None:
        tx.run(
            f"""
            UNWIND $rows AS row
            MATCH (source:{source_label} {{entity_id: row.source_id}})
            MATCH (target:{target_label} {{entity_id: row.target_id}})
            MERGE (source)-[:{relationship}]->(target)
            """,
            rows=rows,
        ).consume()
