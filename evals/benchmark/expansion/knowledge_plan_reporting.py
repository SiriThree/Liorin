"""Reporting helpers for Phase G0.2 Knowledge task planning."""
from __future__ import annotations
import hashlib, json, re
from collections import Counter, defaultdict
from typing import Any


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+","",text.lower(),flags=re.UNICODE)


def plan_effective_diversity(plans: list[dict[str,Any]], fact_map: dict[str,dict[str,Any]]) -> dict[str,Any]:
    sigs=defaultdict(list); fact_sets=set(); evidence_sets=set()
    for p in plans:
        sem={
            "task_type":p["primary_task_type"],"reasoning":p["reasoning_type"],"answer_scope":p["answer_scope"],
            "fact_semantics":sorted(_norm(fact_map[f].get("fact_text","")) for f in p["required_fact_ids"] if f in fact_map),
            "relationship":p["fact_relationship"],
        }
        sig=hashlib.sha256(json.dumps(sem,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        sigs[sig].append(p)
        fact_sets.add(tuple(sorted(p["required_fact_ids"]))); evidence_sets.add(tuple(sorted(p["required_evidence_ids"])))
    groups=[rows for rows in sigs.values() if len(rows)>1]
    cross=0
    for rows in groups:
        product_sets={tuple(r["product_ids"]) for r in rows}
        if len(product_sets)>1: cross += len(rows)-1
    return {
        "task_plans":len(plans),"unique_plan_signatures":len({p["plan_signature"] for p in plans}),"effective_task_plan_semantics":len(sigs),
        "semantic_duplicate_excess":len(plans)-len(sigs),"cross_product_duplicate_plans":cross,"unique_fact_sets":len(fact_sets),"unique_evidence_sets":len(evidence_sets),
        "duplicate_groups":[{"effective_signature":sig,"task_plan_ids":[p["task_plan_id"] for p in rows],"products":[p["product_ids"] for p in rows]} for sig,rows in sigs.items() if len(rows)>1],
    }


def distributions(plans: list[dict[str,Any]]) -> dict[str,Any]:
    n=max(1,len(plans))
    def dist(field):
        c=Counter(p[field] for p in plans);return {k:{"count":v,"ratio":round(v/n,6)} for k,v in sorted(c.items())}
    return {"task_type":dist("primary_task_type"),"reasoning":dist("reasoning_type"),"answer_scope":dist("answer_scope"),"difficulty":dist("difficulty"),"priority":dist("priority")}


def balance_report(plans: list[dict[str,Any]], available_units: list[dict[str,Any]]) -> dict[str,Any]:
    n=max(1,len(plans)); docs=Counter(d for p in plans for d in set(p["document_ids"])); products=Counter(x for p in plans for x in set(p["product_ids"])); planning_topics=Counter(p.get("semantic_topic","knowledge") for p in plans); families=Counter(p["semantic_family_id"] for p in plans); sections=Counter(s for p in plans for s in set(p["section_ids"])); units=Counter(u for p in plans for u in set(p["source_unit_ids"]))
    avail_topics=Counter(u.get("semantic_topic","knowledge") for u in available_units)
    unit_topics={u["source_unit_id"]:u.get("semantic_topic","knowledge") for u in available_units}
    selected_source_topics=Counter()
    for plan in plans:
        for uid in set(plan.get("source_unit_ids", [])):
            if uid in unit_topics:
                selected_source_topics[unit_topics[uid]] += 1
    return {
        "documents":{"covered":len(docs),"plans_per_document":dict(sorted(docs.items())),"max_count":max(docs.values(),default=0),"max_ratio":round(max(docs.values(),default=0)/n,6)},
        "products":{"covered":len(products),"plans_per_product":dict(sorted(products.items())),"max_count":max(products.values(),default=0),"max_ratio":round(max(products.values(),default=0)/n,6)},
        "semantic_topics":{"available":dict(sorted(avail_topics.items())),"selected_source_topics":dict(sorted(selected_source_topics.items())),"covered_source_topics":len(selected_source_topics),"planning_topics":dict(sorted(planning_topics.items())),"planning_topic_count":len(planning_topics),"max_source_topic_count":max(selected_source_topics.values(),default=0),"max_source_topic_ratio":round(max(selected_source_topics.values(),default=0)/n,6)},
        "semantic_families":{"covered":len(families),"selected":dict(sorted(families.items())),"max_count":max(families.values(),default=0),"max_ratio":round(max(families.values(),default=0)/n,6)},
        "sections":{"max_count":max(sections.values(),default=0),"sections_with_2":sum(v==2 for v in sections.values()),"sections_over_2":sum(v>2 for v in sections.values())},
        "source_units":{"max_count":max(units.values(),default=0),"reused_source_units":sum(v>1 for v in units.values())},
    }
