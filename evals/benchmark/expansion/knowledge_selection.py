"""Deterministic constrained selection and task-plan proposal construction for G0.2."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any

from .knowledge_composition import multi_fact_proposals, multi_section_proposals


def _sha_obj(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _plan_id(core: dict[str, Any]) -> str:
    return "KTP-" + _sha_obj(core)[:16]


def _priority_map(capacity_blueprint: dict[str, Any]) -> dict[str, str]:
    out={}
    for p in ("P0","P1","P2"):
        for row in capacity_blueprint.get("source_priority",{}).get(p,[]):
            out[row["source_unit_id"]]=p
    return out


def effective_representatives(units: list[dict[str, Any]], capacity_blueprint: dict[str, Any], previous_uncovered: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    priority=_priority_map(capacity_blueprint); rank={"P0":0,"P1":1,"P2":2}
    previous_products={r.get("product_id") for r in previous_uncovered if r.get("recommended_for_g0_2")}
    previous_docs={"liorin_support_faq"}
    groups=defaultdict(list)
    for u in units:
        if u.get("benchmark_usable") and u.get("category_ownership")=="KNOWLEDGE_AVAILABLE":
            groups[u["cross_product_signature"]].append(u)
    reps=[]; dup_rows=[]
    for sig, rows in sorted(groups.items()):
        def key(u):
            prev=0 if (u.get("product_id") in previous_products or u.get("document_id") in previous_docs) else 1
            return (rank.get(priority.get(u["source_unit_id"],"P2"),2), prev, u["document_id"], u["source_unit_id"])
        chosen=sorted(rows,key=key)[0]; reps.append(chosen)
        if len(rows)>1:
            dup_rows.append({"cross_product_signature":sig,"representative_source_unit_id":chosen["source_unit_id"],"member_source_unit_ids":sorted(u["source_unit_id"] for u in rows),"excess":len(rows)-1})
    return sorted(reps,key=lambda u:u["source_unit_id"]), dup_rows


def _fact_overlap_cost(fid: str, ownership: dict[str,set[str]]) -> tuple[int,int,int,str]:
    s=ownership.get(fid,set())
    return (int("TROUBLESHOOTING" in s), int("FORMAL" in s), int("MIXED" in s), fid)


def _choose_fact(u: dict[str,Any], fact_map: dict[str,dict[str,Any]], ownership: dict[str,set[str]]) -> str | None:
    ids=[fid for fid in u.get("independent_askable_fact_ids",[]) if fid in fact_map and fact_map[fid].get("category_ownership")=="KNOWLEDGE_AVAILABLE"]
    if not ids: return None
    return sorted(ids,key=lambda fid:_fact_overlap_cost(fid,ownership))[0]


def _task_type(u: dict[str,Any], fact: dict[str,Any] | None) -> str:
    topic=u.get("semantic_topic")
    ftype=(fact or {}).get("fact_type")
    text=(fact or {}).get("fact_text","")
    if u.get("source_type")=="faq": return "FAQ_PROCESS"
    if u.get("source_type")=="policy" or topic in {"warranty_information","warranty_rule","return_refund_policy","identity_policy"} or ftype in {"WARRANTY","WARRANTY_POLICY","RETURN_POLICY","POLICY","AFTER_SALES"} or any(k in text for k in ("保修范围","保修服务","购买之日起享受","购买之日起一年","购买之日起2年","购买之日起 2年","维修或更换服务")):
        return "POLICY_OR_WARRANTY"
    if u.get("fact_relationship")=="ATTRIBUTE_VALUE" or topic=="physical_spec" or ftype=="PRODUCT_SPEC": return "PRODUCT_SPEC"
    if u.get("fact_relationship")=="COMPATIBILITY_RELATION" or ftype=="COMPATIBILITY": return "COMPATIBILITY"
    if u.get("fact_relationship")=="LIMITATION" or ftype=="LIMITATION": return "LIMITATION"
    if topic=="product_knowledge" and u.get("fact_relationship")=="INDEPENDENT": return "DIRECT_FACT"
    return "FEATURE_OR_INSTRUCTION"


def _reasoning(task_type: str, relationship: str, multi: bool=False, multi_section: bool=False) -> str:
    if multi_section: return "MULTI_SECTION_SYNTHESIS"
    if multi: return "MULTI_FACT_SYNTHESIS"
    return {
        "DIRECT_FACT":"DIRECT_LOOKUP","PRODUCT_SPEC":"ATTRIBUTE_LOOKUP","FEATURE_OR_INSTRUCTION":"PROCEDURAL" if relationship=="PROCEDURE" else ("CONDITION_APPLICATION" if relationship=="CONDITION_ACTION" else "DIRECT_LOOKUP"),
        "COMPATIBILITY":"COMPATIBILITY_REASONING","LIMITATION":"LIMITATION_REASONING","POLICY_OR_WARRANTY":"POLICY_INTERPRETATION","FAQ_PROCESS":"SET_RETRIEVAL",
    }[task_type]


def _answer_scope(task_type: str, relationship: str, fact_count: int, multi: bool=False, multi_section: bool=False) -> str:
    if multi_section: return "SYNTHESIZED_CONCLUSION"
    if task_type=="COMPATIBILITY": return "COMPATIBILITY_JUDGMENT"
    if task_type=="LIMITATION": return "LIMITATION_JUDGMENT"
    if task_type=="POLICY_OR_WARRANTY": return "POLICY_RULE" if fact_count>1 else "SINGLE_FACT"
    if relationship=="PROCEDURE" and fact_count>1: return "PROCEDURE_SUBSET"
    if fact_count==1: return "SINGLE_FACT"
    return "BOUNDED_FACT_SET"


def _difficulty(task_type: str, relationship: str, fact_count: int, multi_section: bool=False) -> str:
    if multi_section: return "HARD"
    if fact_count>=3 and (relationship in {"CONDITION_ACTION","PROCEDURE","POLICY_RULE"} or task_type=="MULTI_FACT_SYNTHESIS"): return "HARD"
    if task_type in {"COMPATIBILITY","LIMITATION","POLICY_OR_WARRANTY","MULTI_FACT_SYNTHESIS"} or relationship in {"CONDITION_ACTION","PROCEDURE"}: return "MEDIUM"
    return "EASY"


def _evidence_ids(required_facts: list[str], fact_map: dict[str,dict[str,Any]]) -> list[str]:
    return sorted({"section:"+fact_map[fid]["section_id"] for fid in required_facts if fid in fact_map})


def _semantic_family(task_type: str, topic: str, relationship: str, fact_types: list[str], composition_relation: str|None=None) -> str:
    core={"task_type":task_type,"topic":topic,"relationship":relationship,"fact_types":sorted(set(fact_types)),"composition_relation":composition_relation}
    return f"KSF-{task_type}-{topic}-"+_sha_obj(core)[:8]


def _rendering_constraints(task_type: str, product_ids: list[str], required_facts: list[str], fact_map: dict[str,dict[str,Any]], answer_scope: str) -> dict[str,Any]:
    snippets=[]
    for fid in required_facts:
        text=fact_map.get(fid,{}).get("fact_text","").strip()
        if text: snippets.append(text[:120])
    return {
        "allowed_user_context":["product_name","user_goal","explicit_condition"],
        "required_user_context":["product_name"] if product_ids else [],
        "forbidden_answer_terms":snippets,
        "forbidden_internal_terms":["source_unit_id","fact_id","section_id","document_id"],
        "must_not_expand_scope":True,
        "must_not_reveal_answer":True,
        "product_name_allowed":True,
        "expected_query_intent":task_type,
        "answer_scope":answer_scope,
    }


def _future_split_keys(source_units: list[dict[str,Any]], semantic_family: str, facts: list[str], composition_family_id: str|None) -> dict[str,Any]:
    return {
        "document_family":sorted({u["document_id"] for u in source_units}),
        "product_family":sorted({u.get("product_family") or u.get("product_id") or u["document_id"] for u in source_units}),
        "section_family":sorted({s for u in source_units for s in u.get("section_ids",[])}),
        "fact_family":sorted(facts),
        "semantic_family_id":semantic_family,
        "source_unit_ids":sorted(u["source_unit_id"] for u in source_units),
        "composition_family_id":composition_family_id,
    }


def _build_plan(proposal: dict[str,Any], unit_map: dict[str,dict[str,Any]], fact_map: dict[str,dict[str,Any]], priority_map: dict[str,str], *, status: str="DEFERRED") -> dict[str,Any]:
    units=[unit_map[x] for x in proposal["source_unit_ids"]]
    required=list(dict.fromkeys(proposal["required_fact_ids"]))
    ftypes=[fact_map[f].get("fact_type","UNKNOWN") for f in required]
    if proposal["proposal_kind"]=="MULTI_FACT": task_type="MULTI_FACT_SYNTHESIS"
    elif proposal["proposal_kind"]=="MULTI_SECTION": task_type="MULTI_SECTION_SYNTHESIS"
    else: task_type=proposal["primary_task_type"]
    relationship=proposal.get("fact_relationship") or units[0].get("fact_relationship")
    multi=task_type=="MULTI_FACT_SYNTHESIS"; multisection=task_type=="MULTI_SECTION_SYNTHESIS"
    topic=proposal.get("semantic_topic") or units[0].get("semantic_topic") or "knowledge"
    answer=_answer_scope(task_type,relationship,len(required),multi,multisection)
    reasoning=_reasoning(task_type,relationship,multi,multisection)
    semantic_family=_semantic_family(task_type,topic,relationship,ftypes,proposal.get("semantic_relation"))
    source_prios=[priority_map.get(u["source_unit_id"],"P2") for u in units]
    source_priority=min(source_prios,key=lambda p:{"P0":0,"P1":1,"P2":2}[p])
    flags=sorted(set(f for u in units for f in u.get("quality_flags",[])))
    documents=sorted({u["document_id"] for u in units}); sections=sorted({s for u in units for s in u.get("section_ids",[]) }); products=sorted({u["product_id"] for u in units if u.get("product_id")})
    supporting=sorted(set(proposal.get("supporting_fact_ids",[])))
    core={"source_unit_ids":sorted(proposal["source_unit_ids"]),"task_type":task_type,"required_facts":sorted(required),"reasoning":reasoning,"answer_scope":answer}
    plan_id=_plan_id(core)
    selection_rationale=[source_priority,"CAPABILITY_BALANCED"]
    if proposal["proposal_kind"]=="MULTI_FACT": selection_rationale.append("COHERENT_FACT_GROUP")
    if proposal["proposal_kind"]=="MULTI_SECTION": selection_rationale.append("COMPLEMENTARY_MULTI_SECTION")
    if any(p in {"LIO-PROD-017","LIO-PROD-018","LIO-PROD-019","LIO-PROD-020"} for p in products) or "liorin_support_faq" in documents: selection_rationale.append("PREVIOUSLY_UNTESTED_SOURCE")
    return {
        "task_plan_id":plan_id,"plan_version":"knowledge-task-plan-g0.2-v1","primary_task_type":task_type,"semantic_family_id":semantic_family,"reasoning_type":reasoning,
        "difficulty":_difficulty(task_type,relationship,len(required),multisection),"priority":source_priority,"source_unit_ids":sorted(proposal["source_unit_ids"]),
        "document_ids":documents,"section_ids":sections,"product_ids":products,"primary_fact_ids":required,"required_fact_ids":required,"supporting_fact_ids":supporting,
        "required_evidence_ids":_evidence_ids(required,fact_map),"answer_scope":answer,"fact_relationship":relationship,
        "source_necessity":proposal.get("necessity_per_source") or [{"source_unit_id":u["source_unit_id"],"necessary":True} for u in units],
        "multi_fact":multi or len(required)>1,"multi_section":multisection,"procedure_family_id":units[0]["source_unit_id"] if relationship=="PROCEDURE" else None,
        "composition_family_id":proposal.get("composition_family_id"),"composition_validation":proposal.get("composition_validation"),
        "composition_relation_evidence":proposal.get("relation_evidence",[]),"composition_relation_score":proposal.get("relation_score"),
        "source_priority":source_priority,"selection_rationale":selection_rationale,"quality_flags":flags,
        "future_split_keys":_future_split_keys(units,semantic_family,required,proposal.get("composition_family_id")),
        "rendering_constraints":_rendering_constraints(task_type,products,required,fact_map,answer),"status":status,
        "plan_signature":_sha_obj(core),"semantic_topic":topic,
    }


def build_task_plan_proposals(representatives: list[dict[str,Any]], all_units: list[dict[str,Any]], fact_map: dict[str,dict[str,Any]], groups: list[dict[str,Any]], section_map: dict[str,dict[str,Any]], ownership: dict[str,set[str]], capacity_blueprint: dict[str,Any]) -> tuple[list[dict[str,Any]], dict[str,Any]]:
    priority_map=_priority_map(capacity_blueprint); unit_map={u["source_unit_id"]:u for u in all_units}
    proposals=[]
    # One single-source primary proposal per effective KSU representative.
    for u in representatives:
        if u.get("source_type")=="faq":
            req=[fid for fid in u.get("fact_ids",[]) if fid in fact_map][:3]
            if len(req)>=2:
                p={"proposal_kind":"SINGLE_KSU","source_unit_ids":[u["source_unit_id"]],"required_fact_ids":req,"supporting_fact_ids":[],"fact_relationship":u["fact_relationship"],"semantic_topic":u["semantic_topic"],"primary_task_type":"FAQ_PROCESS","composition_family_id":None,"necessity_per_source":[{"source_unit_id":u["source_unit_id"],"necessary":True}]}
                proposals.append(_build_plan(p,unit_map,fact_map,priority_map))
            continue
        fid=_choose_fact(u,fact_map,ownership)
        if not fid: continue
        ft=fact_map[fid]; tt=_task_type(u,ft)
        p={"proposal_kind":"SINGLE_KSU","source_unit_ids":[u["source_unit_id"]],"required_fact_ids":[fid],"supporting_fact_ids":[],"fact_relationship":u["fact_relationship"],"semantic_topic":u["semantic_topic"],"primary_task_type":tt,"composition_family_id":None,"necessity_per_source":[{"source_unit_id":u["source_unit_id"],"necessary":True}]}
        proposals.append(_build_plan(p,unit_map,fact_map,priority_map))
    # Coherent source-grounded multi-fact proposals.
    rep_ids={u["source_unit_id"] for u in representatives}
    mf=multi_fact_proposals([u for u in all_units if u["source_unit_id"] in rep_ids],groups,fact_map)
    for p in mf: proposals.append(_build_plan(p,unit_map,fact_map,priority_map))
    # Conservative same-product complementary multi-section proposals.
    ms=multi_section_proposals(representatives,fact_map,section_map,limit=100)
    for p in ms: proposals.append(_build_plan(p,unit_map,fact_map,priority_map))
    # Dedup exact plan signatures before validation/selection.
    unique={}
    duplicate=0
    for p in sorted(proposals,key=lambda x:x["task_plan_id"]):
        sig=p["plan_signature"]
        if sig in unique: duplicate+=1; continue
        unique[sig]=p
    return list(unique.values()), {"single_ksu_proposals":sum(p["primary_task_type"] not in {"MULTI_FACT_SYNTHESIS","MULTI_SECTION_SYNTHESIS"} for p in unique.values()),"multi_fact_proposals":sum(p["primary_task_type"]=="MULTI_FACT_SYNTHESIS" for p in unique.values()),"multi_section_proposals":sum(p["primary_task_type"]=="MULTI_SECTION_SYNTHESIS" for p in unique.values()),"duplicate_proposals_removed":duplicate}


DEFAULT_QUOTAS={
    "DIRECT_FACT":21,"PRODUCT_SPEC":12,"FEATURE_OR_INSTRUCTION":40,"COMPATIBILITY":21,"LIMITATION":12,"POLICY_OR_WARRANTY":11,"FAQ_PROCESS":8,"MULTI_FACT_SYNTHESIS":30,"MULTI_SECTION_SYNTHESIS":24,
}


def select_balanced(plans: list[dict[str,Any]], issues_by_id: dict[str,list[str]], *, target: int=180, quotas: dict[str,int]|None=None) -> tuple[list[dict[str,Any]], list[dict[str,Any]], list[dict[str,Any]], dict[str,Any]]:
    quotas=dict(quotas or DEFAULT_QUOTAS); rank={"P0":0,"P1":1,"P2":2}
    previous_products={"LIO-PROD-017","LIO-PROD-018","LIO-PROD-019","LIO-PROD-020"}; previous_docs={"liorin_support_faq"}
    valid=[p for p in plans if not issues_by_id.get(p["task_plan_id"])]
    rejected=[]
    for p in plans:
        issues=issues_by_id.get(p["task_plan_id"],[])
        if issues:
            q=dict(p);q["status"]="REJECTED";q["quality_flags"]=sorted(set(q.get("quality_flags",[])+issues)); rejected.append(q)
    doc_count=Counter(); section_count=Counter(); primary_unit_count=Counter(); topic_count=Counter(); family_count=Counter(); product_count=Counter(); selected=[]; selected_ids=set()
    def score(p):
        prev=1 if (set(p["product_ids"]) & previous_products or set(p["document_ids"]) & previous_docs) else 0
        rare_task=1 if p["primary_task_type"] in {"COMPATIBILITY","LIMITATION","POLICY_OR_WARRANTY","FAQ_PROCESS","MULTI_FACT_SYNTHESIS","MULTI_SECTION_SYNTHESIS"} else 0
        return (rank.get(p["priority"],2), -prev, -rare_task, len(p["required_fact_ids"]), p["task_plan_id"])
    def can_take(p, relaxed=False):
        if p["task_plan_id"] in selected_ids: return False
        if p["priority"]=="P2": return False
        # Ordinary document cap 12; FAQ/policy have naturally smaller pools.
        for d in set(p["document_ids"]):
            if doc_count[d] >= (14 if relaxed else 12): return False
        for s in set(p["section_ids"]):
            if section_count[s] >= 2: return False
        if family_count[p["semantic_family_id"]] >= 21:
            return False
        if p["primary_task_type"] != "MULTI_SECTION_SYNTHESIS":
            for u in p["source_unit_ids"]:
                if primary_unit_count[u] >= 1: return False
        return True
    def take(p):
        p=dict(p);p["status"]="PLANNED";selected.append(p);selected_ids.add(p["task_plan_id"])
        for d in set(p["document_ids"]): doc_count[d]+=1
        for s in set(p["section_ids"]): section_count[s]+=1
        if p["primary_task_type"] != "MULTI_SECTION_SYNTHESIS":
            for u in p["source_unit_ids"]: primary_unit_count[u]+=1
        for x in p["product_ids"]: product_count[x]+=1
        topic_count[p.get("semantic_topic","knowledge")]+=1
        family_count[p["semantic_family_id"]]+=1
    # Reserve the five previously untested sources with soft minima.
    reservations={"LIO-PROD-017":6,"LIO-PROD-018":8,"LIO-PROD-019":6,"LIO-PROD-020":5,"liorin_support_faq":5}
    for key,need in reservations.items():
        pool=[p for p in valid if (key in p["product_ids"] or key in p["document_ids"])]
        for p in sorted(pool,key=score):
            if need<=0: break
            tt=p["primary_task_type"]
            if sum(x["primary_task_type"]==tt for x in selected)>=quotas.get(tt,999): continue
            if can_take(p): take(p);need-=1
    # Fill task-type quotas deterministically, prioritizing under-covered docs/products/topics.
    for tt, quota in quotas.items():
        while sum(x["primary_task_type"]==tt for x in selected)<quota:
            pool=[p for p in valid if p["primary_task_type"]==tt and p["task_plan_id"] not in selected_ids and can_take(p)]
            if not pool: break
            def dynamic(p):
                doc=max((doc_count[d] for d in p["document_ids"]),default=0); prod=max((product_count[x] for x in p["product_ids"]),default=0); topic=topic_count[p.get("semantic_topic","knowledge")]
                # P1 is intentionally used for common/basic capabilities so the first wave
                # does not collapse into an all-P0 pool. Rare/high-value task types remain P0-led.
                p1_selected=sum(x["priority"]=="P1" for x in selected)
                feature_p1=sum(x["priority"]=="P1" and x["primary_task_type"]=="FEATURE_OR_INSTRUCTION" for x in selected)
                if tt=="FEATURE_OR_INSTRUCTION" and feature_p1 < 30:
                    pr = 0 if p["priority"]=="P1" else 1
                elif tt in {"PRODUCT_SPEC","DIRECT_FACT"} and p1_selected < 50:
                    pr = 0 if p["priority"]=="P1" else 1
                else:
                    pr = rank.get(p["priority"],2)
                return (pr,doc,prod,topic,score(p))
            take(sorted(pool,key=dynamic)[0])
    # Fill shortfall from valid P0/P1 without breaking feature/direct caps; prefer task types under quotas.
    while len(selected)<target:
        pool=[]
        for p in valid:
            if not can_take(p,relaxed=True): continue
            if p["task_plan_id"] in selected_ids: continue
            tt=p["primary_task_type"]
            current=Counter(x["primary_task_type"] for x in selected)
            if tt=="FEATURE_OR_INSTRUCTION" and (current[tt]+1)/(len(selected)+1)>0.25: continue
            if tt in {"DIRECT_FACT","PRODUCT_SPEC"} and (current["DIRECT_FACT"]+current["PRODUCT_SPEC"]+1)/(len(selected)+1)>0.20: continue
            pool.append(p)
        if not pool: break
        p1_selected=sum(x["priority"]=="P1" for x in selected)
        diff_rank={"HARD":0,"MEDIUM":1,"EASY":2}
        take(sorted(pool,key=lambda p:((0 if (p1_selected<45 and p["priority"]=="P1") else 1 if p1_selected<45 else rank.get(p["priority"],2)),diff_rank.get(p["difficulty"],2),doc_count[p["document_ids"][0]],topic_count[p.get("semantic_topic","knowledge")],family_count[p["semantic_family_id"]],p["task_plan_id"]))[0])
    # Any valid unselected plan is DEFERRED, not rejected.
    deferred=[]
    for p in valid:
        if p["task_plan_id"] not in selected_ids:
            q=dict(p);q["status"]="DEFERRED";deferred.append(q)
    summary={"target":target,"quota":quotas,"selected":len(selected),"deferred":len(deferred),"rejected":len(rejected),"document_counts":dict(doc_count),"product_counts":dict(product_count),"topic_counts":dict(topic_count)}
    return selected,deferred,rejected,summary
