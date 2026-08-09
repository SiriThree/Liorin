"""Benchmark Expansion Phase G0.1 deterministic Knowledge source-space audit."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .knowledge_capacity import capacity_blueprint, capacity_funnel, fact_type_funnel
from .knowledge_source import audit_knowledge_source_space
from .knowledge_source_reporting import cross_product_duplicates, product_coverage, source_coverage, source_unit_report


def _sha_file(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _sha_obj(x: Any) -> str: return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _write_json(path: Path,x: Any): path.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def _write_jsonl(path: Path,rows): path.write_text("".join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n" for r in rows),encoding="utf-8")
def _read_jsonl(path: Path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _formal_count(root: Path) -> int:
    n=0
    for name in ("dev_v7_3_canonical_v1.json","validation_v7_3_canonical_v1.json"):
        x=json.loads((root/"evals/benchmark/data/canonical"/name).read_text(encoding="utf-8")); rows=x.get("samples",x) if isinstance(x,dict) else x; n+=len(rows)
    return n


def _frozen_gate(root: Path) -> dict[str, Any]:
    private=root/"artifacts/evaluation/dataset-expansion-d2/annotation_batch_manifest.json"
    mixed=root/"artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_annotation_batch_manifest_refrozen.json"
    f0=root/"artifacts/evaluation/dataset-expansion-f0-troubleshooting/phase_f0_summary.json"
    d3r=root/"artifacts/evaluation/dataset-expansion-d3-real-run/phase_d3r_summary.json"
    for p in (private,mixed,f0,d3r):
        if not p.exists(): raise RuntimeError(f"G0.1 missing frozen dependency: {p}")
    px=json.loads(private.read_text()); mx=json.loads(mixed.read_text()); fx=json.loads(f0.read_text()); dx=json.loads(d3r.read_text())
    if int(px.get("packet_count",0))!=76 or int(mx.get("packet_count",0))!=58 or int(fx.get("source_validated",0))!=66:
        raise RuntimeError("G0.1 frozen benchmark input drift")
    if _formal_count(root)!=39: raise RuntimeError("G0.1 formal canonical drift")
    return {"private_batch_hash":px.get("batch_hash"),"mixed_batch_hash":mx.get("batch_hash"),"troubleshooting_candidate_set_hash":json.loads((root/"artifacts/evaluation/dataset-expansion-f0-troubleshooting/troubleshooting_candidate_manifest.json").read_text()).get("candidate_set_hash"),"d3r":"DEFERRED_BY_ENVIRONMENT"}


def _source_drift_gate(root: Path, d0p: Path, space: dict[str,Any]) -> dict[str,Any]:
    d0_docs=json.loads((d0p/"document_source_inventory.json").read_text(encoding="utf-8"))
    d0_facts=_read_jsonl(d0p/"atomic_fact_inventory.jsonl")
    current_docs=space["documents"]; current_facts=[f.to_state() for f in space["facts"]]
    doc_hashes_equal={d["document_id"]:d["sha256"] for d in d0_docs}=={d["document_id"]:d["sha256"] for d in current_docs}
    facts_equal=d0_facts==current_facts
    if not (doc_hashes_equal and facts_equal):
        raise RuntimeError("SOURCE_DRIFT: current Knowledge Corpus no longer matches D0 source/fact inventory")
    return {"status":"NO_SOURCE_DRIFT","document_hashes_equal":doc_hashes_equal,"atomic_fact_inventory_equal":facts_equal,"d0_sources":len(d0_docs),"current_sources":len(current_docs),"d0_atomic_facts":len(d0_facts),"current_atomic_facts":len(current_facts)}


def _previous_uncovered_audit(space: dict[str,Any], root: Path) -> list[dict[str,Any]]:
    targets={
        "LIO-PROD-017":"Air Purifier","LIO-PROD-018":"Air Conditioner","LIO-PROD-019":"Steam Cleaner","LIO-PROD-020":"Bluetooth Laser Mouse",
    }
    units=space["source_units"]; audits=space["fact_audits"]
    rows=[]
    for pid,label in targets.items():
        docs=[d for d in space["documents"] if d.get("product_id")==pid]
        facts=[a for a in audits if a.product_id==pid]
        us=[u for u in units if u.product_id==pid and u.benchmark_usable]
        rows.append({"name":label,"product_id":pid,"source_still_exists":bool(docs),"usable_atomic_facts":sum(a.task_usability=="TASK_USABLE" for a in facts),"knowledge_source_units":len(us),"effective_units":len({u.cross_product_signature for u in us}),"previous_formal_coverage":any(u.section_ids[0] in space["ownership_inputs"]["formal_sections"] for u in us),"recommended_for_g0_2":bool(us),"why_previous_uncovered":"current Formal alias map contains no evidence section for this product source"})
    faq_docs=[d for d in space["documents"] if d["source_type"]=="faq"]
    faq_facts=[a for a in audits if a.source_type=="faq"]
    faq_units=[u for u in units if u.source_type=="faq" and u.benchmark_usable]
    rows.append({"name":"Support FAQ","product_id":None,"source_still_exists":bool(faq_docs),"usable_atomic_facts":sum(a.task_usability=="TASK_USABLE" for a in faq_facts),"knowledge_source_units":len(faq_units),"effective_units":len({u.cross_product_signature for u in faq_units}),"previous_formal_coverage":any(u.section_ids[0] in space["ownership_inputs"]["formal_sections"] for u in faq_units),"recommended_for_g0_2":bool(faq_units),"why_previous_uncovered":"current Formal alias map contains no FAQ evidence section","note":"FAQ is grouped at Q/A SourceUnit level; sentence facts are not inflated into separate QA tasks."})
    return rows


def _priority_blueprint(space: dict[str,Any], source_cov: dict[str,Any], dup: dict[str,Any]) -> dict[str,Any]:
    units=[u for u in space["source_units"] if u.benchmark_usable]
    formal_sections=space["ownership_inputs"]["formal_sections"]
    dup_sigs={x["cross_product_signature"] for x in dup["groups"]}
    p0=[];p1=[];p2=[]
    for u in units:
        reasons=[]
        if not any(s in formal_sections for s in u.section_ids): reasons.append("CURRENTLY_UNTESTED")
        if u.source_type=="faq": reasons.append("FAQ")
        if u.source_type=="policy": reasons.append("POLICY")
        if u.fact_relationship in {"COMPATIBILITY_RELATION","LIMITATION"}: reasons.append(u.fact_relationship)
        if u.coherent_fact_group_ids: reasons.append("MULTI_FACT_COHERENT")
        if u.semantic_topic in {"physical_spec","feature_configuration","maintenance","usage_instruction"}: common=True
        else: common=False
        item={"source_unit_id":u.source_unit_id,"document_id":u.document_id,"product_id":u.product_id,"semantic_topic":u.semantic_topic,"fact_relationship":u.fact_relationship,"reasons":reasons}
        if any(r in reasons for r in ("FAQ","POLICY","COMPATIBILITY_RELATION","LIMITATION","MULTI_FACT_COHERENT")) or ("CURRENTLY_UNTESTED" in reasons and not common): p0.append(item)
        elif u.cross_product_signature in dup_sigs or (common and not reasons): p2.append(item)
        else: p1.append(item)
    return {"P0":p0,"P1":p1,"P2":p2,"counts":{"P0":len(p0),"P1":len(p1),"P2":len(p2)}}


def run_knowledge_source_audit(root: str|Path=".", d0: str|Path="artifacts/evaluation/dataset-expansion-d0", output: str|Path="artifacts/evaluation/dataset-expansion-g0-1-knowledge-source") -> dict[str,Any]:
    root=Path(root).resolve(); d0p=(root/d0).resolve() if not Path(d0).is_absolute() else Path(d0); out=(root/output).resolve() if not Path(output).is_absolute() else Path(output); out.mkdir(parents=True,exist_ok=True)
    frozen=_frozen_gate(root)
    space=audit_knowledge_source_space(root)
    drift=_source_drift_gate(root,d0p,space)
    funnel=capacity_funnel(space); ftf= fact_type_funnel(space); sur=source_unit_report(space); scov=source_coverage(space); pcov=product_coverage(space); dup=cross_product_duplicates(space); blueprint=capacity_blueprint(space,funnel); previous=_previous_uncovered_audit(space,root); priorities=_priority_blueprint(space,scov,dup)

    # Inflation audit demonstrates that procedures/FAQ/policy are preserved as
    # semantic structures rather than multiplied by sentence/step count.
    procedure_units=[u for u in space["source_units"] if u.unit_type=="PROCEDURE"]
    procedure_fact_total=sum(len(u.fact_ids) for u in procedure_units)
    faq_units=[u for u in space["source_units"] if u.unit_type=="FAQ_QA"]
    policy_units=[u for u in space["source_units"] if u.unit_type=="POLICY_RULE"]
    high_fact_sections=[x for x in space["section_audits"] if x["fact_count"]>=10]
    inflation={
        "procedure_source_units":len(procedure_units),
        "procedure_effective_source_units":len({u.cross_product_signature for u in procedure_units if u.benchmark_usable}),
        "procedure_fact_or_step_count_if_mechanically_inflated":procedure_fact_total,
        "procedure_inflation_prevented":max(0,procedure_fact_total-len(procedure_units)),
        "faq_source_units":len(faq_units),
        "faq_fact_count":sum(len(u.fact_ids) for u in faq_units),
        "faq_inflation_prevented":max(0,sum(len(u.fact_ids) for u in faq_units)-len(faq_units)),
        "policy_source_units":len(policy_units),
        "policy_fact_count":sum(len(u.fact_ids) for u in policy_units),
        "policy_inflation_prevented":max(0,sum(len(u.fact_ids) for u in policy_units)-len(policy_units)),
        "high_fact_count_sections_ge_10":len(high_fact_sections),
        "high_fact_count_section_facts":sum(x["fact_count"] for x in high_fact_sections),
        "high_fact_count_section_source_units":sum(1 for u in space["source_units"] if any(sid in {x["section_id"] for x in high_fact_sections} for sid in u.section_ids)),
        "principle":"section/fact counts are not independent task counts",
    }
    _write_json(out/"knowledge_inflation_audit.json",inflation)

    # Document inventory keeps current Source truth plus audit-level stable-id info.
    docs=[]
    for d in space["documents"]:
        docs.append({**d,"stable_section_identity":d.get("stable_section_identity_available"),"notes":"current checked-in Knowledge source; no region/effective-time inferred"})
    _write_json(out/"knowledge_document_inventory.json",docs)
    _write_jsonl(out/"knowledge_section_audit.jsonl",space["section_audits"])
    _write_jsonl(out/"knowledge_atomic_fact_audit.jsonl",[a.to_state() for a in space["fact_audits"]])
    _write_jsonl(out/"knowledge_source_units.jsonl",[u.to_state() for u in space["source_units"]])
    _write_json(out/"knowledge_source_unit_report.json",sur)
    _write_json(out/"knowledge_fact_relationship_distribution.json",dict(Counter(u.fact_relationship for u in space["source_units"])))
    _write_jsonl(out/"knowledge_independent_askable_facts.jsonl",[a.to_state() for a in space["fact_audits"] if a.independently_askable])
    _write_jsonl(out/"knowledge_coherent_fact_groups.jsonl",[g.to_state() for g in space["coherent_groups"]])
    ctx=Counter(x for a in space["fact_audits"] for x in a.required_local_context)
    _write_json(out/"knowledge_context_dependencies.json",{"facts_with_local_context":sum(bool(a.required_local_context) for a in space["fact_audits"]),"context_type_distribution":dict(ctx)})
    own_counts=Counter(a.category_ownership for a in space["fact_audits"]); overlap=Counter(x for a in space["fact_audits"] for x in a.ownership_overlaps)
    _write_json(out/"knowledge_category_ownership.json",{
        "category_ownership_counts":dict(own_counts),
        "observed_overlap_counts":dict(overlap),
        "semantics":"TROUBLESHOOTING is exclusive for active F0 facts; FORMAL/MIXED are recorded overlaps, not automatic exclusion of pure document knowledge.",
        "facts":[{"fact_id":a.fact_id,"document_id":a.document_id,"section_id":a.section_id,"current_owner":a.category_ownership,"observed_overlaps":list(a.ownership_overlaps)} for a in space["fact_audits"]],
    })
    _write_json(out/"knowledge_cross_product_semantic_duplicates.json",dup)
    _write_json(out/"knowledge_source_coverage.json",scov)
    _write_json(out/"knowledge_product_coverage.json",pcov)
    _write_json(out/"knowledge_fact_type_funnel.json",ftf)
    _write_json(out/"knowledge_capacity_funnel.json",funnel)
    uncovered=[u.to_state() for u in space["source_units"] if u.benchmark_usable and not any(s in space["ownership_inputs"]["formal_sections"] for s in u.section_ids)]
    _write_json(out/"knowledge_uncovered_source_units.json",{"count":len(uncovered),"source_units":uncovered})
    _write_json(out/"knowledge_previous_uncovered_source_audit.json",previous)
    _write_json(out/"knowledge_capacity_blueprint.json",{**blueprint,"source_priority":priorities})

    corpus_fp=_sha_obj(sorted((p.relative_to(root).as_posix(),_sha_file(p)) for p in (root/"data/knowledge").rglob("*.md")))
    semantic_units=[u.to_state() for u in sorted(space["source_units"],key=lambda x:x.source_unit_id)]
    source_space_hash=_sha_obj({"documents":[(d["document_id"],d["sha256"]) for d in sorted(space["documents"],key=lambda x:x["document_id"])],"units":semantic_units,"groups":[g.to_state() for g in sorted(space["coherent_groups"],key=lambda x:x.group_id)]})
    manifest={"schema_version":"g0.1-knowledge-source-space-1","generation_version":"deterministic-knowledge-source-audit-g0.1-1","corpus_fingerprint":corpus_fp,"d0_inventory_hash":_sha_obj(sorted((p.name,_sha_file(p)) for p in d0p.iterdir() if p.is_file())),"knowledge_source_space_hash":source_space_hash,"source_drift":drift,"source_count":len(space["documents"]),"section_count":len(space["sections"]),"atomic_fact_count":len(space["facts"]),"source_unit_count":len(space["source_units"]),"effective_source_units":funnel["effective_source_units"],"generation_method":"DETERMINISTIC_SOURCE_AUDIT + RULE_BASED_FACT_GROUPING","llm_used":False,"random_seed":0,"new_queries":0,"new_candidates":0,"new_formal_cases":0,**frozen}
    _write_json(out/"knowledge_source_space_manifest.json",manifest)

    status="COMPLETE"
    summary={"phase":"G0.1","status":status,"sources":len(space["documents"]),"manuals":sum(d["source_type"]=="manual" for d in space["documents"]),"policies":sum(d["source_type"]=="policy" for d in space["documents"]),"faq":sum(d["source_type"]=="faq" for d in space["documents"]),"stable_sections":len(space["sections"]),"atomic_facts":len(space["facts"]),"heuristic_usable":funnel["heuristic_usable"],"task_usable_facts":funnel["task_usable_facts"],"independent_askable_facts":funnel["independent_askable_facts"],"coherent_fact_groups":funnel["coherent_fact_groups"],"knowledge_source_units":funnel["knowledge_source_units"],"benchmark_usable_source_units":funnel["benchmark_usable_source_units"],"effective_source_units":funnel["effective_source_units"],"sources_with_usable_units":scov["sources_with_usable_units"],"products_with_usable_units":pcov["products_with_usable_units"],"cross_product_duplicate_groups":dup["fact_level_duplicate_groups"],"capacity_blueprint":blueprint,"new_queries":0,"new_candidates":0,"new_formal_cases":0,"annotation_runs":0,"production_agent":"NOT RUN","d3r":"DEFERRED_BY_ENVIRONMENT","formal_canonical":39,"source_drift":"NO_SOURCE_DRIFT"}
    _write_json(out/"phase_g0_1_summary.json",summary)
    return summary
