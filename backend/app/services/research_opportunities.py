import hashlib
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from app.models import EvidenceAnchor, PaperDeconstruction
from app.research_models import (
    ConfidenceAssessment,
    CorpusCoverage,
    OpportunityEvidence,
    OpportunityType,
    PaperSelection,
    QueryPlan,
    ResearchOpportunityCandidate,
    ResearchOpportunityRequest,
    ResearchOpportunityResponse,
    ResearchProgressMilestone,
)


class ResearchCorpus(Protocol):
    @property
    def manifest(self) -> dict: ...

    def get(self, paper_id: str) -> PaperDeconstruction | None: ...


@dataclass(frozen=True)
class OpportunityRule:
    candidate_type: OpportunityType
    topic_key: str
    required_term_groups: tuple[tuple[str, ...], ...]
    conflict_term_groups: tuple[tuple[str, ...], ...] = ()
    problem_description: str = ""
    human_confirmation: tuple[str, ...] = ()
    applicable_conditions: tuple[str, ...] = ()
    prohibited_conclusions: tuple[str, ...] = ()


RULES = (
    OpportunityRule(
        candidate_type="shared_unresolved_limitation",
        topic_key="cross-domain-generalization",
        required_term_groups=(
            ("cross-domain", "cross domain", "unseen domain", "generalization"),
            ("not evaluated", "limited", "unresolved", "future work"),
        ),
        problem_description=(
            "Multiple papers leave cross-domain generalization unresolved; test whether "
            "the reported mechanisms transfer beyond their evaluated domains."
        ),
        human_confirmation=(
            "Verify that each paper describes the limitation rather than the curator.",
            "Check later work that may already address cross-domain transfer.",
        ),
        applicable_conditions=(
            "Applies when the included papers study comparable anomaly-detection tasks.",
        ),
        prohibited_conclusions=(
            "Does not establish that cross-domain transfer is novel or unsolved globally.",
        ),
    ),
    OpportunityRule(
        candidate_type="conflicting_findings",
        topic_key="point-adjustment-effect",
        required_term_groups=(
            ("point adjustment", "point-adjustment"),
            ("improves", "benefits", "raises"),
        ),
        conflict_term_groups=(
            ("point adjustment", "point-adjustment"),
            ("inflates", "misleading", "degrades", "does not improve"),
        ),
        problem_description=(
            "The included papers report conflicting conclusions about point adjustment; "
            "a controlled protocol comparison may explain when the conclusions diverge."
        ),
        human_confirmation=(
            "Confirm that the compared metrics and anomaly labels are compatible.",
            "Inspect whether the apparent conflict is caused by implementation details.",
        ),
        applicable_conditions=(
            "Applies only to papers using comparable point-adjustment definitions.",
        ),
        prohibited_conclusions=(
            "Does not prove either protocol conclusion is universally correct.",
        ),
    ),
    OpportunityRule(
        candidate_type="limited_dataset_validation",
        topic_key="dataset-diversity",
        required_term_groups=(
            ("single dataset", "one dataset", "few datasets", "limited datasets"),
        ),
        problem_description=(
            "Evidence is concentrated on a small dataset set; broader validation could "
            "test whether the reported effect depends on benchmark selection."
        ),
        human_confirmation=(
            "Count the actual datasets and separate datasets from dataset variants.",
            "Check whether later replications already broadened the evaluation.",
        ),
        applicable_conditions=(
            "Applies when the cited papers use comparable tasks and metrics.",
        ),
        prohibited_conclusions=(
            "Does not imply the reported results are invalid on their evaluated datasets.",
        ),
    ),
    OpportunityRule(
        candidate_type="missing_robustness_evaluation",
        topic_key="noise-robustness",
        required_term_groups=(
            ("noise", "noisy"),
            ("not evaluated", "missing", "without", "limited"),
        ),
        problem_description=(
            "Noise robustness is not adequately tested in the included evidence; a "
            "controlled corruption study could define the method's operating boundary."
        ),
        human_confirmation=(
            "Confirm the papers do not contain an overlooked noise experiment.",
            "Select corruption processes that match plausible deployment conditions.",
        ),
        applicable_conditions=("Applies to comparable input and anomaly settings.",),
        prohibited_conclusions=(
            "Does not establish that the methods fail under noise.",
        ),
    ),
    OpportunityRule(
        candidate_type="missing_robustness_evaluation",
        topic_key="missing-value-robustness",
        required_term_groups=(
            ("missing value", "missing-value", "missing data"),
            ("not evaluated", "missing", "without", "limited"),
        ),
        problem_description=(
            "Missing-value robustness is under-tested; a controlled missingness study "
            "could identify which assumptions fail as observations disappear."
        ),
        human_confirmation=(
            "Confirm the papers did not evaluate missingness under another name.",
            "Choose MCAR, MAR or deployment-specific missingness mechanisms.",
        ),
        applicable_conditions=("Applies when preprocessing is held comparable.",),
        prohibited_conclusions=(
            "Does not establish robustness or failure before experiments are run.",
        ),
    ),
    OpportunityRule(
        candidate_type="missing_robustness_evaluation",
        topic_key="concept-drift-robustness",
        required_term_groups=(
            ("concept drift", "distribution shift"),
            ("not evaluated", "missing", "without", "limited"),
        ),
        problem_description=(
            "Concept drift is not adequately evaluated; chronological stress tests could "
            "measure how quickly detection quality changes after a distribution shift."
        ),
        human_confirmation=(
            "Verify that the cited setting is temporal drift rather than static domain shift.",
        ),
        applicable_conditions=("Applies to temporally ordered deployment settings.",),
        prohibited_conclusions=("Does not prove that online adaptation is required.",),
    ),
    OpportunityRule(
        candidate_type="high_compute_cost",
        topic_key="training-inference-efficiency",
        required_term_groups=(
            ("training", "inference", "compute", "latency", "memory"),
            ("high cost", "expensive", "overhead", "slow", "resource-intensive"),
        ),
        problem_description=(
            "Reported gains may carry high training or inference cost; an efficiency-aware "
            "comparison could determine whether the trade-off holds under fixed budgets."
        ),
        human_confirmation=(
            "Reproduce runtime and memory measurements on comparable hardware.",
            "Separate implementation overhead from algorithmic complexity.",
        ),
        applicable_conditions=("Applies under explicitly fixed compute budgets.",),
        prohibited_conclusions=(
            "Does not establish that a method is impractical without measured costs.",
        ),
    ),
    OpportunityRule(
        candidate_type="benchmark_saturation",
        topic_key="benchmark-realism",
        required_term_groups=(
            ("benchmark", "dataset"),
            ("saturated", "ceiling", "real-world gap", "real scenario"),
        ),
        problem_description=(
            "Common benchmarks may be saturated or weak proxies for deployment; a curated "
            "real-scenario evaluation could test whether rankings remain stable."
        ),
        human_confirmation=(
            "Verify that saturation is supported by comparable protocols, not raw scores alone.",
            "Define what makes a target scenario operationally realistic.",
        ),
        applicable_conditions=("Applies to repeatedly reused benchmark families.",),
        prohibited_conclusions=(
            "Does not prove that a benchmark is useless or that deployment gains will follow.",
        ),
    ),
    OpportunityRule(
        candidate_type="insufficient_ablation",
        topic_key="component-attribution",
        required_term_groups=(
            ("ablation", "component"),
            ("insufficient", "missing", "limited", "not isolated"),
        ),
        problem_description=(
            "Component attribution remains unclear because ablations are incomplete; a "
            "factorial ablation could separate essential components from added complexity."
        ),
        human_confirmation=(
            "Check appendices and supplementary material for omitted ablations.",
            "Define combinations that isolate interactions rather than one-at-a-time effects.",
        ),
        applicable_conditions=("Applies when components can be disabled comparably.",),
        prohibited_conclusions=(
            "Does not establish that any component is unnecessary before ablation.",
        ),
    ),
    OpportunityRule(
        candidate_type="inconsistent_evaluation_protocol",
        topic_key="evaluation-comparability",
        required_term_groups=(
            ("evaluation", "protocol", "metric", "point adjustment"),
            ("inconsistent", "different", "non-comparable", "not comparable"),
        ),
        problem_description=(
            "Evaluation protocols are not directly comparable; a common protocol could "
            "separate model effects from scoring and preprocessing choices."
        ),
        human_confirmation=(
            "Reconstruct preprocessing, thresholding and metric definitions for every paper.",
            "Confirm that raw predictions are available for fair re-scoring.",
        ),
        applicable_conditions=("Applies only when tasks and labels can be aligned.",),
        prohibited_conclusions=(
            "Does not establish a new model advantage or invalidate prior rankings by itself.",
        ),
    ),
)


