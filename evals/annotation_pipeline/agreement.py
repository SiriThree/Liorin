from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Iterable

from .compare import normalize_for_compare


def cohen_kappa(pairs: list[tuple[Any, Any]]) -> float | None:
    if not pairs:
        return None
    a_values = [str(a) for a, _ in pairs]
    b_values = [str(b) for _, b in pairs]
    observed = sum(a == b for a, b in zip(a_values, b_values)) / len(pairs)
    ca = Counter(a_values)
    cb = Counter(b_values)
    expected = sum((ca[k] / len(pairs)) * (cb[k] / len(pairs)) for k in set(ca) | set(cb))
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def weighted_kappa(pairs: list[tuple[int, int]], min_value: int = 0, max_value: int = 3) -> float | None:
    if not pairs:
        return None
    values = list(range(min_value, max_value + 1))
    n = len(pairs)
    observed = 0.0
    for a, b in pairs:
        observed += ((a - b) / max(1, max_value - min_value)) ** 2
    observed /= n
    ca = Counter(a for a, _ in pairs)
    cb = Counter(b for _, b in pairs)
    expected = 0.0
    for a in values:
        for b in values:
            weight = ((a - b) / max(1, max_value - min_value)) ** 2
            expected += weight * (ca[a] / n) * (cb[b] / n)
    if expected == 0.0:
        return 1.0 if observed == 0.0 else 0.0
    return 1 - observed / expected


def jaccard(a: Iterable[Any], b: Iterable[Any]) -> float:
    sa = {str(x) for x in a}
    sb = {str(x) for x in b}
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def set_f1(a: Iterable[Any], b: Iterable[Any]) -> float:
    sa = {str(x) for x in a}
    sb = {str(x) for x in b}
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    precision = len(sa & sb) / len(sb)
    recall = len(sa & sb) / len(sa)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def fact_key(fact: dict[str, Any]) -> str:
    refs = sorted(str(ref.get("chunk_id") or ref.get("record_id") or "") for ref in fact.get("source_refs", []))
    text = "".join(str(fact.get("fact_text", "")).split()).lower()
    return "|".join(refs) + "::" + text


def source_ref_key(ref: dict[str, Any]) -> str:
    return str(ref.get("chunk_id") or ref.get("record_id") or "")


def fact_agreement_metrics(pairs: list[tuple[dict[str, Any], dict[str, Any]]], field: str = "atomic_facts") -> dict[str, Any]:
    fact_f1s=[]; source_j=[]; number_exact=[]; support_pairs=[]; necessity_pairs=[]
    for a,b in pairs:
        fa=a.get(field,[]); fb=b.get(field,[])
        fact_f1s.append(set_f1([fact_key(x) for x in fa],[fact_key(x) for x in fb]))
        source_j.append(jaccard([source_ref_key(r) for x in fa for r in x.get("source_refs",[])],[source_ref_key(r) for x in fb for r in x.get("source_refs",[])]))
        number_exact.append(sorted(str(n) for x in fa for n in x.get("exact_numbers",[])) == sorted(str(n) for x in fb for n in x.get("exact_numbers",[])))
        ma={fact_key(x):x for x in fa}; mb={fact_key(x):x for x in fb}
        for key in set(ma)&set(mb):
            support_pairs.append((ma[key].get("support_label"),mb[key].get("support_label")))
            necessity_pairs.append((ma[key].get("necessity"),mb[key].get("necessity")))
    return {
        "fact_set_f1": sum(fact_f1s)/max(1,len(fact_f1s)),
        "source_ref_jaccard": sum(source_j)/max(1,len(source_j)),
        "numeric_exact_agreement": sum(number_exact)/max(1,len(number_exact)),
        "support_label_kappa": cohen_kappa(support_pairs),
        "necessity_kappa": cohen_kappa(necessity_pairs),
    }


