"""On-demand deterministic metadata lookup backed by a versioned in-memory index.

This index avoids rescanning and retokenizing full document bodies.  It is suitable
for the current single-process corpus size; larger deployments should materialize
these fields in Milvus scalar indexes, OpenSearch or a dedicated metadata service.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from typing import Any

from retrieval.budget import RetrievalBudget
from retrieval.document_corpus import corpus_version, load_chunked_documents
from retrieval.filters import (
    InvalidRetrievalFilter,
    document_matches_filters,
    retrieval_cache_key,
    validate_filters,
)
from retrieval.fusion import RetrievedEvidence, RetrieverExecutionResult
from retrieval.metadata import normalize_entity
from retrieval.protocols import (
    RetrievalContribution,
    RetrievalError,
    RetrievalFilters,
    RetrievalPrincipal,
    RetrieverStatus,
    ScoreSemantics,
)
from retrieval.trace import trace_event

INDEXED_FIELDS = (
    "product_model",
    "error_code",
    "order_id",
    "ticket_id",
    "customer_id",
    "document_id",
    "policy_id",
    "product_id",
)


@dataclass(frozen=True)
class MetadataIndex:
    version: str
    mappings: dict[str, dict[str, tuple]]



def _values(metadata: dict[str, Any], field: str) -> list[str]:
    aliases = {
        "product_model": ("product_model", "product_models"),
        "error_code": ("error_code", "error_codes"),
        "document_id": ("document_id", "doc_id"),
    }
    raw_values: list[Any] = []
    for key in aliases.get(field, (field,)):
        raw = metadata.get(key)
        if isinstance(raw, list):
            raw_values.extend(raw)
        elif raw not in (None, ""):
            raw_values.append(raw)
    return list(dict.fromkeys(normalize_entity(str(value)) for value in raw_values))


@lru_cache(maxsize=4)
def _build_metadata_index(version: str) -> MetadataIndex:
    mappings: dict[str, dict[str, list]] = {
        field: defaultdict(list) for field in INDEXED_FIELDS
    }
    for doc in load_chunked_documents(version):
        for field in INDEXED_FIELDS:
            for value in _values(doc.metadata, field):
                mappings[field][value].append(doc)
    frozen = {
        field: {value: tuple(docs) for value, docs in values.items()}
        for field, values in mappings.items()
    }
    return MetadataIndex(version=version, mappings=frozen)


def get_metadata_index(version: str | None = None) -> MetadataIndex:
    return _build_metadata_index(version or corpus_version())


def clear_metadata_index_cache() -> None:
    _build_metadata_index.cache_clear()


def metadata_direct_lookup(
    *,
    entities: dict[str, list[str]] | None,
    query: str,
    principal: RetrievalPrincipal,
    filters: RetrievalFilters | dict | None = None,
    source: str | None = None,
    subquery_id: str | None = None,
    k: int = 15,
    budget: RetrievalBudget | None = None,
) -> RetrieverExecutionResult:
    retriever = "metadata_direct_lookup"
    started = perf_counter()
    normalized_entities = {
        field: list(dict.fromkeys(normalize_entity(str(value)) for value in values if value))
        for field, values in (entities or {}).items()
        if field in INDEXED_FIELDS and values
    }
    if not normalized_entities:
        return RetrieverExecutionResult(
            retriever,
            RetrieverStatus.SKIPPED_BY_PLAN,
        )
    # Anonymous principals proceed only to explicit public/global ACL filtering.
    try:
        unified = validate_filters(filters, principal=principal, source=source)
    except InvalidRetrievalFilter as exc:
        error = RetrievalError(
            stage=retriever,
            error_type="InvalidFilter",
            message=str(exc),
            dependency="filters",
            subquery_id=subquery_id,
        )
        return RetrieverExecutionResult(retriever, RetrieverStatus.INVALID_FILTER, errors=[error])
    if budget and not budget.reserve_metadata():
        status = RetrieverStatus.TIMEOUT if budget.latency_exceeded else RetrieverStatus.SKIPPED_BY_BUDGET
        return RetrieverExecutionResult(retriever, status, degraded_reasons=["metadata lookup budget unavailable"])

    index = get_metadata_index()
    by_chunk: dict[str, tuple[Any, set[str], dict[str, list[str]]]] = {}
    for field, values in normalized_entities.items():
        field_index = index.mappings.get(field, {})
        for entity in values:
            for doc in field_index.get(entity, ()):
                if not document_matches_filters(doc.metadata, unified, principal):
                    continue
                key = str(doc.metadata.get("chunk_id") or id(doc))
                if key not in by_chunk:
                    by_chunk[key] = (doc, set(), defaultdict(list))
                by_chunk[key][1].add(field)
                by_chunk[key][2][field].append(entity)

    ranked = sorted(
        by_chunk.values(),
        key=lambda item: (len(item[1]), sum(len(values) for values in item[2].values())),
        reverse=True,
    )[:k]
    evidences: list[RetrievedEvidence] = []
    for rank, (doc, matched_fields, matched_entities) in enumerate(ranked, 1):
        raw_score = float(sum(len(values) for values in matched_entities.values()))
        contribution = RetrievalContribution(
            retriever=retriever,
            subquery_id=subquery_id,
            rank=rank,
            raw_score=raw_score,
            normalized_score=min(1.0, raw_score / max(1.0, len(normalized_entities))),
            fusion_weight=1.35,
            score_semantics=ScoreSemantics.EXACT_HIGHER_BETTER,
            matched_fields=sorted(matched_fields),
            matched_entities={key: list(dict.fromkeys(values)) for key, values in matched_entities.items()},
        )
        evidences.append(
            RetrievedEvidence(
                document=doc,
                source=retriever,
                retrieval_score=raw_score,
                rerank_score=None,
                query=query,
                source_type=doc.metadata.get("doc_type", "unknown"),
                score_semantics=ScoreSemantics.EXACT_HIGHER_BETTER,
                contributions=[contribution],
                matched_chunk_ids=[str(doc.metadata.get("chunk_id", ""))],
                provenance={"matched_fields": sorted(matched_fields), "matched_entities": contribution.matched_entities},
            )
        )
    if budget:
        evidences = evidences[:budget.record_candidates(len(evidences))]
    elapsed = (perf_counter() - started) * 1000
    event = trace_event(
        retriever,
        "complete",
        subquery_id=subquery_id,
        status="success" if evidences else "no_results",
        returned_count=len(evidences),
        elapsed_ms=round(elapsed, 2),
        corpus_version=index.version,
        matched_entities=normalized_entities,
        access_cache_key=retrieval_cache_key(
            query,
            filters=unified,
            principal=principal,
            source=source,
            corpus_version=index.version,
        ),
    )
    for evidence in evidences:
        evidence.trace.append(event)
    return RetrieverExecutionResult(
        retriever,
        RetrieverStatus.SUCCESS if evidences else RetrieverStatus.NO_RESULTS,
        evidences=evidences,
        trace=[event],
        candidate_count=len(evidences),
    )
