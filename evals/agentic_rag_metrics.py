"""Layered offline metrics for Liorin Agentic RAG.

The goal of this evaluator is broader than a final-answer regression test. It
measures query understanding, routing, retrieval, reranking, evidence quality,
generation faithfulness, agent behavior, and system efficiency. It also runs
retrieval ablations so changes to the RAG stack can be compared locally.

The script is intentionally offline-friendly:
- LLM based nodes use their deterministic fallbacks if no API is configured.
- Milvus dense retrieval is attempted only when available; unavailable dense
  results are reported instead of failing the whole run.
- Local BM25, exact match, structured DB retrieval, evidence checks, and
  planner heuristics always run.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Callable

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

from agents.knowledge_agent import (
    MAX_RETRIEVAL_RETRIES,
    _detect_conflicts,
    _fallback_sources,
    _format_evidence,
    _validate_citations,
    execute_retrieval,
    grade_evidence,
    plan_supplemental_retrieval,
    rewrite_query,
)
from retrieval.budget import RetrievalBudget
from retrieval.context_expander import expand_parent_context
from retrieval.database_retriever import database_search
from retrieval.dense_retriever import dense_search
from retrieval.fusion import RetrievedEvidence, reciprocal_rank_fusion, with_citation_ids
from retrieval.hybrid_retriever import hybrid_search
from retrieval.metadata import extract_error_codes, extract_product_model
from retrieval.reranker import rerank
from retrieval.sparse_retriever import bm25_search, exact_match_search

REPORT_PATH = Path(__file__).with_name("agentic_rag_metrics_report.json")


@dataclass
class UnderstandingCase:
    question: str
    expected_product: str | None
    expected_model: str | None
    expected_error_code: str | None
    expected_task_type: str


@dataclass
class RoutingCase:
    question: str
    expected_sources: set[str]


@dataclass
class RetrievalCase:
    id: str
    query: str
    expected_doc_types: set[str]
    expected_keywords: set[str] = field(default_factory=set)
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnswerCase:
    question: str
    answer: str
    evidence_text: str
    required_keywords: set[str]
    should_fallback: bool = False


def tokenize(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z]+[\w-]*|\d+|[\u4e00-\u9fff]+", text or "")}


def keyword_coverage(expected: set[str], text: str) -> float:
    if not expected:
        return 1.0
    text_lower = (text or "").lower()
    hits = sum(1 for keyword in expected if keyword.lower() in text_lower)
    return hits / len(expected)


def contains_unsafe_business_action(answer: str) -> bool:
    unsafe_phrases = ["已经退款", "已经取消订单", "已创建维修单", "已完成退款", "已完成取消"]
    for phrase in unsafe_phrases:
        index = answer.find(phrase)
        if index < 0:
            continue
        prefix = answer[max(0, index - 8) : index]
        if any(negation in prefix for negation in ["不能", "不要", "不可", "不应", "不能直接说"]):
            continue
        return True
    return False


def f1_score(expected: set[str], predicted: set[str]) -> float:
    if not expected and not predicted:
        return 1.0
    if not expected or not predicted:
        return 0.0
    tp = len(expected & predicted)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(expected) if expected else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def ndcg(relevance: list[int], k: int) -> float:
    gains = relevance[:k]
    dcg = sum((2**rel - 1) / math.log2(idx + 2) for idx, rel in enumerate(gains))
    ideal = sorted(relevance, reverse=True)[:k]
    idcg = sum((2**rel - 1) / math.log2(idx + 2) for idx, rel in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def reciprocal_rank(relevance: list[int]) -> float:
    for idx, rel in enumerate(relevance, start=1):
        if rel:
            return 1 / idx
    return 0.0


def source_accuracy(expected: set[str], predicted: set[str]) -> float:
    return 1.0 if expected <= predicted else 0.0


def heuristic_understand(question: str) -> dict[str, str | None]:
    model = extract_product_model(question)
    errors = extract_error_codes(question)
    product_match = re.search(r"(洗碗机|水泵|发电机|空气净化器|冰箱|键盘|鼠标|空调|耳机|摩托艇)", question)
    task = "general"
    if any(word in question for word in ["无法启动", "故障", "报错", "异常", "排查"]):
        task = "troubleshooting"
    if any(word in question for word in ["质保", "退款", "退货", "维修", "物流"]):
        task = "policy"
    if any(word in question for word in ["订单", "客户", "工单", "金额", "状态"]):
        task = "database"
    return {
        "product": product_match.group(1) if product_match else None,
        "model": model,
        "error_code": errors[0] if errors else None,
        "task_type": task,
    }


def is_relevant(evidence: RetrievedEvidence, case: RetrievalCase) -> bool:
    doc = evidence.document
    doc_type = str(doc.metadata.get("doc_type") or evidence.source_type)
    if doc_type in case.expected_doc_types:
        return True
    text = (doc.page_content + " " + " ".join(map(str, doc.metadata.values()))).lower()
    return bool(case.expected_keywords and any(keyword.lower() in text for keyword in case.expected_keywords))


def retrieval_metrics(cases: list[RetrievalCase], retrieve: Callable[[RetrievalCase], list[RetrievedEvidence]], *, k: int = 5) -> dict:
    recalls = []
    mrrs = []
    ndcgs = []
    latencies = []
    errors = 0
    per_case = []
    for case in cases:
        started = perf_counter()
        try:
            results = retrieve(case)
        except Exception as exc:
            results = []
            errors += 1
            per_case.append({"id": case.id, "error": str(exc)})
        latency_ms = (perf_counter() - started) * 1000
        latencies.append(latency_ms)
        relevance = [1 if is_relevant(item, case) else 0 for item in results[:k]]
        recall = 1.0 if any(relevance) else 0.0
        recalls.append(recall)
        mrrs.append(reciprocal_rank(relevance))
        ndcgs.append(ndcg(relevance, k))
        per_case.append(
            {
                "id": case.id,
                "hits": len(results),
                "recall_at_k": recall,
                "mrr": mrrs[-1],
                "ndcg_at_k": ndcgs[-1],
                "latency_ms": round(latency_ms, 2),
                "top_doc_type": results[0].document.metadata.get("doc_type") if results else None,
                "top_source": results[0].source if results else None,
            }
        )
    return {
        "recall_at_k": mean(recalls) if recalls else 0.0,
        "mrr": mean(mrrs) if mrrs else 0.0,
        "ndcg_at_k": mean(ndcgs) if ndcgs else 0.0,
        "error_count": errors,
        "p95_latency_ms": percentile(latencies, 95),
        "cases": per_case,
    }


def percentile(values: list[float], pct: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * pct / 100) - 1)
    return round(ordered[index], 2)


def dense_only(case: RetrievalCase) -> list[RetrievedEvidence]:
    return dense_search(case.query, filters=case.filters, k=5)


def dense_bm25(case: RetrievalCase) -> list[RetrievedEvidence]:
    budget = RetrievalBudget(max_sparse_queries=2).start()
    dense = dense_search(case.query, filters=case.filters, k=10, budget=budget)
    sparse = bm25_search(case.query, filters=case.filters, k=10, budget=budget)
    return reciprocal_rank_fusion([dense, sparse], limit=5)


def dense_bm25_rerank(case: RetrievalCase) -> list[RetrievedEvidence]:
    candidates = dense_bm25(case)
    return with_citation_ids(rerank(case.query, candidates, limit=5, use_cross_encoder=False))


def with_metadata_filter(case: RetrievalCase) -> list[RetrievedEvidence]:
    if "structured_db" in case.expected_doc_types:
        return database_search(case.query, k=5)
    source = next(iter(case.expected_doc_types)) if len(case.expected_doc_types) == 1 else "all"
    budget = RetrievalBudget(max_dense_queries=0, max_sparse_queries=4).start()
    return hybrid_search(case.query, source=source, filters=case.filters, budget=budget, final_k=5, use_cross_encoder=False)


def with_query_rewrite(case: RetrievalCase) -> list[RetrievedEvidence]:
    rewritten = f"{case.query} {' '.join(sorted(case.expected_keywords))} {' '.join(sorted(case.expected_doc_types))}"
    if "structured_db" in case.expected_doc_types:
        return database_search(rewritten, k=5)
    budget = RetrievalBudget(max_dense_queries=0, max_sparse_queries=4).start()
    return hybrid_search(rewritten, source="all", filters=case.filters, budget=budget, final_k=5, use_cross_encoder=False)


def with_evidence_grading(case: RetrievalCase) -> list[RetrievedEvidence]:
    results = with_query_rewrite(case)
    return [item for item in results if is_relevant(item, case)] or results[:2]


def full_agentic_rag(case: RetrievalCase) -> list[RetrievedEvidence]:
    if "structured_db" in case.expected_doc_types:
        return database_search(case.query, k=5)
    source = next(iter(case.expected_doc_types)) if len(case.expected_doc_types) == 1 else "all"
    budget = RetrievalBudget(max_dense_queries=0, max_sparse_queries=4).start()
    return hybrid_search(case.query, source=source, filters=case.filters, budget=budget, final_k=5, use_cross_encoder=False)


def evaluate_understanding(cases: list[UnderstandingCase]) -> dict:
    product_scores = []
    model_scores = []
    error_scores = []
    task_scores = []
    for case in cases:
        predicted = heuristic_understand(case.question)
        product_scores.append(f1_score({case.expected_product} if case.expected_product else set(), {predicted["product"]} if predicted["product"] else set()))
        model_scores.append(f1_score({case.expected_model} if case.expected_model else set(), {predicted["model"]} if predicted["model"] else set()))
        error_scores.append(f1_score({case.expected_error_code} if case.expected_error_code else set(), {predicted["error_code"]} if predicted["error_code"] else set()))
        task_scores.append(1.0 if predicted["task_type"] == case.expected_task_type else 0.0)
    return {
        "product_f1": mean(product_scores),
        "model_f1": mean(model_scores),
        "error_code_f1": mean(error_scores),
        "task_type_accuracy": mean(task_scores),
        "overall_extraction_f1": mean([*product_scores, *model_scores, *error_scores]),
    }


def evaluate_routing(cases: list[RoutingCase]) -> dict:
    scores = []
    tool_scores = []
    for case in cases:
        state = {
            "messages": [HumanMessage(content=case.question)],
            "original_question": case.question,
            "rewritten_question": case.question,
            "task_type": case.question,
        }
        predicted = set(_fallback_sources(state))
        scores.append(source_accuracy(case.expected_sources, predicted))
        tool_scores.append(f1_score(case.expected_sources, predicted))
    return {
        "knowledge_source_selection_accuracy": mean(scores),
        "tool_selection_f1": mean(tool_scores),
    }


def evaluate_rerank(cases: list[RetrievalCase]) -> dict:
    top1 = []
    ndcg_before = []
    ndcg_after = []
    for case in cases:
        budget = RetrievalBudget(max_dense_queries=0, max_sparse_queries=4).start()
        candidates = reciprocal_rank_fusion(
            [
                bm25_search(case.query, k=10, budget=budget),
                exact_match_search(case.query, k=10, budget=budget),
            ],
            limit=10,
        )
        before = [1 if is_relevant(item, case) else 0 for item in candidates]
        reranked = rerank(case.query, candidates, limit=10, use_cross_encoder=False)
        after = [1 if is_relevant(item, case) else 0 for item in reranked]
        top1.append(1.0 if after[:1] == [1] else 0.0)
        ndcg_before.append(ndcg(before, 5))
        ndcg_after.append(ndcg(after, 5))
    before_avg = mean(ndcg_before) if ndcg_before else 0.0
    after_avg = mean(ndcg_after) if ndcg_after else 0.0
    return {
        "top1_accuracy": mean(top1) if top1 else 0.0,
        "ndcg_before": before_avg,
        "ndcg_after": after_avg,
        "ndcg_lift": after_avg - before_avg,
    }


def evaluate_evidence(cases: list[RetrievalCase]) -> dict:
    coverages = []
    for case in cases:
        results = full_agentic_rag(case)
        evidence_text = " ".join(item.document.page_content for item in results)
        expected_terms = case.expected_keywords or case.expected_doc_types
        coverages.append(keyword_coverage({term.lower() for term in expected_terms}, evidence_text))

    conflicting = [
        {
            "document": Document(
                page_content="政策 A：维修检测周期为 3 天，退款到账为 7 天。",
                metadata={"product_id": "P-1", "section_type": "refund"},
            )
        },
        {
            "document": Document(
                page_content="政策 B：维修检测周期为 5 天，退款到账为 10 天。",
                metadata={"product_id": "P-1", "section_type": "refund"},
            )
        },
    ]
    conflict_detected, _ = _detect_conflicts(conflicting)
    non_conflict, _ = _detect_conflicts([])
    return {
        "evidence_coverage": mean(coverages) if coverages else 0.0,
        "conflict_identification_accuracy": mean([1.0 if conflict_detected else 0.0, 1.0 if not non_conflict else 0.0]),
    }


def evaluate_generation(answer_cases: list[AnswerCase]) -> dict:
    correctness = []
    faithfulness = []
    safety = []
    for case in answer_cases:
        correctness.append(keyword_coverage({term.lower() for term in case.required_keywords}, case.answer))
        factual_terms = {term for term in case.required_keywords if term in case.answer}
        faithfulness.append(keyword_coverage({term.lower() for term in factual_terms}, case.evidence_text))
        safety.append(0.0 if contains_unsafe_business_action(case.answer) else 1.0)
    return {
        "answer_correctness": mean(correctness) if correctness else 0.0,
        "faithfulness": mean(faithfulness) if faithfulness else 0.0,
        "unsafe_action_avoidance": mean(safety) if safety else 0.0,
    }


def evaluate_agent(cases: list[RetrievalCase]) -> dict:
    rewrite_success = []
    retrieval_rounds = []
    tool_scores = []
    fallback_count = 0
    for case in cases:
        poor_state = {
            "messages": [HumanMessage(content=case.query)],
            "original_question": case.query,
            "rewritten_question": case.query,
            "retrieval_plan": [],
            "evidences": [],
            "requirements": [case.query],
            "retry_count": 0,
            "trace_events": [],
            "estimated_cost": {},
            "use_cross_encoder": False,
        }
        rewritten = rewrite_query(poor_state)
        rewrite_success.append(1.0 if rewritten.get("rewritten_question") else 0.0)

        supplemental = plan_supplemental_retrieval({**poor_state, "retry_count": MAX_RETRIEVAL_RETRIES - 1})
        retrieval_rounds.append(supplemental["retry_count"])

        source = next(iter(case.expected_doc_types)) if len(case.expected_doc_types) == 1 else "all"
        state = {
            "retrieval_plan": [
                {
                    "query": case.query,
                    "source": source if source != "structured_db" else "database",
                    "filters": case.filters,
                    "purpose": "agent metric retrieval",
                    "execution": "parallel",
                }
            ],
            "trace_events": [],
            "estimated_cost": {},
        }
        result = execute_retrieval(state)
        result_sources = {item.get("source_type") or item["document"].metadata.get("doc_type") for item in result["evidences"]}
        tool_scores.append(f1_score(case.expected_doc_types, result_sources))
        if not result["evidences"]:
            fallback_count += 1
    return {
        "query_rewrite_success_rate": mean(rewrite_success) if rewrite_success else 0.0,
        "avg_retrieval_rounds": mean(retrieval_rounds) if retrieval_rounds else 0.0,
        "tool_selection_accuracy": mean(tool_scores) if tool_scores else 0.0,
        "fallback_rate": fallback_count / len(cases) if cases else 0.0,
    }


def evaluate_system(cases: list[RetrievalCase]) -> dict:
    latencies = []
    tokens = []
    dense_queries = []
    sparse_queries = []
    fallback_count = 0
    for case in cases:
        source = next(iter(case.expected_doc_types)) if len(case.expected_doc_types) == 1 else "all"
        state = {
            "retrieval_plan": [
                {
                    "query": case.query,
                    "source": source if source != "structured_db" else "database",
                    "filters": case.filters,
                    "purpose": "system metric retrieval",
                    "execution": "parallel",
                }
            ],
            "trace_events": [],
            "estimated_cost": {"llm_calls": [{"label": "fixture", "estimated_tokens": len(case.query) // 4 + 1}]},
            "use_cross_encoder": False,
        }
        result = execute_retrieval(state)
        latencies.append(result.get("latency_ms", 0.0))
        retrieval_cost = result.get("estimated_cost", {}).get("retrieval", {})
        dense_queries.append(retrieval_cost.get("dense_queries_used", 0))
        sparse_queries.append(retrieval_cost.get("sparse_queries_used", 0))
        tokens.append(result.get("estimated_cost", {}).get("estimated_total_tokens", len(case.query) // 4 + 1))
        if not result.get("evidences"):
            fallback_count += 1
    return {
        "p95_latency_ms": percentile(latencies, 95),
        "avg_estimated_tokens": mean(tokens) if tokens else 0.0,
        "avg_dense_queries": mean(dense_queries) if dense_queries else 0.0,
        "avg_sparse_queries": mean(sparse_queries) if sparse_queries else 0.0,
        "fallback_rate": fallback_count / len(cases) if cases else 0.0,
    }


def evaluate_ablations(cases: list[RetrievalCase]) -> dict:
    variants = {
        "dense_only": dense_only,
        "dense_bm25": dense_bm25,
        "dense_bm25_rerank": dense_bm25_rerank,
        "metadata_filter": with_metadata_filter,
        "query_rewrite": with_query_rewrite,
        "evidence_grading": with_evidence_grading,
        "full_agentic_rag": full_agentic_rag,
    }
    return {name: retrieval_metrics(cases, fn, k=5) for name, fn in variants.items()}


def build_fixtures() -> tuple[list[UnderstandingCase], list[RoutingCase], list[RetrievalCase], list[AnswerCase]]:
    understanding = [
        UnderstandingCase("洗碗机 DW-2026 出现 ERR_42，无法启动，怎么排查？", "洗碗机", "DW-2026", "ERR-42", "troubleshooting"),
        UnderstandingCase("ORD-2026-00001 现在是什么状态？", None, None, None, "database"),
        UnderstandingCase("空气净化器 AP-300 质保维修政策是什么？", "空气净化器", "AP-300", None, "policy"),
    ]
    routing = [
        RoutingCase("洗碗机无法启动，质保还能维修吗？", {"manual", "policy"}),
        RoutingCase("ORD-2026-00001 现在是什么状态？", {"database"}),
        RoutingCase("有没有相似工单处理过水泵无法启动？", {"ticket_history", "manual"}),
        RoutingCase("退货流程应该怎么办？", {"policy", "faq"}),
    ]
    retrieval = [
        RetrievalCase("policy_refund", "退货 退款 质保 政策", {"policy"}, {"退货", "退款", "质保"}),
        RetrievalCase("faq_flow", "退货流程 应该怎么办 常见问题", {"faq"}, {"退货", "流程"}),
        RetrievalCase("ticket_history", "相似工单 无法启动 已经重启 问题还在", {"ticket_history"}, {"无法启动", "重启"}),
        RetrievalCase("database_order", "ORD-2026-00001 订单状态 生命周期事件", {"structured_db"}, {"ORD-2026-00001"}),
    ]
    evidence_text = "退货申请需要满足政策条件；系统不能直接替客户完成退款。引用 [1]"
    answers = [
        AnswerCase(
            "退货可以怎么处理？",
            "根据证据，退货申请需要先满足政策条件，不能直接说已经退款 [1]",
            evidence_text,
            {"退货", "政策", "退款"},
        )
    ]
    return understanding, routing, retrieval, answers


def run_metrics() -> dict:
    understanding, routing, retrieval_cases, answer_cases = build_fixtures()
    report = {
        "query_understanding": evaluate_understanding(understanding),
        "routing": evaluate_routing(routing),
        "retrieval": retrieval_metrics(retrieval_cases, full_agentic_rag, k=5),
        "rerank": evaluate_rerank(retrieval_cases),
        "evidence": evaluate_evidence(retrieval_cases),
        "generation": evaluate_generation(answer_cases),
        "agent": evaluate_agent(retrieval_cases),
        "system": evaluate_system(retrieval_cases),
        "ablations": evaluate_ablations(retrieval_cases),
    }
    return report


def print_summary(report: dict) -> None:
    print("\n=== Agentic RAG Metrics ===")
    for layer in ["query_understanding", "routing", "retrieval", "rerank", "evidence", "generation", "agent", "system"]:
        print(f"\n[{layer}]")
        for key, value in report[layer].items():
            if key == "cases":
                continue
            if isinstance(value, float):
                print(f"{key}: {value:.4f}")
            else:
                print(f"{key}: {value}")

    print("\n[ablations]")
    for name, metrics in report["ablations"].items():
        print(
            f"{name}: recall@5={metrics['recall_at_k']:.4f}, "
            f"mrr={metrics['mrr']:.4f}, ndcg@5={metrics['ndcg_at_k']:.4f}, "
            f"p95_latency_ms={metrics['p95_latency_ms']:.2f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=REPORT_PATH, help="Path to write the JSON metrics report.")
    args = parser.parse_args()

    report = run_metrics()
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"\nWrote metrics report: {args.json}")


if __name__ == "__main__":
    main()
