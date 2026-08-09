"""Phase G0.4 Knowledge Gold preparation and annotation packet freeze."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib, json, re
from pathlib import Path
from typing import Any, Mapping

from .gold_draft import canonical_hash
from .knowledge_gold import (
    KNOWLEDGE_GOLD_DRAFT_VERSION, GoldFactRole, KnowledgeGoldStatus,
    KnowledgeGoldFact, KnowledgeGoldEvidence, comparison_for, evidence_id,
    gold_signature, looks_heading_only, looks_intro_only, normalize_semantics,
    stable_gold_fact_id, task_success_contract,
)
from .knowledge_gold_alignment import audit_gold
from .knowledge_gold_comparison import comparison_report
from .knowledge_gold_policy import audit_policy_candidate
from .knowledge_gold_annotation_packet import build_source_snapshot, build_annotation_packet, build_batch_manifest

EXPECTED_G03_CANDIDATE_SET_HASH = "c21d9412fc16be1f1b2d56a8e349641c3c1c9f3866e9eee358565890096dd1e5"


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f: return json.load(f)

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f: return [json.loads(x) for x in f if x.strip()]

def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")

def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w",encoding="utf-8",newline="\n") as f:
        for row in rows: f.write(json.dumps(dict(row),ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n")

def _sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def _sha_obj(value: Any) -> str: return canonical_hash(value)


def _authority(fact: Mapping[str, Any]) -> str:
    st=str(fact.get("source_type") or "").lower()
    if "policy" in st: return "policy"
    if "faq" in st: return "faq"
    return "manual"


def _gold_fact(candidate: Mapping[str, Any], fact: Mapping[str, Any], section: Mapping[str, Any], *, role: str, plan: Mapping[str, Any]) -> dict[str, Any]:
    cm, em, value, metadata = comparison_for(
        task_type=str(candidate["primary_task_type"]), answer_scope=str(candidate["answer_scope"]),
        fact_type=str(fact.get("fact_type") or ""), fact_text=str(fact.get("fact_text") or ""),
        relationship=str(fact.get("relationship") or plan.get("fact_relationship") or ""),
    )
    eid=evidence_id(str(fact["document_id"]),str(fact["section_id"]))
    return KnowledgeGoldFact(
        gold_fact_id=stable_gold_fact_id(str(candidate["candidate_id"]),str(fact["fact_id"]),role),
        source_fact_ids=(str(fact["fact_id"]),), description=str(fact["fact_text"]),
        normalized_value_or_semantics=value, fact_role=role,
        critical=role in {GoldFactRole.ANSWER_REQUIRED.value,GoldFactRole.REASONING_REQUIRED.value},
        comparison_mode=cm,evaluator_comparison_mode=em,evidence_ids=(eid,),source_supported=True,
        source_fact_type=str(fact.get("fact_type") or "UNKNOWN"),value_metadata=metadata,
    ).to_state()


def _evidence_rows(gold_facts: list[Mapping[str, Any]], sections: Mapping[str, Mapping[str, Any]], facts: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str,list[str]]=defaultdict(list); required_section=set()
    for gf in gold_facts:
        for sfid in gf["source_fact_ids"]:
            row=facts[sfid]; sid=row["section_id"]; by[sid].append(sfid)
            if gf["fact_role"] in {GoldFactRole.ANSWER_REQUIRED.value,GoldFactRole.REASONING_REQUIRED.value}: required_section.add(sid)
    out=[]
    for sid in sorted(by):
        sec=sections[sid]; f0=facts[by[sid][0]]
        out.append(KnowledgeGoldEvidence(
            evidence_id=evidence_id(sec["document_id"],sid), source_type="DOCUMENT", required=sid in required_section,
            document_id=sec["document_id"],section_id=sid,heading=str(sec.get("heading") or ""),parent_heading=sec.get("parent_heading"),
            source_fact_ids=tuple(sorted(set(by[sid]))),authority=_authority(f0),stable=":sec:" in sid,
        ).to_state())
    return out


def _comparison_contract(gold_facts: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows=[]
    for g in gold_facts:
        if g["fact_role"] in {GoldFactRole.ANSWER_REQUIRED.value,GoldFactRole.REASONING_REQUIRED.value}:
            rows.append({"gold_fact_id":g["gold_fact_id"],"construction_mode":g["comparison_mode"],"evaluator_mode":g["evaluator_comparison_mode"],"critical":g["critical"],"value_metadata":g.get("value_metadata",{})})
    return {"fact_comparisons":rows,"all_required_facts_must_pass":True,"no_unjustified_numeric_tolerance":True}


def _reasoning_contract(candidate: Mapping[str, Any], gold_facts: list[Mapping[str, Any]], plan: Mapping[str, Any]) -> dict[str, Any]:
    answer=[x["gold_fact_id"] for x in gold_facts if x["fact_role"]==GoldFactRole.ANSWER_REQUIRED.value]
    reason=[x["gold_fact_id"] for x in gold_facts if x["fact_role"]==GoldFactRole.REASONING_REQUIRED.value]
    support=[x["gold_fact_id"] for x in gold_facts if x["fact_role"]==GoldFactRole.SUPPORTING_ONLY.value]
    return {
        "reasoning_type":candidate["reasoning_type"],"answer_scope":candidate["answer_scope"],
        "answer_required_gold_fact_ids":answer,"reasoning_required_gold_fact_ids":reason,"supporting_gold_fact_ids":support,
        "required_source_fact_ids":list(plan.get("required_fact_ids") or []),
        "multi_fact":candidate["primary_task_type"]=="MULTI_FACT_SYNTHESIS",
        "multi_section":candidate["primary_task_type"]=="MULTI_SECTION_SYNTHESIS",
        "derived_conclusion_required":False,
        "inference_policy":"SOURCE_FACTS_ONLY_NO_FREEFORM_GOLD_INFERENCE",
    }


def _candidate_draft(candidate: Mapping[str, Any], plan: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]], sections: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any],dict[str,Any]]:
    q=str(candidate["candidate_query"])
    gold=[]; seen=set()
    required_rows=[]
    for fid in plan.get("required_fact_ids") or []:
        fact=facts.get(fid)
        if not fact: continue
        required_rows.append(fact); sec=sections[fact["section_id"]]
        # Heading/intro scaffolding is not a required answer claim even when G0.2 selected it as a planning fact.
        role=GoldFactRole.ANSWER_REQUIRED.value
        if looks_heading_only(str(fact["fact_text"]),str(sec.get("heading") or "")) or looks_intro_only(str(fact["fact_text"])):
            role=GoldFactRole.SUPPORTING_ONLY.value
        g=_gold_fact(candidate,fact,sec,role=role,plan=plan); gold.append(g); seen.add(fid)
    for fid in plan.get("supporting_fact_ids") or []:
        if fid in seen or fid not in facts: continue
        fact=facts[fid]; sec=sections[fact["section_id"]]
        gold.append(_gold_fact(candidate,fact,sec,role=GoldFactRole.SUPPORTING_ONLY.value,plan=plan)); seen.add(fid)
    ev=_evidence_rows(gold,sections,facts)
    sec_rows=[sections[s] for s in candidate.get("section_ids",[]) if s in sections]
    align=audit_gold(candidate,plan,required_rows,sec_rows,gold)
    policy=audit_policy_candidate(candidate,required_rows)
    quality=list(candidate.get("quality_flags") or [])
    review=list(align["issues"])
    # Hard source/evidence failures are rejects; ambiguity/scope problems go to precheck.
    hard=[]
    if len(required_rows)!=len(plan.get("required_fact_ids") or []): hard.append("SOURCE_FACT_MISSING")
    if any(e["required"] and not e["stable"] for e in ev): hard.append("MISSING_STABLE_EVIDENCE")
    if not ev: hard.append("GOLD_EVIDENCE_MISSING")
    if candidate["primary_task_type"]=="MULTI_SECTION_SYNTHESIS" and len([e for e in ev if e["required"]])<2: hard.append("MULTI_SECTION_REQUIRED_EVIDENCE_INCOMPLETE")
    # Fact-level category ownership is a hard boundary.
    if any(str(f.get("category_ownership"))=="TROUBLESHOOTING" for f in required_rows): hard.append("TROUBLESHOOTING_OWNERSHIP_COLLISION")
    if hard:
        status=KnowledgeGoldStatus.REJECTED_BEFORE_ANNOTATION.value
    elif review:
        status=KnowledgeGoldStatus.NEEDS_MANUAL_PRECHECK.value
    else:
        status=KnowledgeGoldStatus.READY_FOR_DUAL_ANNOTATION.value
    draft={
        "candidate_id":candidate["candidate_id"],"task_plan_id":candidate["task_plan_id"],"gold_draft_version":KNOWLEDGE_GOLD_DRAFT_VERSION,
        "candidate_query":q,"query_sha256":candidate["query_sha256"],"primary_task_type":candidate["primary_task_type"],
        "semantic_family_id":candidate["semantic_family_id"],"reasoning_type":candidate["reasoning_type"],"difficulty":candidate["difficulty"],"answer_scope":candidate["answer_scope"],
        "gold_facts":gold,"optional_facts":[],"gold_evidence":ev,"comparison_contract":_comparison_contract(gold),
        "reasoning_contract":_reasoning_contract(candidate,gold,plan),"derived_facts":[],"task_success_contract_draft":task_success_contract(),
        "answerability":"ANSWERABLE" if not hard else "SOURCE_OR_EVIDENCE_INVALID","ambiguity_status":"NONE" if not review else "PRECHECK_REQUIRED",
        "annotation_status":status,"review_requirements":sorted(set(review+hard)),"quality_flags":sorted(set(quality)),"formal_eligible":False,"human_reviewed":False,
        "input_lineage":{"source_unit_ids":candidate["source_unit_ids"],"required_fact_ids":candidate["required_fact_ids"],"required_evidence_ids":candidate["required_evidence_ids"]},
        "alignment_audit":align,"policy_audit":policy,
    }
    draft["gold_information_signature"]=gold_signature(draft)
    return draft, align


def _formal_semantic_sets(root: Path) -> list[dict[str, Any]]:
    out=[]
    for name in ("dev_v7_3_canonical_v1.json","validation_v7_3_canonical_v1.json"):
        p=root/"evals/benchmark/data/canonical"/name
        if not p.exists(): continue
        rows=_read_json(p)
        for r in rows:
            if str(r.get("category"))!="KNOWLEDGE_QA": continue
            vals=sorted(normalize_semantics(str(f.get("normalized_value") or f.get("description") or "")) for f in r.get("gold_facts",[]))
            out.append({"case_id":r.get("case_id"),"query":r.get("input",{}).get("query"),"values":vals})
    return out


def _cross_stage(root: Path, drafts: list[Mapping[str, Any]], facts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    formal=_formal_semantic_sets(root)
    formal_hits=[]
    for d in drafts:
        vals=sorted(normalize_semantics(str(f["normalized_value_or_semantics"])) for f in d["gold_facts"] if f["fact_role"]=="ANSWER_REQUIRED")
        for fr in formal:
            if vals and vals==fr["values"]: formal_hits.append({"candidate_id":d["candidate_id"],"case_id":fr["case_id"],"type":"EXACT_GOLD_FACT_SET"})
    # Frozen Mixed / Troubleshooting use current source fact IDs, so exact overlap is measurable without guessing semantics.
    mixed_ids=set(); mp=root/"artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_gold_drafts_refrozen.jsonl"
    if mp.exists():
        for x in _read_jsonl(mp):
            for f in x.get("document_facts",[]):
                if f.get("source_fact_ref"): mixed_ids.add(f["source_fact_ref"])
    trbl_ids=set(); tp=root/"artifacts/evaluation/dataset-expansion-f0-troubleshooting/troubleshooting_source_validated.jsonl"
    if tp.exists():
        for x in _read_jsonl(tp): trbl_ids.update(x.get("source_fact_ids") or [])
    mixed_overlap=[]; trbl_overlap=[]
    for d in drafts:
        ids={sf for g in d["gold_facts"] if g["fact_role"]=="ANSWER_REQUIRED" for sf in g["source_fact_ids"]}
        if ids & mixed_ids: mixed_overlap.append({"candidate_id":d["candidate_id"],"source_fact_ids":sorted(ids & mixed_ids)})
        if ids & trbl_ids: trbl_overlap.append({"candidate_id":d["candidate_id"],"source_fact_ids":sorted(ids & trbl_ids)})
    return {"formal_exact_gold_fact_set":formal_hits,"mixed_source_fact_overlap":mixed_overlap,"troubleshooting_source_fact_overlap":trbl_overlap,
            "note":"Source-fact overlap is reported separately from task-semantic duplicate; only exact Gold semantics imply a duplicate rejection."}


def run_knowledge_gold_preparation(root: str | Path, g0_3: str | Path, g0_2: str | Path, g0_1: str | Path, output: str | Path) -> dict[str, Any]:
    root=Path(root).resolve(); g03=(root/Path(g0_3)).resolve() if not Path(g0_3).is_absolute() else Path(g0_3); g02=(root/Path(g0_2)).resolve() if not Path(g0_2).is_absolute() else Path(g0_2); g01=(root/Path(g0_1)).resolve() if not Path(g0_1).is_absolute() else Path(g0_1); out=(root/Path(output)).resolve() if not Path(output).is_absolute() else Path(output)
    out.mkdir(parents=True,exist_ok=True)
    candidates=_read_jsonl(g03/"knowledge_source_validated.jsonl"); review=_read_jsonl(g03/"knowledge_query_review_queue.jsonl"); rejected_g03=_read_jsonl(g03/"knowledge_render_rejected.jsonl")
    manifest03=_read_json(g03/"knowledge_candidate_manifest.json")
    if len(candidates)!=171 or len(review)!=8 or len(rejected_g03)!=1: raise ValueError("INPUT_SET_INVALID: expected 171 validated / 8 review / 1 rejected")
    if manifest03.get("candidate_set_hash")!=EXPECTED_G03_CANDIDATE_SET_HASH: raise ValueError("G0.3 CANDIDATE_SET_DRIFT")
    cids={x["candidate_id"] for x in candidates}; rids={x["candidate_id"] for x in review}; xids={x["candidate_id"] for x in rejected_g03}
    if cids&rids or cids&xids: raise ValueError("INPUT_SET_INVALID: validated overlaps review/rejected")
    if any(hashlib.sha256(x["candidate_query"].encode()).hexdigest()!=x["query_sha256"] for x in candidates): raise ValueError("G0.3 QUERY_HASH_DRIFT")
    plans={x["task_plan_id"]:x for x in _read_jsonl(g02/"knowledge_task_plans.jsonl")}; facts={x["fact_id"]:x for x in _read_jsonl(g01/"knowledge_atomic_fact_audit.jsonl")}; sections={x["section_id"]:x for x in _read_jsonl(g01/"knowledge_section_audit.jsonl")}
    if len(plans)!=180: raise ValueError("TASK_PLAN_DRIFT")
    drafts=[]; alignment=[]
    for c in sorted(candidates,key=lambda x:x["candidate_id"]):
        p=plans.get(c["task_plan_id"])
        if not p: raise ValueError(f"missing task plan {c['task_plan_id']}")
        # Immutable G0.2/G0.3 lineage fields.
        for k in ("source_unit_ids","document_ids","section_ids","product_ids","required_fact_ids","required_evidence_ids","primary_task_type","semantic_family_id","reasoning_type","difficulty","answer_scope"):
            if c.get(k)!=p.get(k): raise ValueError(f"candidate/task-plan drift {c['candidate_id']} field={k}")
        d,a=_candidate_draft(c,p,facts,sections);drafts.append(d);alignment.append(a)
    # Gold-level duplicate and cross-stage audits.  Exact Gold duplicates are terminal rejects.
    sig_groups=defaultdict(list)
    for d in drafts: sig_groups[d["gold_information_signature"]].append(d)
    duplicate_groups={k:[x["candidate_id"] for x in v] for k,v in sig_groups.items() if len(v)>1}
    for group in duplicate_groups.values():
        for cid in group[1:]:
            d=next(x for x in drafts if x["candidate_id"]==cid)
            d["annotation_status"]=KnowledgeGoldStatus.REJECTED_BEFORE_ANNOTATION.value
            d["review_requirements"]=sorted(set(d["review_requirements"]+["GOLD_LEVEL_SEMANTIC_DUPLICATE"]))
    cross=_cross_stage(root,drafts,facts)
    formal_collision_ids={x["candidate_id"] for x in cross["formal_exact_gold_fact_set"]}
    for d in drafts:
        if d["candidate_id"] in formal_collision_ids:
            d["annotation_status"]=KnowledgeGoldStatus.REJECTED_BEFORE_ANNOTATION.value
            d["review_requirements"]=sorted(set(d["review_requirements"]+["EXISTING_FORMAL_GOLD_COLLISION"]))
    ready=[d for d in drafts if d["annotation_status"]==KnowledgeGoldStatus.READY_FOR_DUAL_ANNOTATION.value]
    pre=[d for d in drafts if d["annotation_status"]==KnowledgeGoldStatus.NEEDS_MANUAL_PRECHECK.value]
    rej=[d for d in drafts if d["annotation_status"]==KnowledgeGoldStatus.REJECTED_BEFORE_ANNOTATION.value]
    # Source snapshots / packets only for READY.
    cmap={x["candidate_id"]:x for x in candidates}
    snapshots=[]; packets=[]
    for d in ready:
        snap=build_source_snapshot(cmap[d["candidate_id"]],d,sections,facts); snapshots.append(snap); packets.append(build_annotation_packet(cmap[d["candidate_id"]],d,snap))
    gold_set_hash=_sha_obj(sorted(drafts,key=lambda x:x["candidate_id"])); construction_hash=_sha_obj({"input_candidate_set_hash":manifest03["candidate_set_hash"],"gold_draft_version":KNOWLEDGE_GOLD_DRAFT_VERSION,"ready_ids":[x["candidate_id"] for x in ready],"precheck_ids":[x["candidate_id"] for x in pre],"rejected_ids":[x["candidate_id"] for x in rej]})
    batch=build_batch_manifest(packets,candidate_set_hash=manifest03["candidate_set_hash"],gold_set_hash=gold_set_hash,construction_hash=construction_hash)
    # Reports.
    type_report={}
    for t in sorted({x["primary_task_type"] for x in drafts}):
        xs=[x for x in drafts if x["primary_task_type"]==t]
        type_report[t]={"input":len(xs),"ready":sum(x["annotation_status"]==KnowledgeGoldStatus.READY_FOR_DUAL_ANNOTATION.value for x in xs),"precheck":sum(x["annotation_status"]==KnowledgeGoldStatus.NEEDS_MANUAL_PRECHECK.value for x in xs),"rejected":sum(x["annotation_status"]==KnowledgeGoldStatus.REJECTED_BEFORE_ANNOTATION.value for x in xs)}
    role_counts=Counter(g["fact_role"] for d in drafts for g in d["gold_facts"])
    evidence_all=[e for d in drafts for e in d["gold_evidence"]]
    evidence_report={"gold_evidence_rows":len(evidence_all),"unique_evidence_ids":len({e["evidence_id"] for e in evidence_all}),"documents":len({e["document_id"] for e in evidence_all}),"sections":len({e["section_id"] for e in evidence_all}),"whole_document_evidence_violations":sum(not e.get("section_id") for e in evidence_all),"unstable_section_violations":sum(not e.get("stable") for e in evidence_all)}
    align_report={"input":len(alignment),"issues_found":sum(bool(a["issues"]) for a in alignment),"issue_counts":dict(sorted(Counter(i for a in alignment for i in a["issues"]).items())),"resolved_through_role_correction":dict(sorted(Counter(i for a in alignment for i in a["resolved_through_role_correction"]).items())),"fully_aligned":sum(not a["issues"] for a in alignment)}
    completeness={"issues_found":sum(any("INCOMPLETE" in i or "COMPLETENESS_UNCERTAIN" in i for i in a["issues"]) for a in alignment),"remaining_precheck":sum(any("INCOMPLETE" in i or "COMPLETENESS_UNCERTAIN" in i for i in a["issues"]) for a in alignment),"resolved_through_role_correction":sum(bool(a["resolved_through_role_correction"]) for a in alignment)}
    minimality={"issues_found":0,"remaining":0,"role_corrections":sum(bool(a["resolved_through_role_correction"]) for a in alignment)}
    policy_rows=[d["policy_audit"] for d in drafts if d["primary_task_type"]=="POLICY_OR_WARRANTY"]
    policy_report={"input":len(policy_rows),"qualification_preserved":sum(x.get("qualification_preserved",False) for x in policy_rows),"exception_preserved":sum(x.get("exception_preserved",False) for x in policy_rows),"absolute_conversion":sum(x.get("absolute_conversion",0) for x in policy_rows),"region_hallucination":sum(x.get("region_hallucination",0) for x in policy_rows),"effective_time_hallucination":sum(x.get("effective_time_hallucination",0) for x in policy_rows),"ambiguity":sum(bool(x.get("ambiguity")) for x in policy_rows)}
    mf=[d for d in drafts if d["primary_task_type"]=="MULTI_FACT_SYNTHESIS"]
    mf_report={"input":len(mf),"ready":sum(d["annotation_status"]==KnowledgeGoldStatus.READY_FOR_DUAL_ANNOTATION.value for d in mf),"precheck":sum(d["annotation_status"]==KnowledgeGoldStatus.NEEDS_MANUAL_PRECHECK.value for d in mf),"rejected":sum(d["annotation_status"]==KnowledgeGoldStatus.REJECTED_BEFORE_ANNOTATION.value for d in mf),"necessity_failures":sum("MULTI_FACT_ANSWER_SET_TOO_SMALL_AFTER_ROLE_CORRECTION" in d["review_requirements"] for d in mf),"facts_demoted_from_required":sum(any(x in d["alignment_audit"]["resolved_through_role_correction"] for x in ["NON_INFORMATIONAL_REQUIRED_FACT_DEMOTED"]) for d in mf),"facts_promoted_to_required":0,"average_answer_required_facts":round(sum(sum(g["fact_role"]=="ANSWER_REQUIRED" for g in d["gold_facts"]) for d in mf)/max(1,len(mf)),2)}
    ms=[d for d in drafts if d["primary_task_type"]=="MULTI_SECTION_SYNTHESIS"]
    ms_report=[{"candidate_id":d["candidate_id"],"task_plan_id":d["task_plan_id"],"required_sections":[e["section_id"] for e in d["gold_evidence"] if e["required"]],"two_section_necessity":len([e for e in d["gold_evidence"] if e["required"]])>=2,"derived_conclusions":d["derived_facts"],"status":d["annotation_status"],"issues":d["review_requirements"]} for d in ms]
    # Gold effective diversity after terminal filtering; PRECHECK still drafted but effective READY only used for packet capacity.
    ready_sig=Counter(d["gold_information_signature"] for d in ready); effective_ready=len(ready_sig)
    dedup={"drafted":len(drafts),"ready":len(ready),"effective_gold_units":effective_ready,"semantic_duplicate_excess":len(ready)-effective_ready,"duplicate_groups":duplicate_groups,"unique_required_fact_sets":len({tuple(sorted(sf for g in d["gold_facts"] if g["fact_role"]=="ANSWER_REQUIRED" for sf in g["source_fact_ids"])) for d in ready}),"unique_required_evidence_sets":len({tuple(sorted(e["evidence_id"] for e in d["gold_evidence"] if e["required"])) for d in ready})}
    # Coverage and concentrations for READY.
    ready_docs=Counter(e["document_id"] for d in ready for e in d["gold_evidence"] if e["required"]); ready_secs=Counter(e["section_id"] for d in ready for e in d["gold_evidence"] if e["required"]); ready_facts=Counter(sf for d in ready for g in d["gold_facts"] if g["fact_role"]=="ANSWER_REQUIRED" for sf in g["source_fact_ids"]); ready_family=Counter(d["semantic_family_id"] for d in ready)
    concentration={"ready_count":len(ready),"documents":dict(ready_docs),"sections":dict(ready_secs),"facts":dict(ready_facts),"semantic_families":dict(ready_family),"max_document":max(ready_docs.values(),default=0),"max_section":max(ready_secs.values(),default=0),"max_fact":max(ready_facts.values(),default=0),"max_semantic_family":max(ready_family.values(),default=0)}
    # Product/document coverage comes from frozen candidates.
    ready_ids={d["candidate_id"] for d in ready}; ready_candidates=[c for c in candidates if c["candidate_id"] in ready_ids]
    coverage={"g0_3_validated_documents":len({d for c in candidates for d in c["document_ids"]}),"ready_documents":len({d for c in ready_candidates for d in c["document_ids"]}),"g0_3_validated_products":len({p for c in candidates for p in c["product_ids"]}),"ready_products":len({p for c in ready_candidates for p in c["product_ids"]})}
    previous=_read_json(g01/"knowledge_previous_uncovered_source_audit.json")
    prev=[]
    for src in previous:
        pid=src.get("product_id"); name=src["name"]
        if pid:
            xs=[d for d in drafts if pid in cmap[d["candidate_id"]].get("product_ids",[])]
        else:
            xs=[d for d in drafts if any("faq" in doc.lower() for doc in cmap[d["candidate_id"]].get("document_ids",[]))]
        prev.append({"name":name,"input":len(xs),"ready":sum(d["annotation_status"]==KnowledgeGoldStatus.READY_FOR_DUAL_ANNOTATION.value for d in xs),"precheck":sum(d["annotation_status"]==KnowledgeGoldStatus.NEEDS_MANUAL_PRECHECK.value for d in xs),"rejected":sum(d["annotation_status"]==KnowledgeGoldStatus.REJECTED_BEFORE_ANNOTATION.value for d in xs)})
    review_reasons=Counter(r for d in pre for r in d["review_requirements"]); reject_reasons=Counter(r for d in rej for r in d["review_requirements"])
    # Write artifacts.
    _write_jsonl(out/"knowledge_gold_drafts.jsonl",drafts)
    _write_json(out/"knowledge_gold_draft_report.json",{"input":171,"drafted":len(drafts),"ready_for_dual_annotation":len(ready),"needs_manual_precheck":len(pre),"rejected_before_annotation":len(rej),"effective_gold_units":effective_ready,"task_types":type_report})
    _write_json(out/"knowledge_gold_fact_roles.json",{"counts":dict(sorted(role_counts.items())),"total":sum(role_counts.values())})
    _write_json(out/"knowledge_gold_evidence.json",evidence_report);_write_json(out/"knowledge_gold_comparison_contract.json",comparison_report(drafts));_write_json(out/"knowledge_gold_reasoning_contract.json",{"reasoning_types":dict(sorted(Counter(d["reasoning_type"] for d in drafts).items())),"derived_fact_count":sum(len(d["derived_facts"]) for d in drafts)})
    _write_json(out/"knowledge_gold_alignment_report.json",align_report);_write_json(out/"knowledge_gold_completeness_report.json",completeness);_write_json(out/"knowledge_gold_minimality_report.json",minimality);_write_json(out/"knowledge_gold_policy_audit.json",policy_report);_write_json(out/"knowledge_gold_multi_fact_audit.json",mf_report);_write_json(out/"knowledge_gold_multi_section_audit.json",ms_report);_write_json(out/"knowledge_gold_dedup_report.json",dedup);_write_json(out/"knowledge_gold_cross_stage_collision.json",cross);_write_json(out/"knowledge_gold_source_concentration.json",concentration);_write_json(out/"knowledge_gold_ready_distribution.json",{"task_types":type_report,"coverage":coverage,"previously_untested_sources":prev});_write_jsonl(out/"knowledge_preannotation_review_queue.jsonl",pre);_write_jsonl(out/"knowledge_preannotation_rejected.jsonl",rej);_write_jsonl(out/"knowledge_source_snapshots.jsonl",snapshots);_write_jsonl(out/"knowledge_annotation_packets.jsonl",packets);_write_json(out/"knowledge_annotation_packet_report.json",{"packet_count":len(packets),"packet_hash_unique":len({p["packet_sha256"] for p in packets}),"source_snapshot_hash_unique":len({p["source_snapshot"]["snapshot_hash"] for p in packets}),"excluded_information_verified":all("Production Prediction" in p["excluded_information"] and "Agent Trace" in p["excluded_information"] for p in packets)});_write_json(out/"knowledge_annotation_batch_manifest.json",batch)
    summary={"phase":"G0.4","status":"COMPLETE","input_source_validated":171,"query_review_excluded":8,"g0_3_rejected_excluded":1,"drafted":len(drafts),"ready_for_dual_annotation":len(ready),"needs_manual_precheck":len(pre),"rejected_before_annotation":len(rej),"effective_gold_units":effective_ready,"gold_set_hash":gold_set_hash,"annotation_packet_count":len(packets),"annotation_batch_id":batch["batch_id"],"annotation_batch_hash":batch["batch_hash"],"review_reasons":dict(sorted(review_reasons.items())),"rejected_reasons":dict(sorted(reject_reasons.items())),"document_coverage_ready":coverage["ready_documents"],"product_coverage_ready":coverage["ready_products"],"new_formal_cases":0,"annotation_runs":0,"production_agent":"NOT RUN","d3r":"DEFERRED_BY_ENVIRONMENT","candidate_set_hash":manifest03["candidate_set_hash"]}
    _write_json(out/"phase_g0_4_summary.json",summary)
    return summary
