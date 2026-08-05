from __future__ import annotations

import sqlite3
import sys
import threading
import time
import types
from pathlib import Path

import pytest

# The execution environment used for this audit does not provide LangChain.  These
# minimal interface stubs let us test Liorin's own retrieval logic without claiming
# real LangChain/Milvus/CrossEncoder integration.
try:
    from langchain_core.documents import Document  # type: ignore
except ModuleNotFoundError:
    langchain_core = types.ModuleType("langchain_core")
    documents = types.ModuleType("langchain_core.documents")
    messages = types.ModuleType("langchain_core.messages")

    class Document:
        def __init__(self, page_content: str, metadata: dict | None = None):
            self.page_content = page_content
            self.metadata = metadata or {}

    class BaseMessage:
        def __init__(self, content: str = "", **kwargs):
            self.content = content

    class AIMessage(BaseMessage):
        pass

    class HumanMessage(BaseMessage):
        pass

    documents.Document = Document
    messages.AIMessage = AIMessage
    messages.HumanMessage = HumanMessage
    langchain_core.documents = documents
    langchain_core.messages = messages
    # Mark the stub as package-like so later production imports can resolve
    # additional LangChain Core submodules in the same pytest process.
    langchain_core.__path__ = []
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.documents"] = documents
    sys.modules["langchain_core.messages"] = messages

if "tools.documents" not in sys.modules:
    tools_documents = types.ModuleType("tools.documents")
    tools_documents.get_vectorstore = lambda: (_ for _ in ()).throw(RuntimeError("no vectorstore"))
    sys.modules["tools.documents"] = tools_documents

from config import DEFAULT_DB_PATH
from retrieval.budget import RetrievalBudget
from retrieval.context_expander import expand_parent_context
from retrieval.database_retriever import SQL_TEMPLATES, database_search
from retrieval.dense_retriever import dense_search
from retrieval.filters import document_matches_filters
from retrieval.fusion import RetrievedEvidence, RetrieverExecutionResult, reciprocal_rank_fusion
from retrieval.hybrid_retriever import _result_error_status, hybrid_retrieve
from retrieval.metadata_lookup import MetadataIndex, metadata_direct_lookup
from retrieval.protocols import (
    QueryUnderstanding,
    RetrievalContribution,
    RetrievalFilters,
    RetrievalPrincipal,
    RetrievalStatus,
    RetrievalSubquery,
    RetrieverStatus,
    ScoreSemantics,
)
from retrieval.reranker import rerank
from retrieval.sparse_retriever import BM25Index, bm25_search, clear_bm25_cache, get_bm25_index


def principal(tenant: str = "default", **kwargs) -> RetrievalPrincipal:
    return RetrievalPrincipal(
        user_id=kwargs.pop("user_id", "support-1"),
        tenant_id=tenant,
        roles=kwargs.pop("roles", ["support"]),
        groups=kwargs.pop("groups", ["support"]),
        permissions=kwargs.pop("permissions", [
            "knowledge:read", "database:read", "ticket:read",
            "classification:confidential:read",
        ]),
        authenticated=True,
        **kwargs,
    )


def doc(
    chunk_id: str,
    content: str,
    *,
    tenant: str = "default",
    section_id: str | None = None,
    **metadata,
):
    base = {
        "document_id": metadata.pop("document_id", "doc-1"),
        "doc_id": metadata.get("document_id", "doc-1"),
        "section_id": section_id or f"sec-{chunk_id}",
        "parent_id": section_id or f"sec-{chunk_id}",
        "chunk_id": chunk_id,
        "doc_type": metadata.pop("doc_type", "manual"),
        "source": metadata.pop("source", "manual"),
        "source_file": metadata.pop("source_file", "manual.md"),
        "tenant_id": tenant,
        "allowed_user_ids": metadata.pop("allowed_user_ids", []),
        "allowed_groups": metadata.pop("allowed_groups", []),
        "required_permissions": metadata.pop("required_permissions", []),
        "classification": metadata.pop("classification", "public"),
        "acl_identity_public": metadata.pop("acl_identity_public", True),
        "effective_from_ts": metadata.pop("effective_from_ts", 0),
        "effective_to_ts": metadata.pop("effective_to_ts", 0),
        "active": metadata.pop("active", True),
        "section_path": metadata.pop("section_path", "故障 / 错误码"),
        "version": metadata.pop("version", "v2"),
        "effective_from": metadata.pop("effective_from", None),
        "effective_to": metadata.pop("effective_to", None),
    }
    base.update(metadata)
    return Document(page_content=content, metadata=base)


