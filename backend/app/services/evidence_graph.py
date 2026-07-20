from typing import Any, Protocol

from app.evidence_graph_models import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceGraphResponse,
)
from app.gold_dataset import GoldDataset
from app.models import PaperDeconstruction


class EvidenceGraphNotFoundError(LookupError):
    pass


class EvidenceGraphUnavailableError(RuntimeError):
    pass


class Neo4jDriver(Protocol):
    def session(self) -> Any: ...


class GoldEvidenceGraphSource:
    def __init__(self, dataset: GoldDataset) -> None:
        self._dataset = dataset

    def get(self, paper_id: str) -> EvidenceGraphResponse:
        record = self._dataset.get(paper_id)
        if record is None:
            raise EvidenceGraphNotFoundError(paper_id)
        return self._build(record)

    @staticmethod
    def _build(record: PaperDeconstruction) -> EvidenceGraphResponse:
        paper_node_id = f"paper:{record.paper_id}"
        nodes = [
            EvidenceGraphNode(
                node_id=paper_node_id,
                node_type="paper",
                label=record.title,
                summary=f"{record.venue} · {record.year} · {record.status}",
                local_id=record.paper_id,
            )
        ]
        edges: list[EvidenceGraphEdge] = []

        def add_node(
            node_type: str,
            local_id: str,
            label: str,
            summary: str | None,
            relationship: str,
            verified: bool | None = None,
        ) -> str:
            node_id = f"{record.paper_id}:{node_type}:{local_id}"
            nodes.append(
                EvidenceGraphNode(
                    node_id=node_id,
                    node_type=node_type,
                    label=label,
                    summary=summary,
                    local_id=local_id,
                    verified=verified,
                )
            )
            edges.append(
                EvidenceGraphEdge(
                    source_id=paper_node_id,
                    target_id=node_id,
                    relationship=relationship,
                )
            )
            return node_id

        evidence_ids = {
            item.id: add_node(
                "evidence",
                item.id,
                item.label,
                item.excerpt,
                "HAS_EVIDENCE",
                item.verified,
            )
            for item in record.evidence
        }
        claim_ids = {
            item.id: add_node(
                "claim", item.id, item.statement, item.claim_type, "HAS_CLAIM"
            )
            for item in record.claims
        }
        experiment_ids = {
            item.id: add_node(
                "experiment", item.id, item.title, item.question, "HAS_EXPERIMENT"
            )
            for item in record.experiment_intents
        }
        artifact_ids = {
            item.id: add_node(
                "artifact", item.id, item.label, item.role, "HAS_ARTIFACT"
            )
            for item in record.artifacts
        }
        narrative_ids = {
            item.id: add_node(
                "narrative_move",
                item.id,
                item.move,
                item.purpose,
                "HAS_NARRATIVE_MOVE",
            )
            for item in record.narrative_moves
        }

        for node_ids, items in (
            (narrative_ids, record.narrative_moves),
            (claim_ids, record.claims),
            (experiment_ids, record.experiment_intents),
            (artifact_ids, record.artifacts),
        ):
            for item in items:
                for evidence_id in item.evidence_ids:
                    edges.append(
                        EvidenceGraphEdge(
                            source_id=node_ids[item.id],
                            target_id=evidence_ids[evidence_id],
                            relationship="SUPPORTED_BY",
                        )
                    )

        for node_ids, items in (
            (experiment_ids, record.experiment_intents),
            (artifact_ids, record.artifacts),
        ):
            for item in items:
                for claim_id in item.supports_claim_ids:
                    edges.append(
                        EvidenceGraphEdge(
                            source_id=node_ids[item.id],
                            target_id=claim_ids[claim_id],
                            relationship="SUPPORTS",
                        )
                    )

        return EvidenceGraphResponse(
            paper_id=record.paper_id,
            source="gold_snapshot",
            nodes=nodes,
            edges=edges,
            warnings=[
                "This graph is derived from the reviewed development seed, not queried from Neo4j.",
                "Unverified EvidenceAnchor nodes remain visibly unverified and do not claim PDF page locations.",
            ],
        )


