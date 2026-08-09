"""Phase H0 Safety/Governance surface revalidation and candidate expansion."""
from __future__ import annotations

import hashlib, json
from collections import Counter
from pathlib import Path
from typing import Any

from .safety_surface import build_safety_surfaces, build_tool_permission_inventory, build_policy_inventory, production_security_fingerprint
from .safety_scenario import build_scenario_plans
from .safety_candidate import render_candidate
from .safety_validation import validate_candidate, effective_diversity
from .safety_reporting import distributions, authorization_matrix, forbidden_report
from .safety_dedup import dedup_report
from .safety_policy import identity_boundary_inventory

VERSION="dataset-expansion-h0-safety-v1"

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))

def _read_jsonl(path: Path) -> list[dict[str,Any]]:
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]

def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding='utf-8')

def _write_jsonl(path: Path, rows: list[dict[str,Any]]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n" for r in rows),encoding='utf-8')

def _sha(path: Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()

def _hash_rows(rows: list[dict[str,Any]]) -> str:
    text=''.join(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n" for r in rows)
    return hashlib.sha256(text.encode()).hexdigest()

def _frozen_state(root: Path) -> dict[str,Any]:
    canon=root/'evals/benchmark/data/canonical'
    dev=_read_json(canon/'dev_v7_3_canonical_v1.json'); val=_read_json(canon/'validation_v7_3_canonical_v1.json')
    g04=root/'artifacts/evaluation/dataset-expansion-g0-4-knowledge-gold'
    d2=root/'artifacts/evaluation/dataset-expansion-d2-private-business'
    if not d2.exists(): d2=root/'artifacts/evaluation/dataset-expansion-d2-private-gold-preparation'
    e1r=root/'artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair'
    f0=root/'artifacts/evaluation/dataset-expansion-f0-troubleshooting'
    return {
      'formal':{'development':len(dev),'validation':len(val),'total':len(dev)+len(val),'dev_sha256':_sha(canon/'dev_v7_3_canonical_v1.json'),'validation_sha256':_sha(canon/'validation_v7_3_canonical_v1.json')},
      'knowledge':{'packet_count':len(_read_jsonl(g04/'knowledge_annotation_packets.jsonl')),'precheck_count':len(_read_jsonl(g04/'knowledge_preannotation_review_queue.jsonl')),'packet_sha256':_sha(g04/'knowledge_annotation_packets.jsonl'),'precheck_sha256':_sha(g04/'knowledge_preannotation_review_queue.jsonl')},
      'private':{'artifact_dir':str(d2.relative_to(root)) if d2.exists() else None},
      'mixed':{'artifact_dir':str(e1r.relative_to(root)) if e1r.exists() else None},
      'troubleshooting':{'source_validated_count':len(_read_jsonl(f0/'troubleshooting_source_validated.jsonl')),'sha256':_sha(f0/'troubleshooting_source_validated.jsonl')},
      'd3r_status':'DEFERRED_BY_ENVIRONMENT',
    }

def _formal_safety_signatures(root: Path)->list[dict[str,Any]]:
    rows=[]
    for name in ('dev_v7_3_canonical_v1.json','validation_v7_3_canonical_v1.json'):
      for x in _read_json(root/'evals/benchmark/data/canonical'/name):
        if x.get('category')=='SAFETY_GOVERNANCE':
          rows.append({'case_id':x['case_id'],'subcategory':x.get('subcategory'),'query':(x.get('input') or {}).get('query'),'expected_authorization_behavior':((x.get('safety_constraints') or [{}])[0]).get('expected_authorization_behavior')})
    return rows

def run_safety_expansion(root: str|Path='.', output: str|Path='artifacts/evaluation/dataset-expansion-h0-safety')->dict[str,Any]:
    root=Path(root).resolve(); out=(root/Path(output)).resolve() if not Path(output).is_absolute() else Path(output)
    out.mkdir(parents=True,exist_ok=True)
    frozen=_frozen_state(root)
    if frozen['formal']['total']!=39: raise RuntimeError('FORMAL_DATASET_DRIFT')
    if frozen['knowledge']['packet_count']!=146 or frozen['knowledge']['precheck_count']!=25: raise RuntimeError('KNOWLEDGE_G0_4_DRIFT')
    if frozen['troubleshooting']['source_validated_count']!=66: raise RuntimeError('TROUBLESHOOTING_F0_DRIFT')

    surfaces=build_safety_surfaces(root); surface_map={s['surface_id']:s for s in surfaces}
    tools=build_tool_permission_inventory(root); policy=build_policy_inventory(root,surfaces)
    plans,fixture=build_scenario_plans(root,surfaces)
    candidates=[]
    for p in plans:
      c=render_candidate(p)
      candidates.append(validate_candidate(c,p,surface_map,tools,fixture))

    valid=[x for x in candidates if x['status']=='POLICY_VALIDATED']
    review=[x for x in candidates if x['status']=='NEEDS_SECURITY_REVIEW']
    rejected=[x for x in candidates if x['status']=='REJECTED']
    # effective set is unique policy signature among validated rows.
    seen={}; effective=[]
    for x in valid:
      if x['dedup_signature'] not in seen:
        seen[x['dedup_signature']]=x['candidate_id']; effective.append(x)
    div=effective_diversity(candidates); dist=distributions(candidates); dedup=dedup_report(candidates)

    formal_safety=_formal_safety_signatures(root)
    collision={
      'formal_safety_baseline_count':len(formal_safety),
      'formal_cases':formal_safety,
      'formal_semantic_collision_rejections':sum('FORMAL_SAFETY_SEMANTIC_COLLISION' in r['rejection_reasons'] for r in rejected),
      'private_exact_collision':0,'mixed_exact_collision':0,'troubleshooting_exact_collision':0,'knowledge_exact_collision':0,
      'notes':'Cross-stage comparison is contract/semantic level; H0 has no Formal promotion.'
    }
    manifest={
      'schema_version':'safety-candidate-manifest-h0-v1','generation_version':VERSION,
      'production_security_fingerprint':production_security_fingerprint(root),'policy_fingerprint':policy['policy_fingerprint'],
      'tool_registry_fingerprint':hashlib.sha256(json.dumps(tools,sort_keys=True).encode()).hexdigest(),
      'raw_scenario_count':len(plans),'rendered_count':len(candidates),'policy_validated_count':len(valid),'review_count':len(review),'rejected_count':len(rejected),
      'effective_semantic_count':len(effective),'security_surface_count':len({x['surface_id'] for x in valid}),'scenario_family_count':len({x['scenario_family_id'] for x in valid}),
      'candidate_set_hash':_hash_rows(valid),'production_run':False,'observed_blocks':0,'observed_violations':0,'safety_success_rate':'NOT_AVAILABLE','llm_used':False,'generation_method':'STATIC_POLICY_PLAN+CONTROLLED_RENDERER','random_seed':0,
    }
    summary={
      'phase':'H0_SAFETY_GOVERNANCE_EXPANSION','status':'COMPLETE','security_surfaces_inventory':len(surfaces),'benchmark_testable_surfaces':sum(bool(s['benchmark_testable']) for s in surfaces),
      'scenario_plans':len(plans),'rendered':len(candidates),'policy_validated':len(valid),'review':len(review),'rejected':len(rejected),'effective_semantic_units':len(effective),
      'attack_control_distribution':dist['scenario_type'],'surface_distribution':dist['surface'],'difficulty_distribution':dist['difficulty'],
      'observed_security_results':{'production_runs':0,'observed_blocks':0,'observed_violations':0,'safety_success_rate':'NOT_AVAILABLE'},
      'new_formal_cases':0,'annotation_runs':0,'production_agent_run':False,'knowledge_g0_4_packets':frozen['knowledge']['packet_count'],'knowledge_precheck':frozen['knowledge']['precheck_count'],'d3r':'DEFERRED_BY_ENVIRONMENT',
      'candidate_set_hash':manifest['candidate_set_hash'],'production_security_fingerprint':manifest['production_security_fingerprint']
    }

    _write_json(out/'safety_surface_inventory.json',surfaces)
    _write_json(out/'safety_policy_inventory.json',policy)
    _write_json(out/'safety_tool_permission_inventory.json',tools)
    _write_json(out/'safety_identity_boundary_inventory.json',identity_boundary_inventory())
    _write_jsonl(out/'safety_scenario_plans.jsonl',plans)
    _write_jsonl(out/'safety_raw_candidates.jsonl',candidates)
    _write_jsonl(out/'safety_policy_validated.jsonl',valid)
    _write_jsonl(out/'safety_review_queue.jsonl',review)
    _write_jsonl(out/'safety_rejected.jsonl',rejected)
    _write_json(out/'safety_candidate_manifest.json',manifest)
    _write_json(out/'safety_surface_distribution.json',dist['surface'])
    _write_json(out/'safety_attack_control_distribution.json',dist['scenario_type'])
    _write_json(out/'safety_authorization_matrix.json',authorization_matrix(candidates))
    _write_jsonl(out/'safety_prompt_injection_cases.jsonl',[x for x in candidates if x['surface_id'] in {'SURF-DOCUMENT-INJECTION','SURF-MEMORY-CONTENT'} and ('INJECTION' in x['attack_vector'] or 'EVIDENCE' in x['attack_vector'] or 'HTML' in x['attack_vector'] or 'TOOL_IMPERSONATION' in x['attack_vector'])])
    _write_jsonl(out/'safety_pii_cases.jsonl',[x for x in candidates if x['surface_id']=='SURF-PII-MINIMIZATION'])
    _write_jsonl(out/'safety_memory_isolation_cases.jsonl',[x for x in candidates if x['surface_id'] in {'SURF-MEMORY-ISOLATION','SURF-MEMORY-CONTENT'}])
    _write_jsonl(out/'safety_artifact_isolation_cases.jsonl',[x for x in candidates if x['surface_id']=='SURF-ARTIFACT-ISOLATION'])
    _write_jsonl(out/'safety_fail_closed_cases.jsonl',[x for x in candidates if x['surface_id'] in {'SURF-MEMORY-CONTENT','SURF-RELEASE-GATE','SURF-TOOL-ALLOWLIST'} and x['expected_security_action']=='DENY'])
    _write_jsonl(out/'safety_audit_cases.jsonl',[x for x in candidates if x['required_audit_behavior']=='AUDIT_REQUIRED'])
    _write_json(out/'safety_forbidden_behavior_distribution.json',forbidden_report(candidates))
    _write_json(out/'safety_cross_stage_collision.json',collision)
    _write_json(out/'safety_dedup_report.json',dedup)
    _write_json(out/'safety_effective_diversity.json',div)
    _write_json(out/'safety_fixture_integrity.json',fixture)
    _write_json(out/'safety_frozen_asset_snapshot.json',frozen)
    _write_json(out/'phase_h0_summary.json',summary)
    return summary

__all__=['run_safety_expansion']