def evidence(document, retriever: str, raw: float, *, semantics=ScoreSemantics.BM25_HIGHER_BETTER):
    normalized = 1 / (1 + raw) if semantics == ScoreSemantics.DISTANCE_LOWER_BETTER else raw / (1 + raw)
    return RetrievedEvidence(
        document=document,
        source=retriever,
        retrieval_score=normalized,
        rerank_score=None,
        query="q",
        source_type=document.metadata.get("doc_type", "manual"),
        score_semantics=semantics,
        contributions=[
            RetrievalContribution(
                retriever=retriever,
                subquery_id="sq-1",
                rank=1,
                raw_score=raw,
                normalized_score=max(0.0, min(1.0, normalized)),
                score_semantics=semantics,
            )
        ],
        matched_chunk_ids=[document.metadata["chunk_id"]],
    )


def test_no_entity_skips_metadata_direct_lookup():
    result = metadata_direct_lookup(
        entities={}, query="机器不工作", principal=principal(), filters={}, budget=RetrievalBudget().start()
    )
    assert result.status == RetrieverStatus.SKIPPED_BY_PLAN
    assert result.evidences == []


def test_model_and_error_code_match_exact_metadata(monkeypatch):
    target = doc("c1", "AX-300 E10", product_models=["AX-300"], product_model="AX-300", error_codes=["E10"], error_code="E10")
    other = doc("c2", "AX-300 E1002", product_models=["AX-300"], product_model="AX-300", error_codes=["E1002"], error_code="E1002")
    mappings = {
        "product_model": {"AX-300": (target, other)},
        "error_code": {"E10": (target,), "E1002": (other,)},
        "order_id": {}, "ticket_id": {}, "customer_id": {}, "document_id": {}, "policy_id": {}, "product_id": {},
    }
    monkeypatch.setattr("retrieval.metadata_lookup.get_metadata_index", lambda: MetadataIndex("v", mappings))
    result = metadata_direct_lookup(
        entities={"product_model": ["AX-300"], "error_code": ["E10"]},
        query="AX-300 E10",
        principal=principal(),
        filters={},
        budget=RetrievalBudget().start(),
    )
    assert result.status == RetrieverStatus.SUCCESS
    assert result.evidences[0].document.metadata["chunk_id"] == "c1"
    assert set(result.evidences[0].contributions[0].matched_fields) == {"error_code", "product_model"}
    assert all(item.document.metadata["error_code"] != "E1002" for item in result.evidences if "error_code" in item.contributions[0].matched_fields)


def test_e10_never_substring_matches_e1002(monkeypatch):
    e1002 = doc("c2", "正文 E1002", error_codes=["E1002"], error_code="E1002")
    mappings = {field: {} for field in ("product_model", "error_code", "order_id", "ticket_id", "customer_id", "document_id", "policy_id", "product_id")}
    mappings["error_code"] = {"E1002": (e1002,)}
    monkeypatch.setattr("retrieval.metadata_lookup.get_metadata_index", lambda: MetadataIndex("v", mappings))
    result = metadata_direct_lookup(entities={"error_code": ["E10"]}, query="E10", principal=principal(), filters={})
    assert result.status == RetrieverStatus.NO_RESULTS


