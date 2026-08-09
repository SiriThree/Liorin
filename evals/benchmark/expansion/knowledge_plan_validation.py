"""Hard validation gates for Phase G0.2 task plans."""
from __future__ import annotations
from collections import Counter
from typing import Any


def validate_plan(plan: dict[str, Any], fact_map: dict[str, dict[str, Any]], unit_map: dict[str, dict[str, Any]], ownership: dict[str, set[str]]) -> list[str]:
    issues=[]
    units=[unit_map.get(x) for x in plan.get("source_unit_ids", [])]
    if not units or any(u is None for u in units): issues.append("SOURCE_UNIT_MISSING")
    if any(u and (not u.get("benchmark_usable") or u.get("category_ownership") != "KNOWLEDGE_AVAILABLE") for u in units): issues.append("CATEGORY_OWNERSHIP_INVALID")
    req=plan.get("required_fact_ids", [])
    if not req or any(fid not in fact_map for fid in req): issues.append("REQUIRED_FACT_MISSING")
    if any(fact_map.get(fid,{}).get("category_ownership") != "KNOWLEDGE_AVAILABLE" for fid in req): issues.append("REQUIRED_FACT_OTHER_CATEGORY")
    for fid in req:
        f=fact_map.get(fid,{})
        text=f.get("fact_text","")
        if "这些限制旨在" in text or "联邦通信委员会" in text or "FCC 第" in text:
            issues.append("SOURCE_UNIT_ISSUE_REGULATORY_BOILERPLATE")
        if any(x in text for x in ("此功能", "该功能", "本功能")):
            issues.append("SOURCE_UNIT_ISSUE_UNRESOLVED_DEICTIC")
        if f.get("fact_type")=="PRODUCT_SPEC" and len(text)>140 and sum(k in text for k in ("电压","功率","型号","购买日期","技术热线","联系"))>=3:
            issues.append("SOURCE_UNIT_ISSUE_COMPOUND_ATTRIBUTE_BLOB")
    scope=plan.get("answer_scope")
    if scope == "SINGLE_FACT" and len(req)!=1: issues.append("ANSWER_SCOPE_FACT_COUNT_MISMATCH")
    if scope == "BOUNDED_FACT_SET" and not (2 <= len(req) <= 3): issues.append("ANSWER_SCOPE_FACT_COUNT_MISMATCH")
    if plan.get("primary_task_type") == "MULTI_FACT_SYNTHESIS" and len(req)<2: issues.append("MULTI_FACT_NEEDS_2_FACTS")
    if plan.get("primary_task_type") == "MULTI_SECTION_SYNTHESIS" and len(set(plan.get("section_ids",[])))<2: issues.append("MULTI_SECTION_NEEDS_2_SECTIONS")
    if plan.get("multi_section") and len(set(plan.get("required_evidence_ids",[])))<2: issues.append("MULTI_SECTION_EVIDENCE_INCOMPLETE")
    if len(set(req)) != len(req): issues.append("DUPLICATE_REQUIRED_FACT")
    # Active troubleshooting ownership is exclusive even inside a composition.
    # Formal/Mixed overlaps may still support a genuinely different multi-fact/multi-section
    # knowledge task, so only single-fact exact reuse is rejected for those categories.
    if any("TROUBLESHOOTING" in ownership.get(fid, set()) for fid in req):
        issues.append("COLLIDES_TROUBLESHOOTING_FACT")
    if len(req)==1:
        overlaps=ownership.get(req[0], set())
        if "FORMAL" in overlaps: issues.append("COLLIDES_FORMAL_FACT")
        if "MIXED" in overlaps: issues.append("COLLIDES_MIXED_FACT")
    if plan.get("primary_task_type") == "POLICY_OR_WARRANTY" and "POLICY_AMBIGUITY" in plan.get("quality_flags",[]):
        issues.append("POLICY_AMBIGUITY")
    rc=plan.get("rendering_constraints",{})
    required_rc={"allowed_user_context","required_user_context","forbidden_answer_terms","forbidden_internal_terms","must_not_expand_scope","must_not_reveal_answer","product_name_allowed","expected_query_intent"}
    if not required_rc.issubset(rc): issues.append("RENDERING_CONSTRAINT_INCOMPLETE")
    fs=plan.get("future_split_keys",{})
    required_fs={"document_family","product_family","section_family","fact_family","semantic_family_id","source_unit_ids","composition_family_id"}
    if not required_fs.issubset(fs): issues.append("FUTURE_SPLIT_KEYS_INCOMPLETE")
    return sorted(set(issues))


def balance_issues(plans: list[dict[str, Any]]) -> dict[str, Any]:
    n=max(1,len(plans)); task=Counter(p["primary_task_type"] for p in plans); diff=Counter(p["difficulty"] for p in plans); docs=Counter(d for p in plans for d in set(p["document_ids"])); topics=Counter(p["semantic_family_id"] for p in plans)
    feature=task.get("FEATURE_OR_INSTRUCTION",0)/n
    direct_spec=(task.get("DIRECT_FACT",0)+task.get("PRODUCT_SPEC",0))/n
    easy=diff.get("EASY",0)/n
    max_doc=max(docs.values(),default=0)/n
    max_sem=max(topics.values(),default=0)/n
    return {
        "feature_ratio":round(feature,6),"feature_cap_pass":feature<=0.25,
        "direct_spec_ratio":round(direct_spec,6),"direct_spec_cap_pass":direct_spec<=0.20,
        "easy_ratio":round(easy,6),"difficulty_warning":easy>0.50,
        "max_document_ratio":round(max_doc,6),"document_concentration_warning":max_doc>0.08,
        "max_semantic_family_ratio":round(max_sem,6),"semantic_concentration_warning":max_sem>0.12,
    }
