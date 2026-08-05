"""Stable Retrieval/Verifier/Agentic RAG evaluation schema and deterministic metrics."""
from __future__ import annotations

from collections import Counter
from math import log2
import statistics
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from retrieval.protocols import RetrievalPrincipal


class RetrievalEvaluationSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str
    query: str
    conversation_context: list[dict[str, str]] = Field(default_factory=list)
    principal: RetrievalPrincipal
    expected_source: list[str] = Field(default_factory=list)
    expected_document_ids: list[str] = Field(default_factory=list)
    expected_section_ids: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    required_evidence_facts: list[str] = Field(default_factory=list)
    forbidden_sources: list[str] = Field(default_factory=list)
    outdated_sources: list[str] = Field(default_factory=list)
    expected_action: str
    expected_clarification: str | None = None
    expected_subquery_terms: list[str] = Field(default_factory=list)
    expected_conflicts: list[str] = Field(default_factory=list)
    difficulty: str = "unknown"
    category: str = "general"
    split: Literal["train", "validation", "blind", "test"] = "validation"
    reviewed_gold: bool = False
    reviewer_record_id: str | None = None


class EvaluationPrediction(BaseModel):
    sample_id: str
    ranked_document_ids: list[str] = Field(default_factory=list)
    ranked_section_ids: list[str] = Field(default_factory=list)
    used_sources: list[str] = Field(default_factory=list)
    acl_violations: list[str] = Field(default_factory=list)
    predicted_requirements: list[str] = Field(default_factory=list)
    covered_requirements: list[str] = Field(default_factory=list)
    detected_conflicts: list[str] = Field(default_factory=list)
    rejected_outdated_sources: list[str] = Field(default_factory=list)
    verification_action: str | None = None
    selected_sources: list[str] = Field(default_factory=list)
    subqueries: list[str] = Field(default_factory=list)
    retry_decision: bool | None = None
    clarification: str | None = None
    handoff: bool = False
    retrieval_rounds: int = 0
    answer: str = ""
    cited_document_ids: list[str] = Field(default_factory=list)
    supported_claims: int = 0
    unsupported_claims: int = 0
    factual_correctness: float | None = Field(default=None, ge=0.0, le=1.0)
    timed_out: bool = False
    latency_ms: float = 0.0
    model_calls: int = 0
    token_cost: float = 0.0
    external_dependency_calls: int = 0
    degraded: bool = False