class Neo4jEvidenceGraphSource:
    _node_query = """
    MATCH (paper:Paper {paper_id: $paper_id})
    OPTIONAL MATCH (paper)-[]->(entity)
    RETURN paper, collect(DISTINCT entity) AS entities
    """
    _edge_query = """
    MATCH (paper:Paper {paper_id: $paper_id})-[relationship]->(entity)
    RETURN 'paper:' + paper.paper_id AS source_id,
           entity.entity_id AS target_id,
           type(relationship) AS relationship
    UNION ALL
    MATCH (paper:Paper {paper_id: $paper_id})-[]->(source)
          -[relationship:SUPPORTED_BY|SUPPORTS]->(target)
    RETURN source.entity_id AS source_id,
           target.entity_id AS target_id,
           type(relationship) AS relationship
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def get(self, paper_id: str) -> EvidenceGraphResponse:
        try:
            with self._driver.session() as session:
                node_record = session.run(self._node_query, paper_id=paper_id).single()
                if node_record is None or node_record["paper"] is None:
                    raise EvidenceGraphNotFoundError(paper_id)
                paper = dict(node_record["paper"])
                entities = [dict(item) for item in node_record["entities"] if item is not None]
                edge_rows = [
                    dict(item)
                    for item in session.run(self._edge_query, paper_id=paper_id)
                ]
        except EvidenceGraphNotFoundError:
            raise
        except Exception as exc:
            raise EvidenceGraphUnavailableError("Neo4j evidence graph is unavailable") from exc

        nodes = [
            EvidenceGraphNode(
                node_id=f"paper:{paper_id}",
                node_type="paper",
                label=str(paper.get("title") or paper_id),
                summary=" · ".join(
                    str(value)
                    for value in (
                        paper.get("venue"),
                        paper.get("year"),
                        paper.get("annotation_status"),
                    )
                    if value is not None
                ),
                local_id=paper_id,
            )
        ]
        for entity in entities:
            node_type = _node_type_from_entity_id(str(entity["entity_id"]))
            nodes.append(
                EvidenceGraphNode(
                    node_id=str(entity["entity_id"]),
                    node_type=node_type,
                    label=_entity_label(entity, node_type),
                    summary=_entity_summary(entity, node_type),
                    local_id=str(entity.get("local_id") or "") or None,
                    verified=(
                        bool(entity.get("verified")) if node_type == "evidence" else None
                    ),
                )
            )
        edges = [EvidenceGraphEdge.model_validate(item) for item in edge_rows]
        return EvidenceGraphResponse(
            paper_id=paper_id,
            source="neo4j",
            nodes=nodes,
            edges=edges,
            warnings=[
                "Neo4j is a rebuildable relationship index; MySQL remains authoritative.",
            ],
        )


def _node_type_from_entity_id(entity_id: str) -> str:
    label = entity_id.split(":", 2)[1] if entity_id.count(":") >= 2 else ""
    mapping = {
        "Claim": "claim",
        "Experiment": "experiment",
        "Artifact": "artifact",
        "Evidence": "evidence",
        "NarrativeMove": "narrative_move",
    }
    if label not in mapping:
        raise EvidenceGraphUnavailableError(f"unsupported Neo4j entity label: {label}")
    return mapping[label]


def _entity_label(entity: dict[str, Any], node_type: str) -> str:
    fields = {
        "claim": ("statement", "local_id"),
        "experiment": ("title", "question", "local_id"),
        "artifact": ("label", "role", "local_id"),
        "evidence": ("label", "excerpt", "local_id"),
        "narrative_move": ("move", "purpose", "local_id"),
    }[node_type]
    return next((str(entity[key]) for key in fields if entity.get(key)), node_type)


def _entity_summary(entity: dict[str, Any], node_type: str) -> str | None:
    fields = {
        "claim": ("claim_type",),
        "experiment": ("question", "design_reason"),
        "artifact": ("role", "why_here"),
        "evidence": ("excerpt",),
        "narrative_move": ("purpose",),
    }[node_type]
    return next((str(entity[key]) for key in fields if entity.get(key)), None)
