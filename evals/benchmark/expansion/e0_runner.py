"""Phase E0 Mixed candidate construction runner. Never executes Production/Judge/Annotators."""
from __future__ import annotations
import hashlib,json,sqlite3
from collections import Counter
from pathlib import Path
from .mixed_planner import generate_mixed_candidates,GENERATION_VERSION
from .mixed_validation import validate_mixed_candidate
from .mixed_dedup import mixed_dedup_report
from .mixed_reporting import distributions


def _json_hash(x)->str:
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def _file_hash(p:Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()
def _write_json(p:Path,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
def _write_jsonl(p:Path,rows): p.write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in rows),encoding='utf-8')

def _formal_mixed(root:Path):
    bridge_payload=json.loads((root/'artifacts/evaluation/dataset-expansion-d1/legacy_section_alias_map.json').read_text())
    bridge_rows=bridge_payload if isinstance(bridge_payload,list) else bridge_payload.get('mappings') or bridge_payload.get('rows') or []
    bridge={(x.get('document_id'),x.get('legacy_ref') or x.get('legacy_section_id')):x.get('current_section_id') for x in bridge_rows}
    rows=[]
    for fn in ('dev_v7_3_canonical_v1.json','validation_v7_3_canonical_v1.json'):
        data=json.loads((root/'evals/benchmark/data/canonical'/fn).read_text()); arr=data if isinstance(data,list) else data.get('samples') or []
        for c in arr:
            if c.get('category')!='MIXED_KNOWLEDGE_STRUCTURED': continue
            docs=[]; recs=[]; prods=[]
            for e in c.get('gold_evidence',[]):
                if e.get('source_type')=='DOCUMENT': docs.append(bridge.get((e.get('document_id'),e.get('section_id')),e.get('section_id')))
                elif e.get('source_type')=='STRUCTURED_DATA': recs.append(e.get('record_type'))
            for f in c.get('gold_facts',[]):
                val=str(f.get('normalized_value',''))
                if 'LIO-PROD-' in val: prods.append(val)
            rows.append({'case_id':c['case_id'],'subcategory':c.get('subcategory'),'semantic_family':'MIXED_TICKET_MANUAL' if c.get('subcategory')=='TICKET_MANUAL' else c.get('subcategory'),'structured_record_types':sorted(set(recs)),'current_document_sections':sorted(x for x in docs if x),'products':prods,'query':c.get('input',{}).get('query')})
    return rows