def _recall(ranked: list[str], relevant: set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / len(relevant) if relevant else 1.0


def _mrr(ranked: list[str], relevant: set[str]) -> float:
    return next((1.0 / (idx + 1) for idx, item in enumerate(ranked) if item in relevant), 0.0)


def _ndcg(ranked: list[str], relevant: set[str], k: int) -> float:
    dcg = sum(1.0 / log2(idx + 2) for idx, item in enumerate(ranked[:k]) if item in relevant)
    ideal = sum(1.0 / log2(idx + 2) for idx in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 1.0


def _prf(predicted: set[str], expected: set[str]) -> tuple[float, float, float]:
    tp = len(predicted & expected)
    precision = tp / len(predicted) if predicted else (1.0 if not expected else 0.0)
    recall = tp / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def score_sample(sample: RetrievalEvaluationSample, prediction: EvaluationPrediction) -> dict[str, float]:
    relevant_docs = set(sample.expected_document_ids)
    relevant_sections = set(sample.expected_section_ids)
    requirement_p, requirement_r, _ = _prf(set(prediction.covered_requirements), set(sample.requirements))
    expected_sources = set(sample.expected_source)
    source_accuracy = len(set(prediction.used_sources) & expected_sources) / len(expected_sources) if expected_sources else 1.0
    forbidden = set(prediction.used_sources) & set(sample.forbidden_sources)
    outdated_expected = set(sample.outdated_sources)
    conflict_expected = set(sample.expected_conflicts)
    conflict_p, conflict_r, _ = _prf(set(prediction.detected_conflicts), conflict_expected)
    expected_subquery_terms = {item.casefold() for item in sample.expected_subquery_terms}
    generated_subquery_text = " ".join(prediction.subqueries).casefold()
    subquery_quality = (
        sum(1 for item in expected_subquery_terms if item in generated_subquery_text) / len(expected_subquery_terms)
        if expected_subquery_terms else 1.0
    )
    total_claims = prediction.supported_claims + prediction.unsupported_claims
    diversity = len(set(prediction.used_sources)) / max(1, len(prediction.ranked_document_ids[:10]))
    return {
        "recall@5": _recall(prediction.ranked_document_ids, relevant_docs, 5),
        "recall@10": _recall(prediction.ranked_document_ids, relevant_docs, 10),
        "recall@20": _recall(prediction.ranked_document_ids, relevant_docs, 20),
        "mrr": _mrr(prediction.ranked_document_ids, relevant_docs),
        "ndcg@10": _ndcg(prediction.ranked_document_ids, relevant_docs, 10),
        "section_recall@10": _recall(prediction.ranked_section_ids, relevant_sections, 10),
        "source_accuracy": source_accuracy,
        "filter_accuracy": 1.0 if not forbidden else 0.0,
        "acl_violation_rate": 1.0 if prediction.acl_violations else 0.0,
        "evidence_diversity": diversity,
        "requirement_coverage_precision": requirement_p,
        "requirement_coverage_recall": requirement_r,
        "verification_action_accuracy": float(prediction.verification_action == sample.expected_action),
        "conflict_detection_precision": conflict_p,
        "conflict_detection_recall": conflict_r,
        "outdated_evidence_rejection_rate": (
            len(set(prediction.rejected_outdated_sources) & outdated_expected) / len(outdated_expected)
            if outdated_expected else 1.0
        ),
        "planner_source_selection_accuracy": source_accuracy,
        "subquery_quality": subquery_quality,
        "retry_decision_accuracy": float((prediction.retry_decision or False) == (sample.expected_action in {"supplement", "rewrite", "decompose", "relax_filters"})),
        "clarification_accuracy": float(bool(prediction.clarification) == bool(sample.expected_clarification)),
        "handoff_accuracy": float(prediction.handoff == (sample.expected_action == "handoff")),
        "citation_correctness": len(set(prediction.cited_document_ids) & relevant_docs) / max(1, len(set(prediction.cited_document_ids))),
        "citation_completeness": len(set(prediction.cited_document_ids) & relevant_docs) / max(1, len(relevant_docs)),
        "unsupported_claim_rate": prediction.unsupported_claims / total_claims if total_claims else 0.0,
        "factual_correctness": prediction.factual_correctness if prediction.factual_correctness is not None else 0.0,
        "retrieval_rounds": float(prediction.retrieval_rounds),
        "latency_ms": prediction.latency_ms,
        "model_calls": float(prediction.model_calls),
        "token_cost": prediction.token_cost,
        "external_dependency_calls": float(prediction.external_dependency_calls),
        "degraded_rate": float(prediction.degraded),
        "timeout_rate": float(prediction.timed_out),
    }


def summarize_scores(rows: list[dict[str, float]]) -> dict[str, Any]:
    if not rows:
        return {"sample_count": 0, "metrics": {}}
    keys = sorted(set().union(*(row.keys() for row in rows)))
    metrics = {key: statistics.mean(row.get(key, 0.0) for row in rows) for key in keys}
    latencies = [row.get("latency_ms", 0.0) for row in rows]
    for percentile, name in ((0.50, "p50_latency_ms"), (0.95, "p95_latency_ms"), (0.99, "p99_latency_ms")):
        ordered = sorted(latencies)
        position = int(round((len(ordered) - 1) * percentile))
        metrics[name] = ordered[position]
    return {"sample_count": len(rows), "metrics": metrics}
