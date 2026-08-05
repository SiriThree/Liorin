"""Unified evidence, retriever outcome and provenance-preserving fusion."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document

from retrieval.protocols import (
    RetrievalContribution,
    RetrievalError,
    RetrieverStatus,
    ScoreSemantics,
)


@dataclass
class RetrievedEvidence:
    """Internal evidence object passed through retrieval, fusion and reranking."""

    document: Document
    source: str
    retrieval_score: float | None
    rerank_score: float | None
    query: str
    source_type: str = "unknown"
    citation_id: str | None = None
    parent_context: str | None = None
    relevance_score: float | None = None
    coverage_tags: list[str] = field(default_factory=list)
    conflict_group: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    contributions: list[RetrievalContribution] = field(default_factory=list)
    score_semantics: ScoreSemantics = ScoreSemantics.RRF_HIGHER_BETTER
    rerank_method: str | None = None
    rerank_degraded_reason: str | None = None
    authority: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    matched_chunk_ids: list[str] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)

    def clone(self) -> "RetrievedEvidence":
        return RetrievedEvidence(
            document=self.document,
            source=self.source,
            retrieval_score=self.retrieval_score,
            rerank_score=self.rerank_score,
            query=self.query,
            source_type=self.source_type,
            citation_id=self.citation_id,
            parent_context=self.parent_context,
            relevance_score=self.relevance_score,
            coverage_tags=list(self.coverage_tags),
            conflict_group=self.conflict_group,
            trace=deepcopy(self.trace),
            contributions=[RetrievalContribution.model_validate(c.to_state()) for c in self.contributions],
            score_semantics=self.score_semantics,
            rerank_method=self.rerank_method,
            rerank_degraded_reason=self.rerank_degraded_reason,
            authority=self.authority,
            provenance=deepcopy(self.provenance),
            matched_chunk_ids=list(self.matched_chunk_ids),
            degraded_reasons=list(self.degraded_reasons),
        )

    def to_state(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "source": self.source,
            "source_type": self.source_type,
            "retrieval_score": self.retrieval_score,
            "rerank_score": self.rerank_score,
            "relevance_score": self.relevance_score,
            "coverage_tags": list(self.coverage_tags),
            "conflict_group": self.conflict_group,
            "citation_id": self.citation_id,
            "parent_context": self.parent_context,
            "query": self.query,
            "trace": deepcopy(self.trace),
            "contributions": [item.to_state() for item in self.contributions],
            "score_semantics": str(self.score_semantics),
            "rerank_method": self.rerank_method,
            "rerank_degraded_reason": self.rerank_degraded_reason,
            "authority": self.authority,
            "provenance": deepcopy(self.provenance),
            "matched_chunk_ids": list(self.matched_chunk_ids),
            "degraded_reasons": list(self.degraded_reasons),
        }


@dataclass
class RetrieverExecutionResult:
    """Structured result returned by every concrete retrieval dependency."""

    retriever: str
    status: RetrieverStatus
    evidences: list[RetrievedEvidence] = field(default_factory=list)
    errors: list[RetrievalError] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)
    soft_timeout: bool = False
    candidate_count: int = 0

    @property
    def succeeded(self) -> bool:
        return self.status in {RetrieverStatus.SUCCESS, RetrieverStatus.NO_RESULTS}

    def to_state(self) -> dict[str, Any]:
        return {
            "retriever": self.retriever,
            "status": str(self.status),
            "evidences": [item.to_state() for item in self.evidences],
            "errors": [error.to_state() for error in self.errors],
            "trace": deepcopy(self.trace),
            "degraded_reasons": list(self.degraded_reasons),
            "soft_timeout": self.soft_timeout,
            "candidate_count": self.candidate_count,
        }


def document_key(doc: Document) -> str:
    metadata = doc.metadata
    return str(
        metadata.get("chunk_id")
        or "|".join(
            [
                str(metadata.get("source_file", "")),
                str(metadata.get("chunk_start", metadata.get("start_index", ""))),
                doc.page_content[:80],
            ]
        )
    )


def with_citation_ids(evidences: list[RetrievedEvidence]) -> list[RetrievedEvidence]:
    for idx, evidence in enumerate(evidences, start=1):
        evidence.citation_id = f"E{idx}"
    return evidences


def normalize_score(raw_score: float, semantics: ScoreSemantics) -> float:
    """Convert heterogeneous raw scores to a [0, 1] higher-is-better direction."""

    score = float(raw_score)
    if semantics == ScoreSemantics.DISTANCE_LOWER_BETTER:
        return 1.0 / (1.0 + max(0.0, score))
    if semantics == ScoreSemantics.SIMILARITY_HIGHER_BETTER:
        if -1.0 <= score <= 1.0:
            return max(0.0, min(1.0, (score + 1.0) / 2.0))
        return 0.5 + score / (2.0 * (1.0 + abs(score)))
    if score <= 0:
        return 0.0
    return score / (1.0 + score)


def _merge_evidence(target: RetrievedEvidence, incoming: RetrievedEvidence) -> None:
    existing = {
        (
            item.retriever,
            item.subquery_id,
            item.rank,
            item.raw_score,
        )
        for item in target.contributions
    }
    for contribution in incoming.contributions:
        key = (
            contribution.retriever,
            contribution.subquery_id,
            contribution.rank,
            contribution.raw_score,
        )
        if key not in existing:
            target.contributions.append(
                RetrievalContribution.model_validate(contribution.to_state())
            )
            existing.add(key)
    target.trace.extend(deepcopy(incoming.trace))
    target.coverage_tags = list(dict.fromkeys([*target.coverage_tags, *incoming.coverage_tags]))
    target.matched_chunk_ids = list(
        dict.fromkeys([*target.matched_chunk_ids, *incoming.matched_chunk_ids])
    )
    target.degraded_reasons = list(
        dict.fromkeys([*target.degraded_reasons, *incoming.degraded_reasons])
    )
    target.provenance.update(deepcopy(incoming.provenance))


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedEvidence]],
    *,
    weights: dict[str, float] | None = None,
    k: int = 60,
    limit: int = 15,
) -> list[RetrievedEvidence]:
    """Fuse candidates while preserving every retriever's rank and raw score."""

    weights = weights or {}
    by_key: dict[str, RetrievedEvidence] = {}
    scores: dict[str, float] = {}

    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            key = document_key(item.document)
            retriever_name = item.contributions[0].retriever if item.contributions else item.source
            weight = float(weights.get(retriever_name, 1.0))
            if item.contributions:
                for contribution in item.contributions:
                    contribution.rank = rank
                    contribution.fusion_weight = float(
                        weights.get(contribution.retriever, weight)
                    )
            else:
                raw = float(item.retrieval_score or 0.0)
                item.contributions.append(
                    RetrievalContribution(
                        retriever=retriever_name,
                        rank=rank,
                        raw_score=raw,
                        normalized_score=normalize_score(raw, item.score_semantics),
                        fusion_weight=weight,
                        score_semantics=item.score_semantics,
                    )
                )
            if key not in by_key:
                by_key[key] = item.clone()
            else:
                _merge_evidence(by_key[key], item)
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)

    fused: list[RetrievedEvidence] = []
    for key, item in by_key.items():
        item.retrieval_score = scores[key]
        item.score_semantics = ScoreSemantics.RRF_HIGHER_BETTER
        item.source = "+".join(
            sorted({contribution.retriever for contribution in item.contributions})
        )
        fused.append(item)
    return sorted(fused, key=lambda item: item.retrieval_score or 0.0, reverse=True)[:limit]
