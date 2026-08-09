"""Phase G0.2 deterministic balanced KnowledgeTaskPlan planning."""
from __future__ import annotations
import hashlib, json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .knowledge_selection import effective_representatives, build_task_plan_proposals, select_balanced
from .knowledge_plan_validation import validate_plan, balance_issues
from .knowledge_plan_reporting import plan_effective_diversity, distributions, balance_report

EXPECTED_SOURCE_SPACE_HASH="206fac5baaf012483066e913e56bfb10fb6ce97cc1d4d6dfeb9b22b8800cc40b"

def _sha_file(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def _sha_obj(x:Any)->str:return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _read_jsonl(p:Path):return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
def _write_json(p:Path,x:Any):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def _write_jsonl(p:Path,rows):p.write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n" for x in rows),encoding="utf-8")

def _formal_count(root:Path)->int:
    total=0
    for name in ("dev_v7_3_canonical_v1.json","validation_v7_3_canonical_v1.json"):
        x=json.loads((root/"evals/benchmark/data/canonical"/name).read_text(encoding="utf-8"));rows=x.get("samples",x) if isinstance(x,dict) else x;total+=len(rows)
    return total

def _frozen_gate(root:Path,g01:Path)->dict[str,Any]:
    manifest=json.loads((g01/"knowledge_source_space_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("knowledge_source_space_hash")!=EXPECTED_SOURCE_SPACE_HASH or int(manifest.get("effective_source_units",0))!=1195: raise RuntimeError("SOURCE_SPACE_DRIFT")
    private=json.loads((root/"artifacts/evaluation/dataset-expansion-d2/annotation_batch_manifest.json").read_text())
    mixed=json.loads((root/"artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_annotation_batch_manifest_refrozen.json").read_text())
    f0=json.loads((root/"artifacts/evaluation/dataset-expansion-f0-troubleshooting/phase_f0_summary.json").read_text())
    d3r=json.loads((root/"artifacts/evaluation/dataset-expansion-d3-real-run/phase_d3r_summary.json").read_text())
    if int(private.get("packet_count",0))!=76 or int(mixed.get("packet_count",0))!=58 or int(f0.get("source_validated",0))!=66 or _formal_count(root)!=39: raise RuntimeError("PREVIOUS_FROZEN_ASSET_DRIFT")
    return {"source_space_hash":manifest["knowledge_source_space_hash"],"corpus_fingerprint":manifest["corpus_fingerprint"],"private_batch_hash":private.get("batch_hash"),"mixed_batch_hash":mixed.get("batch_hash"),"troubleshooting_candidate_set_hash":json.loads((root/"artifacts/evaluation/dataset-expansion-f0-troubleshooting/troubleshooting_candidate_manifest.json").read_text()).get("candidate_set_hash"),"d3r":"DEFERRED_BY_ENVIRONMENT"}

def _ownership_map(g01:Path)->dict[str,set[str]]:
    x=json.loads((g01/"knowledge_category_ownership.json").read_text(encoding="utf-8"));return {r["fact_id"]:set(r.get("observed_overlaps",[])) for r in x["facts"]}

def _previous_selection(plans:list[dict[str,Any]], previous:list[dict[str,Any]])->list[dict[str,Any]]:
    rows=[]
    for r in previous:
        pid=r.get("product_id");doc="liorin_support_faq" if r.get("name")=="Support FAQ" else None
        chosen=[p for p in plans if (pid and pid in p["product_ids"]) or (doc and doc in p["document_ids"])]
        rows.append({**r,"planned":len(chosen),"effective":len({p["plan_signature"] for p in chosen}),"selected":bool(chosen)})
    return rows

def run_knowledge_task_planning(root:str|Path=".",g0_1:str|Path="artifacts/evaluation/dataset-expansion-g0-1-knowledge-source",output:str|Path="artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning")->dict[str,Any]:
    root=Path(root).resolve();g01=(root/g0_1).resolve() if not Path(g0_1).is_absolute() else Path(g0_1);out=(root/output).resolve() if not Path(output).is_absolute() else Path(output);out.mkdir(parents=True,exist_ok=True)
    frozen=_frozen_gate(root,g01)
    units=_read_jsonl(g01/"knowledge_source_units.jsonl");facts=_read_jsonl(g01/"knowledge_atomic_fact_audit.jsonl");groups=_read_jsonl(g01/"knowledge_coherent_fact_groups.jsonl");sections=_read_jsonl(g01/"knowledge_section_audit.jsonl")
    fact_map={x["fact_id"]:x for x in facts};unit_map={x["source_unit_id"]:x for x in units};section_map={x["section_id"]:x for x in sections};ownership=_ownership_map(g01)
    bp=json.loads((g01/"knowledge_capacity_blueprint.json").read_text(encoding="utf-8"));prev=json.loads((g01/"knowledge_previous_uncovered_source_audit.json").read_text(encoding="utf-8"))
    reps,rep_dups=effective_representatives(units,bp,prev)
    if len(reps)!=1195: raise RuntimeError(f"G0.2 effective representative drift: {len(reps)}")
    priority_map={r["source_unit_id"]:p for p in ("P0","P1","P2") for r in bp["source_priority"][p]}
    eligible=[{**u,"selection_priority":priority_map.get(u["source_unit_id"],"P2")} for u in reps]
    proposals,proposal_stats=build_task_plan_proposals(reps,units,fact_map,groups,section_map,ownership,bp)
    issues={p["task_plan_id"]:validate_plan(p,fact_map,unit_map,ownership) for p in proposals}
    planned,deferred,rejected,selection=select_balanced(proposals,issues,target=180)
    # Validation after selection must remain clean.
    post={p["task_plan_id"]:validate_plan(p,fact_map,unit_map,ownership) for p in planned}
    if any(post.values()): raise RuntimeError(f"G0.2 selected invalid plans: {[(k,v) for k,v in post.items() if v][:3]}")
    dist=distributions(planned);balance=balance_report(planned,reps);guards=balance_issues(planned);diversity=plan_effective_diversity(planned,fact_map);previous=_previous_selection(planned,prev)
    # Cross-stage collision report uses rejected exact single-fact overlaps plus partial overlap flags on planned composite tasks.
    collision_reasons=Counter(x for rs in issues.values() for x in rs if x.startswith("COLLIDES_"));partial=Counter()
    for p in planned:
        ov=set().union(*(ownership.get(fid,set()) for fid in p["required_fact_ids"]))
        for k in ("FORMAL","MIXED","TROUBLESHOOTING"):
            if k in ov: partial[k]+=1
    collision={"rejected_exact_single_fact":dict(collision_reasons),"planned_partial_or_composite_overlap":dict(partial),"principle":"exact single-fact reuse is rejected; composite plans may contain previously observed facts only when required fact set/reasoning/answer scope is different"}
    # Concentration and hard balance gates.
    feature_ratio=dist["task_type"].get("FEATURE_OR_INSTRUCTION",{}).get("ratio",0);direct_spec=(dist["task_type"].get("DIRECT_FACT",{}).get("count",0)+dist["task_type"].get("PRODUCT_SPEC",{}).get("count",0))/max(1,len(planned))
    if feature_ratio>0.25: raise RuntimeError("BALANCE_FAIL: FEATURE_OR_INSTRUCTION >25%")
    if direct_spec>0.20: raise RuntimeError("BALANCE_FAIL: DIRECT+SPEC >20%")
    if len(planned)<165: raise RuntimeError(f"G0.2 insufficient high-quality planning capacity: {len(planned)}")
    if diversity["effective_task_plan_semantics"]<165: raise RuntimeError(f"G0.2 semantic duplicate excess too high: {diversity}")
    # Priority report.
    avail_priority=Counter(x["selection_priority"] for x in eligible);selected_priority=Counter(p["priority"] for p in planned)
    priority_report={p:{"available":avail_priority[p],"selected":selected_priority[p]} for p in ("P0","P1","P2")}
    # Source balance / task quota report.
    proposal_by_type=Counter(p["primary_task_type"] for p in proposals)
    valid_by_type=Counter(p["primary_task_type"] for p in proposals if not issues[p["task_plan_id"]])
    rejected_by_type=Counter(p["primary_task_type"] for p in proposals if issues[p["task_plan_id"]])
    task_quota={"target":selection["quota"],"proposal_available":dict(sorted(proposal_by_type.items())),"quality_valid_available":dict(sorted(valid_by_type.items())),"quality_rejected":dict(sorted(rejected_by_type.items())),"actual":{k:v["count"] for k,v in dist["task_type"].items()},"feature_cap":0.25,"direct_spec_cap":0.20,"feature_cap_pass":feature_ratio<=0.25,"direct_spec_cap_pass":direct_spec<=0.20}
    # All proposal states.
    planned_ids={p["task_plan_id"] for p in planned};rejected_ids={p["task_plan_id"] for p in rejected};all_rows=[]
    deferred_map={p["task_plan_id"]:p for p in deferred};rejected_map={p["task_plan_id"]:p for p in rejected};planned_map={p["task_plan_id"]:p for p in planned}
    for p in proposals:
        all_rows.append(planned_map.get(p["task_plan_id"]) or rejected_map.get(p["task_plan_id"]) or deferred_map[p["task_plan_id"]])
    # Artifacts.
    _write_jsonl(out/"knowledge_selection_eligible_pool.jsonl",eligible)
    _write_json(out/"knowledge_selection_priority_report.json",priority_report)
    _write_json(out/"knowledge_source_balance_plan.json",{"target_sources":">=20","target_products":">=18","ordinary_manual_soft_cap":12,"previously_untested_soft_minima":{"LIO-PROD-017":6,"LIO-PROD-018":8,"LIO-PROD-019":6,"LIO-PROD-020":5,"liorin_support_faq":5},"actual":balance})
    _write_json(out/"knowledge_task_type_quota.json",task_quota)
    _write_jsonl(out/"knowledge_multi_fact_compositions.jsonl",[p for p in all_rows if p["primary_task_type"]=="MULTI_FACT_SYNTHESIS"])
    _write_jsonl(out/"knowledge_multi_section_compositions.jsonl",[p for p in all_rows if p["primary_task_type"]=="MULTI_SECTION_SYNTHESIS"])
    _write_jsonl(out/"knowledge_task_plan_proposals.jsonl",all_rows)
    _write_jsonl(out/"knowledge_task_plans.jsonl",planned)
    _write_jsonl(out/"knowledge_task_plan_deferred.jsonl",deferred)
    _write_jsonl(out/"knowledge_task_plan_rejected.jsonl",rejected)
    _write_json(out/"knowledge_task_type_distribution.json",dist["task_type"]);_write_json(out/"knowledge_reasoning_distribution.json",dist["reasoning"]);_write_json(out/"knowledge_answer_scope_distribution.json",dist["answer_scope"]);_write_json(out/"knowledge_difficulty_distribution.json",dist["difficulty"])
    _write_json(out/"knowledge_document_balance.json",balance["documents"]);_write_json(out/"knowledge_product_balance.json",balance["products"]);_write_json(out/"knowledge_semantic_topic_balance.json",balance["semantic_topics"]);_write_json(out/"knowledge_semantic_family_balance.json",balance["semantic_families"])
    _write_json(out/"knowledge_previous_uncovered_source_selection.json",previous);_write_json(out/"knowledge_plan_dedup_report.json",diversity);_write_json(out/"knowledge_plan_cross_stage_collision.json",collision)
    concentration={"guards":guards,"document":balance["documents"],"section":balance["sections"],"source_unit":balance["source_units"],"semantic_family":balance["semantic_families"]};_write_json(out/"knowledge_plan_concentration_report.json",concentration);_write_json(out/"knowledge_task_plan_effective_diversity.json",diversity)
    plan_set_hash=_sha_obj(sorted(({k:v for k,v in p.items() if k!="status"} for p in planned), key=lambda x:x["task_plan_id"]))
    manifest={"schema_version":"g0.2-knowledge-task-plan-1","planning_version":"deterministic-balanced-knowledge-planning-g0.2-1","source_space_hash":frozen["source_space_hash"],"corpus_fingerprint":frozen["corpus_fingerprint"],"eligible_ksu_count":len(eligible),"proposal_count":len(proposals),"planned_count":len(planned),"deferred_count":len(deferred),"rejected_count":len(rejected),"effective_plan_count":diversity["effective_task_plan_semantics"],"source_count":balance["documents"]["covered"],"product_count":balance["products"]["covered"],"semantic_topic_count":balance["semantic_topics"]["covered_source_topics"],"task_type_count":len(dist["task_type"]),"planning_method":"DETERMINISTIC_CONSTRAINED_SELECTION + SOURCE_GROUNDED_COMPOSITION","random_seed":0,"task_plan_set_hash":plan_set_hash,"max_active_candidate_per_task_plan":1,"new_queries":0,"new_candidates":0,"new_formal_cases":0,"annotation_runs":0,"production_agent":"NOT RUN",**{k:v for k,v in frozen.items() if k not in {"source_space_hash","corpus_fingerprint"}}}
    _write_json(out/"knowledge_task_plan_manifest.json",manifest)
    summary={"phase":"G0.2","status":"COMPLETE","effective_ksu_input":len(eligible),"p0_available":avail_priority["P0"],"p1_available":avail_priority["P1"],"p2_available":avail_priority["P2"],"task_plan_proposals":len(proposals),"planned":len(planned),"deferred":len(deferred),"rejected":len(rejected),"effective_task_plan_semantics":diversity["effective_task_plan_semantics"],"documents":balance["documents"]["covered"],"products":balance["products"]["covered"],"semantic_topics":balance["semantic_topics"]["covered_source_topics"],"feature_ratio":feature_ratio,"direct_spec_ratio":round(direct_spec,6),"previously_untested_selected":sum(r["selected"] for r in previous),"new_queries":0,"new_candidates":0,"new_formal_cases":0,"annotation_runs":0,"production_agent":"NOT RUN","formal_canonical":39,"d3r":"DEFERRED_BY_ENVIRONMENT","task_plan_set_hash":plan_set_hash,"proposal_stats":proposal_stats,"balance_guards":guards}
    _write_json(out/"phase_g0_2_summary.json",summary)
    return summary
