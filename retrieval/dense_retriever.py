"""Milvus dense retrieval with unified filters, score semantics and errors."""
from __future__ import annotations

import os
from time import perf_counter
from typing import Any

from retrieval.budget import RetrievalBudget
from retrieval.filters import (
    InvalidRetrievalFilter,
    build_milvus_expression,
    document_matches_filters,
    retrieval_cache_key,
    validate_filters,
)
from retrieval.fusion import RetrievedEvidence, RetrieverExecutionResult, normalize_score
from retrieval.protocols import (
    RetrievalContribution,
    RetrievalError,
    RetrievalFilters,
    RetrievalPrincipal,
    RetrieverStatus,
    ScoreSemantics,
)
from retrieval.trace import trace_event
from retrieval.resilience import call_with_resilience, RetryPolicy
from tools.documents import get_vectorstore


def _score_semantics(vectorstore: Any) -> ScoreSemantics:
    configured = os.getenv("DENSE_SCORE_SEMANTICS", "").strip().lower()
    if configured:
        return ScoreSemantics(configured)
    search_params = getattr(vectorstore, "search_params", None) or getattr(vectorstore, "_search_params", None) or {}
    metric = str(search_params.get("metric_type") or "").upper()
    if metric in {"COSINE", "IP", "INNER_PRODUCT"}:
        return ScoreSemantics.SIMILARITY_HIGHER_BETTER
    # LangChain Milvus ``similarity_search_with_score`` commonly returns L2
    # distance for default collections.  Deployments using COSINE/IP must expose
    # metric_type or set DENSE_SCORE_SEMANTICS explicitly.
    return ScoreSemantics.DISTANCE_LOWER_BETTER


