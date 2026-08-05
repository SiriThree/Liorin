"""Offline checks for the Agentic RAG retrieval workflow.

This script avoids external LLM and Milvus requirements. It validates the
planner heuristics, local hybrid retrieval path, structured database retrieval,
evidence/citation helpers, retry bounds, and trace/budget accounting.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from agents.knowledge_agent import (
    MAX_RETRIEVAL_RETRIES,
    _detect_conflicts,
    _fallback_sources,
    _validate_citations,
    execute_retrieval,
    plan_supplemental_retrieval,
)
from langchain_core.documents import Document
from retrieval.budget import RetrievalBudget
from retrieval.database_retriever import database_search
from retrieval.hybrid_retriever import hybrid_search
from retrieval.metadata import extract_error_codes, extract_product_model
from retrieval.protocols import RetrievalPrincipal, RetrievalSubquery, VerificationDecision
from retrieval.sparse_retriever import tokenize


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _test_principal() -> RetrievalPrincipal:
    return RetrievalPrincipal(
        user_id="support-eval",
        tenant_id="TENANT-CONSUMER",
        roles=["support"],
        groups=["support"],
        permissions=[
            "database:read",
            "ticket:read",
            "order:read",
            "document:read",
            "classification:confidential:read",
        ],
        region="CN",
        authenticated=True,
    )


def check_planner_sources() -> None:
    cases = [
        ("洗碗机无法启动，质保还能维修吗？", {"manual", "policy"}),
        ("ORD-2026-00001 现在是什么状态？", {"database"}),
        ("有没有相似工单处理过水泵无法启动？", {"ticket_history", "manual"}),
        ("退货流程应该怎么办？", {"policy", "faq"}),
    ]
    for question, expected in cases:
        state = {
            "messages": [HumanMessage(content=question)],
            "original_question": question,
            "rewritten_question": question,
            "task_type": question,
        }
        sources = set(_fallback_sources(state))
        _assert(expected & sources == expected, f"planner source mismatch: {question} -> {sources}")


def check_database_retrieval() -> None:
    response = database_search("ORD-2026-00002 订单状态和生命周期事件", principal=_test_principal(), k=5)
    results = response.evidences
    _assert(results, "database_search returned no evidence")
    _assert(all(item.source_type == "structured_db" for item in results), "database_search source_type mismatch")
    _assert(any("结构化业务数据" in item.document.page_content for item in results), "database evidence should include structured data")
    _assert(all("SELECT " not in item.document.page_content.upper() for item in results), "database evidence should not expose SQL")
    _assert(all(item.citation_id for item in results), "database evidence missing citation id")


def check_hybrid_local_retrieval() -> None:
    budget = RetrievalBudget(max_dense_queries=0, max_sparse_queries=4).start()
    results = hybrid_search(
        "退货 退款 质保",
        source="policy",
        budget=budget,
        final_k=3,
        use_cross_encoder=False,
    )
    _assert(results, "hybrid_search returned no local evidence")
    _assert(budget.dense_queries_used == 0, "dense budget should disable dense retrieval")
    _assert(budget.sparse_queries_used <= 4, "sparse retrieval exceeded budget")
    _assert(all(item.citation_id for item in results), "hybrid evidence missing citation ids")
    _assert(any(item.parent_context for item in results), "parent section expansion missing")


def check_execute_retrieval_trace() -> None:
    state = {
        "retrieval_plan": [
            {
                "query": "ORD-2026-00002 状态",
                "source": "database",
                "filters": {},
                "purpose": "查询订单状态",
                "execution": "parallel",
            },
        ],
        "trace_events": [],
        "estimated_cost": {},
        "use_cross_encoder": False,
        "principal": _test_principal().to_state(),
    }
    result = execute_retrieval(state)
    _assert(result["evidences"], "execute_retrieval returned no evidence")
    _assert(result["trace_events"], "execute_retrieval missing trace events")
    _assert(result["estimated_cost"]["retrieval"]["final_evidence_count"] <= 8, "final evidence budget exceeded")
    _assert(result["latency_ms"] >= 0, "latency not recorded")
    _assert(result["dense_queries_used"] >= 0 and result["sparse_queries_used"] >= 0, "global budget state not returned")


def check_validation_helpers() -> None:
    evidences = execute_retrieval(
        {
            "retrieval_plan": [
                {
                    "query": "ORD-2026-00002 状态",
                    "source": "database",
                    "filters": {},
                    "purpose": "查询订单状态",
                    "execution": "parallel",
                }
            ],
            "trace_events": [],
            "estimated_cost": {},
            "use_cross_encoder": False,
            "principal": _test_principal().to_state(),
        }
    )["evidences"]
    _assert(not _validate_citations("答案引用 [1]", evidences), "valid numeric citation rejected")
    _assert(_validate_citations("答案引用 [999]", evidences), "invalid citation not detected")
    conflict, _group = _detect_conflicts(evidences)
    _assert(isinstance(conflict, bool), "conflict detector should return bool")


def check_chinese_tokenization_and_entities() -> None:
    tokens = set(tokenize("空气净化器滤芯复位 ERR-42 AP-300"))
    _assert("空气净化器" in tokens, "Chinese tokenizer should preserve domain phrase")
    _assert("滤芯复位" in tokens, "Chinese tokenizer should preserve reset phrase")
    _assert(extract_error_codes("报错 ERR-42，型号 AP-300")[0] == "ERR-42", "error code extraction failed")
    _assert(extract_product_model("报错 ERR-42，型号 AP-300") == "AP-300", "product model extraction confused with error code")


def check_conflict_precision() -> None:
    normal = [
        {
            "document": Document(
                page_content="7 天退货、15 天换货、1 年质保。",
                metadata={"product_id": "P-1", "section_type": "policy"},
            )
        }
    ]
    conflict = [
        {
            "document": Document(
                page_content="A100 滤芯提示灯复位时长为 5 秒。",
                metadata={"product_id": "P-1", "section_type": "maintenance"},
            )
        },
        {
            "document": Document(
                page_content="A100 滤芯提示灯复位时长为 10 秒。",
                metadata={"product_id": "P-1", "section_type": "maintenance"},
            )
        },
    ]
    _assert(not _detect_conflicts(normal)[0], "different policy windows should not be treated as conflict")
    _assert(_detect_conflicts(conflict)[0], "same subject/predicate values should be conflict")


def check_global_budget_across_rounds() -> None:
    state = {
        "retrieval_started_at": 0.0,
        "dense_queries_used": 0,
        "sparse_queries_used": 7,
        "retrieval_plan": [
            {
                "query": "退货 退款 政策",
                "source": "policy",
                "filters": {},
                "purpose": "查询政策",
                "execution": "parallel",
            }
        ],
        "trace_events": [],
        "estimated_cost": {},
        "use_cross_encoder": False,
    }
    result = execute_retrieval(state)
    _assert(result["sparse_queries_used"] <= 8, "global sparse budget exceeded across rounds")


def check_retry_bound() -> None:
    state = {
        "retry_count": MAX_RETRIEVAL_RETRIES - 1,
        "requirements": ["质保范围", "维修流程"],
        "missing_requirements": ["维修流程"],
        "rewritten_question": "洗碗机无法启动是否能质保维修",
        "verification_decision": VerificationDecision(
            action="supplement",
            reason="missing repair process",
            missing_requirements=["维修流程"],
            next_subqueries=[
                RetrievalSubquery(
                    subquery_id="eval-supplement-1",
                    query="洗碗机 维修流程",
                    source="policy",
                    reason="补充缺失的维修流程",
                )
            ],
        ).to_state(),
    }
    result = plan_supplemental_retrieval(state)
    _assert(result["retry_count"] == MAX_RETRIEVAL_RETRIES, "supplemental retry bound increment failed")
    _assert(result["retrieval_plan"], "supplemental plan missing")
    _assert("维修流程" in result["retrieval_plan"][0]["query"] and "质保范围" not in result["retrieval_plan"][0]["query"], "supplemental search should focus on missing requirements")


def main() -> None:
    checks = [
        check_planner_sources,
        check_database_retrieval,
        check_hybrid_local_retrieval,
        check_execute_retrieval_trace,
        check_validation_helpers,
        check_chinese_tokenization_and_entities,
        check_conflict_precision,
        check_global_budget_across_rounds,
        check_retry_bound,
    ]
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    print("PASS agentic_rag_eval")


if __name__ == "__main__":
    main()