def test_dense_and_bm25_run_in_parallel_and_fuse():
    barrier = threading.Barrier(2)
    d1 = doc("same", "故障处理", product_model="AX-300")

    def dense_fn(*args, **kwargs):
        barrier.wait(timeout=1)
        time.sleep(0.03)
        return RetrieverExecutionResult("dense_milvus", RetrieverStatus.SUCCESS, [evidence(d1, "dense_milvus", 0.2, semantics=ScoreSemantics.DISTANCE_LOWER_BETTER)])

    def sparse_fn(*args, **kwargs):
        barrier.wait(timeout=1)
        time.sleep(0.03)
        return RetrieverExecutionResult("sparse_bm25", RetrieverStatus.SUCCESS, [evidence(d1, "sparse_bm25", 3.0)])

    started = time.perf_counter()
    result = hybrid_retrieve(
        QueryUnderstanding(original_query="故障", normalized_query="故障", requirements=["故障"]),
        RetrievalSubquery(subquery_id="sq-1", query="故障", source="manual"),
        principal=principal(),
        budget=RetrievalBudget(max_latency_ms=3000).start(),
        use_cross_encoder=False,
        dense_fn=dense_fn,
        sparse_fn=sparse_fn,
    )
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25
    assert result.evidences
    assert result.response.status == RetrievalStatus.SUCCESS
    assert {c.retriever for c in result.evidences[0].contributions} == {"dense_milvus", "sparse_bm25"}


def test_fusion_preserves_all_contributions_and_raw_scores():
    same = doc("c1", "x")
    fused = reciprocal_rank_fusion([[evidence(same, "dense_milvus", 0.4)], [evidence(same, "sparse_bm25", 7.2)]])
    assert len(fused) == 1
    assert {(c.retriever, c.raw_score, c.rank) for c in fused[0].contributions} == {
        ("dense_milvus", 0.4, 1), ("sparse_bm25", 7.2, 1)
    }


def test_dense_distance_is_converted_to_higher_better():
    near, far = doc("near", "near"), doc("far", "far")

    class Store:
        search_params = {"metric_type": "L2"}
        def similarity_search_with_score(self, query, **kwargs):
            return [(far, 4.0), (near, 0.1)]

    result = dense_search(
        "q", principal=principal(), filters={}, budget=RetrievalBudget().start(), vectorstore_factory=Store
    )
    assert result.status == RetrieverStatus.SUCCESS
    assert result.evidences[0].document.metadata["chunk_id"] == "near"
    contribution = result.evidences[0].contributions[0]
    assert contribution.score_semantics == ScoreSemantics.DISTANCE_LOWER_BETTER
    assert contribution.normalized_score > result.evidences[1].contributions[0].normalized_score


def test_acl_applies_to_dense_bm25_metadata_and_document_filter(monkeypatch):
    allowed = doc("ok", "AX-300", tenant="T1", product_model="AX-300", product_models=["AX-300"])
    denied = doc("bad", "AX-300", tenant="T2", product_model="AX-300", product_models=["AX-300"])
    p = principal("T1")

    class Store:
        search_params = {"metric_type": "COSINE"}
        def similarity_search_with_score(self, query, **kwargs):
            assert 'tenant_id == "T1"' in kwargs["expr"]
            return [(denied, 0.99), (allowed, 0.8)]

    dense = dense_search("AX-300", principal=p, filters={}, vectorstore_factory=Store)
    assert [x.document.metadata["chunk_id"] for x in dense.evidences] == ["ok"]

    index = BM25Index(
        "v", (allowed, denied), (("ax-300",), ("ax-300",)),
        (__import__("collections").Counter({"ax-300": 1}), __import__("collections").Counter({"ax-300": 1})),
        __import__("collections").Counter({"ax-300": 2}), 1.0,
    )
    monkeypatch.setattr("retrieval.sparse_retriever.get_bm25_index", lambda: index)
    sparse = bm25_search("AX-300", principal=p, filters={})
    assert [x.document.metadata["chunk_id"] for x in sparse.evidences] == ["ok"]

    mappings = {field: {} for field in ("product_model", "error_code", "order_id", "ticket_id", "customer_id", "document_id", "policy_id", "product_id")}
    mappings["product_model"] = {"AX-300": (allowed, denied)}
    monkeypatch.setattr("retrieval.metadata_lookup.get_metadata_index", lambda: MetadataIndex("v", mappings))
    exact = metadata_direct_lookup(entities={"product_model": ["AX-300"]}, query="AX-300", principal=p, filters={})
    assert [x.document.metadata["chunk_id"] for x in exact.evidences] == ["ok"]
    assert document_matches_filters(allowed.metadata, RetrievalFilters(tenant_id="T1"), p)
    assert not document_matches_filters(denied.metadata, RetrievalFilters(tenant_id="T1"), p)


