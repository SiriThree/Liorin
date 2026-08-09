"""Gold-level alignment, minimality, completeness, and scope-risk audit."""
from __future__ import annotations
import re
from typing import Any, Mapping
from .knowledge_gold import looks_heading_only, looks_intro_only, unresolved_deictic

_BROAD_GROUP = re.compile(r"需要同时(?:了解|满足|遵守)哪些|哪些相互关联的要求|具体要求是什么|具体应该怎么操作")


def audit_gold(candidate: Mapping[str, Any], plan: Mapping[str, Any], fact_rows: list[Mapping[str, Any]], section_rows: list[Mapping[str, Any]], gold_facts: list[Mapping[str, Any]]) -> dict[str, Any]:
    issues=[]; resolved=[]
    answer=[x for x in gold_facts if x["fact_role"]=="ANSWER_REQUIRED"]
    required_source=set(plan.get("required_fact_ids") or [])
    represented={sf for g in gold_facts for sf in g["source_fact_ids"] if g["fact_role"] in {"ANSWER_REQUIRED","REASONING_REQUIRED","SUPPORTING_ONLY"}}
    missing=sorted(required_source-represented)
    if missing: issues.append("GOLD_INCOMPLETE_MISSING_PLANNED_FACT")
    # A heading/intro that was planned as a required fact is not itself an answer fact.
    demoted=[g for g in gold_facts if g["fact_role"]=="SUPPORTING_ONLY" and any(sf in required_source for sf in g["source_fact_ids"])]
    if demoted: resolved.append("NON_INFORMATIONAL_REQUIRED_FACT_DEMOTED")
    # If a multi-fact task loses too much answer substance after role correction, human precheck is safer.
    if candidate["primary_task_type"]=="MULTI_FACT_SYNTHESIS" and len(answer)<2:
        issues.append("MULTI_FACT_ANSWER_SET_TOO_SMALL_AFTER_ROLE_CORRECTION")
    # Broad group questions over a section with substantially more facts are not deterministically complete.
    q=str(candidate["candidate_query"])
    if candidate["primary_task_type"]=="MULTI_FACT_SYNTHESIS" and _BROAD_GROUP.search(q):
        for sec in section_rows:
            if int(sec.get("fact_count") or 0) > len(required_source)+2:
                issues.append("BROAD_GROUP_SCOPE_COMPLETENESS_UNCERTAIN"); break
    # Product spec planning is suspect when source is neither an explicit product spec nor an obvious value/spec relation.
    if candidate["primary_task_type"]=="PRODUCT_SPEC":
        f=fact_rows[0]
        text=str(f.get("fact_text") or "")
        if f.get("fact_type")!="PRODUCT_SPEC" and not re.search(r"\d\s*(?:kg|g|mm|cm|m|V|W|Hz|A|°C|℃|%|英尺|米)|=|标准|认证|重量|电压|规格", text, re.I):
            issues.append("PRODUCT_SPEC_SOURCE_SEMANTICS_UNCERTAIN")
    # Unresolved deictic source semantics make a unique Gold risky unless the query supplies the referent.
    for f in fact_rows:
        if unresolved_deictic(str(f.get("fact_text") or "")) and not any(x in q for x in ("此功能","该功能","上述","这项")):
            issues.append("SOURCE_REFERENT_NOT_EXPLICIT_IN_QUERY")
    # Single-section evidence required by plan must exist; multi-section must remain >=2.
    if candidate["primary_task_type"]=="MULTI_SECTION_SYNTHESIS" and len(set(candidate.get("section_ids") or []))<2:
        issues.append("MULTI_SECTION_EVIDENCE_INSUFFICIENT")
    return {
        "candidate_id":candidate["candidate_id"],"issues":sorted(set(issues)),"resolved_through_role_correction":sorted(set(resolved)),
        "answer_required_fact_count":len(answer),"planned_required_fact_count":len(required_source),"represented_planned_facts":len(required_source & represented),
        "gold_complete":not any(x.startswith("GOLD_INCOMPLETE") or "COMPLETENESS_UNCERTAIN" in x for x in issues),
        "gold_minimal":True if not answer else all(bool(x["normalized_value_or_semantics"]) for x in answer),
    }
