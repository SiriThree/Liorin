"""Production retrieval pipeline for Liorin Agentic RAG."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable

from retrieval.budget import RetrievalBudget
from retrieval.context_expander import expand_parent_context
from retrieval.database_retriever import database_search
from retrieval.dense_retriever import dense_search
from retrieval.filters import InvalidRetrievalFilter, validate_filters
from retrieval.fusion import (
    RetrievedEvidence,
    RetrieverExecutionResult,
    reciprocal_rank_fusion,
    with_citation_ids,
)
from retrieval.metadata import extract_business_entities
from retrieval.metadata_lookup import metadata_direct_lookup
from retrieval.protocols import (
    QueryUnderstanding,
    RetrievalError,
    RetrievalFilters,
    RetrievalPrincipal,
    RetrievalResponse,
    RetrievalStatus,
    RetrievalSubquery,
    RetrieverStatus,
)
from retrieval.reranker import rerank
from retrieval.sparse_retriever import bm25_search
from retrieval.trace import trace_event


@dataclass
class RetrievalPipelineResult:
    response: RetrievalResponse
    evidences: list[RetrievedEvidence]
    retriever_results: list[RetrieverExecutionResult]


def _result_error_status(results: list[RetrieverExecutionResult]) -> RetrievalStatus:
    """Aggregate empty-result outcomes without over-reporting budget exhaustion.

    A single optional route may be disabled by budget while another planned route
    executes normally and returns no matches.  That case is a genuine
    ``no_results`` outcome, not a request-level ``budget_exhausted`` failure.
    Budget exhaustion is reported only when every route that was not skipped by
    the plan was itself skipped by budget.
    """

    statuses = {result.status for result in results}
    if RetrieverStatus.PERMISSION_DENIED in statuses:
        return RetrievalStatus.PERMISSION_DENIED
    if RetrieverStatus.INVALID_FILTER in statuses:
        return RetrievalStatus.INVALID_FILTER
    if RetrieverStatus.TIMEOUT in statuses:
        return RetrievalStatus.TIMEOUT
    if RetrieverStatus.DEPENDENCY_ERROR in statuses:
        return RetrievalStatus.DEPENDENCY_ERROR

    planned_statuses = {
        status for status in statuses if status != RetrieverStatus.SKIPPED_BY_PLAN
    }
    if planned_statuses and planned_statuses <= {RetrieverStatus.SKIPPED_BY_BUDGET}:
        return RetrievalStatus.BUDGET_EXHAUSTED
    return RetrievalStatus.NO_RESULTS


def _query_aware_weights(understanding: QueryUnderstanding) -> dict[str, float]:
    entities = understanding.direct_lookup_entities()
    weights = {
        "dense_milvus": 1.0,
        "sparse_bm25": 1.0,
        "metadata_direct_lookup": 1.15,
        "structured_database": 1.25,
    }
    if understanding.error_codes or understanding.product_models:
        weights["metadata_direct_lookup"] = 1.45
    if any(field in entities for field in ("order_id", "ticket_id", "customer_id")):
        weights["structured_database"] = 1.6
    if not entities:
        weights["dense_milvus"] = 1.15
    return weights


def _parallel_main_recall(
    query: str,
    *,
    principal: RetrievalPrincipal,
    filters: RetrievalFilters,
    source: str | None,
    subquery_id: str,
    dense_k: int,
    sparse_k: int,
    budget: RetrievalBudget,
    dense_fn: Callable[..., RetrieverExecutionResult],
    sparse_fn: Callable[..., RetrieverExecutionResult],
) -> list[RetrieverExecutionResult]:
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="liorin-retrieval")
    futures = {
        executor.submit(
            dense_fn,
            query,
            principal=principal,
            filters=filters,
            source=source,
            subquery_id=subquery_id,
            k=dense_k,
            budget=budget,
        ): "dense_milvus",
        executor.submit(
            sparse_fn,
            query,
            principal=principal,
            filters=filters,
            source=source,
            subquery_id=subquery_id,
            k=sparse_k,
            budget=budget,
        ): "sparse_bm25",
    }
    timeout = max(0.001, budget.remaining_timeout_ms / 1000)
    done, pending = wait(futures, timeout=timeout)
    results: list[RetrieverExecutionResult] = []
    for future in done:
        name = futures[future]
        try:
            results.append(future.result())
        except Exception as exc:
            error = RetrievalError(
                stage=name,
                error_type=type(exc).__name__,
                message=str(exc),
                retryable=True,
                dependency=name,
                subquery_id=subquery_id,
            )
            results.append(
                RetrieverExecutionResult(name, RetrieverStatus.DEPENDENCY_ERROR, errors=[error])
            )
    for future in pending:
        name = futures[future]
        future.cancel()
        message = (
            f"{name} exceeded scheduler timeout; underlying thread/external request "
            "may continue because hard cancellation is not guaranteed"
        )
        error = RetrievalError(
            stage=name,
            error_type="SoftTimeout",
            message=message,
            retryable=True,
            dependency=name,
            subquery_id=subquery_id,
        )
        results.append(
            RetrieverExecutionResult(
                name,
                RetrieverStatus.TIMEOUT,
                errors=[error],
                degraded_reasons=[message],
                soft_timeout=True,
            )
        )
    executor.shutdown(wait=False, cancel_futures=True)
    return results


def _planned_main_recall(
    query: str,
    *,
    mode: str,
    principal: RetrievalPrincipal,
    filters: RetrievalFilters,
    source: str | None,
    subquery_id: str,
    dense_k: int,
    sparse_k: int,
    budget: RetrievalBudget,
    dense_fn: Callable[..., RetrieverExecutionResult],
    sparse_fn: Callable[..., RetrieverExecutionResult],
) -> list[RetrieverExecutionResult]:
    """Run the planned main recall while keeping Dense+BM25 as the default."""

    common = {
        "principal": principal,
        "filters": filters,
        "source": source,
        "subquery_id": subquery_id,
        "budget": budget,
    }
    if mode == "dense":
        return [
            dense_fn(query, k=dense_k, **common),
            RetrieverExecutionResult("sparse_bm25", RetrieverStatus.SKIPPED_BY_PLAN),
        ]
    if mode == "sparse":
        return [
            RetrieverExecutionResult("dense_milvus", RetrieverStatus.SKIPPED_BY_PLAN),
            sparse_fn(query, k=sparse_k, **common),
        ]
    return _parallel_main_recall(
        query,
        principal=principal,
        filters=filters,
        source=source,
        subquery_id=subquery_id,
        dense_k=dense_k,
        sparse_k=sparse_k,
        budget=budget,
        dense_fn=dense_fn,
        sparse_fn=sparse_fn,
    )


def hybrid_retrieve(
    understanding: QueryUnderstanding,
    subquery: RetrievalSubquery,
    *,
    principal: RetrievalPrincipal,
    budget: RetrievalBudget | None = None,
    dense_k: int = 15,
    sparse_k: int = 15,
    candidate_k: int = 15,
    final_k: int = 5,
    use_cross_encoder: bool = True,
    dense_fn: Callable[..., RetrieverExecutionResult] = dense_search,
    sparse_fn: Callable[..., RetrieverExecutionResult] = bm25_search,
    metadata_fn: Callable[..., RetrieverExecutionResult] = metadata_direct_lookup,
    database_fn: Callable[..., RetrieverExecutionResult] = database_search,
) -> RetrievalPipelineResult:
    """Execute the production Stage-2 retrieval flow and return RetrievalResponse."""

    budget = (budget or RetrievalBudget()).start()
    query = subquery.query or understanding.normalized_query or understanding.original_query
    source = subquery.source
    trace: list[dict[str, Any]] = []
    try:
        filters = validate_filters(subquery.filters, principal=principal, source=source)
    except InvalidRetrievalFilter as exc:
        error = RetrievalError(
            stage="retrieval_pipeline",
            error_type="InvalidFilter",
            message=str(exc),
            dependency="filters",
            subquery_id=subquery.subquery_id,
        )
        response = RetrievalResponse(
            status=RetrievalStatus.INVALID_FILTER,
            errors=[error],
            budget_snapshot=budget.to_state(),
            executed_subqueries=[subquery.subquery_id],
        )
        return RetrievalPipelineResult(response, [], [])
    # Anonymous requests continue only to the common public-only ACL filter.

    entities = understanding.direct_lookup_entities()
    if not entities:
        entities = extract_business_entities(query)
    results: list[RetrieverExecutionResult] = []

    run_unstructured = source not in {"database", "structured_db"} and subquery.retrieval_mode != "database"
    if subquery.retrieval_mode == "metadata":
        run_unstructured = False
    if run_unstructured:
        results.extend(
            _planned_main_recall(
                query,
                mode=subquery.retrieval_mode,
                principal=principal,
                filters=filters,
                source=None if source == "all" else source,
                subquery_id=subquery.subquery_id,
                dense_k=dense_k,
                sparse_k=sparse_k,
                budget=budget,
                dense_fn=dense_fn,
                sparse_fn=sparse_fn,
            )
        )

    # No call, index access or budget charge occurs without deterministic entities.
    if entities:
        results.append(
            metadata_fn(
                entities=entities,
                query=query,
                principal=principal,
                filters=filters,
                source=None if source in {"all", "database", "structured_db"} else source,
                subquery_id=subquery.subquery_id,
                k=sparse_k,
                budget=budget,
            )
        )
    else:
        results.append(
            RetrieverExecutionResult(
                "metadata_direct_lookup",
                RetrieverStatus.SKIPPED_BY_PLAN,
            )
        )

    business_entities = {
        field: values
        for field, values in entities.items()
        if field in {"order_id", "ticket_id", "customer_id"}
    }
    if business_entities or source in {"database", "structured_db"} or subquery.retrieval_mode == "database":
        results.append(
            database_fn(
                query,
                principal=principal,
                entities=business_entities,
                filters=filters,
                subquery_id=subquery.subquery_id,
                k=final_k,
                budget=budget,
            )
        )

    ranked_lists = [result.evidences for result in results if result.evidences]
    fused = reciprocal_rank_fusion(
        ranked_lists,
        weights=_query_aware_weights(understanding),
        limit=min(candidate_k, budget.max_candidates),
    ) if ranked_lists else []

    coarse = rerank(
        query,
        fused,
        limit=min(candidate_k, budget.max_candidates),
        use_cross_encoder=use_cross_encoder,
        include_parent=False,
        budget=budget,
        stage="coarse",
        subquery_id=subquery.subquery_id,
    )
    expanded = expand_parent_context(
        coarse.evidences,
        principal=principal,
        filters=filters,
        budget=budget,
        subquery_id=subquery.subquery_id,
    )
    final = rerank(
        query,
        expanded.evidences,
        limit=min(final_k, budget.max_final_evidences),
        use_cross_encoder=use_cross_encoder,
        include_parent=True,
        budget=budget,
        stage="final",
        subquery_id=subquery.subquery_id,
    )
    evidences = with_citation_ids(final.evidences)
    budget.record_final_evidences(len(evidences))

    errors = [error for result in results for error in result.errors]
    errors.extend(coarse.errors)
    errors.extend(expanded.errors)
    errors.extend(final.errors)
    degraded = [
        reason
        for result in results
        if result.status != RetrieverStatus.SKIPPED_BY_PLAN
        for reason in result.degraded_reasons
    ]
    degraded.extend(coarse.degraded_reasons)
    degraded.extend(expanded.degraded_reasons)
    degraded.extend(final.degraded_reasons)
    degraded = list(dict.fromkeys(degraded))
    if evidences and (errors or degraded):
        status = RetrievalStatus.PARTIAL
    elif evidences:
        status = RetrievalStatus.SUCCESS
    else:
        status = _result_error_status(results)

    for result in results:
        trace.extend(result.trace)
    trace.extend(coarse.trace)
    trace.extend(expanded.trace)
    trace.extend(final.trace)
    trace.append(
        trace_event(
            "retrieval_pipeline",
            "complete",
            subquery_id=subquery.subquery_id,
            status=str(status),
            retriever_statuses={result.retriever: str(result.status) for result in results},
            fused_count=len(fused),
            final_count=len(evidences),
            contribution_count=sum(len(item.contributions) for item in evidences),
            error_count=len(errors),
            degraded_reason_count=len(degraded),
            budget_after=budget.to_state(),
        )
    )
    response = RetrievalResponse(
        status=status,
        evidences=[item.to_state() for item in evidences],
        errors=errors,
        audit={
            "retriever_outcomes": [result.to_state() for result in results],
            "fused_candidate_count": len(fused),
            "coarse_rerank_method": coarse.method,
            "final_rerank_method": final.method,
            "soft_timeout": any(result.soft_timeout for result in results)
            or coarse.soft_timeout
            or final.soft_timeout,
        },
        budget_snapshot=budget.to_state(),
        trace=trace,
        executed_subqueries=[subquery.subquery_id],
        degraded_reasons=degraded,
    )
    return RetrievalPipelineResult(response, evidences, results)


def hybrid_search(
    query: str,
    *,
    source: str | None = None,
    filters: dict | None = None,
    dense_k: int = 15,
    sparse_k: int = 15,
    candidate_k: int = 15,
    final_k: int = 5,
    budget: RetrievalBudget | None = None,
    use_cross_encoder: bool = True,
    principal: RetrievalPrincipal | None = None,
) -> list[RetrievedEvidence]:
    """Compatibility wrapper around the production structured pipeline."""

    principal = principal or RetrievalPrincipal.anonymous()
    understanding = QueryUnderstanding(
        original_query=query,
        normalized_query=query,
        requirements=[query],
    )
    subquery = RetrievalSubquery(
        subquery_id="legacy-sq-1",
        query=query,
        source=source or "all",
        filters=filters or {},
        retrieval_mode="hybrid",
        reason="legacy hybrid_search compatibility",
    )
    return hybrid_retrieve(
        understanding,
        subquery,
        principal=principal,
        budget=budget,
        dense_k=dense_k,
        sparse_k=sparse_k,
        candidate_k=candidate_k,
        final_k=final_k,
        use_cross_encoder=use_cross_encoder,
    ).evidences