def test_database_acl_and_parameterized_sql():
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    order_id, tenant_id = conn.execute(
        "SELECT o.order_id, c.tenant_id FROM orders o JOIN customers c ON c.customer_id=o.customer_id LIMIT 1"
    ).fetchone()
    conn.close()
    result = database_search(
        order_id,
        principal=principal(tenant_id),
        entities={"order_id": [order_id]},
        filters={},
        budget=RetrievalBudget().start(),
    )
    assert result.status == RetrieverStatus.SUCCESS
    assert result.evidences
    assert all("SQL：" not in item.document.page_content for item in result.evidences)
    denied = database_search(
        order_id,
        principal=principal("WRONG-TENANT"),
        entities={"order_id": [order_id]},
        filters={},
    )
    assert denied.status == RetrieverStatus.NO_RESULTS
    for templates in SQL_TEMPLATES.values():
        for template in templates:
            assert "?" in template.sql
            assert order_id not in template.sql


def test_parent_expansion_denies_unauthorized_parent(monkeypatch):
    original = evidence(doc("c1", "small", section_id="sec-1"), "sparse_bm25", 1.0)
    monkeypatch.setattr(
        "retrieval.context_expander.get_section_context",
        lambda *args, **kwargs: (None, {"section_id": "sec-1"}, "parent_section_permission_denied"),
    )
    result = expand_parent_context(
        [original], principal=principal(), filters=RetrievalFilters(tenant_id="default"), budget=RetrievalBudget().start()
    )
    assert result.evidences == [original]
    assert original.parent_context is None
    assert result.errors[0].error_type == "PermissionDenied"


def test_budget_exhaustion_retains_all_original_evidence(monkeypatch):
    items = [evidence(doc(f"c{i}", f"chunk {i}", section_id=f"sec-{i}"), "sparse_bm25", 1.0) for i in range(3)]
    monkeypatch.setattr("retrieval.context_expander.get_section_context", lambda *args, **kwargs: ("X" * 50, {}, None))
    budget = RetrievalBudget(max_context_chars=0).start()
    result = expand_parent_context(items, principal=principal(), filters=RetrievalFilters(tenant_id="default"), budget=budget)
    assert result.evidences == items
    assert all(item.parent_context is None for item in items)


def test_milvus_failure_is_dependency_error_not_no_results():
    def broken():
        raise ConnectionError("Milvus unavailable")
    result = dense_search("q", principal=principal(), filters={}, vectorstore_factory=broken)
    assert result.status == RetrieverStatus.DEPENDENCY_ERROR
    assert result.errors and result.errors[0].dependency == "milvus"


def test_reranker_failure_is_explicit_degradation(monkeypatch):
    item = evidence(doc("c1", "AX-300 故障处理"), "sparse_bm25", 2.0)
    monkeypatch.setattr("retrieval.reranker._load_cross_encoder", lambda: (_ for _ in ()).throw(RuntimeError("load failed")))
    result = rerank("AX-300 故障", [item], use_cross_encoder=True, budget=RetrievalBudget().start())
    assert result.method == "heuristic"
    assert result.errors and "load failed" in result.errors[0].message
    assert result.evidences[0].rerank_method == "heuristic_coarse"


def test_bm25_index_cache_and_version_invalidation(monkeypatch):
    import retrieval.sparse_retriever as sparse
    calls = []
    monkeypatch.setattr(sparse, "load_chunked_documents", lambda version: calls.append(version) or [doc(f"{version}", version)])
    sparse._build_bm25_index.cache_clear()
    first = sparse.get_bm25_index("v1")
    again = sparse.get_bm25_index("v1")
    second = sparse.get_bm25_index("v2")
    assert first is again
    assert first is not second
    assert calls == ["v1", "v2"]


def test_benchmark_adapter_still_uses_production_retrieval():
    source = Path("evals/benchmark/adapters/retrieval.py").read_text(encoding="utf-8")
    assert "from agents.knowledge_agent import execute_retrieval, plan_retrieval, understand_query" in source
    assert "execute_retrieval(state)" in source
    assert "hybrid_retriever" not in source


