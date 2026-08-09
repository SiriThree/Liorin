"""Benchmark Expansion Phase F0 deterministic Troubleshooting/Clarification/Recovery-oriented construction."""
from __future__ import annotations

import hashlib, json, re
from collections import Counter,defaultdict
from pathlib import Path
from typing import Any

from .troubleshooting_source import build_troubleshooting_source_units
from .troubleshooting_plan import build_candidates
from .troubleshooting_validation import validate_candidates,effective_signature
from .troubleshooting_reporting import behavior_distribution,concentration,effective_diversity
from .troubleshooting_recovery import recovery_action_matrix


def _sha_file(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _sha_obj(x: Any) -> str: return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _write_json(path: Path,x: Any): path.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def _write_jsonl(path: Path,rows): path.write_text("".join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n" for r in rows),encoding="utf-8")
def _read_jsonl(path: Path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
def _norm(q: str): return re.sub(r"[\s，。！？：:、,.!?\"'“”]","",q or "").lower()


def _formal_rows(root: Path):
    rows=[]
    for name in ("dev_v7_3_canonical_v1.json","validation_v7_3_canonical_v1.json"):
        x=json.loads((root/"evals/benchmark/data/canonical"/name).read_text(encoding="utf-8"))
        xs=x.get("samples") if isinstance(x,dict) else x
        rows.extend(xs or [])
    return rows


def _collision_filter(root: Path, validated):
    formal=_formal_rows(root)
    formal_q={_norm((x.get("input") or {}).get("query") or ""):x for x in formal}
    trouble_ids={x.get("case_id") for x in formal if x.get("category")=="TROUBLESHOOTING"}
    mixed_ids={x.get("case_id") for x in formal if x.get("category")=="MIXED_KNOWLEDGE_STRUCTURED"}
    alias_path=root/"artifacts/evaluation/dataset-expansion-d1/legacy_section_alias_map.json"
    alias_payload=json.loads(alias_path.read_text(encoding="utf-8")) if alias_path.exists() else []
    aliases=alias_payload.get("aliases", []) if isinstance(alias_payload, dict) else alias_payload
    protected_sections=set()
    for a in aliases:
        if a.get("case_id") in trouble_ids|mixed_ids and a.get("resolution_status")=="RESOLVED":
            protected_sections.add(a.get("current_section_id"))
    e1r=root/"artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/manual_scope_repair_ready.jsonl"
    mixed_fact_ids=set()
    if e1r.exists():
        for x in _read_jsonl(e1r): mixed_fact_ids.update(x.get("selected_fact_scope") or [])
    kept=[]; rejected=[]; report={"existing_formal_troubleshooting_count":len(trouble_ids),"existing_formal_mixed_count":len(mixed_ids),"protected_current_sections":sorted(x for x in protected_sections if x),"exact_query_collisions":[],"formal_section_collisions":[],"mixed_gold_fact_collisions":[]}
    for c in validated:
        reasons=[]
        if _norm(c.candidate_query) in formal_q:
            reasons.append("DUPLICATE_EXISTING_FORMAL_QUERY"); report["exact_query_collisions"].append(c.candidate_id)
        if any(s in protected_sections for s in c.source_section_ids):
            reasons.append("DUPLICATE_EXISTING_FORMAL_SECTION"); report["formal_section_collisions"].append(c.candidate_id)
        # Same selected Manual facts as frozen Mixed are rejected for ordinary direct/rewrite tasks; clarification/control variants remain distinct behavior.
        if set(c.source_fact_ids)&mixed_fact_ids and c.task_type in {"DIRECT_TROUBLESHOOTING","RECOVERY_ORIENTED_REWRITE"}:
            reasons.append("DUPLICATE_FROZEN_MIXED_MANUAL_FACT"); report["mixed_gold_fact_collisions"].append(c.candidate_id)
        if reasons:
            from dataclasses import replace
            rejected.append(replace(c,status="REJECTED",rejection_reasons=tuple(sorted(set(reasons)))))
        else: kept.append(c)
    return kept,rejected,report


def _scenario_report(rows):
    groups=defaultdict(list)
    for r in rows: groups[r.scenario_family_id].append(r)
    out=[]
    for sid,xs in sorted(groups.items()):
        out.append({"scenario_family_id":sid,"source_unit_id":xs[0].source_unit_id,
                    "full_context_candidate_ids":[x.candidate_id for x in xs if x.task_type=="SUFFICIENT_CONTEXT_NO_CLARIFICATION"],
                    "clarification_variant_ids":[x.candidate_id for x in xs if x.task_type=="CLARIFICATION_REQUIRED"],
                    "recovery_variant_ids":[x.candidate_id for x in xs if "RECOVERY_ORIENTED" in x.behavior_labels],
                    "candidate_ids":[x.candidate_id for x in xs]})
    return out


def run_troubleshooting_expansion(root: str|Path=".", d0: str|Path="artifacts/evaluation/dataset-expansion-d0", output: str|Path="artifacts/evaluation/dataset-expansion-f0-troubleshooting") -> dict[str,Any]:
    root=Path(root).resolve(); d0p=(root/d0).resolve() if not Path(d0).is_absolute() else Path(d0); out=(root/output).resolve() if not Path(output).is_absolute() else Path(output); out.mkdir(parents=True,exist_ok=True)
    # Frozen-state gates.
    private_batch=root/"artifacts/evaluation/dataset-expansion-d2/annotation_batch_manifest.json"
    mixed_batch=root/"artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_annotation_batch_manifest_refrozen.json"
    d3r=root/"artifacts/evaluation/dataset-expansion-d3-real-run/phase_d3r_summary.json"
    if not (private_batch.exists() and mixed_batch.exists() and d3r.exists()): raise RuntimeError("F0 requires frozen Private/Mixed/D3-R artifacts")
    private=json.loads(private_batch.read_text()); mixed=json.loads(mixed_batch.read_text()); d3rx=json.loads(d3r.read_text())
    if int(private.get("packet_count",0))!=76 or int(mixed.get("packet_count",0))!=58: raise RuntimeError("frozen packet count drift")
    if d3rx.get("agreement_status") not in {"NOT_RUN",None} and d3rx.get("agreement") not in {"NOT_RUN",None}: raise RuntimeError("unexpected D3-R agreement drift")

    units,unit_report=build_troubleshooting_source_units(root)
    raw=build_candidates(units)
    valid0,reject0=validate_candidates(raw,units)
    valid,reject_collision,collision=_collision_filter(root,valid0)
    rejected=reject0+reject_collision

    # Runtime/observed recovery boundary stays construction-only.
    for c in valid:
        assert not c.recovery_eligibility.observed_first_pass_failure and not c.recovery_eligibility.formal_recovery_eligible
    effective=effective_diversity(valid)
    behavior=behavior_distribution(valid)
    scenario=_scenario_report(valid)
    um={u.source_unit_id:u for u in units}

    # Reports.
    symptom=Counter(c.semantic_family_id for c in valid)
    products=Counter(c.product_id for c in valid if c.product_id); docs=Counter(um[c.source_unit_id].document_id for c in valid)
    step_struct={
        "single_step":sum(len(c.required_steps)==1 for c in valid),"multi_step":sum(len(c.required_steps)>=2 for c in valid),
        "conditional":sum("CONDITIONAL" in c.behavior_labels for c in valid),
        "ordered_source_units":sum(um[c.source_unit_id].step_order=="ORDERED" for c in valid),
        "partially_ordered_source_units":sum(um[c.source_unit_id].step_order=="PARTIALLY_ORDERED" for c in valid),
        "unordered_source_units":sum(um[c.source_unit_id].step_order=="UNORDERED" for c in valid),
        "safety_critical_candidates":sum(bool(c.safety_requirements) for c in valid),
        "terminal_or_handoff_candidates":sum(c.task_type=="ESCALATION_HANDOFF" for c in valid),
    }
    ctx=Counter(x for c in valid for x in c.hidden_required_context)
    clar=[c for c in valid if c.task_type=="CLARIFICATION_REQUIRED"]
    controls=[c for c in valid if c.task_type=="SUFFICIENT_CONTEXT_NO_CLARIFICATION"]
    hand=[c for c in valid if c.task_type=="ESCALATION_HANDOFF"]
    rec=[c for c in valid if c.recovery_eligibility.recovery_eligible]
    rec_trigger=Counter(c.recovery_eligibility.recovery_trigger_type for c in rec)
    rec_action=Counter(a for c in rec for a in c.recovery_eligibility.acceptable_recovery_actions)
    conc=concentration(valid,units)
    qnorm=Counter(_norm(c.candidate_query) for c in valid)
    sourceunit=Counter(c.source_unit_id for c in valid); scenario_c=Counter(c.scenario_family_id for c in valid); sig=Counter(effective_signature(c) for c in valid)
    cross=Counter()
    # Same normalized required action text across products.
    step_action={s.step_id:re.sub(r"\s+","",s.action).lower() for u in units for s in u.diagnostic_steps}
    key_products=defaultdict(set); key_count=Counter()
    for c in valid:
        for sid in c.required_steps:
            a=step_action.get(sid)
            if a: key_products[a].add(c.product_id); key_count[a]+=1
    cross_product=sum(max(0,key_count[a]-1) for a,ps in key_products.items() if len(ps)>1)
    dedup={"exact_query_duplicates":sum(v-1 for v in qnorm.values() if v>1),"normalized_query_duplicates":sum(v-1 for v in qnorm.values() if v>1),
           "same_source_unit_excess":sum(v-1 for v in sourceunit.values() if v>1),"same_scenario_family_excess":sum(v-1 for v in scenario_c.values() if v>1),
           "same_semantic_signature_excess":sum(v-1 for v in sig.values() if v>1),"cross_product_same_semantic_fact_excess":cross_product}

    # Artifacts.
    _write_jsonl(out/"troubleshooting_source_units.jsonl",[u.to_state() for u in units])
    _write_json(out/"troubleshooting_source_unit_report.json",unit_report)
    _write_jsonl(out/"troubleshooting_task_plans.jsonl",[c.to_state() for c in raw])
    _write_jsonl(out/"troubleshooting_raw_candidates.jsonl",[c.to_state() for c in raw])
    _write_jsonl(out/"troubleshooting_source_validated.jsonl",[c.to_state() for c in valid])
    _write_jsonl(out/"troubleshooting_rejected.jsonl",[c.to_state() for c in rejected])
    _write_json(out/"troubleshooting_semantic_families.json",{"symptom_families":dict(sorted(symptom.items())),"task_behavior_taxonomy":behavior})
    _write_json(out/"troubleshooting_scenario_families.json",scenario)
    _write_json(out/"troubleshooting_behavior_distribution.json",behavior)
    _write_json(out/"troubleshooting_product_coverage.json",{"unique_products":len(products),"candidate_counts":dict(products),"products":sorted(products)})
    _write_json(out/"troubleshooting_document_coverage.json",{"unique_documents":len(docs),"candidate_counts":dict(docs),"documents":sorted(docs)})
    _write_json(out/"troubleshooting_step_structure.json",step_struct)
    _write_json(out/"troubleshooting_context_requirements.json",{"hidden_required_context_distribution":dict(ctx),"candidates_with_hidden_required_context":sum(bool(c.hidden_required_context) for c in valid)})
    _write_jsonl(out/"troubleshooting_clarification_candidates.jsonl",[c.to_state() for c in clar])
    _write_jsonl(out/"troubleshooting_false_clarification_controls.jsonl",[c.to_state() for c in controls])
    _write_jsonl(out/"troubleshooting_handoff_candidates.jsonl",[c.to_state() for c in hand])
    _write_jsonl(out/"troubleshooting_recovery_eligibility.jsonl",[{"candidate_id":c.candidate_id,"source_unit_id":c.source_unit_id,"recovery_eligibility_status":"ELIGIBLE" if c.recovery_eligibility.recovery_eligible else "NOT_ELIGIBLE","recovery":c.recovery_eligibility.to_state()} for c in valid])
    _write_json(out/"troubleshooting_recovery_action_matrix.json",recovery_action_matrix())
    _write_json(out/"troubleshooting_source_concentration.json",conc)
    _write_json(out/"troubleshooting_dedup_report.json",dedup)
    _write_json(out/"troubleshooting_existing_collision_report.json",collision)
    _write_json(out/"troubleshooting_effective_diversity.json",effective)

    rejection_reasons=Counter(r for c in rejected for r in c.rejection_reasons)
    manifest={
        "schema_version":"f0-troubleshooting-candidate-1","generation_version":"deterministic-troubleshooting-f0-1",
        "corpus_fingerprint":_sha_obj(sorted((p.relative_to(root).as_posix(),_sha_file(p)) for p in (root/"data/knowledge").rglob("*.md"))),
        "d0_inventory_hash":_sha_obj(sorted((p.name,_sha_file(p)) for p in d0p.iterdir() if p.is_file())),
        "production_capability_fingerprint":_sha_file(d0p/"production_capability_inventory.json"),
        "source_unit_count":len(units),"raw_candidate_count":len(raw),"source_validated_count":len(valid),"rejected_count":len(rejected),
        "effective_semantic_count":effective["effective_semantic_units"],"scenario_family_count":effective["scenario_families"],
        "generation_method":"DETERMINISTIC_SOURCE_UNIT_PLAN + CONTROLLED_LANGUAGE_RENDERER","random_seed":0,
        "candidate_set_hash":_sha_obj([c.to_state() for c in valid]),
        "private_batch_hash":private.get("batch_hash"),"mixed_batch_hash":mixed.get("batch_hash"),"d3r_status":"DEFERRED_BY_ENVIRONMENT",
    }
    _write_json(out/"troubleshooting_candidate_manifest.json",manifest)
    summary={
        "phase":"F0","status":"COMPLETE" if len(valid)>=65 and effective["effective_semantic_units"]>=55 and len(clar)>=12 and len(controls)>=10 and len(hand)>=8 and len([c for c in valid if "RECOVERY_ORIENTED" in c.behavior_labels])>=15 else "PARTIAL",
        "source_units":len(units),"benchmark_usable_source_units":unit_report["benchmark_usable"],"raw_candidates":len(raw),"source_validated":len(valid),"rejected":len(rejected),
        "effective_semantic_units":effective["effective_semantic_units"],"scenario_families":effective["scenario_families"],"procedure_families":effective["procedure_families"],
        "behavior_distribution":behavior,"clarification_required":len(clar),"false_clarification_controls":len(controls),"handoff":len(hand),
        "recovery_eligible":len(rec),"recovery_oriented_behavior":sum("RECOVERY_ORIENTED" in c.behavior_labels for c in valid),"recovery_trigger_distribution":dict(rec_trigger),"recovery_action_distribution":dict(rec_action),
        "unique_products":len(products),"unique_documents":len(docs),"symptom_families":len(symptom),"rejection_reasons":dict(rejection_reasons),
        "observed_production_first_pass_failures":0,"real_recovery_runs":0,"recovered_cases":0,"new_formal_cases":0,"production_agent":"NOT RUN","annotation_runs":0,"d3r":"DEFERRED_BY_ENVIRONMENT",
        "private_frozen_batch_unchanged":True,"mixed_frozen_batch_unchanged":True,"formal_canonical_expected":39,
    }
    _write_json(out/"phase_f0_summary.json",summary)

    # Roadmap only appends current phase status; history remains unchanged.
    road=root/"artifacts/evaluation/benchmark-expansion-roadmap-status.json"
    rx=json.loads(road.read_text(encoding="utf-8")) if road.exists() else {}
    rx["troubleshooting_expansion"]={"status":summary["status"],"phase":"F0","source_validated":len(valid),"effective_semantic_units":effective["effective_semantic_units"],"observed_first_pass_failure":0,"real_recovery_runs":0,"recovered_cases":0}
    _write_json(road,rx)
    return summary
