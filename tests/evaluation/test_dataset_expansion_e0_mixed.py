from __future__ import annotations
import json,re
from pathlib import Path
import pytest
from evals.benchmark.expansion.mixed_planner import generate_mixed_candidates
from evals.benchmark.expansion.mixed_validation import validate_mixed_candidate
from evals.benchmark.expansion.e0_runner import run_mixed_expansion

ROOT=Path(__file__).resolve().parents[2]
D0=ROOT/'artifacts/evaluation/dataset-expansion-d0'

@pytest.fixture(scope='module')
def e0_run(tmp_path_factory):
    out=tmp_path_factory.mktemp('e0')/'artifacts'; summary=run_mixed_expansion(ROOT,D0,out); return out,summary

def _rows(path): return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def test_e0_reproducible_counts_and_completion(e0_run):
    out,s=e0_run; assert s['status']=='COMPLETE'; assert (s['raw_candidates'],s['source_validated'],s['rejected'],s['effective_candidates'])==(68,58,10,48); assert s['validated_families']==5

def test_d3r_deferred_not_complete(e0_run):
    _=e0_run; x=json.loads((ROOT/'artifacts/evaluation/benchmark-expansion-roadmap-status.json').read_text()); d=x['private_dual_annotation']; assert d['status']=='DEFERRED_BY_ENVIRONMENT' and d['actual_a_decisions']==d['actual_b_decisions']==0 and d['agreement']=='NOT_RUN'

def test_mixed_necessity_both_sources_required(e0_run):
    out,_=e0_run; rows=_rows(out/'mixed_source_validated.jsonl'); assert rows and all(r['mixed_necessity']['structured_source_required'] and r['mixed_necessity']['document_source_required'] for r in rows); assert all(any(e.startswith('record:') for e in r['candidate_evidence_refs']) and any(e.startswith('doc:') for e in r['candidate_evidence_refs']) for r in rows)

def test_return_policy_family_fails_closed_on_wrong_temporal_basis(e0_run):
    out,_=e0_run; rows=_rows(out/'mixed_rejected.jsonl'); r=[x for x in rows if x['mixed_family_id']=='MIXED_ORDER_RETURN_POLICY']; assert len(r)==10; assert all('UNSUPPORTED_TEMPORAL_BASIS_DELIVERY_DATE_REQUIRED' in x['rejection_reasons'] and 'TIME_DRIFT_WITHOUT_FROZEN_REFERENCE_DATE' in x['rejection_reasons'] for x in r)

def test_order_cancel_policy_covers_all_real_states(e0_run):
    out,_=e0_run; x=json.loads((out/'mixed_structured_state_coverage.json').read_text())['MIXED_ORDER_STATUS_POLICY']; assert set(x)=={'Processing','Shipped','Delivered','Cancelled'}

def test_warranty_policy_balances_coverage_states(e0_run):
    out,_=e0_run; x=json.loads((out/'mixed_structured_state_coverage.json').read_text())['MIXED_WARRANTY_STATUS_POLICY']; assert x=={'expired':4,'in_warranty':4}

def test_all_20_manual_products_receive_mixed_coverage(e0_run):
    out,_=e0_run; x=json.loads((out/'mixed_document_coverage.json').read_text()); assert x['manual_documents_covered']==20

def test_d0_uncovered_manuals_17_to_20_are_covered(e0_run):
    out,_=e0_run; docs=json.loads((out/'mixed_document_coverage.json').read_text())['document_counts']; assert all(any(k.startswith(f'source:manual:LIO-PROD-{i:03d}_') for k in docs) for i in range(17,21))

def test_no_raw_private_ids_or_product_routing_leak(e0_run):
    out,_=e0_run; rows=_rows(out/'mixed_source_validated.jsonl'); raw=re.compile(r'\b(?:ORD|TCK|WAR|CUST)-')
    products=json.loads((ROOT/'data/structured/products.json').read_text()); names={p['product_id']:p['name'] for p in products}
    assert all(not raw.search(r['candidate_query']) for r in rows)
    routed=[r for r in rows if r['mixed_mode']=='ENTITY_TO_KNOWLEDGE_ROUTING']; assert all(names[r['product_ref']] not in r['candidate_query'] for r in routed)

def test_new_document_refs_use_current_section_identity(e0_run):
    out,_=e0_run; rows=_rows(out/'mixed_source_validated.jsonl'); assert all(':sec:' in s for r in rows for s in r['document_section_refs']); assert all(not re.search(r'-H\d+$',s) for r in rows for s in r['document_section_refs'])

def test_existing_formal_mixed_not_duplicated(e0_run):
    out,_=e0_run; d=json.loads((out/'mixed_dedup_report.json').read_text()); assert d['existing_formal_duplicate_count']==0

def test_policy_concentration_guard_under_warning(e0_run):
    out,_=e0_run; x=json.loads((out/'mixed_policy_fact_concentration.json').read_text()); assert x['concentration_warning'] is False; assert x['max_policy_fact_ratio_over_all_validated'] < .15

def test_entity_concentration_and_tenant_product_diversity(e0_run):
    out,_=e0_run; x=json.loads((out/'mixed_entity_concentration.json').read_text()); assert x['unique_entities']==58 and x['max_per_entity']==1; assert x['unique_products']==20 and x['unique_tenants']==19

def test_candidate_ids_stable(e0_run,tmp_path):
    out1,s1=e0_run; out2=tmp_path/'rerun'; s2=run_mixed_expansion(ROOT,D0,out2); m1=json.loads((out1/'mixed_candidate_manifest.json').read_text()); m2=json.loads((out2/'mixed_candidate_manifest.json').read_text()); assert m1['candidate_set_sha256']==m2['candidate_set_sha256']; assert [x['candidate_id'] for x in _rows(out1/'mixed_source_validated.jsonl')]==[x['candidate_id'] for x in _rows(out2/'mixed_source_validated.jsonl')]

def test_formal_canonical_count_remains_39(e0_run):
    _=e0_run; total=0
    for fn in ('dev_v7_3_canonical_v1.json','validation_v7_3_canonical_v1.json'):
        d=json.loads((ROOT/'evals/benchmark/data/canonical'/fn).read_text()); total+=len(d if isinstance(d,list) else d['samples'])
    assert total==39