def test_pipeline_does_not_invoke_metadata_lookup_without_entities():
    def no_results(name: str):
        return lambda *args, **kwargs: RetrieverExecutionResult(name, RetrieverStatus.NO_RESULTS)

    def forbidden_metadata(*args, **kwargs):
        raise AssertionError("metadata lookup must not be invoked without deterministic entities")

    result = hybrid_retrieve(
        QueryUnderstanding(
            original_query="机器突然不工作",
            normalized_query="机器突然不工作",
            requirements=["解释无法工作的原因"],
        ),
        RetrievalSubquery(subquery_id="sq-no-entity", query="机器突然不工作", source="manual"),
        principal=principal(),
        use_cross_encoder=False,
        dense_fn=no_results("dense_milvus"),
        sparse_fn=no_results("sparse_bm25"),
        metadata_fn=forbidden_metadata,
    )
    outcomes = result.response.audit["retriever_outcomes"]
    metadata = next(item for item in outcomes if item["retriever"] == "metadata_direct_lookup")
    assert metadata["status"] == RetrieverStatus.SKIPPED_BY_PLAN


def test_milvus_prefilter_contains_identity_acl_and_effective_time():
    from retrieval.filters import build_milvus_expression

    p = RetrievalPrincipal(
        user_id='agent"1',
        tenant_id="T1",
        roles=["agent"],
        groups=["support", "north"],
        permissions=["knowledge:read", "classification:confidential:read"],
        authenticated=True,
    )
    expr = build_milvus_expression(
        RetrievalFilters(tenant_id="T1", effective_at="2026-08-05T00:00:00Z"), p
    )
    assert 'tenant_id == "T1"' in expr
    assert "acl_identity_public == true" in expr
    assert "JSON_CONTAINS(allowed_user_ids" in expr
    assert 'agent\\"1' in expr
    assert "JSON_CONTAINS_ANY(allowed_groups" in expr
    assert "effective_from_ts <=" in expr and "effective_to_ts" in expr
    assert 'classification in ["public", "internal", "confidential"]' in expr


def test_access_sensitive_cache_key_changes_with_principal_and_filters():
    from retrieval.filters import retrieval_cache_key

    f1 = RetrievalFilters(tenant_id="T1", region="CN")
    f2 = RetrievalFilters(tenant_id="T1", region="US")
    p1 = principal("T1", user_id="u1", roles=["agent"])
    p2 = principal("T1", user_id="u2", roles=["agent"])
    base = retrieval_cache_key("q", filters=f1, principal=p1, corpus_version="v1")
    assert base != retrieval_cache_key("q", filters=f2, principal=p1, corpus_version="v1")
    assert base != retrieval_cache_key("q", filters=f1, principal=p2, corpus_version="v1")
    assert base != retrieval_cache_key("q", filters=f1, principal=p1, corpus_version="v2")


def test_document_corpus_exposes_document_section_chunk_hierarchy():
    from retrieval.document_corpus import load_chunked_documents

    docs = load_chunked_documents()
    assert docs
    required = {
        "document_id", "section_id", "chunk_id", "parent_id", "section_path",
        "section_start", "section_end", "chunk_start", "chunk_end", "source_file",
        "version", "effective_from", "effective_to", "tenant_id", "allowed_user_ids",
        "allowed_groups", "required_permissions", "classification", "acl_identity_public",
        "active", "language", "source", "effective_from_ts", "effective_to_ts",
        "product_models", "error_codes", "corpus_version",
    }
    assert all(required.issubset(item.metadata) for item in docs)
    assert all(item.metadata["parent_id"] == item.metadata["section_id"] for item in docs)


def test_same_section_expands_once_and_preserves_chunk_provenance(monkeypatch):
    calls = []
    first = evidence(doc("c1", "first", section_id="sec-shared"), "sparse_bm25", 2.0)
    second = evidence(doc("c2", "second", section_id="sec-shared"), "dense_milvus", 0.1, semantics=ScoreSemantics.DISTANCE_LOWER_BETTER)

    def section(*args, **kwargs):
        calls.append(args[0])
        return "完整章节内容", {"section_path": "故障 / E10"}, None

    monkeypatch.setattr("retrieval.context_expander.get_section_context", section)
    result = expand_parent_context(
        [first, second],
        principal=principal(),
        filters=RetrievalFilters(tenant_id="default"),
        budget=RetrievalBudget().start(),
    )
    assert calls == ["sec-shared"]
    assert len(result.evidences) == 1
    merged = result.evidences[0]
    assert merged.parent_context == "完整章节内容"
    assert set(merged.matched_chunk_ids) >= {"c1", "c2"}
    assert {item["chunk_id"] for item in merged.provenance["section_chunk_provenance"]} == {"c1", "c2"}