@dataclass(frozen=True)
class EvidenceStatement:
    paper: PaperDeconstruction
    text: str
    anchors: tuple[EvidenceAnchor, ...]


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _matched_terms(
    text: str, groups: tuple[tuple[str, ...], ...]
) -> list[str] | None:
    normalized = _normalize(text)
    matched: list[str] = []
    for group in groups:
        term = next((item for item in group if _normalize(item) in normalized), None)
        if term is None:
            return None
        matched.append(term)
    return matched


class ResearchOpportunityService:
    def __init__(self, corpus: ResearchCorpus) -> None:
        self.corpus = corpus

    def analyze(
        self, request: ResearchOpportunityRequest
    ) -> ResearchOpportunityResponse:
        included, selections = self._retrieve(request)
        coverage = self._coverage(included, len(selections))
        plan = QueryPlan(
            query=request.query,
            steps=[
                "Search the local reviewed-paper registry using deterministic query terms.",
                "Exclude queued, development-seed and unverified-evidence records.",
                "Match verified EvidenceAnchor-linked statements against versioned rules.",
                "Require distinct-paper coverage before emitting any candidate.",
            ],
            inclusion_rules=[
                "Paper status is double_annotated or frozen.",
                "At least one cited EvidenceAnchor is verified.",
                "Paper year is inside the requested range.",
                "Paper content matches at least one normalized query term.",
            ],
            exclusion_rules=[
                "Queued and development_seed records cannot support an opportunity.",
                "Unverified or unresolved EvidenceAnchor IDs are excluded.",
                "Rules below minimum distinct-paper coverage emit no candidate.",
            ],
            selections=selections,
            coverage=coverage,
            possible_omissions=[
                "The offline corpus may omit recent, paywalled or unregistered papers.",
                "Deterministic phrase rules can miss synonyms and implicit limitations.",
                "Limitations without a verified EvidenceAnchor are intentionally ignored.",
                "Queued and single-reviewer records are visible in the plan but excluded.",
            ],
        )
        candidates = self._apply_rules(included, request, coverage)
        progress_map = self._progress_map(included)
        if not candidates:
            return ResearchOpportunityResponse(
                status="insufficient_evidence",
                disclaimer=self._disclaimer(),
                message=(
                    "No rule reached the required verified distinct-paper coverage; "
                    "no research opportunity candidate was emitted."
                ),
                query_plan=plan,
                progress_map=progress_map,
                candidates=[],
            )
        return ResearchOpportunityResponse(
            status="ok",
            disclaimer=self._disclaimer(),
            message=(
                "Candidates are evidence-backed questions for human review, not confirmed "
                "innovation claims."
            ),
            query_plan=plan,
            progress_map=progress_map,
            candidates=candidates,
        )

    @staticmethod
    def _disclaimer() -> str:
        return (
            "Research Opportunity Candidate only. The system does not establish novelty, "
            "priority, feasibility or a guaranteed research contribution."
        )

    def _retrieve(
        self, request: ResearchOpportunityRequest
    ) -> tuple[list[PaperDeconstruction], list[PaperSelection]]:
        tokens = [item for item in _normalize(request.query).split() if len(item) >= 2]
        included: list[PaperDeconstruction] = []
        selections: list[PaperSelection] = []
        for manifest_item in self.corpus.manifest.get("papers", []):
            paper_id = str(manifest_item["paper_id"])
            record = self.corpus.get(paper_id)
            title = str(manifest_item.get("title", paper_id))
            status = str(manifest_item.get("status", "unknown"))
            year = self._manifest_year(paper_id, record)
            reason = "Included as reviewed, verified and query-matched evidence."
            decision: Literal["included", "excluded"] = "included"
            if record is None:
                decision = "excluded"
                reason = "No publicly loadable reviewed record; queued metadata is not evidence."
            elif record.status not in {"double_annotated", "frozen"}:
                decision = "excluded"
                reason = f"Record status {record.status} is not review-complete."
            elif not any(item.verified for item in record.evidence):
                decision = "excluded"
                reason = "Record has no verified EvidenceAnchor."
            elif request.year_from is not None and record.year < request.year_from:
                decision = "excluded"
                reason = "Paper is earlier than year_from."
            elif request.year_to is not None and record.year > request.year_to:
                decision = "excluded"
                reason = "Paper is later than year_to."
            elif tokens and not any(token in self._paper_text(record) for token in tokens):
                decision = "excluded"
                reason = "No normalized query term matched the reviewed record."
            if decision == "included" and record is not None:
                included.append(record)
            selections.append(
                PaperSelection(
                    paper_id=paper_id,
                    title=title,
                    year=year,
                    status=status,
                    decision=decision,
                    reason=reason,
                )
            )
        return included, selections

    @staticmethod
    def _manifest_year(
        paper_id: str, record: PaperDeconstruction | None
    ) -> int:
        if record is not None:
            return record.year
        try:
            return int(paper_id.rsplit("-", 1)[-1])
        except ValueError:
            return 1900

    @staticmethod
    def _paper_text(record: PaperDeconstruction) -> str:
        values = [
            record.title,
            record.venue,
            *(item.statement for item in record.claims),
            *(item.question for item in record.experiment_intents),
            *(item.design_reason for item in record.experiment_intents),
            *record.limitations,
        ]
        return _normalize(" ".join(values))

    def _coverage(
        self, included: list[PaperDeconstruction], retrieved_count: int
    ) -> CorpusCoverage:
        years = [item.year for item in included]
        return CorpusCoverage(
            corpus_id=str(self.corpus.manifest.get("dataset_version", "unknown")),
            retrieved_paper_count=retrieved_count,
            included_evidence_paper_count=len(included),
            year_from=min(years) if years else None,
            year_to=max(years) if years else None,
            venues=sorted({item.venue for item in included}),
            paper_ids=sorted(item.paper_id for item in included),
        )

    @staticmethod
    def _statements(
        records: list[PaperDeconstruction],
    ) -> list[EvidenceStatement]:
        statements: list[EvidenceStatement] = []
        for record in records:
            anchors = {item.id: item for item in record.evidence if item.verified}
            for claim in record.claims:
                cited = tuple(
                    anchors[item]
                    for item in claim.evidence_ids
                    if item in anchors
                )
                if cited:
                    statements.append(
                        EvidenceStatement(record, claim.statement, cited)
                    )
            for experiment in record.experiment_intents:
                cited = tuple(
                    anchors[item]
                    for item in experiment.evidence_ids
                    if item in anchors
                )
                if cited:
                    text = " ".join(
                        [
                            experiment.title,
                            experiment.question,
                            experiment.design_reason,
                            *experiment.variables,
                        ]
                    )
                    statements.append(EvidenceStatement(record, text, cited))
        return statements

    def _apply_rules(
        self,
        records: list[PaperDeconstruction],
        request: ResearchOpportunityRequest,
        coverage: CorpusCoverage,
    ) -> list[ResearchOpportunityCandidate]:
        statements = self._statements(records)
        candidates: list[ResearchOpportunityCandidate] = []
        for rule in RULES:
            supporting = self._evidence_for_rule(
                statements, rule.required_term_groups, "supporting"
            )
            conflicting = (
                self._evidence_for_rule(
                    statements, rule.conflict_term_groups, "conflicting"
                )
                if rule.conflict_term_groups
                else []
            )
            paper_ids = {
                item.paper_id for item in [*supporting, *conflicting]
            }
            if len(paper_ids) < request.minimum_evidence_papers:
                continue
            if rule.candidate_type == "conflicting_findings" and not conflicting:
                continue
            candidate_id = hashlib.sha256(
                f"{rule.candidate_type}:{rule.topic_key}:{','.join(sorted(paper_ids))}".encode()
            ).hexdigest()[:16]
            candidates.append(
                ResearchOpportunityCandidate(
                    candidate_id=f"roc-{candidate_id}",
                    candidate_type=rule.candidate_type,
                    topic_key=rule.topic_key,
                    problem_description=rule.problem_description,
                    evidence_paper_count=len(paper_ids),
                    supporting_evidence=supporting,
                    conflicting_evidence=conflicting,
                    conflict_evidence_note=(
                        "Conflicting evidence matched the same deterministic topic rule."
                        if conflicting
                        else "No conflicting evidence matched in the included corpus."
                    ),
                    corpus_coverage=coverage,
                    confidence=self._confidence(
                        len(paper_ids),
                        len(supporting) + len(conflicting),
                        bool(conflicting),
                        request.minimum_evidence_papers,
                    ),
                    human_confirmation_required=list(rule.human_confirmation),
                    applicable_conditions=list(rule.applicable_conditions),
                    prohibited_conclusions=list(rule.prohibited_conclusions),
                )
            )
        return candidates

    @staticmethod
    def _evidence_for_rule(
        statements: list[EvidenceStatement],
        groups: tuple[tuple[str, ...], ...],
        relation: Literal["supporting", "conflicting"],
    ) -> list[OpportunityEvidence]:
        if not groups:
            return []
        results: list[OpportunityEvidence] = []
        seen: set[tuple[str, str]] = set()
        for statement in statements:
            terms = _matched_terms(statement.text, groups)
            if terms is None:
                continue
            for anchor in statement.anchors:
                key = (statement.paper.paper_id, anchor.id)
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    OpportunityEvidence(
                        paper_id=statement.paper.paper_id,
                        paper_title=statement.paper.title,
                        year=statement.paper.year,
                        source_statement=statement.text,
                        relation=relation,
                        evidence_anchor=anchor,
                        matched_rule_terms=terms,
                    )
                )
        return results

    @staticmethod
    def _confidence(
        paper_count: int,
        anchor_count: int,
        has_conflict: bool,
        minimum_papers: int,
    ) -> ConfidenceAssessment:
        coverage_component = min(paper_count / max(minimum_papers + 1, 3), 1.0)
        anchor_component = min(anchor_count / max(paper_count * 2, 1), 1.0)
        conflict_component = 0.05 if has_conflict else 0.0
        score = min(
            0.85,
            round(
                0.25
                + 0.35 * coverage_component
                + 0.2 * anchor_component
                + conflict_component,
                3,
            ),
        )
        return ConfidenceAssessment(
            score=score,
            level="medium" if score >= 0.6 else "low",
            calculation=(
                "min(0.85, 0.25 + 0.35*distinct-paper coverage + "
                "0.20*verified-anchor density + 0.05*conflict visibility)"
            ),
            basis=[
                f"{paper_count} distinct evidence papers were cited.",
                f"{anchor_count} verified EvidenceAnchors matched deterministic rules.",
                f"Minimum distinct-paper threshold was {minimum_papers}.",
                "Confidence is capped at 0.85 and is not a novelty probability.",
            ],
        )

    @staticmethod
    def _progress_map(
        records: list[PaperDeconstruction],
    ) -> list[ResearchProgressMilestone]:
        milestones: list[ResearchProgressMilestone] = []
        for record in sorted(records, key=lambda item: (item.year, item.paper_id)):
            evidence_by_id = {
                item.id: item for item in record.evidence if item.verified
            }
            method_claim = next(
                (item for item in record.claims if item.claim_type == "method"),
                record.claims[0] if record.claims else None,
            )
            if method_claim is None:
                continue
            anchors = [
                evidence_by_id[item]
                for item in method_claim.evidence_ids
                if item in evidence_by_id
            ]
            if not anchors:
                continue
            milestones.append(
                ResearchProgressMilestone(
                    milestone_id=f"progress-{record.paper_id}",
                    year=record.year,
                    title=record.title,
                    paper_id=record.paper_id,
                    venue=record.venue,
                    summary=method_claim.statement,
                    evidence_anchors=anchors,
                )
            )
        return milestones
