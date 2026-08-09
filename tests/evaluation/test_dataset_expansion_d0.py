from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.benchmark.expansion.coverage_audit import audit_canonical_coverage, semantic_family
from evals.benchmark.expansion.fact_inventory import build_structured_fact_candidates, extract_atomic_facts
from evals.benchmark.expansion.relation_inventory import build_relation_inventory
from evals.benchmark.expansion.runner import run_dataset_expansion_audit
from evals.benchmark.expansion.source_inventory import build_document_source_inventory, build_structured_source_inventory

ROOT = Path(__file__).resolve().parents[2]


def canonical():
    base=ROOT/'evals/benchmark/data/canonical'
    return json.loads((base/'dev_v7_3_canonical_v1.json').read_text(encoding='utf-8')) + json.loads((base/'validation_v7_3_canonical_v1.json').read_text(encoding='utf-8'))


def test_d0_existing_formal_count_reproducible(tmp_path):
    result=run_dataset_expansion_audit(ROOT,tmp_path/'audit')
    assert result['existing_formal_canonical_cases']==39
    assert result['development_cases']==34
    assert result['validation_cases']==5
    assert result['formal_safety_cases']==3
    assert result['new_formal_cases_generated']==0


def test_document_inventory_stable_and_source_linked():
    docs,sections=build_document_source_inventory(ROOT)
    assert len(docs)==22
    assert sum(d['source_type']=='manual' for d in docs)==20
    assert {d['source_type'] for d in docs}=={'manual','policy','faq'}
    section_ids={s['section_id'] for s in sections}
    assert len(section_ids)==len(sections)
    facts=extract_atomic_facts(sections)
    assert facts
    assert all(f.section_id in section_ids for f in facts)
    assert all(f.source_id.startswith('source:') for f in facts)


def test_structured_inventory_uses_real_database_and_tool_exposure():
    inv=build_structured_source_inventory(ROOT)
    counts={r['table']:r['record_count'] for r in inv['tables']}
    assert counts['customers']==300
    assert counts['orders']==1500
    assert counts['tickets']==420
    assert counts['warranty_cases']==140
    templates={x['template_id'] for x in inv['sql_templates']}
    assert {'order_detail','ticket_detail','warranty_cases'} <= templates
    orders=next(r for r in inv['tables'] if r['table']=='orders')
    assert 'status' in orders['fields_exposed_through_production_tool']
    assert 'tracking_number' in orders['fields_not_exposed_through_production_tool']


def test_event_fields_flagged_not_gold_usable_until_stable_event_identity():
    inv=build_structured_source_inventory(ROOT)
    facts=build_structured_fact_candidates(ROOT,inv)
    event=[f for f in facts if f.record_type in {'order_event','ticket_event'}]
    assert event
    assert all(not f.benchmark_usable for f in event)
    normal=[f for f in facts if f.fact_type in {'order.status','ticket.status','warranty.coverage_status'}]
    assert normal and all(f.benchmark_usable for f in normal)


def test_relations_reference_real_sources():
    rows=build_relation_inventory(ROOT)
    ids={r.relation_id for r in rows}
    assert len(ids)==len(rows)
    assert 'rel:order:product' in ids
    assert 'rel:product:manual' in ids
    assert all(r.gold_resolvable for r in rows)


def test_semantic_family_deterministic_and_surface_variation_detected():
    rows=canonical()
    first=[semantic_family(x) for x in rows]
    second=[semantic_family(x) for x in rows]
    assert first==second
    audit=audit_canonical_coverage(rows)
    assert audit['raw_case_count']==39
    assert audit['effective_case_count']==35
    assert audit['surface_variations']==4
    assert audit['semantic_family_count']==5


def test_legacy_gold_references_resolve_without_pretending_identity_equality(tmp_path):
    run_dataset_expansion_audit(ROOT,tmp_path/'audit')
    validation=json.loads((tmp_path/'audit/source_reference_validation.json').read_text(encoding='utf-8'))
    assert validation['all_references_resolvable'] is True
    assert validation['status_distribution']['UNIQUE_HEADING_ALIAS']==40
    assert validation['status_distribution']['RESOLVED']==10
    assert 'not identity equality' in validation['document_alias_policy']


def test_inventory_hash_stable_for_same_repository(tmp_path):
    a=run_dataset_expansion_audit(ROOT,tmp_path/'a')
    b=run_dataset_expansion_audit(ROOT,tmp_path/'b')
    assert a['inventory_hash_sha256']==b['inventory_hash_sha256']


def test_privacy_sensitive_structured_ids_not_written_to_concentration_artifact(tmp_path):
    run_dataset_expansion_audit(ROOT,tmp_path/'audit')
    text=(tmp_path/'audit/source_concentration.json').read_text(encoding='utf-8')
    assert 'TCK-2026-' not in text
    assert 'ORD-2026-' not in text
    assert 'cases_per_structured_record_hashed' in text


def test_unsupported_write_capability_is_flagged(tmp_path):
    run_dataset_expansion_audit(ROOT,tmp_path/'audit')
    caps=json.loads((tmp_path/'audit/production_capability_inventory.json').read_text(encoding='utf-8'))
    write=next(x for x in caps if x['capability_id']=='write_business_operation')
    assert write['formal_benchmark_usable'] is False
    assert write['production_path']=='NOT PRESENT'


def test_d0_does_not_create_benchmark_case_files(tmp_path):
    run_dataset_expansion_audit(ROOT,tmp_path/'audit')
    names={p.name for p in (tmp_path/'audit').iterdir()}
    assert not any('case' in n.lower() and 'diagnostic' not in n.lower() for n in names)
    summary=json.loads((tmp_path/'audit/phase_d0_summary.json').read_text(encoding='utf-8'))
    assert summary['new_formal_cases_generated']==0