def test_reranker_text_prioritizes_metadata_chunk_and_parent():
    from retrieval.reranker import build_reranker_text

    item = evidence(
        doc(
            "c1",
            "当前块说明 E10 的排查步骤",
            product_name="空气净化器",
            product_models=["AX-300"],
            error_codes=["E10"],
            section_path="故障 / 错误码 E10",
            version="v7",
            effective_from="2026-01-01",
        ),
        "sparse_bm25",
        2.0,
    )
    item.parent_context = "父章节包含完整的维修步骤"
    text = build_reranker_text(item, "AX-300 E10", include_parent=True)
    for expected in ("文档类型：manual", "空气净化器", "AX-300", "错误码 E10", "v7", "当前命中块", "父章节窗口"):
        assert expected in text


def test_database_does_not_treat_knowledge_read_as_database_permission():
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    order_id = conn.execute("SELECT order_id FROM orders LIMIT 1").fetchone()[0]
    tenant_id = conn.execute(
        "SELECT c.tenant_id FROM orders o JOIN customers c ON c.customer_id=o.customer_id WHERE o.order_id=?",
        (order_id,),
    ).fetchone()[0]
    conn.close()
    read_only_knowledge = RetrievalPrincipal(
        user_id="agent",
        tenant_id=tenant_id,
        roles=["agent"],
        permissions=["knowledge:read"],
        authenticated=True,
    )
    result = database_search(
        order_id,
        principal=read_only_knowledge,
        entities={"order_id": [order_id]},
    )
    assert result.status == RetrieverStatus.PERMISSION_DENIED
    assert result.errors[0].dependency == "acl"


def test_invalid_filter_is_structured_pipeline_error():
    result = hybrid_retrieve(
        QueryUnderstanding(original_query="q", normalized_query="q", requirements=["q"]),
        RetrievalSubquery(
            subquery_id="sq-invalid",
            query="q",
            source="manual",
            filters={"untrusted_field": "x"},
        ),
        principal=principal(),
        use_cross_encoder=False,
    )
    assert result.response.status == RetrievalStatus.INVALID_FILTER
    assert result.response.errors[0].error_type == "InvalidFilter"


def test_product_id_is_direct_lookup_entity_not_product_model():
    from retrieval.metadata import extract_business_entities

    entities = extract_business_entities("查询 PROD-003 的售后记录")
    assert entities["product_id"] == ["PROD-003"]
    assert "PROD-003" not in entities.get("product_model", [])
    understanding = QueryUnderstanding(
        original_query="查询 PROD-003",
        normalized_query="查询 PROD-003",
        product_id="PROD-003",
        requirements=["查询产品售后记录"],
    )
    assert understanding.direct_lookup_entities()["product_id"] == ["PROD-003"]


def test_parent_section_window_is_anchored_around_hit(monkeypatch):
    from retrieval.document_corpus import CorpusSnapshot, get_section_context

    section_start = 1000
    text = "# 很长章节\n" + ("开头无关内容" * 500) + "\nTARGET-E502-REPAIR\n" + ("结尾内容" * 300)
    target = text.index("TARGET-E502-REPAIR")
    section_id = "section-long"
    metadata = {
        "section_id": section_id,
        "section_start": section_start,
        "tenant_id": "default",
        "allowed_user_ids": [],
        "allowed_groups": [],
        "required_permissions": [],
        "classification": "public",
        "acl_identity_public": True,
        "active": True,
    }
    monkeypatch.setattr(
        "retrieval.document_corpus.get_corpus_snapshot",
        lambda: CorpusSnapshot("v", (), {section_id: text}, {section_id: metadata}),
    )
    context, _, denial = get_section_context(
        section_id,
        principal=principal(),
        filters=RetrievalFilters(tenant_id="default"),
        max_chars=500,
        anchor_start=section_start + target,
        anchor_end=section_start + target + len("TARGET-E502-REPAIR"),
    )
    assert denial is None
    assert context.startswith("# 很长章节")
    assert "TARGET-E502-REPAIR" in context
    assert len(context) <= 500


