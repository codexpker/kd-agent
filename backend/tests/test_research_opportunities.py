from collections.abc import Iterable

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import Claim, EvidenceAnchor, PaperDeconstruction
from app.research_models import ResearchOpportunityRequest
from app.research_planning_models import (
    ResearchPlanClaimInput,
    ResearchCoachResponse,
    ResearchPlanRequest,
)
from app.services.research_opportunities import ResearchOpportunityService
from app.services.research_planning import ResearchPlanningService


client = TestClient(app)


class FixtureCorpus:
    def __init__(self, records: Iterable[PaperDeconstruction]) -> None:
        materialized = list(records)
        self._records = {item.paper_id: item for item in materialized}
        self._manifest = {
            "dataset_version": "synthetic-opportunity-fixture",
            "papers": [
                {
                    "paper_id": item.paper_id,
                    "title": item.title,
                    "status": item.status,
                }
                for item in materialized
            ],
        }

    @property
    def manifest(self) -> dict:
        return self._manifest

    def get(self, paper_id: str) -> PaperDeconstruction | None:
        return self._records.get(paper_id)


def _reviewed_record(
    paper_id: str,
    year: int,
    *,
    conflict_statement: str,
    verified: bool = True,
) -> PaperDeconstruction:
    statements = [
        "A deterministic time series anomaly detection method is evaluated.",
        "Cross-domain generalization is not evaluated and remains limited.",
        conflict_statement,
        "The method is validated on a single dataset.",
        "Noise robustness is not evaluated.",
        "Training is expensive and has high cost.",
        "The common benchmark is saturated and has a real-world gap.",
        "Component ablation is insufficient and interactions are not isolated.",
        "The evaluation protocol is inconsistent and non-comparable.",
    ]
    evidence = [
        EvidenceAnchor(
            id=f"ev-{index}",
            kind="sentence",
            label=f"Synthetic evidence {index}",
            excerpt=statement,
            page=index,
            verified=verified,
        )
        for index, statement in enumerate(statements, 1)
    ]
    claims = [
        Claim(
            id=f"claim-{index}",
            claim_type="method" if index == 1 else "boundary",
            statement=statement,
            evidence_ids=[f"ev-{index}"],
        )
        for index, statement in enumerate(statements, 1)
    ]
    return PaperDeconstruction(
        dataset_version="synthetic-opportunity-fixture",
        paper_id=paper_id,
        title=f"Synthetic reviewed time series anomaly detection paper {paper_id}",
        venue="SyntheticVenue",
        year=year,
        status="double_annotated",
        narrative_moves=[],
        claims=claims,
        experiment_intents=[],
        artifacts=[],
        evidence=evidence,
        limitations=["Synthetic fixture only; not a real research result."],
    )


def _synthetic_corpus(*, verified: bool = True) -> FixtureCorpus:
    return FixtureCorpus(
        [
            _reviewed_record(
                "synthetic-a-2021",
                2021,
                conflict_statement="Point adjustment improves the reported score.",
                verified=verified,
            ),
            _reviewed_record(
                "synthetic-b-2023",
                2023,
                conflict_statement="Point adjustment inflates and produces misleading scores.",
                verified=verified,
            ),
        ]
    )


