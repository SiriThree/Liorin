"""Reporting helpers for Phase G0.1."""
from __future__ import annotations
from collections import Counter, defaultdict
from typing import Any


def source_unit_report(space: dict[str, Any]) -> dict[str, Any]:
    units = space["source_units"]
    usable = [u for u in units if u.benchmark_usable]
    by_doc = Counter(u.document_id for u in usable)
    by_product = Counter(u.product_id for u in usable if u.product_id)
    by_type = Counter(u.unit_type for u in units)
    by_topic = Counter(u.semantic_topic for u in usable)
    by_rel = Counter(u.fact_relationship for u in units)
    return {
        "source_units": len(units),
        "benchmark_usable": len(usable),
        "benchmark_usable_with_grouping": sum(u.knowledge_usability == "BENCHMARK_USABLE_WITH_GROUPING" for u in units),
        "not_usable": sum(u.knowledge_usability == "NOT_USABLE" for u in units),
        "owned_by_other_category": sum(u.knowledge_usability == "OWNED_BY_OTHER_CATEGORY" for u in units),
        "by_source": dict(sorted(by_doc.items())),
        "by_product": dict(sorted(by_product.items())),
        "by_unit_type": dict(sorted(by_type.items())),
        "by_semantic_topic": dict(sorted(by_topic.items())),
        "by_fact_relationship": dict(sorted(by_rel.items())),
    }


def source_coverage(space: dict[str, Any]) -> dict[str, Any]:
    docs = space["documents"]
    units = space["source_units"]
    usable = [u for u in units if u.benchmark_usable]
    counts = Counter(u.document_id for u in usable)
    eff_by_doc: dict[str, set[str]] = defaultdict(set)
    for u in usable: eff_by_doc[u.document_id].add(u.cross_product_signature)
    rows=[]
    for d in docs:
        rows.append({
            "document_id": d["document_id"], "source_type": d["source_type"], "product_id": d.get("product_id"),
            "usable_units": counts[d["document_id"]], "effective_units": len(eff_by_doc[d["document_id"]]),
            "has_usable_units": counts[d["document_id"]] > 0,
        })
    return {"total_sources": len(docs), "sources_with_usable_units": sum(r["has_usable_units"] for r in rows), "sources_without_usable_units": [r["document_id"] for r in rows if not r["has_usable_units"]], "sources": rows}


def product_coverage(space: dict[str, Any]) -> dict[str, Any]:
    docs = space["documents"]
    products = sorted({d.get("product_id") for d in docs if d.get("product_id")})
    usable = [u for u in space["source_units"] if u.benchmark_usable]
    counts=Counter(u.product_id for u in usable if u.product_id)
    eff: dict[str,set[str]]=defaultdict(set)
    for u in usable:
        if u.product_id: eff[u.product_id].add(u.cross_product_signature)
    return {"total_products":len(products),"products_with_usable_units":sum(counts[p]>0 for p in products),"products_without_usable_units":[p for p in products if counts[p]==0],"products":[{"product_id":p,"usable_units":counts[p],"effective_units":len(eff[p])} for p in products]}


def cross_product_duplicates(space: dict[str, Any]) -> dict[str, Any]:
    # Detect both whole-unit duplicates and primary fact semantics repeated
    # across different products. Whole-unit hashing alone misses common manual
    # boilerplate embedded in otherwise different sections.
    unit_groups: dict[str,list[Any]]=defaultdict(list)
    for u in space["source_units"]:
        if u.benchmark_usable and u.product_id:
            unit_groups[u.cross_product_signature].append(u)
    unit_rows=[]
    for sig, us in unit_groups.items():
        products=sorted({u.product_id for u in us if u.product_id})
        if len(products)>1:
            unit_rows.append({"cross_product_signature":sig,"products":products,"source_unit_ids":[u.source_unit_id for u in us],"semantic_topic":us[0].semantic_topic,"fact_relationship":us[0].fact_relationship,"unit_count":len(us)})

    fact_rows=[]
    fact_groups: dict[str,list[Any]]=defaultdict(list)
    for a in space["fact_audits"]:
        if a.product_id and a.task_usability in {"TASK_USABLE","GROUP_ONLY","CONTEXT_DEPENDENT"}:
            norm=''.join(ch for ch in a.fact_text.lower() if ch.isalnum() or '\u4e00' <= ch <= '\u9fff')
            fact_groups[norm].append(a)
    for sig, rows in fact_groups.items():
        products=sorted({r.product_id for r in rows if r.product_id})
        if len(products)>1:
            fact_rows.append({"normalized_semantics":sig,"products":products,"fact_ids":[r.fact_id for r in rows],"fact_types":sorted({r.fact_type for r in rows}),"fact_count":len(rows),"example":rows[0].fact_text})
    return {
        "unit_level_duplicate_groups":len(unit_rows),
        "unit_level_duplicate_units":sum(r["unit_count"] for r in unit_rows),
        "unit_level_semantic_duplicate_excess":sum(r["unit_count"]-1 for r in unit_rows),
        "fact_level_duplicate_groups":len(fact_rows),
        "fact_level_duplicate_facts":sum(r["fact_count"] for r in fact_rows),
        "fact_level_semantic_duplicate_excess":sum(r["fact_count"]-1 for r in fact_rows),
        "groups":sorted(unit_rows,key=lambda r:(-r["unit_count"],r["cross_product_signature"])),
        "fact_groups":sorted(fact_rows,key=lambda r:(-r["fact_count"],r["normalized_semantics"])),
    }