def dense_search(
    query: str,
    *,
    principal: RetrievalPrincipal,
    filters: RetrievalFilters | dict | None = None,
    source: str | None = None,
    subquery_id: str | None = None,
    k: int = 15,
    budget: RetrievalBudget | None = None,
    vectorstore_factory=get_vectorstore,
) -> RetrieverExecutionResult:
    retriever = "dense_milvus"
    started = perf_counter()
    if source in {"ticket_history", "database", "structured_db"}:
        return RetrieverExecutionResult(retriever, RetrieverStatus.SKIPPED_BY_PLAN)
    # Anonymous principals proceed only to explicit public/global ACL filtering.
    try:
        unified = validate_filters(filters, principal=principal, source=source)
        expr = build_milvus_expression(unified, principal)
    except InvalidRetrievalFilter as exc:
        error = RetrievalError(stage=retriever, error_type="InvalidFilter", message=str(exc), dependency="filters", subquery_id=subquery_id)
        return RetrieverExecutionResult(retriever, RetrieverStatus.INVALID_FILTER, errors=[error])
    if budget and not budget.reserve_dense():
        status = RetrieverStatus.TIMEOUT if budget.latency_exceeded else RetrieverStatus.SKIPPED_BY_BUDGET
        return RetrieverExecutionResult(retriever, status, degraded_reasons=["dense budget unavailable"])

    timeout_ms = budget.remaining_timeout_ms if budget else 25_000
    hard_timeout_supported = True
    try:
        def invoke_milvus():
            vectorstore = vectorstore_factory()
            kwargs: dict[str, Any] = {"k": k, "expr": expr}
            local_hard_timeout = True
            if timeout_ms > 0:
                kwargs["timeout"] = max(0.001, timeout_ms / 1000)
            try:
                rows = vectorstore.similarity_search_with_score(query, **kwargs)
            except TypeError:
                local_hard_timeout = False
                kwargs.pop("timeout", None)
                rows = vectorstore.similarity_search_with_score(query, **kwargs)
            return vectorstore, rows, local_hard_timeout

        vectorstore, results, hard_timeout_supported = call_with_resilience(
            "milvus",
            invoke_milvus,
            retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.01, max_delay_seconds=0.05),
            retry_if=lambda exc: not isinstance(exc, (ValueError, TypeError)),
            max_concurrency=8,
        )
    except Exception as exc:
        error_type = "TimeoutError" if "timeout" in str(exc).lower() else type(exc).__name__
        status = RetrieverStatus.TIMEOUT if error_type == "TimeoutError" else RetrieverStatus.DEPENDENCY_ERROR
        error = RetrievalError(stage=retriever, error_type=error_type, message=str(exc), retryable=True, dependency="milvus", subquery_id=subquery_id)
        event = trace_event(retriever, "error", subquery_id=subquery_id, status=str(status), error_type=error_type, elapsed_ms=round((perf_counter() - started) * 1000, 2))
        return RetrieverExecutionResult(retriever, status, errors=[error], trace=[event])

    try:
        semantics = _score_semantics(vectorstore)
        evidences: list[RetrievedEvidence] = []
        unauthorized_count = 0
        for rank, result in enumerate(results, 1):
            doc, raw_score = result
            if not document_matches_filters(doc.metadata, unified, principal):
                unauthorized_count += 1
                continue
            normalized = normalize_score(float(raw_score), semantics)
            contribution = RetrievalContribution(
                retriever=retriever,
                subquery_id=subquery_id,
                rank=rank,
                raw_score=float(raw_score),
                normalized_score=normalized,
                score_semantics=semantics,
            )
            evidences.append(RetrievedEvidence(
                document=doc,
                source=retriever,
                retrieval_score=normalized,
                rerank_score=None,
                query=query,
                source_type=doc.metadata.get("doc_type", "unknown"),
                score_semantics=ScoreSemantics.SIMILARITY_HIGHER_BETTER,
                contributions=[contribution],
                matched_chunk_ids=[str(doc.metadata.get("chunk_id", ""))],
            ))
    except Exception as exc:
        error = RetrievalError(
            stage=retriever,
            error_type=type(exc).__name__,
            message=f"invalid dense result/score semantics: {exc}",
            retryable=False,
            dependency="milvus_score_contract",
            subquery_id=subquery_id,
        )
        event = trace_event(
            retriever,
            "error",
            subquery_id=subquery_id,
            status="dependency_error",
            error_type=type(exc).__name__,
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
        return RetrieverExecutionResult(
            retriever, RetrieverStatus.DEPENDENCY_ERROR, errors=[error], trace=[event]
        )
    evidences.sort(key=lambda item: item.retrieval_score or 0.0, reverse=True)
    if budget:
        evidences = evidences[:budget.record_candidates(len(evidences))]
    elapsed = (perf_counter() - started) * 1000
    soft_timeout = elapsed > timeout_ms if timeout_ms > 0 else True
    errors: list[RetrievalError] = []
    status = RetrieverStatus.SUCCESS if evidences else RetrieverStatus.NO_RESULTS
    degraded: list[str] = []
    if soft_timeout:
        status = RetrieverStatus.TIMEOUT if not evidences else RetrieverStatus.SUCCESS
        degraded.append("Milvus call exceeded remaining timeout; hard cancellation not guaranteed")
        errors.append(RetrievalError(stage=retriever, error_type="SoftTimeout", message=degraded[-1], retryable=True, dependency="milvus", subquery_id=subquery_id))
    event = trace_event(
        retriever,
        "complete",
        subquery_id=subquery_id,
        status=str(status),
        returned_count=len(evidences),
        raw_count=len(results),
        unauthorized_filtered=unauthorized_count,
        elapsed_ms=round(elapsed, 2),
        timeout_ms=timeout_ms,
        soft_timeout=soft_timeout,
        hard_timeout_supported=hard_timeout_supported,
        score_semantics=str(semantics),
        filter_expression=expr,
        access_cache_key=retrieval_cache_key(
            query, filters=unified, principal=principal, source=source
        ),
    )
    for evidence in evidences:
        evidence.trace.append(event)
    return RetrieverExecutionResult(retriever, status, evidences, errors, [event], degraded, soft_timeout, len(evidences))