def test_current_offline_corpus_returns_insufficient_evidence() -> None:
    response = client.post(
        "/api/v1/research/opportunities",
        json={"query": "time series anomaly detection"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_evidence"
    assert payload["candidates"] == []
    assert payload["query_plan"]["coverage"]["retrieved_paper_count"] == 5
    assert payload["query_plan"]["coverage"]["included_evidence_paper_count"] == 0
    assert all(
        item["decision"] == "excluded"
        for item in payload["query_plan"]["selections"]
    )
    assert "确定创新点" not in response.text
    assert "confirmed innovation" not in payload["message"].casefold()


def test_synthetic_reviewed_corpus_exercises_all_eight_rules() -> None:
    response = ResearchOpportunityService(_synthetic_corpus()).analyze(
        ResearchOpportunityRequest(query="time series anomaly detection")
    )

    assert response.status == "ok"
    assert "确定创新点" not in response.model_dump_json()
    assert response.query_plan.coverage.corpus_id == "synthetic-opportunity-fixture"
    assert len(response.progress_map) == 2
    assert {item.candidate_type for item in response.candidates} == {
        "shared_unresolved_limitation",
        "conflicting_findings",
        "limited_dataset_validation",
        "missing_robustness_evaluation",
        "high_compute_cost",
        "benchmark_saturation",
        "insufficient_ablation",
        "inconsistent_evaluation_protocol",
    }
    for candidate in response.candidates:
        assert candidate.output_type == "research_opportunity_candidate"
        assert candidate.evidence_paper_count == 2
        assert candidate.supporting_evidence
        assert all(
            item.evidence_anchor.verified
            for item in [
                *candidate.supporting_evidence,
                *candidate.conflicting_evidence,
            ]
        )
        assert candidate.conflict_evidence_note
        assert candidate.confidence.score <= 0.85
        assert candidate.confidence.calculation
        assert candidate.human_confirmation_required
        assert candidate.applicable_conditions
        assert candidate.prohibited_conclusions

    conflict = next(
        item
        for item in response.candidates
        if item.candidate_type == "conflicting_findings"
    )
    assert conflict.supporting_evidence
    assert conflict.conflicting_evidence


def test_unverified_synthetic_anchors_cannot_generate_candidates() -> None:
    response = ResearchOpportunityService(
        _synthetic_corpus(verified=False)
    ).analyze(ResearchOpportunityRequest(query="time series anomaly detection"))

    assert response.status == "insufficient_evidence"
    assert response.candidates == []
    assert response.query_plan.coverage.included_evidence_paper_count == 0
    assert all(
        item.reason == "Record has no verified EvidenceAnchor."
        for item in response.query_plan.selections
    )


def test_minimum_distinct_paper_threshold_is_enforced() -> None:
    response = ResearchOpportunityService(_synthetic_corpus()).analyze(
        ResearchOpportunityRequest(
            query="time series anomaly detection", minimum_evidence_papers=3
        )
    )

    assert response.status == "insufficient_evidence"
    assert response.candidates == []


def test_query_plan_reports_year_filter_exclusions() -> None:
    response = ResearchOpportunityService(_synthetic_corpus()).analyze(
        ResearchOpportunityRequest(
            query="time series anomaly detection", year_from=2023, year_to=2024
        )
    )

    assert response.status == "insufficient_evidence"
    assert any(
        item.reason == "Paper is earlier than year_from."
        for item in response.query_plan.selections
    )


def test_api_rejects_invalid_request_ranges_and_thresholds() -> None:
    reversed_years = client.post(
        "/api/v1/research/opportunities",
        json={
            "query": "time series anomaly detection",
            "year_from": 2025,
            "year_to": 2020,
        },
    )
    invalid_threshold = client.post(
        "/api/v1/research/opportunities",
        json={
            "query": "time series anomaly detection",
            "minimum_evidence_papers": 1,
        },
    )

    assert reversed_years.status_code == 422
    assert invalid_threshold.status_code == 422


def _project_claim() -> ResearchPlanClaimInput:
    return ResearchPlanClaimInput(
        research_question=(
            "Does the proposed detector remain reliable under controlled domain shift?"
        ),
        hypothesis=(
            "The proposed method retains more detection quality than comparable baselines "
            "as the predeclared shift severity increases."
        ),
        proposed_method="A user-defined association-aware detector",
    )


def test_current_offline_corpus_blocks_experiment_plan_generation() -> None:
    response = client.post(
        "/api/v1/research/experiment-plans",
        json={
            "opportunity": {"query": "time series anomaly detection"},
            "candidate_id": "roc-not-available",
            "project_claim": _project_claim().model_dump(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_evidence"
    assert payload["candidate"] is None
    assert payload["plan"] is None
    assert payload["project_claim"]["origin"] == "user_supplied"


def test_synthetic_candidate_generates_closed_experiment_and_artifact_plan() -> None:
    corpus = _synthetic_corpus()
    opportunity_request = ResearchOpportunityRequest(
        query="time series anomaly detection"
    )
    opportunity = ResearchOpportunityService(corpus).analyze(opportunity_request)
    candidate = next(
        item
        for item in opportunity.candidates
        if item.candidate_type == "shared_unresolved_limitation"
    )
    response = ResearchPlanningService(corpus).create(
        ResearchPlanRequest(
            opportunity=opportunity_request,
            candidate_id=candidate.candidate_id,
            project_claim=_project_claim(),
        )
    )

    assert response.status == "ready_for_review"
    assert response.plan is not None
    assert response.plan.project_claim == _project_claim()
    assert _project_claim().hypothesis in response.plan.experiments[0].validation_goal
    assert {item.experiment_type for item in response.plan.experiments} == {
        "main_comparison",
        "baseline_coverage",
        "ablation",
        "sensitivity",
        "robustness",
        "failure_case_analysis",
    }
    assert {item.artifact_type for item in response.plan.artifacts} == {
        "result_table",
        "ablation_table",
        "sensitivity_curve",
        "robustness_plot",
        "failure_case_panel",
        "tradeoff_plot",
    }
    experiment_ids = {
        item.experiment_id for item in response.plan.experiments
    }
    assert all(
        set(item.source_experiment_ids) <= experiment_ids
        for item in response.plan.artifacts
    )
    assert all(
        item.validation_goal
        and item.variables
        and item.output_fields
        and item.evidence_boundary
        for item in response.plan.artifacts
    )
    snapshot_ids = {
        (item.paper_id, item.evidence_anchor.id)
        for item in response.plan.evidence_snapshot
    }
    assert snapshot_ids
    assert all(
        (reference.paper_id, reference.evidence_anchor_id) in snapshot_ids
        for experiment in response.plan.experiments
        for reference in experiment.rationale.evidence_references
    )
    assert all(
        experiment.rationale.inference_type == "system_planning_inference"
        for experiment in response.plan.experiments
    )
    assert "contains no experimental results" in response.message

    invalid_payload = response.model_dump()
    invalid_payload["plan"]["source_candidate_id"] = "roc-unrelated"
    with pytest.raises(ValidationError, match="source candidate"):
        ResearchCoachResponse.model_validate(invalid_payload)


def test_experiment_plan_api_rejects_candidate_outside_current_query(
    monkeypatch,
) -> None:
    corpus = _synthetic_corpus()
    monkeypatch.setattr("app.api.get_gold_dataset", lambda: corpus)

    response = client.post(
        "/api/v1/research/experiment-plans",
        json={
            "opportunity": {"query": "time series anomaly detection"},
            "candidate_id": "roc-does-not-exist",
            "project_claim": _project_claim().model_dump(),
        },
    )

    assert response.status_code == 404
    assert "not available" in response.json()["detail"]


def test_experiment_plan_api_returns_synthetic_positive_path(monkeypatch) -> None:
    corpus = _synthetic_corpus()
    opportunity_request = ResearchOpportunityRequest(
        query="time series anomaly detection"
    )
    candidate = ResearchOpportunityService(corpus).analyze(
        opportunity_request
    ).candidates[0]
    monkeypatch.setattr("app.api.get_gold_dataset", lambda: corpus)

    response = client.post(
        "/api/v1/research/experiment-plans",
        json={
            "opportunity": opportunity_request.model_dump(),
            "candidate_id": candidate.candidate_id,
            "project_claim": _project_claim().model_dump(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready_for_review"
    assert payload["plan"]["source_candidate_id"] == candidate.candidate_id
    assert payload["plan"]["project_claim"]["origin"] == "user_supplied"


def test_experiment_plan_api_rejects_underspecified_project_claim() -> None:
    response = client.post(
        "/api/v1/research/experiment-plans",
        json={
            "opportunity": {"query": "time series anomaly detection"},
            "candidate_id": "roc-anything",
            "project_claim": {
                "research_question": "too short",
                "hypothesis": "too short",
                "proposed_method": "x",
            },
        },
    )

    assert response.status_code == 422
