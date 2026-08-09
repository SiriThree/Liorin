"""Validation gates for G0.3 controlled Knowledge query rendering."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

_INTERNAL_PATTERNS = [
    r"\bKSU-[0-9a-f]+\b", r"\bKTP-[0-9a-f]+\b", r"\baf:[0-9a-f]+\b",
    r"\bLIO-PROD-\d+\b", r"source_unit", r"fact_id", r"section_id", r"document_id",
    r"Gold", r"Evidence", r"required facts", r"semantic family", r"reasoning type", r"task plan",
    r"\[PRODUCT\]", r"PRODUCT_X", r"PLACEHOLDER", r"FIXTURE", r"SOURCE_UNIT",
]
_TROUBLESHOOTING_QUERY = re.compile(r"坏了|故障|异常|无法启动|不启动|没反应|怎么办|排查|报错|错误码")
_PRIVATE_QUERY = re.compile(r"我的订单|这个订单号|我的工单|我的保修单|我的保修状态|我的客户信息|tenant", re.I)


def normalize_query(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()\-—_]+", "", str(text or "").lower())


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _numeric_tokens(text: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?(?:\s*(?:kg|g|mm|cm|m|L|ml|V|W|Hz|dH|%|秒|分钟|小时|天|个月|年|号))?", text, re.I))


def _query_leakage(query: str, facts: list[str], plan: dict[str, Any], allowed_context_text: str = "") -> dict[str, Any]:
    qn = normalize_query(query)
    exact=[];numeric=[];semantic=[]
    for fact in facts:
        fn=normalize_query(fact)
        # A fact that is literally the section heading is allowed as user-visible task context;
        # it is not treated as leaked answer content. A heading-only single-fact plan is reviewed separately.
        if len(fn)>=6 and fn in qn and fn not in normalize_query(allowed_context_text): exact.append(fact)
        for n in _numeric_tokens(fact):
            nn=normalize_query(n)
            # Numeric tokens already present in user-visible section/product naming are context, not leaked answer values.
            if nn and nn in normalize_query(allowed_context_text):
                continue
            # Avoid one-digit substring false positives inside model codes such as AE00704.
            if re.fullmatch(r"\d", nn):
                if not re.search(rf"(?<!\d){re.escape(nn)}(?!\d)", normalize_query(query)):
                    continue
            if nn and nn in qn: numeric.append(n)
    # Outcome leakage: query asserts unsupported polarity rather than asking relation.
    bool_leak = bool(re.search(r"既然.*(?:不支持|不能|不可以|仅限|一定|肯定)", query))
    compat_leak = bool(plan["primary_task_type"]=="COMPATIBILITY" and re.search(r"为什么不支持|既然不支持|确认不支持", query))
    limitation_leak = bool(plan["primary_task_type"]=="LIMITATION" and re.search(r"既然不能|为什么不能|确认不能", query))
    policy_leak = bool(plan["primary_task_type"]=="POLICY_OR_WARRANTY" and re.search(r"既然.*(?:保修|退货|退款)|一定可以|一定不能", query))
    return {"exact":exact,"numeric":sorted(set(numeric)),"boolean":bool_leak,"compatibility":compat_leak,"limitation":limitation_leak,"policy":policy_leak,"semantic":semantic}


def _naturalness(query: str, pattern: str) -> tuple[list[str], list[str]]:
    issues=[];warnings=[]
    if len(query)<8: issues.append("UNNATURAL_RENDERING_TOO_SHORT")
    if len(query)>110: warnings.append("NATURALNESS_LONG_QUERY")
    if re.search(r"请返回|attribute_value|required|section|source|fact|evidence", query, re.I): issues.append("INTERNAL_BENCHMARK_LANGUAGE")
    if query.count("？")+query.count("?")>1: warnings.append("MULTIPLE_QUESTION_MARKS")
    if re.search(r"相关要点|详细介绍一下|介绍一下这个产品|有哪些功能$|怎么使用$", query): issues.append("SCOPE_TOO_BROAD_SURFACE")
    return issues,warnings


def validate_rendered(plan: dict[str, Any], rendered: dict[str, Any], fact_map: dict[str, dict[str, Any]], section_map: dict[str, dict[str, Any]], existing_queries: set[str]) -> dict[str, Any]:
    query=rendered["query"];facts=[fact_map[f]["fact_text"] for f in plan["required_fact_ids"]]
    issues=[];warnings=[]
    nat_i,nat_w=_naturalness(query,rendered["pattern"]);issues+=nat_i;warnings+=nat_w

    # Intent/category validation.
    if _PRIVATE_QUERY.search(query): issues.append("CATEGORY_DRIFT_PRIVATE_OR_MIXED")
    # Direct troubleshooting ownership drift can surface even if G0.2 missed a source classification.
    if _TROUBLESHOOTING_QUERY.search(query) and plan.get("semantic_topic") not in {"maintenance","safety_usage","faq_process"} and plan.get("primary_task_type")!="FAQ_PROCESS":
        issues.append("CATEGORY_DRIFT_TROUBLESHOOTING")
    expected=plan["rendering_constraints"].get("expected_query_intent")
    if expected and plan["primary_task_type"]!=expected and not (expected=="MULTI_FACT_SYNTHESIS" and plan["primary_task_type"]=="MULTI_FACT_SYNTHESIS"):
        warnings.append("INTENT_METADATA_MISMATCH")

    # Scope/fact alignment relies on frozen controlled renderer targets and text-level broadness guards.
    targets=set(rendered["metadata"].get("targets",[]));required=set(plan["required_fact_ids"])
    if targets!=required: issues.append("REQUIRED_FACT_ALIGNMENT_FAILED")
    if plan["answer_scope"]=="SINGLE_FACT" and len(required)!=1: issues.append("SINGLE_FACT_SCOPE_PLAN_INVALID")
    if plan["answer_scope"]=="BOUNDED_FACT_SET" and not (2<=len(required)<=3): issues.append("BOUNDED_FACT_SET_SCOPE_INVALID")
    if plan["primary_task_type"]=="MULTI_FACT_SYNTHESIS":
        if len(required)<2: issues.append("MULTI_FACT_SCOPE_COLLAPSE")
        if "MULTIFACT" not in rendered["pattern"]: issues.append("MULTI_FACT_SCOPE_COLLAPSE")
    if plan["primary_task_type"]=="MULTI_SECTION_SYNTHESIS":
        if len(set(plan["section_ids"]))<2: issues.append("MULTI_SECTION_RELATION_LOST")
        if "MULTISECTION" not in rendered["pattern"] or not rendered["metadata"].get("relation_anchor"): issues.append("MULTI_SECTION_RELATION_LOST")
        if len(rendered["metadata"].get("required_sections",[]))<2: issues.append("MULTI_SECTION_NECESSITY_FAILED")

    # Source/evidence trace.
    missing_facts=[f for f in required if f not in fact_map]
    missing_sections=[s for s in plan["section_ids"] if s not in section_map]
    if missing_facts: issues.append("SOURCE_FACT_MISSING")
    if missing_sections: issues.append("SOURCE_SECTION_MISSING")
    if not plan.get("required_evidence_ids"): issues.append("EVIDENCE_MISSING")
    if plan["primary_task_type"]=="MULTI_SECTION_SYNTHESIS" and len(plan["required_evidence_ids"])<2: issues.append("MULTI_SECTION_EVIDENCE_INCOMPLETE")

    # Leakage.
    context_text=" ".join([str(rendered.get("heading", "")), str(rendered.get("product_name", ""))])
    leak=_query_leakage(query,facts,plan,context_text)
    if any(leak[k] for k in ("exact","numeric","boolean","compatibility","limitation","policy")): issues.append("ANSWER_LEAKAGE")
    internal=[p for p in _INTERNAL_PATTERNS if re.search(p,query,re.I)]
    if internal: issues.append("INTERNAL_TERM_LEAKAGE")

    # Policy qualification: renderer must not absolutize or hallucinate region/time.
    policy={"qualification_sensitive":plan["primary_task_type"]=="POLICY_OR_WARRANTY","absolute_interpretation":False,"region_hallucination":False,"time_hallucination":False,"exception_loss":False}
    if policy["qualification_sensitive"]:
        policy["absolute_interpretation"]=bool(re.search(r"一定|必然|无条件|所有情况|百分之百",query))
        policy["region_hallucination"]=bool(re.search(r"美国|欧洲|中国大陆|全球|地区政策",query))
        # calendar years are disallowed unless they are part of source; renderer never needs them.
        policy["time_hallucination"]=bool(re.search(r"20\d{2}年|当前版本|今年政策",query))
        if any(policy[k] for k in ("absolute_interpretation","region_hallucination","time_hallucination")): issues.append("POLICY_RENDERING_VIOLATION")

    norm=normalize_query(query)
    collision={"exact_query":query.strip() in existing_queries,"normalized_query":norm in {normalize_query(x) for x in existing_queries}}
    if collision["exact_query"] or collision["normalized_query"]: issues.append("CROSS_STAGE_QUERY_COLLISION")

    # Rendering review heuristics. These do not alter task semantics.
    review=[]
    if rendered["pattern"]=="DIRECT_META_SECTION": review.append("LOW_VALUE_META_KNOWLEDGE_QUERY")
    if any(normalize_query(fact_map[f]["fact_text"]) == normalize_query(str(section_map.get(fact_map[f]["section_id"],{}).get("heading",""))) for f in required if f in fact_map):
        review.append("HEADING_ONLY_FACT_QUERY_REVIEW")
    if plan["primary_task_type"]=="PRODUCT_SPEC" and not re.search(r"\d|=|＝|标准|认证|规格|尺寸|重量|容量|功率|接口|电压|型号|螺钉|参数", " ".join(facts), re.I):
        review.append("PRODUCT_SPEC_SEMANTICS_UNCERTAIN")
    if plan["primary_task_type"]=="DIRECT_FACT" and any(re.search(r"不启动|故障|异常|无法|排查", str(section_map.get(s,{}).get("heading",""))) for s in plan["section_ids"]):
        issues.append("CATEGORY_DRIFT_TROUBLESHOOTING")
    if plan["primary_task_type"]=="MULTI_SECTION_SYNTHESIS" and len(query)>90: review.append("MULTI_SECTION_QUERY_NATURALNESS_REVIEW")
    if plan["primary_task_type"]=="COMPATIBILITY":
        ft=" ".join(facts)
        if not re.search(r"支持|不支持|兼容|适用|系统要求|Windows|USB|端子|年龄|模式|遥控|电池型号", ft, re.I):
            review.append("PLANNING_COMPATIBILITY_SEMANTICS_UNCERTAIN")
        if re.search(r"感谢.*购买|航行规则|当地法规|消费者权益法", ft):
            review.append("PLANNING_COMPATIBILITY_SEMANTICS_UNCERTAIN")
        if re.search(r"适用于大多数场景", ft):
            review.append("VAGUE_COMPATIBILITY_SCOPE_REVIEW")
    if plan["primary_task_type"]=="POLICY_OR_WARRANTY":
        ft=" ".join(facts); hd=" ".join(str(section_map.get(s,{}).get("heading","")) for s in plan["section_ids"])
        if ("加拿大" in hd and re.search(r"欧盟|欧洲国家",ft)) or ("美国" in hd and "加拿大" in ft):
            review.append("POLICY_SOURCE_CONTEXT_MISMATCH")

    return {
        "issues":sorted(set(issues)),"warnings":sorted(set(warnings)),"review_reasons":sorted(set(review)),
        "naturalness":{"pass":not nat_i,"warnings":nat_w,"length":len(query)},
        "intent":{"pass":not any(x.startswith("CATEGORY_DRIFT") or x=="INTENT_DRIFT" for x in issues),"expected":expected},
        "scope":{"pass":not any(x in issues for x in ("SCOPE_EXPANSION","SCOPE_COLLAPSE","REQUIRED_FACT_ALIGNMENT_FAILED","MULTI_FACT_SCOPE_COLLAPSE","MULTI_SECTION_RELATION_LOST")),"targets":sorted(targets)},
        "fact_alignment":{"required":len(required),"covered":len(targets & required),"missing":sorted(required-targets),"extra":sorted(targets-required),"supporting_promoted":False},
        "evidence_alignment":{"pass":not any(x in issues for x in ("EVIDENCE_MISSING","MULTI_SECTION_EVIDENCE_INCOMPLETE","SOURCE_FACT_MISSING","SOURCE_SECTION_MISSING")),"required_evidence_ids":list(plan.get("required_evidence_ids",[]))},
        "leakage":{**leak,"internal_patterns":internal,"pass":not any(x in issues for x in ("ANSWER_LEAKAGE","INTERNAL_TERM_LEAKAGE"))},
        "policy":policy,"collision":collision,
    }


def candidate_semantic_signature(plan: dict[str, Any], rendered: dict[str, Any]) -> str:
    return semantic_hash({
        "task_type":plan["primary_task_type"],"semantic_family":plan["semantic_family_id"],
        "required_facts":sorted(plan["required_fact_ids"]),"required_evidence":sorted(plan["required_evidence_ids"]),
        "reasoning":plan["reasoning_type"],"answer_scope":plan["answer_scope"],
        "normalized_query_intent":rendered["pattern"],
    })


def dedup_candidates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    exact=Counter(r["candidate_query"] for r in rows);norm=Counter(normalize_query(r["candidate_query"]) for r in rows);sig=Counter(r["dedup_signature"] for r in rows)
    fact=Counter(tuple(sorted(r["required_fact_ids"])) for r in rows);ev=Counter(tuple(sorted(r["required_evidence_ids"])) for r in rows)
    return {
        "exact_query_duplicate_excess":sum(v-1 for v in exact.values() if v>1),
        "normalized_query_duplicate_excess":sum(v-1 for v in norm.values() if v>1),
        "semantic_duplicate_excess":sum(v-1 for v in sig.values() if v>1),
        "unique_query_intent_signatures":len(sig),"unique_fact_sets":len(fact),"unique_evidence_sets":len(ev),
        "duplicate_semantic_signatures":[{"signature":k,"count":v} for k,v in sig.items() if v>1],
    }
