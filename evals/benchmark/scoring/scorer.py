"""Objective scorer for the Liorin Agentic RAG Benchmark.

Free-form answer quality is reported with a deterministic lexical
``fact_coverage_proxy`` only. It is not an answer correctness rate.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def f1(gold: list[str] | set[str], pred: list[str] | set[str]) -> float:
    gold_set = set(gold or [])
    pred_set = set(pred or [])
    if not gold_set and not pred_set:
        return 1.0
    if not gold_set or not pred_set:
        return 0.0
    precision = len(gold_set & pred_set) / len(pred_set)
    recall = len(gold_set & pred_set) / len(gold_set)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def exact(left: Any, right: Any) -> float:
    return 1.0 if left == right else 0.0


def ndcg(ranked: list[str], qrels: dict[str, int], k: int = 10) -> float:
    gains = [qrels.get(chunk_id, 0) for chunk_id in ranked[:k]]
    dcg = sum((2**gain - 1) / math.log2(idx + 2) for idx, gain in enumerate(gains))
    ideal = sorted(qrels.values(), reverse=True)[:k]
    idcg = sum((2**gain - 1) / math.log2(idx + 2) for idx, gain in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def ap_at_k(ranked: list[str], qrels: dict[str, int], k: int = 10) -> float:
    relevant = {chunk_id for chunk_id, grade in qrels.items() if grade >= 2}
    if not relevant:
        return 0.0
    hits = 0
    total = 0.0
    for idx, chunk_id in enumerate(ranked[:k], start=1):
        if chunk_id in relevant:
            hits += 1
            total += hits / idx
    return total / min(len(relevant), k)


def lexical_fact_proxy(answer: str, fact: dict[str, Any]) -> float:
    answer_norm = norm(answer)
    fact_text = norm(fact.get("text") or fact.get("fact_text") or "")
    if not fact_text:
        return 1.0
    match = fact.get("match", {})
    anchors = [norm(item) for item in match.get("required_anchors", []) if len(norm(item)) >= 2]
    anchor_score = sum(item in answer_norm for item in anchors) / len(anchors) if anchors else 0.0
    numbers = [str(item) for item in match.get("exact_numbers", []) or fact.get("exact_numbers", [])]
    number_score = sum(item in answer for item in numbers) / len(numbers) if numbers else 1.0
    bigrams = lambda text: {text[i : i + 2] for i in range(max(0, len(text) - 1))}
    fact_bigrams = bigrams(fact_text)
    answer_bigrams = bigrams(answer_norm)
    char_score = len(fact_bigrams & answer_bigrams) / max(1, len(fact_bigrams))
    return min(1.0, max(anchor_score, char_score) * 0.8 + number_score * 0.2)


def score_row(sample: dict[str, Any], pred: dict[str, Any]) -> dict[str, float]:
    layer = sample["layer"]
    gold = sample.get("gold") or {}
    pred = pred or {}
    out: dict[str, float] = {}
    if layer == "query_understanding":
        gold_entities = gold.get("entities", {})
        pred_entities = pred.get("entities", {})
        fields = ["product_name", "product_id", "product_model", "product_alias", "accessory_model", "error_code"]
        out["entity_accuracy"] = statistics.mean(exact(gold_entities.get(key), pred_entities.get(key)) for key in fields)
        out["task_type_accuracy"] = exact(gold.get("task_type"), pred.get("task_type"))
        out["requirement_f1"] = f1([r["concept_id"] for r in gold.get("requirements", [])], pred.get("requirement_concept_ids", []))
        out["clarification_accuracy"] = exact(gold.get("needs_clarification"), pred.get("needs_clarification"))
        out["clarification_slot_f1"] = f1(gold.get("clarification_slots", []), pred.get("clarification_slots", []))
        out["objective_score"] = statistics.mean(out.values())
    elif layer == "routing":
        selected = set(pred.get("selected_sources", []))
        required = set(gold.get("required_sources", []))
        conditional = set(gold.get("conditional_sources", []))
        optional = set(gold.get("optional_sources", []))
        forbidden = set(gold.get("forbidden_sources", []))
        acceptable = required | conditional | optional
        out["required_source_recall"] = len(selected & required) / max(1, len(required))
        out["source_precision"] = len(selected & acceptable) / max(1, len(selected)) if selected else 0.0
        out["forbidden_avoidance"] = 1.0 if not selected & forbidden else 0.0
        out["plan_min_query_accuracy"] = 1.0 if int(pred.get("planned_query_count", 0)) >= gold.get("expected_plan", {}).get("min_queries", 0) else 0.0
        out["objective_score"] = 0.45 * out["required_source_recall"] + 0.25 * out["source_precision"] + 0.2 * out["forbidden_avoidance"] + 0.1 * out["plan_min_query_accuracy"]
    elif layer == "retrieval":
        ranked = pred.get("ranked_chunk_ids", [])
        qrels = gold.get("qrels", {})
        relevant = {chunk_id for chunk_id, grade in qrels.items() if grade >= 2}
        for k in [1, 3, 5, 10]:
            out[f"recall@{k}"] = len(relevant & set(ranked[:k])) / max(1, len(relevant))
        out["mrr"] = next((1 / (idx + 1) for idx, chunk_id in enumerate(ranked) if chunk_id in relevant), 0.0)
        out["ndcg@10"] = ndcg(ranked, qrels, 10)
        out["map@10"] = ap_at_k(ranked, qrels, 10)
        out["objective_score"] = 0.45 * out["ndcg@10"] + 0.25 * out["recall@5"] + 0.15 * out["mrr"] + 0.15 * out["map@10"]
    elif layer == "agent_behavior":
        out["action_accuracy"] = exact(gold.get("expected_action"), pred.get("action"))
        expected_verification_action = gold.get("expected_verification_action")
        out["verification_action_accuracy"] = (
            exact(expected_verification_action, pred.get("verification_action"))
            if expected_verification_action is not None
            else 1.0
        )
        out["reason_f1"] = f1(gold.get("reason_codes", []), pred.get("reason_codes", []))
        out["clarification_slot_f1"] = f1(gold.get("required_clarification_slots", []), pred.get("clarification_slots", []))
        out["supplemental_source_f1"] = f1(gold.get("required_supplemental_sources", []), pred.get("supplemental_sources", []))
        out["budget_compliance"] = 1.0 if pred.get("retrieval_rounds", 0) <= gold.get("max_retrieval_rounds", 999) else 0.0
        out["objective_score"] = 0.4 * out["action_accuracy"] + 0.1 * out["verification_action_accuracy"] + 0.15 * out["reason_f1"] + 0.1 * out["clarification_slot_f1"] + 0.15 * out["supplemental_source_f1"] + 0.1 * out["budget_compliance"]
    elif layer in {"answer_generation", "end_to_end"}:
        answer = pred.get("answer", "")
        cited = set(pred.get("cited_chunk_ids", []))
        facts = gold.get("required_atomic_facts", [])
        out["response_type_accuracy"] = exact(gold.get("expected_response_type"), pred.get("response_type"))
        if layer == "end_to_end":
            out["decision_accuracy"] = exact(gold.get("decision_code"), pred.get("decision_code"))
            out["required_source_recall"] = len(set(pred.get("used_sources", [])) & set(gold.get("required_sources", []))) / max(1, len(gold.get("required_sources", [])))
            out["required_action_f1"] = f1(gold.get("required_actions", []), pred.get("actions", []))
            out["budget_compliance"] = 1.0 if pred.get("retrieval_rounds", 0) <= gold.get("max_retrieval_rounds", 999) else 0.0
        required_chunks = {ref["chunk_id"] for fact in facts for ref in fact.get("source_refs", []) if ref.get("chunk_id")}
        out["citation_recall"] = len(cited & required_chunks) / max(1, len(required_chunks))
        out["fact_coverage_proxy"] = statistics.mean([lexical_fact_proxy(answer, fact) for fact in facts]) if facts else 1.0
        risky = ["已经退款", "已经取消订单", "已创建维修单", "已完成赔付", "已经修改订单"]
        out["unsafe_action_avoidance"] = 1.0 if not any(phrase in answer for phrase in risky) else 0.0
        if layer == "answer_generation":
            out["objective_score"] = 0.35 * out["response_type_accuracy"] + 0.45 * out["citation_recall"] + 0.2 * out["unsafe_action_avoidance"]
        else:
            out["objective_score"] = 0.25 * out["response_type_accuracy"] + 0.25 * out["decision_accuracy"] + 0.2 * out["required_source_recall"] + 0.1 * out["required_action_f1"] + 0.1 * out["citation_recall"] + 0.1 * out["budget_compliance"]
    return out


def score_predictions(
    predictions_path: str | Path,
    dataset_path: str | Path,
    *,
    layers: set[str] | None = None,
    allow_partial: bool = False,
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    samples = load_json(dataset_path)
    rows = load_json(predictions_path)
    pred_by_id = {row["id"]: row.get("prediction", {}) for row in rows}
    if layers:
        samples = [sample for sample in samples if sample["layer"] in layers]
    if allow_partial:
        samples = [sample for sample in samples if sample["id"] in pred_by_id]
    details = []
    by_layer: dict[str, list[dict[str, float]]] = defaultdict(list)
    missing = []
    errors = []
    for sample in samples:
        if sample["id"] not in pred_by_id:
            missing.append(sample["id"])
        try:
            scores = score_row(sample, pred_by_id.get(sample["id"], {}))
        except Exception as exc:
            scores = {"objective_score": 0.0}
            errors.append({"id": sample["id"], "error": str(exc)})
        details.append({"id": sample["id"], "layer": sample["layer"], "scores": scores})
        by_layer[sample["layer"]].append(scores)
    summary = {}
    for layer, values in by_layer.items():
        keys = sorted(set().union(*(value.keys() for value in values)))
        summary[layer] = {key: statistics.mean(value.get(key, 0.0) for value in values) for key in keys}
    objectives = [item["scores"]["objective_score"] for item in details if "objective_score" in item["scores"]]
    return {
        "dataset": str(dataset_path),
        "sample_count": len(samples),
        "prediction_count": len(rows),
        "missing_prediction_ids": missing,
        "error_count": len(errors),
        "errors": errors,
        "macro_objective_score": statistics.mean(objectives) if objectives else 0.0,
        "by_layer": summary,
        "details": details,
        "run_metadata": run_metadata or {},
        "warning": "fact_coverage_proxy is deterministic lexical coverage, not answer correctness; use locked judge or human review for semantic quality.",
    }
