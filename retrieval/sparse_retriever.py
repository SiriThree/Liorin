"""Versioned BM25 retrieval over the local hierarchical corpus."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter

from retrieval.budget import RetrievalBudget
from retrieval.document_corpus import corpus_version, load_chunked_documents
from retrieval.filters import (
    InvalidRetrievalFilter,
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

ALNUM_PATTERN = re.compile(r"[A-Za-z]+[\w-]*|\d+")
MODEL_OR_ERROR_PATTERN = re.compile(r"\b[A-Z]{1,8}[-_ ]?\d{2,6}[A-Z0-9-]*\b", re.IGNORECASE)
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
DOMAIN_TERMS = [
    "空气净化器", "滤芯复位", "无理由退货", "订单状态事件", "质保案例", "售后工单",
    "工单事件", "生命周期事件", "无法启动", "启动失败", "蓝牙配对", "冷却系统",
    "门封密封", "噪音振动", "退款到账", "退货流程", "维修检测", "延长保修",
    "发货状态", "订单状态", "客户记录", "历史工单", "相似工单",
]


@lru_cache(maxsize=1)
def _jieba():
    try:
        import jieba
        for term in DOMAIN_TERMS:
            jieba.add_word(term)
        return jieba
    except Exception:
        return None


def _fallback_chinese_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    terms = sorted(DOMAIN_TERMS, key=len, reverse=True)
    index = 0
    while index < len(text):
        matched = next((term for term in terms if text.startswith(term, index)), None)
        if matched:
            tokens.append(matched)
            index += len(matched)
            continue
        for size in (4, 3, 2):
            if index + size <= len(text):
                tokens.append(text[index:index + size])
        index += 1
    return tokens


def tokenize(text: str) -> list[str]:
    """Tokenize without double-counting the same alphanumeric span via two regexes."""
    tokens: list[str] = []
    covered: list[tuple[int, int]] = []
    for match in MODEL_OR_ERROR_PATTERN.finditer(text):
        tokens.append(match.group(0).replace(" ", "").replace("_", "-").lower())
        covered.append(match.span())
    for match in ALNUM_PATTERN.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in covered):
            continue
        tokens.append(match.group(0).lower())
    segmenter = _jieba()
    for chunk in CHINESE_PATTERN.findall(text):
        if segmenter:
            tokens.extend(token.lower() for token in segmenter.cut(chunk) if token.strip())
        else:
            tokens.extend(token.lower() for token in _fallback_chinese_tokens(chunk))
    return [token for token in tokens if len(token) > 1]


@dataclass(frozen=True)
class BM25Index:
    version: str
    docs: tuple
    tokenized_docs: tuple[tuple[str, ...], ...]
    term_counts: tuple[Counter, ...]
    doc_freq: Counter
    avg_len: float


@lru_cache(maxsize=4)
def _build_bm25_index(version: str) -> BM25Index:
    docs = tuple(load_chunked_documents(version))
    tokenized = tuple(
        tuple(tokenize(doc.page_content + " " + " ".join(map(str, doc.metadata.values()))))
        for doc in docs
    )
    counts = tuple(Counter(tokens) for tokens in tokenized)
    doc_freq: Counter = Counter()
    for tokens in tokenized:
        doc_freq.update(set(tokens))
    avg_len = sum(len(tokens) for tokens in tokenized) / max(1, len(tokenized))
    return BM25Index(version, docs, tokenized, counts, doc_freq, avg_len)


def get_bm25_index(version: str | None = None) -> BM25Index:
    return _build_bm25_index(version or corpus_version())


def clear_bm25_cache() -> None:
    _build_bm25_index.cache_clear()


def bm25_search(
    query: str,
    *,
    principal: RetrievalPrincipal,
    filters: RetrievalFilters | dict | None = None,
    source: str | None = None,
    subquery_id: str | None = None,
    k: int = 15,
    budget: RetrievalBudget | None = None,
) -> RetrieverExecutionResult:
    retriever = "sparse_bm25"
    started = perf_counter()
    # Anonymous principals proceed only to explicit public/global ACL filtering.
    try:
        unified = validate_filters(filters, principal=principal, source=source)
    except InvalidRetrievalFilter as exc:
        error = RetrievalError(stage=retriever, error_type="InvalidFilter", message=str(exc), dependency="filters", subquery_id=subquery_id)
        return RetrieverExecutionResult(retriever, RetrieverStatus.INVALID_FILTER, errors=[error])
    if budget and not budget.reserve_sparse():
        status = RetrieverStatus.TIMEOUT if budget.latency_exceeded else RetrieverStatus.SKIPPED_BY_BUDGET
        return RetrieverExecutionResult(retriever, status, degraded_reasons=["sparse budget unavailable"])

    try:
        index = call_with_resilience(
            "bm25_index",
            get_bm25_index,
            retry_policy=RetryPolicy(max_attempts=1),
            max_concurrency=16,
        )
    except Exception as exc:
        error = RetrievalError(
            stage=retriever,
            error_type=type(exc).__name__,
            message=str(exc),
            retryable=True,
            dependency="bm25_index",
            subquery_id=subquery_id,
        )
        event = trace_event(
            retriever, "error", subquery_id=subquery_id,
            status="dependency_error", error_type=type(exc).__name__,
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
        return RetrieverExecutionResult(
            retriever, RetrieverStatus.DEPENDENCY_ERROR, errors=[error], trace=[event]
        )
    query_tokens = tokenize(query)
    if not query_tokens:
        return RetrieverExecutionResult(retriever, RetrieverStatus.NO_RESULTS)
    scored: list[RetrievedEvidence] = []
    for doc, counts, tokens in zip(index.docs, index.term_counts, index.tokenized_docs):
        if budget and budget.latency_exceeded:
            partial = sorted(
                scored,
                key=lambda item: item.retrieval_score or 0.0,
                reverse=True,
            )[:k]
            for rank, item in enumerate(partial, 1):
                item.contributions[0].rank = rank
            partial = partial[:budget.record_candidates(len(partial))]
            error = RetrievalError(
                stage=retriever,
                error_type="TimeoutError",
                message="BM25 latency budget reached; partial ranked candidates returned",
                retryable=True,
                dependency="local_bm25",
                subquery_id=subquery_id,
            )
            event = trace_event(
                retriever,
                "soft_timeout",
                subquery_id=subquery_id,
                status="timeout",
                returned_count=len(partial),
                candidate_count=len(index.docs),
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
                corpus_version=index.version,
            )
            for item in partial:
                item.trace.append(event)
            return RetrieverExecutionResult(
                retriever,
                RetrieverStatus.TIMEOUT,
                evidences=partial,
                errors=[error],
                trace=[event],
                degraded_reasons=[error.message],
                soft_timeout=True,
                candidate_count=len(partial),
            )
        if not document_matches_filters(doc.metadata, unified, principal):
            continue
        score = 0.0
        doc_len = len(tokens) or 1
        for token in query_tokens:
            tf = counts.get(token, 0)
            if not tf:
                continue
            df = index.doc_freq[token]
            idf = math.log(1 + (len(index.docs) - df + 0.5) / (df + 0.5))
            score += idf * (tf * 2.2) / (tf + 1.2 * (1 - 0.75 + 0.75 * doc_len / max(index.avg_len, 1)))
        if score <= 0:
            continue
        scored.append(RetrievedEvidence(
            document=doc,
            source=retriever,
            retrieval_score=score,
            rerank_score=None,
            query=query,
            source_type=doc.metadata.get("doc_type", "unknown"),
            score_semantics=ScoreSemantics.BM25_HIGHER_BETTER,
            matched_chunk_ids=[str(doc.metadata.get("chunk_id", ""))],
            contributions=[RetrievalContribution(
                retriever=retriever, subquery_id=subquery_id, rank=1,
                raw_score=score, normalized_score=normalize_score(score, ScoreSemantics.BM25_HIGHER_BETTER),
                score_semantics=ScoreSemantics.BM25_HIGHER_BETTER,
            )],
        ))
    results = sorted(scored, key=lambda item: item.retrieval_score or 0.0, reverse=True)[:k]
    for rank, item in enumerate(results, 1):
        item.contributions[0].rank = rank
    if budget:
        results = results[:budget.record_candidates(len(results))]
    elapsed = (perf_counter() - started) * 1000
    event = trace_event(
        retriever,
        "complete",
        subquery_id=subquery_id,
        status="success" if results else "no_results",
        candidate_count=len(index.docs),
        returned_count=len(results),
        elapsed_ms=round(elapsed, 2),
        corpus_version=index.version,
        access_cache_key=retrieval_cache_key(
            query,
            filters=unified,
            principal=principal,
            source=source,
            corpus_version=index.version,
        ),
    )
    for item in results:
        item.trace.append(event)
    return RetrieverExecutionResult(retriever, RetrieverStatus.SUCCESS if results else RetrieverStatus.NO_RESULTS, results, trace=[event], candidate_count=len(results))


# Backward-compatible name; implementation is now metadata-index based and imported lazily.
def exact_match_search(query: str, **kwargs):
    """Compatibility alias for deterministic metadata lookup, never body scanning."""

    from retrieval.metadata import extract_business_entities

    entities = extract_business_entities(query)
    if not entities:
        return RetrieverExecutionResult(
            "metadata_direct_lookup",
            RetrieverStatus.SKIPPED_BY_PLAN,
        )
    from retrieval.metadata_lookup import metadata_direct_lookup

    return metadata_direct_lookup(entities=entities, query=query, **kwargs)