def run_mixed_expansion(root:str|Path,d0:str|Path,output:str|Path)->dict:
    root=Path(root).resolve(); d0=(root/Path(d0)).resolve() if not Path(d0).is_absolute() else Path(d0); out=(root/Path(output)).resolve() if not Path(output).is_absolute() else Path(output); out.mkdir(parents=True,exist_ok=True)
    # Freeze deferred D3 status without editing historical D3 artifacts.
    d2=json.loads((root/'artifacts/evaluation/dataset-expansion-d2/phase_d2_summary.json').read_text())
    d3=json.loads((root/'artifacts/evaluation/dataset-expansion-d3/phase_d3_summary.json').read_text())
    d3r=json.loads((root/'artifacts/evaluation/dataset-expansion-d3-real-run/phase_d3r_summary.json').read_text())
    roadmap={'private_dual_annotation':{'status':'DEFERRED_BY_ENVIRONMENT','frozen_packet_count':76,'actual_a_decisions':0,'actual_b_decisions':0,'agreement':'NOT_RUN','resumable':True,'d3_status':d3.get('status'),'d3r_status':d3r.get('status'),'d2_batch_hash':d2.get('batch_hash') or d2.get('annotation_batch_hash')}}
    _write_json(root/'artifacts/evaluation/benchmark-expansion-roadmap-status.json',roadmap)
    existing=_formal_mixed(root); _write_json(out/'existing_mixed_inventory.json',{'count':len(existing),'effective_count':len(existing),'semantic_family_distribution':dict(Counter(x['semantic_family'] for x in existing)),'cases':existing})
    raw=generate_mixed_candidates(root); raw_states=[c.to_state() for c in raw]
    validated=[validate_mixed_candidate(root,c) for c in raw]
    kept=[c for c in validated if c.status.value=='SOURCE_VALIDATED']; rejected=[c for c in validated if c.status.value=='REJECTED']
    dedup=mixed_dedup_report(kept,existing)
    # Existing-formal section collisions are hard rejected if any slipped through.
    if dedup['existing_formal_duplicate_count']:
        bad={x['candidate_id'] for x in dedup['existing_formal_collisions']}
        for c in kept[:]:
            if c.candidate_id in bad:
                c.status=type(c.status).REJECTED; c.rejection_reasons.append('EXISTING_FORMAL_DUPLICATE'); kept.remove(c); rejected.append(c)
    kept_states=[c.to_state() for c in kept]; rej_states=[c.to_state() for c in rejected]
    _write_jsonl(out/'mixed_raw_candidates.jsonl',raw_states); _write_jsonl(out/'mixed_source_validated.jsonl',kept_states); _write_jsonl(out/'mixed_rejected.jsonl',rej_states)
    dist=distributions(kept); rawdist=distributions(validated); rejdist=distributions(rejected)
    _write_json(out/'mixed_family_distribution.json',{'raw':rawdist['family'],'validated':dist['family'],'rejected':rejdist['family'],'existing_formal':dict(Counter(x['semantic_family'] for x in existing))})
    _write_json(out/'mixed_relation_coverage.json',{'families':sorted(set(x.mixed_family_id for x in kept)),'count':len(set(x.mixed_family_id for x in kept)),'required_relation_paths':dict(Counter(x.relation_path for x in kept))})
    _write_json(out/'mixed_source_necessity_report.json',{'both_sources_required':len(kept),'pseudo_mixed_rejected':sum(1 for x in rejected if any(r in {'STRUCTURED_SOURCE_UNNECESSARY','DOCUMENT_SOURCE_UNNECESSARY'} for r in x.rejection_reasons)),'all_retained_remove_either_source_incomplete':all(not x.mixed_necessity.without_structured_complete and not x.mixed_necessity.without_document_complete for x in kept)})
    _write_json(out/'mixed_structured_state_coverage.json',dist['states'])
    _write_json(out/'mixed_document_coverage.json',{'documents_covered':len(dist['documents']),'document_counts':dist['documents'],'manual_documents_covered':len([k for k in dist['documents'] if k.startswith('source:manual:')]),'policy_documents_covered':len([k for k in dist['documents'] if k.startswith('source:policy:')])})
    policy=[x for x in kept if x.document_source_id.startswith('source:policy:')]; pc=distributions(policy)
    max_fact=max(pc['facts'].values(),default=0); max_sec=max(pc['sections'].values(),default=0)
    _write_json(out/'mixed_policy_fact_concentration.json',{'policy_candidate_count':len(policy),'max_cases_per_policy_fact':max_fact,'max_cases_per_policy_section':max_sec,'max_policy_fact_ratio_over_all_validated':(max_fact/len(kept) if kept else None),'concentration_warning':bool(kept and max_fact/len(kept)>.15),'fact_counts':pc['facts'],'section_counts':pc['sections']})
    _write_json(out/'mixed_entity_concentration.json',{'unique_entities':len(dist['entities']),'unique_customers':len(dist['customers']),'unique_products':len(dist['products']),'unique_tenants':len(dist['tenants']),'max_per_entity':max(dist['entities'].values(),default=0),'max_per_customer':max(dist['customers'].values(),default=0),'max_per_product':max(dist['products'].values(),default=0),'max_per_tenant':max(dist['tenants'].values(),default=0),'product_counts':dist['products'],'tenant_counts':dist['tenants']})
    _write_json(out/'mixed_dedup_report.json',dedup)
    signatures=len({c.dedup_signature for c in kept}); combos=len({(c.structured_entity_ref,tuple(c.document_fact_refs)) for c in kept})
    _write_json(out/'mixed_effective_diversity.json',{'raw_candidates':len(raw),'source_validated':len(kept),'effective_semantic_signatures':signatures,'unique_source_combinations':combos,'family_count':len(set(c.mixed_family_id for c in kept))})
    outcomes=Counter((c.derived_fact_draft or {}).get('result','NONE') for c in kept)
    _write_json(out/'mixed_derived_outcome_report.json',dict(outcomes))
    db=root/'data/structured/liorin.db'; corpus_files=sorted((root/'data/knowledge').rglob('*.md')); corpus_fp=hashlib.sha256(''.join(f'{p.relative_to(root)}:{_file_hash(p)}\n' for p in corpus_files).encode()).hexdigest()
    formal_hash=_json_hash(existing); d0_hash=json.loads((d0/'phase_d0_summary.json').read_text()).get('inventory_hash_sha256')
    candidate_set_hash=_json_hash(kept_states)
    manifest={'schema_version':'mixed-candidate-manifest-1.0','generation_version':GENERATION_VERSION,'d0_inventory_hash':d0_hash,'db_sha256':_file_hash(db),'knowledge_corpus_fingerprint':corpus_fp,'tool_registry_sha256':_file_hash(root/'tools/database.py'),'existing_formal_mixed_hash':formal_hash,'candidate_set_sha256':candidate_set_hash,'raw_count':len(raw),'validated_count':len(kept),'rejected_count':len(rejected),'effective_count':signatures,'family_count':len(set(c.mixed_family_id for c in kept)),'generation_method':'DETERMINISTIC_SOURCE_PLAN','random_seed':None,'production_agent_run':False,'annotator_run':False}
    _write_json(out/'mixed_candidate_manifest.json',manifest)
    summary={'phase':'E0','status':'COMPLETE' if signatures>=48 and len(set(c.mixed_family_id for c in kept))>=5 and dedup['existing_formal_duplicate_count']==0 else 'PARTIAL','d3r_deferred_status':'DEFERRED_BY_ENVIRONMENT','agreement':'NOT_RUN','existing_formal_mixed':len(existing),'existing_formal_families':len(set(x['semantic_family'] for x in existing)),'raw_candidates':len(raw),'source_validated':len(kept),'rejected':len(rejected),'effective_candidates':signatures,'validated_families':len(set(c.mixed_family_id for c in kept)),'new_formal_cases':0,'annotation_runs':0,'production_agent_run':False,'rejection_reasons':dict(Counter(r for c in rejected for r in c.rejection_reasons)),'manifest_sha256':_json_hash(manifest)}
    _write_json(out/'phase_e0_summary.json',summary)
    return summary
