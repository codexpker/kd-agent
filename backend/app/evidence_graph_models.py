from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EvidenceGraphNode(BaseModel):
    node_id: str = Field(min_length=1)
    node_type: Literal[
        "paper", "claim", "experiment", "artifact", "evidence", "narrative_move"
    ]
    label: str = Field(min_length=1)
    summary: str | None = None
    local_id: str | None = None
    verified: bool | None = None


class EvidenceGraphEdge(BaseModel):
    source_id: str
    target_id: str
    relationship: Literal[
        "HAS_CLAIM",
        "HAS_EVIDENCE",
        "HAS_EXPERIMENT",
        "HAS_ARTIFACT",
        "HAS_NARRATIVE_MOVE",
        "SUPPORTED_BY",
        "SUPPORTS",
    ]


class EvidenceGraphResponse(BaseModel):
    paper_id: str
    source: Literal["neo4j", "gold_snapshot"]
    status: Literal["ready"] = "ready"
    nodes: list[EvidenceGraphNode]
    edges: list[EvidenceGraphEdge]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_closed_graph(self) -> "EvidenceGraphResponse":
        node_ids = [item.node_id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("evidence graph node ids must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source_id not in known or edge.target_id not in known:
                raise ValueError("evidence graph edge references an unknown node")
        return self
