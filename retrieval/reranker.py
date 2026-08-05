"""Two-stage reranking with structured text, timeout and explicit degradation."""
from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from retrieval.budget import RetrievalBudget
from retrieval.fusion import RetrievedEvidence
from retrieval.protocols import RetrievalError
from retrieval.sparse_retriever import tokenize
from retrieval.trace import trace_event
from retrieval.observability import record_reranker_fallback, record_reranker_request
from retrieval.resilience import call_with_resilience, RetryPolicy

DEFAULT_RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")


@dataclass
class RerankResult:
    evidences: list[RetrievedEvidence]
    errors: list[RetrievalError] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)
    method: str = "heuristic"
    soft_timeout: bool = False


@lru_cache(maxsize=1)
def _load_cross_encoder():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(DEFAULT_RERANKER_MODEL)


def _near_match_excerpt(text: str, query: str, max_chars: int = 1200) -> str:
    if len(text) <= max_chars:
        return text
    query_terms = [term.casefold() for term in tokenize(query) if len(term) >= 2]
    lower = text.casefold()
    positions = [lower.find(term) for term in query_terms if lower.find(term) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - max_chars // 3)
    end = min(len(text), start + max_chars)
    return text[start:end]


def build_reranker_text(
    evidence: RetrievedEvidence,
    query: str,
    *,
    include_parent: bool,
    max_chars: int = 2200,
) -> str:
    """Prioritize metadata, title and the matched chunk/window before truncation."""

    metadata = evidence.document.metadata
    header = "\n".join(
        [
            f"文档类型：{metadata.get('doc_type') or ''}",
            f"产品：{metadata.get('product_name') or ''}",
            f"型号：{metadata.get('product_models') or metadata.get('product_model') or ''}",
            f"章节路径：{metadata.get('section_path') or metadata.get('section') or ''}",
            f"错误码：{metadata.get('error_codes') or metadata.get('error_code') or ''}",
            f"版本：{metadata.get('version') or ''}",
            f"生效日期：{metadata.get('effective_from') or metadata.get('effective_date') or ''}",
            f"来源：{metadata.get('source_file') or metadata.get('source') or ''}",
        ]
    )
    chunk = _near_match_excerpt(evidence.document.page_content, query, max_chars=1200)
    blocks = [header, "当前命中块：\n" + chunk]
    if include_parent and evidence.parent_context:
        blocks.append("父章节窗口：\n" + _near_match_excerpt(evidence.parent_context, query, max_chars=900))
    return "\n\n".join(blocks)[:max_chars]


def _heuristic_score(query: str, evidence: RetrievedEvidence, *, include_parent: bool) -> float:
    query_terms = {term for term in tokenize(query.casefold()) if len(term) >= 2}
    rerank_text = build_reranker_text(evidence, query, include_parent=include_parent).casefold()
    if not query_terms:
        overlap = 0.0
    else:
        overlap = sum(1 for term in query_terms if term in rerank_text) / len(query_terms)
    contribution_score = max(
        (contribution.normalized_score for contribution in evidence.contributions),
        default=0.0,
    )
    authority_bonus = 0.1 if evidence.authority else 0.0
    return min(1.0, overlap * 0.75 + contribution_score * 0.2 + authority_bonus)


def rerank(
    query: str,
    evidences: list[RetrievedEvidence],
    *,
    limit: int = 8,
    use_cross_encoder: bool = True,
    include_parent: bool = False,
    budget: RetrievalBudget | None = None,
    stage: str = "coarse",
    subquery_id: str | None = None,
) -> RerankResult:
    if not evidences:
        return RerankResult([])

    record_reranker_request(use_cross_encoder=use_cross_encoder)
    degraded: list[str] = []
    errors: list[RetrievalError] = []
    traces: list[dict[str, Any]] = []
    method = "heuristic"
    soft_timeout = False
    remaining_ms = budget.remaining_timeout_ms if budget else 25_000
    should_use_model = use_cross_encoder and remaining_ms >= 250

    if should_use_model:
        try:
            cross_encoder = call_with_resilience(
                "cross_encoder_load", _load_cross_encoder,
                retry_policy=RetryPolicy(max_attempts=1), max_concurrency=2,
            )
        except Exception as exc:
            cross_encoder = None
            reason = f"reranker model load failed: {type(exc).__name__}: {exc}"
            degraded.append(reason)
            errors.append(RetrievalError(
                stage=f"reranker_{stage}",
                error_type=type(exc).__name__,
                message=str(exc),
                retryable=True,
                dependency="cross_encoder",
                subquery_id=subquery_id,
            ))
        if cross_encoder is not None:
            pairs = [
                (query, build_reranker_text(item, query, include_parent=include_parent))
                for item in evidences
            ]
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                call_with_resilience,
                "cross_encoder_inference",
                lambda: cross_encoder.predict(pairs),
                retry_policy=RetryPolicy(max_attempts=1),
                max_concurrency=2,
            )
            try:
                raw_scores = future.result(timeout=max(0.001, remaining_ms / 1000))
                scores = [float(score) for score in raw_scores]
                if len(scores) != len(evidences):
                    raise ValueError(
                        f"cross-encoder returned {len(scores)} scores for {len(evidences)} evidences"
                    )
                if any(not math.isfinite(score) for score in scores):
                    raise ValueError("cross-encoder returned a non-finite score")
                for item, score in zip(evidences, scores):
                    item.rerank_score = score
                    item.rerank_method = f"cross_encoder_{stage}"
                method = "cross_encoder"
            except FutureTimeout:
                future.cancel()
                soft_timeout = True
                reason = "reranker exceeded remaining timeout; underlying inference may continue"
                degraded.append(reason)
                errors.append(RetrievalError(
                    stage=f"reranker_{stage}",
                    error_type="SoftTimeout",
                    message=reason,
                    retryable=True,
                    dependency="cross_encoder",
                    subquery_id=subquery_id,
                ))
            except Exception as exc:
                reason = f"reranker inference failed: {type(exc).__name__}: {exc}"
                degraded.append(reason)
                errors.append(RetrievalError(
                    stage=f"reranker_{stage}",
                    error_type=type(exc).__name__,
                    message=str(exc),
                    retryable=True,
                    dependency="cross_encoder",
                    subquery_id=subquery_id,
                ))
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
    elif use_cross_encoder:
        degraded.append("low remaining latency budget; heuristic reranker used")

    if method != "cross_encoder":
        if use_cross_encoder:
            record_reranker_fallback()
        for item in evidences:
            item.rerank_score = _heuristic_score(query, item, include_parent=include_parent)
            item.rerank_method = f"heuristic_{stage}"
            if degraded:
                item.rerank_degraded_reason = degraded[-1]
                item.degraded_reasons = list(dict.fromkeys([*item.degraded_reasons, *degraded]))

    ranked = sorted(evidences, key=lambda item: item.rerank_score or 0.0, reverse=True)[:limit]
    event = trace_event(
        f"reranker_{stage}",
        "complete",
        subquery_id=subquery_id,
        status="degraded" if degraded else "success",
        method=method,
        returned_count=len(ranked),
        include_parent=include_parent,
        remaining_timeout_ms=remaining_ms,
        soft_timeout=soft_timeout,
    )
    traces.append(event)
    for item in ranked:
        item.trace.append(event)
    return RerankResult(ranked, errors, traces, degraded, method, soft_timeout)
