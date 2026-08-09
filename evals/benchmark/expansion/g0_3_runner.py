"""Phase G0.3 controlled query rendering + candidate validation."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .knowledge_candidate import KnowledgeCandidate
from .knowledge_query_renderer import RENDER_VERSION, render_query
from .knowledge_query_validation import candidate_semantic_signature, dedup_candidates, normalize_query, semantic_hash, validate_rendered
from .knowledge_render_reporting import balance, distribution, surface_report

EXPECTED_TASK_PLAN_HASH="f8cabae08e04aeb30d61cb5e7fd605ef0e947d768b828256e5a610e2df098a0d"


def _read_jsonl(p:Path): return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
def _write_json(p:Path,x:Any): p.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def _write_jsonl(p:Path,rows): p.write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n" for x in rows),encoding="utf-8")
def _sha_obj(x:Any): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def _formal_count(root:Path)->int:
    n=0
    for name in ("dev_v7_3_canonical_v1.json","validation_v7_3_canonical_v1.json"):
        x=json.loads((root/"evals/benchmark/data/canonical"/name).read_text(encoding="utf-8")); rows=x.get("samples",x) if isinstance(x,dict) else x; n+=len(rows)
    return n


def _frozen_gate(root:Path,g02:Path,g01:Path)->dict[str,Any]:
    m=json.loads((g02/"knowledge_task_plan_manifest.json").read_text(encoding="utf-8"))
    if int(m.get("planned_count",0))!=180 or int(m.get("effective_plan_count",0))!=180 or m.get("task_plan_set_hash")!=EXPECTED_TASK_PLAN_HASH: raise RuntimeError("TASK_PLAN_DRIFT")
    sm=json.loads((g01/"knowledge_source_space_manifest.json").read_text(encoding="utf-8"))
    if sm.get("knowledge_source_space_hash")!=m.get("source_space_hash"): raise RuntimeError("SOURCE_SPACE_DRIFT")
    if _formal_count(root)!=39: raise RuntimeError("FORMAL_DRIFT")
    private=json.loads((root/"artifacts/evaluation/dataset-expansion-d2/annotation_batch_manifest.json").read_text())
    mixed=json.loads((root/"artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_annotation_batch_manifest_refrozen.json").read_text())
    f0=json.loads((root/"artifacts/evaluation/dataset-expansion-f0-troubleshooting/troubleshooting_candidate_manifest.json").read_text())
    if private.get("packet_count")!=76 or mixed.get("packet_count")!=58 or f0.get("source_validated_count",f0.get("source_validated")) not in (66,None):
        raise RuntimeError("PREVIOUS_FROZEN_ASSET_DRIFT")
    return {"task_plan_set_hash":m["task_plan_set_hash"],"source_space_hash":sm["knowledge_source_space_hash"],"corpus_fingerprint":sm["corpus_fingerprint"],"private_batch_hash":private.get("batch_hash"),"mixed_batch_hash":mixed.get("batch_hash"),"troubleshooting_candidate_set_hash":f0.get("candidate_set_hash"),"d3r":"DEFERRED_BY_ENVIRONMENT"}


def _collect_query_strings(x:Any)->set[str]:
    out=set()
    if isinstance(x,dict):
        for k,v in x.items():
            if k in {"query","candidate_query","user_query","input_query"} and isinstance(v,str) and v.strip(): out.add(v.strip())
            else: out |= _collect_query_strings(v)
    elif isinstance(x,list):
        for v in x: out |= _collect_query_strings(v)
    return out


def _existing_queries(root:Path)->set[str]:
    out=set()
    for name in ("dev_v7_3_canonical_v1.json","validation_v7_3_canonical_v1.json"):
        out |= _collect_query_strings(json.loads((root/"evals/benchmark/data/canonical"/name).read_text(encoding="utf-8")))
    for p in [
        root/"artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_gold_drafts_refrozen.jsonl",
        root/"artifacts/evaluation/dataset-expansion-f0-troubleshooting/troubleshooting_source_validated.jsonl",
    ]:
        if p.exists():
            for row in _read_jsonl(p): out |= _collect_query_strings(row)
    return out


def run_knowledge_query_rendering(root:str|Path=".",g0_2:str|Path="artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning",g0_1:str|Path="artifacts/evaluation/dataset-expansion-g0-1-knowledge-source",output:str|Path="artifacts/evaluation/dataset-expansion-g0-3-knowledge-rendering")->dict[str,Any]:
    root=Path(root).resolve();g02=(root/g0_2).resolve() if not Path(g0_2).is_absolute() else Path(g0_2);g01=(root/g0_1).resolve() if not Path(g0_1).is_absolute() else Path(g0_1);out=(root/output).resolve() if not Path(output).is_absolute() else Path(output);out.mkdir(parents=True,exist_ok=True)
    frozen=_frozen_gate(root,g02,g01)
    plans=_read_jsonl(g02/"knowledge_task_plans.jsonl"); facts=_read_jsonl(g01/"knowledge_atomic_fact_audit.jsonl"); sections=_read_jsonl(g01/"knowledge_section_audit.jsonl"); docs=json.loads((g01/"knowledge_document_inventory.json").read_text(encoding="utf-8"))
    if len(plans)!=180: raise RuntimeError("TASK_PLAN_DRIFT")
    fact_map={x["fact_id"]:x for x in facts};section_map={x["section_id"]:x for x in sections};doc_map={x["document_id"]:x for x in docs};existing=_existing_queries(root)

    raw=[];render_results=[];review=[];rejected=[];validated=[]
    for p in plans:
        rendered=render_query(p,fact_map,section_map,doc_map)
        validation=validate_rendered(p,rendered,fact_map,section_map,existing)
        query=rendered["query"]; qsha=hashlib.sha256(query.encode()).hexdigest(); cid="KQC-"+hashlib.sha256(f"{p['task_plan_id']}|{RENDER_VERSION}|{normalize_query(query)}".encode()).hexdigest()[:16]
        dedup=candidate_semantic_signature(p,rendered)
        issues=list(validation["issues"]);review_reasons=list(validation["review_reasons"])
        status="SOURCE_VALIDATED"
        if issues: status="REJECTED"
        elif review_reasons: status="NEEDS_QUERY_REVIEW"
        cand=KnowledgeCandidate(candidate_id=cid,task_plan_id=p["task_plan_id"],render_version=RENDER_VERSION,candidate_query=query,language="zh-CN",primary_task_type=p["primary_task_type"],semantic_family_id=p["semantic_family_id"],reasoning_type=p["reasoning_type"],difficulty=p["difficulty"],answer_scope=p["answer_scope"],source_unit_ids=tuple(p["source_unit_ids"]),document_ids=tuple(p["document_ids"]),section_ids=tuple(p["section_ids"]),product_ids=tuple(p["product_ids"]),required_fact_ids=tuple(p["required_fact_ids"]),required_evidence_ids=tuple(p["required_evidence_ids"]),rendering_constraints=p["rendering_constraints"],render_pattern=rendered["pattern"],render_metadata=rendered["metadata"],query_validation={"naturalness":validation["naturalness"],"intent":validation["intent"]},source_validation={"facts_exist":not any(x=="SOURCE_FACT_MISSING" for x in issues),"sections_exist":not any(x=="SOURCE_SECTION_MISSING" for x in issues),"document_ids":list(p["document_ids"])},scope_validation={"scope":validation["scope"],"fact_alignment":validation["fact_alignment"],"evidence_alignment":validation["evidence_alignment"]},leakage_validation=validation["leakage"],collision_validation=validation["collision"],dedup_signature=dedup,query_sha256=qsha,status=status,quality_flags=tuple(validation["warnings"]+review_reasons),rejection_reasons=tuple(issues)).to_state()
        # Preserve immutable plan lineage in rendering result, without copying mutable plan state into candidate contract.
        result={"task_plan_id":p["task_plan_id"],"candidate_id":cid,"candidate_query":query,"render_pattern":rendered["pattern"],"render_metadata":rendered["metadata"],"status":status,"issues":issues,"review_reasons":review_reasons,"query_sha256":qsha,"plan_signature":p["plan_signature"]}
        raw.append(cand);render_results.append(result)
        if status=="SOURCE_VALIDATED": validated.append(cand)
        elif status=="NEEDS_QUERY_REVIEW": review.append(cand)
        else: rejected.append(cand)

    # Candidate-level dedup after validation; duplicate semantics fail closed rather than silently dropping.
    d=dedup_candidates(validated)
    if d["semantic_duplicate_excess"]:
        dup_sigs={x["signature"] for x in d["duplicate_semantic_signatures"]}
        moved=[];kept=[]
        for r in validated:
            if r["dedup_signature"] in dup_sigs:
                rr={**r,"status":"REJECTED","rejection_reasons":sorted(set(r["rejection_reasons"]+["SEMANTIC_DUPLICATE"]))};rejected.append(rr);moved.append(rr)
            else: kept.append(r)
        validated=kept;d=dedup_candidates(validated)

    # Reports.
    all_nonrejected=validated+review
    pattern=surface_report(raw)
    naturalness={"attempts":len(raw),"pass":sum(1 for r in raw if r["query_validation"]["naturalness"]["pass"]),"warnings":sum(bool(r["quality_flags"]) for r in raw),"rejects":sum("UNNATURAL_RENDERING" in " ".join(r["rejection_reasons"]) for r in raw)}
    intent={"pass":sum(r["query_validation"]["intent"]["pass"] for r in raw),"intent_drift":sum("INTENT_DRIFT" in r["rejection_reasons"] for r in raw),"category_drift":sum(any(x.startswith("CATEGORY_DRIFT") for x in r["rejection_reasons"]) for r in raw)}
    scope={"pass":sum(r["scope_validation"]["scope"]["pass"] for r in raw),"expansion":sum("SCOPE_EXPANSION" in r["rejection_reasons"] for r in raw),"collapse":sum("SCOPE_COLLAPSE" in r["rejection_reasons"] or "MULTI_FACT_SCOPE_COLLAPSE" in r["rejection_reasons"] for r in raw),"mutation":sum("INTENT_DRIFT" in r["rejection_reasons"] for r in raw)}
    fact_align={"all_required_facts_demanded":sum(r["scope_validation"]["fact_alignment"]["missing"]==[] for r in raw),"required_fact_missing":sum(bool(r["scope_validation"]["fact_alignment"]["missing"]) for r in raw),"supporting_fact_promoted":sum(bool(r["scope_validation"]["fact_alignment"]["supporting_promoted"]) for r in raw),"extra_unsupported_fact":sum(bool(r["scope_validation"]["fact_alignment"]["extra"]) for r in raw)}
    evidence={"complete":sum(r["scope_validation"]["evidence_alignment"]["pass"] for r in raw),"issues":sum(not r["scope_validation"]["evidence_alignment"]["pass"] for r in raw)}
    leakage_keys=["numeric","boolean","compatibility","limitation","policy","exact"]
    leakage={k:sum(bool(r["leakage_validation"].get(k)) for r in raw) for k in leakage_keys};leakage["internal"]=sum(bool(r["leakage_validation"].get("internal_patterns")) for r in raw)
    # Specialist audits.
    policy_rows=[r for r in raw if r["primary_task_type"]=="POLICY_OR_WARRANTY"]
    faq_rows=[r for r in raw if r["primary_task_type"]=="FAQ_PROCESS"]
    mf=[r for r in raw if r["primary_task_type"]=="MULTI_FACT_SYNTHESIS"]
    ms=[r for r in raw if r["primary_task_type"]=="MULTI_SECTION_SYNTHESIS"]
    policy_audit={"planned":len(policy_rows),"source_validated":sum(r["status"]=="SOURCE_VALIDATED" for r in policy_rows),"qualification_preserved":sum(not any(x in r["rejection_reasons"] for x in ("POLICY_RENDERING_VIOLATION","ANSWER_LEAKAGE")) for r in policy_rows),"absolute_interpretation_failures":sum("POLICY_RENDERING_VIOLATION" in r["rejection_reasons"] for r in policy_rows),"region_hallucination":sum(bool(re.search(r"美国|欧洲|中国大陆|全球",r["candidate_query"])) for r in policy_rows),"effective_time_hallucination":sum(bool(re.search(r"20\d{2}年|今年政策|当前版本",r["candidate_query"])) for r in policy_rows)}
    faq_audit={"planned":len(faq_rows),"source_validated":sum(r["status"]=="SOURCE_VALIDATED" for r in faq_rows),"exact_canonical_copies":sum(r["candidate_query"].strip("？?") == r["render_metadata"].get("canonical_heading","").strip("？?") for r in faq_rows),"naturalized":sum(bool(r["render_metadata"].get("faq_naturalized")) for r in faq_rows)}
    mf_audit={"planned":len(mf),"rendered":len(mf),"source_validated":sum(r["status"]=="SOURCE_VALIDATED" for r in mf),"scope_collapse":sum("MULTI_FACT_SCOPE_COLLAPSE" in r["rejection_reasons"] for r in mf),"necessity_preserved":sum(r["scope_validation"]["scope"]["pass"] for r in mf),"average_required_facts":round(sum(len(r["required_fact_ids"]) for r in mf)/max(1,len(mf)),2)}
    ms_audit=[]
    plan_map={p["task_plan_id"]:p for p in plans}
    for r in ms:
        p=plan_map[r["task_plan_id"]]
        ms_audit.append({"task_plan_id":r["task_plan_id"],"candidate_id":r["candidate_id"],"relation":p.get("composition_relation_evidence",[]),"sections":p["section_ids"],"query_intent":r["candidate_query"],"both_necessary":len(p["required_evidence_ids"])>=2,"relation_preserved":"MULTI_SECTION_RELATION_LOST" not in r["rejection_reasons"],"status":r["status"]})
    category={"knowledge":sum(not any(x.startswith("CATEGORY_DRIFT") for x in r["rejection_reasons"]) for r in raw),"category_drift":sum(any(x.startswith("CATEGORY_DRIFT") for x in r["rejection_reasons"]) for r in raw)}
    collisions={"formal_exact_or_normalized":sum("CROSS_STAGE_QUERY_COLLISION" in r["rejection_reasons"] for r in raw),"private_category_drift":sum("CATEGORY_DRIFT_PRIVATE_OR_MIXED" in r["rejection_reasons"] for r in raw),"mixed_collision":0,"troubleshooting_collision":sum("CATEGORY_DRIFT_TROUBLESHOOTING" in r["rejection_reasons"] for r in raw),"note":"plan-level frozen fact/evidence collisions remain governed by G0.2; G0.3 reports query-level exact/normalized and category drift"}
    eff=dedup_candidates(validated);eff.update({"rendered":len(raw),"source_validated":len(validated),"effective_semantic_units":len(validated)-eff["semantic_duplicate_excess"],"effective_ratio":round((len(validated)-eff["semantic_duplicate_excess"])/max(1,len(validated)),6)})
    bal=balance(validated,doc_map)
    task_dist=distribution(validated,"primary_task_type");difficulty=distribution(validated,"difficulty");reasoning=distribution(validated,"reasoning_type");answer=distribution(validated,"answer_scope")
    reasons=Counter(x for r in raw for x in r["rejection_reasons"]);reviews=Counter(x for r in review for x in r["quality_flags"])

    # Write artifacts.
    _write_jsonl(out/"knowledge_render_input.jsonl",plans);_write_jsonl(out/"knowledge_render_results.jsonl",render_results);_write_jsonl(out/"knowledge_render_rejected.jsonl",rejected);_write_jsonl(out/"knowledge_query_review_queue.jsonl",review);_write_jsonl(out/"knowledge_raw_candidates.jsonl",raw);_write_jsonl(out/"knowledge_source_validated.jsonl",validated)
    _write_json(out/"knowledge_rendering_pattern_report.json",pattern);_write_json(out/"knowledge_query_naturalness_report.json",naturalness);_write_json(out/"knowledge_query_intent_alignment.json",intent);_write_json(out/"knowledge_query_scope_alignment.json",scope);_write_json(out/"knowledge_query_fact_alignment.json",fact_align);_write_json(out/"knowledge_query_evidence_alignment.json",evidence);_write_json(out/"knowledge_query_leakage_report.json",leakage);_write_json(out/"knowledge_query_policy_audit.json",policy_audit);_write_json(out/"knowledge_query_multi_fact_audit.json",mf_audit);_write_json(out/"knowledge_query_multi_section_audit.json",ms_audit);_write_json(out/"knowledge_query_category_ownership.json",category);_write_json(out/"knowledge_query_cross_stage_collision.json",collisions);_write_json(out/"knowledge_candidate_dedup_report.json",eff);_write_json(out/"knowledge_candidate_effective_diversity.json",eff);_write_json(out/"knowledge_candidate_document_balance.json",bal["documents"]);_write_json(out/"knowledge_candidate_product_balance.json",bal["products"]);_write_json(out/"knowledge_candidate_task_type_distribution.json",task_dist);_write_json(out/"knowledge_candidate_difficulty_distribution.json",difficulty);_write_json(out/"knowledge_candidate_reasoning_distribution.json",reasoning);_write_json(out/"knowledge_candidate_answer_scope_distribution.json",answer)
    candidate_set_hash=_sha_obj(sorted(({k:v for k,v in r.items() if k not in {"quality_flags"}} for r in validated),key=lambda x:x["candidate_id"]))
    manifest={"schema_version":"g0.3-knowledge-candidate-1","render_version":RENDER_VERSION,"task_plan_set_hash":frozen["task_plan_set_hash"],"render_method":"CONTROLLED_LANGUAGE_RENDERER","renderer_version":RENDER_VERSION,"llm_used":False,"input_task_plans":len(plans),"rendered_count":len(raw),"source_validated_count":len(validated),"query_review_count":len(review),"rejected_count":len(rejected),"effective_candidate_count":eff["effective_semantic_units"],"document_count":bal["documents"]["covered"],"product_count":bal["products"]["covered"],"task_type_count":len(task_dist),"candidate_set_hash":candidate_set_hash,"max_active_candidate_per_task_plan":1,"new_formal_cases":0,"gold":"NOT PREPARED","annotation_runs":0,"production_agent":"NOT RUN",**frozen}
    _write_json(out/"knowledge_candidate_manifest.json",manifest)
    summary={"phase":"G0.3","status":"COMPLETE" if len(validated)>=165 and eff["effective_ratio"]>=0.95 else "PARTIAL","input_task_plans":180,"rendering_attempts":len(raw),"rendered":len(raw),"source_validated":len(validated),"needs_query_review":len(review),"rejected":len(rejected),"effective_semantic_units":eff["effective_semantic_units"],"effective_ratio":eff["effective_ratio"],"semantic_duplicate_excess":eff["semantic_duplicate_excess"],"document_coverage":bal["documents"]["covered"],"product_coverage":bal["products"]["covered"],"rejection_reasons":dict(sorted(reasons.items())),"review_reasons":dict(sorted(reviews.items())),"candidate_set_hash":candidate_set_hash,"new_formal_cases":0,"gold":"NOT PREPARED","annotation_runs":0,"production_agent":"NOT RUN","formal_canonical":39,"d3r":"DEFERRED_BY_ENVIRONMENT"}
    _write_json(out/"phase_g0_3_summary.json",summary)
    return summary