def test_cross_encoder_malformed_score_count_degrades(monkeypatch):
    class BrokenEncoder:
        def predict(self, pairs):
            return [0.9]

    items = [
        evidence(doc("c1", "AX-300 E10"), "sparse_bm25", 2.0),
        evidence(doc("c2", "AX-300 repair"), "sparse_bm25", 1.5),
    ]
    monkeypatch.setattr("retrieval.reranker._load_cross_encoder", lambda: BrokenEncoder())
    result = rerank(
        "AX-300 E10",
        items,
        use_cross_encoder=True,
        budget=RetrievalBudget(max_latency_ms=5000).start(),
    )
    assert result.method == "heuristic"
    assert result.errors
    assert result.errors[0].error_type == "ValueError"
    assert "scores for 2 evidences" in result.errors[0].message
    assert all(item.rerank_method == "heuristic_coarse" for item in result.evidences)


def test_support_role_does_not_bypass_document_acl():
    restricted = doc(
        "restricted",
        "internal",
        allowed_user_ids=["another-user"],
        acl_identity_public=False,
    )
    support = principal(user_id="support-1", roles=["support"], groups=[])
    assert support.is_privileged is False
    assert not document_matches_filters(
        restricted.metadata,
        RetrievalFilters(tenant_id="default"),
        support,
    )


def test_pipeline_trace_reports_partial_not_success():
    item = evidence(doc("c-partial", "evidence"), "sparse_bm25", 2.0)

    def dense_error(*args, **kwargs):
        from retrieval.protocols import RetrievalError
        return RetrieverExecutionResult(
            "dense_milvus",
            RetrieverStatus.DEPENDENCY_ERROR,
            errors=[RetrievalError(
                stage="dense_milvus",
                error_type="ConnectionError",
                message="down",
                retryable=True,
                dependency="milvus",
                subquery_id="sq-partial",
            )],
        )

    def sparse_success(*args, **kwargs):
        return RetrieverExecutionResult("sparse_bm25", RetrieverStatus.SUCCESS, [item])

    result = hybrid_retrieve(
        QueryUnderstanding(original_query="q", normalized_query="q", requirements=["q"]),
        RetrievalSubquery(subquery_id="sq-partial", query="q", source="manual"),
        principal=principal(),
        use_cross_encoder=False,
        dense_fn=dense_error,
        sparse_fn=sparse_success,
    )
    assert result.response.status == RetrievalStatus.PARTIAL
    pipeline_event = [event for event in result.response.trace if event["step"] == "retrieval_pipeline"][-1]
    assert pipeline_event["status"] == RetrievalStatus.PARTIAL


