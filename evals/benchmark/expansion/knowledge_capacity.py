"""Capacity funnel and first-wave blueprint for Phase G0.1."""
from __future__ import annotations
from collections import Counter, defaultdict
from typing import Any


def capacity_funnel(space: dict[str, Any]) -> dict[str, Any]:
    facts = space["facts"]
    audits = space["fact_audits"]
    units = space["source_units"]
    groups = space["coherent_groups"]
    task_usable = [a for a in audits if a.task_usability == "TASK_USABLE"]
    task_construction_usable = [a for a in audits if a.task_usability in {"TASK_USABLE","GROUP_ONLY","CONTEXT_DEPENDENT"}]
    independent_count = sum(a.independently_askable for a in audits)
    effective_units = {u.cross_product_signature for u in units if u.benchmark_usable}
    return {
        "atomic_fact_candidates": len(facts),
        "heuristic_usable": sum(bool(f.benchmark_usable) for f in facts),
        "task_usable_facts": len(task_usable),
        "task_construction_usable_facts": len(task_construction_usable),
        "independent_askable_facts": independent_count,
        "independent_askable_ratio_of_task_construction_usable": round(independent_count / max(1,len(task_construction_usable)), 6),
        "group_only_facts": sum(a.task_usability == "GROUP_ONLY" for a in audits),
        "context_dependent": sum(a.task_usability == "CONTEXT_DEPENDENT" for a in audits),
        "fragments": sum(a.task_usability == "FRAGMENT" for a in audits),
        "non_task_information": sum(a.task_usability == "NON_TASK_INFORMATION" for a in audits),
        "owned_by_troubleshooting": sum(a.category_ownership == "TROUBLESHOOTING" for a in audits),
        "owned_by_mixed": sum(a.category_ownership == "MIXED" for a in audits),
        "unsupported": sum(a.task_usability == "UNSUPPORTED" for a in audits),
        "coherent_fact_groups": len(groups),
        "knowledge_source_units": len(units),
        "benchmark_usable_source_units": sum(u.benchmark_usable for u in units),
        "benchmark_usable_with_grouping": sum(u.knowledge_usability == "BENCHMARK_USABLE_WITH_GROUPING" for u in units),
        "not_usable_source_units": sum(u.knowledge_usability == "NOT_USABLE" for u in units),
        "owned_by_other_category_source_units": sum(u.knowledge_usability == "OWNED_BY_OTHER_CATEGORY" for u in units),
        "effective_source_units": len(effective_units),
    }


def fact_type_funnel(space: dict[str, Any]) -> dict[str, Any]:
    fact_map = {f.fact_id: f for f in space["facts"]}
    audits = space["fact_audits"]
    by_type: dict[str, list[Any]] = defaultdict(list)
    for a in audits:
        by_type[a.fact_type].append(a)
    effective_by_type = Counter()
    for u in space["source_units"]:
        if not u.benchmark_usable:
            continue
        types = sorted({fact_map[fid].fact_type for fid in u.primary_fact_ids if fid in fact_map})
        for t in types:
            effective_by_type[t] += 1
    out = {}
    for t, rows in sorted(by_type.items()):
        out[t] = {
            "source_count": len(rows),
            "task_usable": sum(r.task_usability == "TASK_USABLE" for r in rows),
            "independent_askable": sum(r.independently_askable for r in rows),
            "group_only": sum(r.task_usability == "GROUP_ONLY" for r in rows),
            "context_dependent": sum(r.task_usability == "CONTEXT_DEPENDENT" for r in rows),
            "excluded": sum(r.task_usability in {"FRAGMENT","NON_TASK_INFORMATION","CATEGORY_OWNERSHIP_EXCLUDED","UNSUPPORTED"} for r in rows),
            "effective_contribution": effective_by_type.get(t, 0),
        }
    return out


def capacity_blueprint(space: dict[str, Any], funnel: dict[str, Any]) -> dict[str, Any]:
    usable_units = [u for u in space["source_units"] if u.benchmark_usable]
    effective = funnel["effective_source_units"]
    independent = funnel["independent_askable_facts"]
    groups = funnel["coherent_fact_groups"]
    documents = {u.document_id for u in usable_units}
    topics = {u.semantic_topic for u in usable_units}
    # Candidate capacity is deliberately much smaller than raw source capacity.
    # The first wave is capped for balanced selection; it is not FactCount*x.
    floor = min(120, max(90, int(min(effective, independent + groups) * 0.12)))
    recommended = min(180, max(floor, int(min(effective, independent + groups) * 0.18)))
    upper = min(240, max(recommended, int(min(effective, independent + groups) * 0.24)))
    confidence = "HIGH" if len(documents) >= 20 and len(topics) >= 7 and effective >= 300 else "MEDIUM"
    return {
        "minimum_high_quality_candidate_capacity": floor,
        "recommended_first_wave_capacity": recommended,
        "upper_reasonable_capacity": upper,
        "confidence": confidence,
        "basis": {
            "effective_source_units": effective,
            "independent_askable_facts": independent,
            "coherent_fact_groups": groups,
            "usable_sources": len(documents),
            "semantic_topics": len(topics),
            "principle": "balanced source-unit/task-semantic selection; no paraphrase multiplication",
        },
        "note": "Planning capacity, not generated Candidate count and not Formal Benchmark size.",
    }