def build_agreement_report(records_a: list[dict[str, Any]], records_b: list[dict[str, Any]]) -> dict[str, Any]:
    a_by_id = {row["sample_id"]: row["annotation"] for row in records_a}
    b_by_id = {row["sample_id"]: row["annotation"] for row in records_b}
    common = sorted(set(a_by_id) & set(b_by_id))
    report: dict[str, Any] = {
        "sample_count": len(common),
        "missing_in_a": sorted(set(b_by_id) - set(a_by_id)),
        "missing_in_b": sorted(set(a_by_id) - set(b_by_id)),
        "by_layer": {},
    }
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for sample_id in common:
        a = a_by_id[sample_id]
        b = b_by_id[sample_id]
        grouped[a["layer"]].append((a, b))

    for layer, pairs in grouped.items():
        layer_report: dict[str, Any] = {"count": len(pairs)}
        layer_report["quality_status_kappa"] = cohen_kappa([(a["quality_status"], b["quality_status"]) for a, b in pairs])
        if layer == "query_understanding":
            layer_report.update(
                {
                    "task_type_kappa": cohen_kappa([(a["task_type"], b["task_type"]) for a, b in pairs]),
                    "clarification_kappa": cohen_kappa([(a["needs_clarification"], b["needs_clarification"]) for a, b in pairs]),
                    "entity_exact_mean": sum(
                        sum(a["entities"].get(k) == b["entities"].get(k) for k in a["entities"]) / len(a["entities"])
                        for a, b in pairs
                    ) / len(pairs),
                    "requirement_jaccard": sum(
                        jaccard([x["concept_id"] for x in a["requirements"]], [x["concept_id"] for x in b["requirements"]])
                        for a, b in pairs
                    ) / len(pairs),
                    "clarification_slot_jaccard": sum(jaccard(a["clarification_slots"], b["clarification_slots"]) for a, b in pairs) / len(pairs),
                }
            )
        elif layer == "routing":
            for field in ["required_sources", "conditional_sources", "optional_sources", "forbidden_sources"]:
                layer_report[field + "_jaccard"] = sum(jaccard(a[field], b[field]) for a, b in pairs) / len(pairs)
            layer_report["parallelizable_kappa"] = cohen_kappa([(a["parallelizable"], b["parallelizable"]) for a, b in pairs])
        elif layer == "retrieval":
            qrel_pairs: list[tuple[int, int]] = []
            binary_f1: list[float] = []
            for a, b in pairs:
                keys = set(a["qrels"]) | set(b["qrels"])
                for key in keys:
                    qrel_pairs.append((int(a["qrels"].get(key, 0)), int(b["qrels"].get(key, 0))))
                binary_f1.append(set_f1([k for k, v in a["qrels"].items() if v >= 2], [k for k, v in b["qrels"].items() if v >= 2]))
            layer_report["weighted_kappa"] = weighted_kappa(qrel_pairs)
            layer_report["binary_relevance_f1"] = sum(binary_f1) / len(binary_f1)
            layer_report.update(fact_agreement_metrics(pairs))
        elif layer == "answer_generation":
            layer_report["response_type_kappa"] = cohen_kappa([(a["expected_response_type"], b["expected_response_type"]) for a, b in pairs])
            layer_report.update(fact_agreement_metrics(pairs))
            layer_report["forbidden_claim_jaccard"] = sum(jaccard(a["forbidden_claims"], b["forbidden_claims"]) for a, b in pairs) / len(pairs)
        elif layer == "agent_behavior":
            layer_report["action_kappa"] = cohen_kappa([(a["expected_action"], b["expected_action"]) for a, b in pairs])
            for field in ["reason_codes", "clarification_slots", "supplemental_sources", "allowed_actions"]:
                layer_report[field + "_jaccard"] = sum(jaccard(a[field], b[field]) for a, b in pairs) / len(pairs)
        elif layer == "end_to_end":
            layer_report["response_type_kappa"] = cohen_kappa([(a["expected_response_type"], b["expected_response_type"]) for a, b in pairs])
            layer_report["decision_kappa"] = cohen_kappa([(a["decision_code"], b["decision_code"]) for a, b in pairs])
            for field in ["required_sources", "conditional_sources", "required_actions", "allowed_actions"]:
                layer_report[field + "_jaccard"] = sum(jaccard(a[field], b[field]) for a, b in pairs) / len(pairs)
            layer_report.update(fact_agreement_metrics(pairs))
        report["by_layer"][layer] = layer_report

    # Overall exact annotation agreement intentionally excludes rationale/confidence.
    exact = 0
    for sample_id in common:
        exact += normalize_for_compare(a_by_id[sample_id]) == normalize_for_compare(b_by_id[sample_id])
    report["exact_annotation_agreement"] = exact / max(1, len(common))
    return report