def test_database_applies_unified_product_and_classification_filters():
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    order_id, tenant_id, product_id = conn.execute(
        """
        SELECT o.order_id, c.tenant_id, oi.product_id
        FROM orders o
        JOIN customers c ON c.customer_id=o.customer_id
        JOIN order_items oi ON oi.order_id=o.order_id
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    p = principal(tenant_id)
    matched = database_search(
        order_id,
        principal=p,
        entities={"order_id": [order_id]},
        filters={"product_id": product_id, "classification": "confidential"},
    )
    assert matched.status == RetrieverStatus.SUCCESS
    assert any(item.document.metadata.get("product_id") == product_id for item in matched.evidences)
    mismatched = database_search(
        order_id,
        principal=p,
        entities={"order_id": [order_id]},
        filters={"product_id": "PROD-DOES-NOT-EXIST"},
    )
    assert mismatched.status == RetrieverStatus.NO_RESULTS


def test_database_requires_confidential_classification_permission():
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    order_id, tenant_id = conn.execute(
        "SELECT o.order_id, c.tenant_id FROM orders o JOIN customers c ON c.customer_id=o.customer_id LIMIT 1"
    ).fetchone()
    conn.close()
    no_classification = RetrievalPrincipal(
        user_id="agent",
        tenant_id=tenant_id,
        roles=["agent"],
        permissions=["database:read"],
        authenticated=True,
    )
    result = database_search(
        order_id,
        principal=no_classification,
        entities={"order_id": [order_id]},
    )
    assert result.status == RetrieverStatus.PERMISSION_DENIED


def test_bm25_soft_timeout_returns_ranked_partial_candidates(monkeypatch):
    import retrieval.sparse_retriever as sparse
    from collections import Counter

    docs = (
        doc("low", "E10"),
        doc("high", "E10 E10 E10"),
        doc("later", "E10 E10"),
    )
    tokens = tuple(tuple(sparse.tokenize(item.page_content)) for item in docs)
    counts = tuple(Counter(value) for value in tokens)
    frequencies = Counter()
    for value in tokens:
        frequencies.update(set(value))
    monkeypatch.setattr(
        sparse,
        "get_bm25_index",
        lambda: BM25Index("v", docs, tokens, counts, frequencies, 2.0),
    )

    class ExpiringBudget:
        def __init__(self):
            self.checks = 0
        def reserve_sparse(self):
            return True
        @property
        def latency_exceeded(self):
            self.checks += 1
            return self.checks >= 3
        def record_candidates(self, count):
            return count

    result = bm25_search(
        "E10",
        principal=principal(),
        filters={},
        budget=ExpiringBudget(),
    )
    assert result.status == RetrieverStatus.TIMEOUT
    assert result.soft_timeout is True
    assert result.evidences
    scores = [item.retrieval_score for item in result.evidences]
    assert scores == sorted(scores, reverse=True)
    assert [item.contributions[0].rank for item in result.evidences] == list(
        range(1, len(result.evidences) + 1)
    )


def test_local_production_pipeline_uses_real_bm25_corpus_and_section_expansion():
    budget = RetrievalBudget(
        max_dense_queries=0,
        max_sparse_queries=2,
        max_metadata_queries=1,
        max_database_queries=1,
        max_candidates=20,
        max_final_evidences=5,
        max_context_chars=5000,
        max_latency_ms=5000,
    ).start()
    result = hybrid_retrieve(
        QueryUnderstanding(
            original_query="退货退款政策和维修周期",
            normalized_query="退货退款政策和维修周期",
            requirements=["说明退货退款政策", "说明维修周期"],
        ),
        RetrievalSubquery(
            subquery_id="sq-local-real",
            query="退货退款政策和维修周期",
            source="policy",
            retrieval_mode="hybrid",
        ),
        principal=principal(),
        budget=budget,
        use_cross_encoder=False,
    )
    assert result.evidences
    outcomes = {item.retriever: item for item in result.retriever_results}
    assert outcomes["dense_milvus"].status == RetrieverStatus.SKIPPED_BY_BUDGET
    assert outcomes["sparse_bm25"].status == RetrieverStatus.SUCCESS
    assert outcomes["metadata_direct_lookup"].status == RetrieverStatus.SKIPPED_BY_PLAN
    assert any(item.parent_context for item in result.evidences)
    assert result.response.status == RetrievalStatus.PARTIAL


def test_database_source_alias_normalizes_to_structured_db():
    filters = RetrievalFilters.from_legacy({"source": "database"}, tenant_id="T1")
    assert filters.source == "structured_db"


def test_retrieval_package_is_included_in_build_artifact():
    import tomllib
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "retrieval" in config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]


def test_mixed_budget_skip_and_executed_no_result_is_no_results():
    results = [
        RetrieverExecutionResult(
            "dense_milvus", RetrieverStatus.SKIPPED_BY_BUDGET
        ),
        RetrieverExecutionResult(
            "sparse_bm25", RetrieverStatus.NO_RESULTS
        ),
        RetrieverExecutionResult(
            "metadata_direct_lookup", RetrieverStatus.SKIPPED_BY_PLAN
        ),
    ]
    assert _result_error_status(results) == RetrievalStatus.NO_RESULTS


def test_all_planned_routes_skipped_by_budget_is_budget_exhausted():
    results = [
        RetrieverExecutionResult(
            "dense_milvus", RetrieverStatus.SKIPPED_BY_BUDGET
        ),
        RetrieverExecutionResult(
            "sparse_bm25", RetrieverStatus.SKIPPED_BY_BUDGET
        ),
        RetrieverExecutionResult(
            "metadata_direct_lookup", RetrieverStatus.SKIPPED_BY_PLAN
        ),
    ]
    assert _result_error_status(results) == RetrievalStatus.BUDGET_EXHAUSTED
