"""Phase D0 source/fact/relation/coverage audit runner."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .capacity_estimator import candidate_pool_recommendation, estimate_capacity
from .coverage_audit import audit_canonical_coverage, build_existing_dataset_inventory, semantic_family
from .fact_inventory import build_structured_fact_candidates, extract_atomic_facts, troubleshooting_space
from .relation_inventory import build_mixed_combination_inventory, build_relation_inventory
from .source_inventory import build_document_source_inventory, build_structured_source_inventory

ARTIFACT_VERSION="dataset-expansion-d0-v1"


def _canonical_samples(root: Path) -> list[dict[str, Any]]:
    base=root/'evals/benchmark/data/canonical'
    return json.loads((base/'dev_v7_3_canonical_v1.json').read_text(encoding='utf-8')) + json.loads((base/'validation_v7_3_canonical_v1.json').read_text(encoding='utf-8'))


def _safety_surfaces(root: Path) -> list[dict[str, Any]]:
    # Each entry maps to an actual enforcement or trace surface in the current repository.
    specs=[
        ("TENANT_ISOLATION","structured/retrieval/memory/artifact","IdentityContext tenant boundary","governance + retrieval ACL + structured tool + memory/artifact policy"),
        ("USER_ISOLATION","structured/memory/artifact","verified customer / user boundary","structured owner check + memory/artifact policy"),
        ("SESSION_ISOLATION","working_memory","session-scoped working memory","context/memory identity"),
        ("IDENTITY_CONFLICT","request identity","IdentityResolver conflict rejection","identity/resolver.py"),
        ("UNAUTHORIZED_STRUCTURED_QUERY","structured_database","structured:read:self + owner/tenant","tools/database.py"),
        ("MEMORY_CROSS_USER","memory","memory identity policy","memory governance"),
        ("MEMORY_CROSS_TENANT","memory","memory tenant policy","memory governance"),
        ("ARTIFACT_CROSS_USER","artifact","artifact resolver identity","artifact/resolver.py"),
        ("ARTIFACT_CROSS_TENANT","artifact","artifact tenant identity","artifact/resolver.py"),
        ("PROMPT_INJECTION_USER","model/tool/retrieval","governance/safety evaluator + tool auth","governance/retrieval security"),
        ("PROMPT_INJECTION_RETRIEVED_CONTENT","retrieved_document","retrieval security scanner","retrieval/security.py"),
        ("SENSITIVE_DATA","PII/private records","redaction + principal-bound access","retrieval/security.py + tools/database.py"),
    ]
    return [{"attack_surface_id":a,"resource_type":r,"actor_boundary":b,"policy_source":p,"production_enforcement_point":p,"trace_observability":"AVAILABLE_OR_PARTIAL","candidate_positive_case":True,"candidate_negative_case":True,"formal_gold_possible":True} for a,r,b,p in specs]


def _capabilities(root: Path, structured: dict[str,Any]) -> list[dict[str,Any]]:
    templates=[x['template_id'] for x in structured['sql_templates']]
    return [
        {"capability_id":"knowledge_document_qa","production_path":"supervisor -> knowledge_agent -> hybrid_retrieve","agent":"knowledge_agent","tool":None,"input_requirements":["query"],"identity_requirements":[],"output_type":"grounded answer","trace_availability":"AVAILABLE","formal_benchmark_usable":True},
        {"capability_id":"troubleshooting","production_path":"supervisor -> knowledge_agent -> retrieve/verify/recover","agent":"knowledge_agent","tool":None,"input_requirements":["symptom/query","product context when ambiguity requires"],"identity_requirements":[],"output_type":"answer/clarification/handoff","trace_availability":"AVAILABLE","formal_benchmark_usable":True},
        {"capability_id":"private_structured_read","production_path":"support_workflow identity -> supervisor -> order_agent -> execute_sql_template","agent":"order_agent","tool":"execute_sql_template","input_requirements":["verified customer","allow-listed template"],"identity_requirements":["tenant_id","customer_id","structured:read:self"],"output_type":"structured read-only result","trace_availability":"AVAILABLE contract / agent smoke blocked by dependency","formal_benchmark_usable":True,"templates":templates},
        {"capability_id":"mixed_structured_knowledge","production_path":"supervisor -> order_agent + knowledge_agent","agent":"supervisor","tool":"specialist agents","input_requirements":["private structured fact","document/policy fact"],"identity_requirements":["verified identity when private data required"],"output_type":"synthesized grounded answer","trace_availability":"PARTIAL until real Production smoke","formal_benchmark_usable":True},
        {"capability_id":"write_business_operation","production_path":"NOT PRESENT","agent":None,"tool":None,"input_requirements":[],"identity_requirements":[],"output_type":None,"trace_availability":"NOT_APPLICABLE","formal_benchmark_usable":False,"reason":"Current structured business tool is read-only; no refund/cancel/ticket-create side effect is exposed."},
    ]


def _structured_cardinality(root: Path) -> dict[str,Any]:
    db=root/'data/structured/liorin.db'
    with sqlite3.connect(db) as conn:
        result={}
        for table in ['customers','products','orders','order_items','order_status_events','tickets','ticket_events','warranty_cases']:
            result[table]=int(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
        result['order_status_distribution']=dict(conn.execute('SELECT status,COUNT(*) FROM orders GROUP BY status').fetchall())
        result['ticket_status_distribution']=dict(conn.execute('SELECT status,COUNT(*) FROM tickets GROUP BY status').fetchall())
        result['warranty_coverage_distribution']=dict(conn.execute('SELECT coverage_status,COUNT(*) FROM warranty_cases GROUP BY coverage_status').fetchall())
        result['customer_tenant_count']=int(conn.execute('SELECT COUNT(DISTINCT tenant_id) FROM customers').fetchone()[0])
        result['customer_count']=result['customers']; result['product_count']=result['products']
        result['orders_with_multiple_products']=int(conn.execute('SELECT COUNT(*) FROM (SELECT order_id FROM order_items GROUP BY order_id HAVING COUNT(DISTINCT product_id)>1)').fetchone()[0])
        result['tickets_without_order']=int(conn.execute('SELECT COUNT(*) FROM tickets WHERE order_id IS NULL').fetchone()[0])
    return result


def _source_concentration(samples: list[dict[str,Any]]) -> dict[str,Any]:
    docs=Counter(); evid=Counter(); facts=Counter(); records=Counter()
    private_id=re.compile(r"(?:ORD|TCK|CUST|WAR)-\d{4}-\d+|CUST-\d+", re.I)
    def privacy_safe(value: str) -> str:
        text=str(value)
        return f"private-ref:{hashlib.sha256(text.encode()).hexdigest()[:16]}" if private_id.search(text) else text
    for s in samples:
        for e in s.get('gold_evidence') or []:
            if e.get('document_id'): docs[str(e['document_id'])]+=1
            if e.get('evidence_id'): evid[privacy_safe(str(e['evidence_id']))]+=1
            if e.get('record_type') and e.get('record_id'): records[f"{e['record_type']}:{hashlib.sha256(str(e['record_id']).encode()).hexdigest()[:12]}"]+=1
        for f in s.get('gold_facts') or []:
            if f.get('fact_id'): facts[privacy_safe(str(f['fact_id']))]+=1
    return {"cases_per_document":dict(docs.most_common()),"cases_per_evidence_or_section":dict(evid.most_common()),"cases_per_fact":dict(facts.most_common()),"cases_per_structured_record_hashed":dict(records.most_common())}


def _coverage_matrix(samples: list[dict[str,Any]], capacities: list[Any]) -> list[dict[str,Any]]:
    by_cat=defaultdict(list)
    for s in samples: by_cat[s['category']].append(s)
    cap={c.category:c for c in capacities}
    rows=[]
    for category in ['KNOWLEDGE_QA','TROUBLESHOOTING','PRIVATE_BUSINESS_QUERY','MIXED_KNOWLEDGE_STRUCTURED','SAFETY_GOVERNANCE']:
        group=by_cat.get(category,[])
        eff=len({(semantic_family(s), tuple(sorted(e.get('evidence_id','') for e in s.get('gold_evidence') or [])), tuple(sorted(f.get('fact_id','') for f in s.get('gold_facts') or []))) for s in group})
        c=cap[category]
        rows.append({"category":category,"existing":len(group),"effective":eff,"semantic_families":len({semantic_family(s) for s in group}),"capacity_recommended":c.recommended,"capacity_upper":c.upper_reasonable_bound,"gap_to_recommended":max(0,c.recommended-eff)})
    return rows


def _validate_source_references(root: Path, samples: list[dict[str,Any]], documents, sections) -> dict[str,Any]:
    import sqlite3
    from collections import defaultdict, Counter
    bydoc=defaultdict(list)
    for section in sections: bydoc[str(section['document_id']).removesuffix('.md')].append(section)
    statuses=Counter(); rows=[]
    db=root/'data/structured/liorin.db'
    conn=sqlite3.connect(db)
    table_map={'ticket':('tickets','ticket_id'),'order':('orders','order_id'),'warranty':('warranty_cases','case_id'),'customer':('customers','customer_id')}
    try:
        for sample in samples:
            for e in sample.get('gold_evidence') or []:
                if e.get('source_type')=='DOCUMENT':
                    doc=str(e.get('document_id') or '').removesuffix('.md'); section_id=str(e.get('section_id') or '')
                    heading=str((e.get('metadata') or {}).get('legacy_heading') or '').strip()
                    exact=[s for s in bydoc.get(doc,[]) if s['section_id']==section_id]
                    hmatch=[s for s in bydoc.get(doc,[]) if heading and str(s['title']).strip()==heading]
                    if exact:
                        status='CURRENT_EXACT'; target=exact[0]['section_id']
                    elif len(hmatch)==1:
                        status='UNIQUE_HEADING_ALIAS'; target=hmatch[0]['section_id']
                    elif len(hmatch)>1:
                        status='AMBIGUOUS_HEADING_ALIAS'; target=None
                    else:
                        status='UNRESOLVED'; target=None
                    statuses[status]+=1
                    rows.append({'case_id':sample['case_id'],'source_type':'DOCUMENT','legacy_document_id':e.get('document_id'),'legacy_section_id':e.get('section_id'),'legacy_heading':heading or None,'status':status,'current_section_id':target})
                elif e.get('source_type')=='STRUCTURED_DATA':
                    rt=str(e.get('record_type') or ''); rid=e.get('record_id'); spec=table_map.get(rt)
                    exists=False
                    if spec and rid:
                        exists=conn.execute(f'SELECT 1 FROM {spec[0]} WHERE {spec[1]}=? LIMIT 1',(rid,)).fetchone() is not None
                    status='RESOLVED' if exists else 'MISSING_RECORD'
                    statuses[status]+=1
                    rows.append({'case_id':sample['case_id'],'source_type':'STRUCTURED_DATA','record_type':rt,'record_ref_hash':hashlib.sha256(str(rid).encode()).hexdigest()[:16] if rid else None,'status':status})
    finally:
        conn.close()
    return {'status_distribution':dict(statuses),'all_references_resolvable':not any(k in statuses for k in ('UNRESOLVED','AMBIGUOUS_HEADING_ALIAS','MISSING_RECORD')),'document_alias_policy':'Legacy Hxxx section ids are not current runtime ids; UNIQUE_HEADING_ALIAS is an explicit deterministic migration bridge, not identity equality.','references':rows}

def _blind_spots(document_inventory, structured_inventory, atomic_facts, structured_facts, relations, mixed, samples, safety):
    tested_docs={str(e.get('document_id')).removesuffix('.md') for s in samples for e in s.get('gold_evidence') or [] if e.get('document_id')}
    all_docs={str(d['document_id']).removesuffix('.md') for d in document_inventory}
    tested_struct_fields={f"{e.get('record_type')}.{e.get('field_path')}" for s in samples for e in s.get('gold_evidence') or [] if e.get('record_type') and e.get('field_path')}
    available_fields={f.fact_type for f in structured_facts if f.benchmark_usable}
    tested_safety={s.get('subcategory') for s in samples if s.get('category')=='SAFETY_GOVERNANCE'}
    return [
        {"priority":"P0","gap":"PRIVATE_BUSINESS_QUERY_FORMAL_COVERAGE","detail":"No fully migrated PRIVATE_BUSINESS_QUERY cases despite production-readable structured facts."},
        {"priority":"P0","gap":"TROUBLESHOOTING_DEPTH","detail":"Existing formal troubleshooting coverage is tiny relative to source-linked troubleshooting sections/facts."},
        {"priority":"P0","gap":"MIXED_RELATION_DIVERSITY","detail":f"Existing mixed cases are concentrated in one legacy family while {len(mixed)} production-supported mixed families are source-grounded."},
        {"priority":"P0","gap":"SAFETY_ATTACK_SURFACE_DIVERSITY","detail":f"Formal safety cases cover {len(tested_safety)} subcategory labels versus {len(safety)} audited real attack surfaces."},
        {"priority":"P1","gap":"LEGACY_SECTION_IDENTITY_MIGRATION","detail":"Formal canonical document Gold uses legacy Hxxx section ids; current corpus uses hashed section ids. D0 validates a unique-heading bridge, but D1 should materialize an explicit migration map before new formal case generation."},
        {"priority":"P1","gap":"STRUCTURED_EVENT_IDENTITY_GAP","detail":"order_events/ticket_events templates omit event_id from output, so event-level field facts do not yet have unique stable Production evidence identity and are excluded from normal structured Gold capacity."},
        {"priority":"P1","gap":"REGION_EFFECTIVE_TIME_SOURCE_GAP","detail":"Current checked-in knowledge documents do not carry explicit region/effective_from/effective_to metadata; region- or time-specific policy cases cannot be expanded as formal Gold without additional governed source metadata."},
        {"priority":"P1","gap":"UNTESTED_DOCUMENTS","detail":f"{len(all_docs-tested_docs)} of {len(all_docs)} checked-in knowledge documents have no formal canonical evidence reference.","examples":sorted(all_docs-tested_docs)[:12]},
        {"priority":"P1","gap":"UNTESTED_STRUCTURED_FIELDS","detail":f"{len(available_fields-tested_struct_fields)} production-readable structured fact types have no formal field-level coverage.","examples":sorted(available_fields-tested_struct_fields)[:20]},
        {"priority":"P1","gap":"CLARIFICATION_AND_HANDOFF","detail":"Current formal canonical set contains little/no reviewed clarification/handoff behavior relative to real ambiguity/escalation space."},
        {"priority":"P2","gap":"MULTI_TURN_REVIEW_DEBT","detail":"Phase 4 has candidate multi-turn sessions but zero formal eligible sessions; D0 does not review them."},
    ]


def _evidence_complexity(samples: list[dict[str,Any]]) -> dict[str,Any]:
    counts=Counter(); source=Counter(); alt=0
    for s in samples:
        required=[e for e in s.get('gold_evidence') or [] if e.get('required',True)]
        n=len(required)
        counts['0' if n==0 else '1' if n==1 else '2' if n==2 else '3+']+=1
        st={e.get('source_type') for e in required}
        if st=={'DOCUMENT'}: source['document_only']+=1
        elif st=={'STRUCTURED_DATA'}: source['structured_only']+=1
        elif 'DOCUMENT' in st and 'STRUCTURED_DATA' in st: source['document_plus_structured']+=1
        elif st: source['other_or_tool']+=1
        if any(e.get('alternative_group') for e in required): alt+=1
    return {'required_evidence_count_distribution':dict(counts),'source_mix_distribution':dict(source),'cases_with_alternative_evidence_group':alt}


def _reasoning_complexity(samples: list[dict[str,Any]]) -> dict[str,int]:
    out=Counter()
    for s in samples:
        cat=s.get('category'); q=str((s.get('input') or {}).get('query') or '')
        ev=s.get('gold_evidence') or []; behavior=s.get('expected_behavior') or {}
        if behavior.get('clarification_required'): out['clarification']+=1
        elif cat=='MIXED_KNOWLEDGE_STRUCTURED': out['multi_source_synthesis']+=1
        elif cat=='PRIVATE_BUSINESS_QUERY': out['ownership_decision_or_structured_lookup']+=1
        elif cat=='TROUBLESHOOTING': out['conditional_troubleshooting']+=1
        elif any(k in q for k in ('还在','超过','之前','之后','到期','有效期')): out['temporal_comparison']+=1
        elif any(k in q for k in ('政策','适用','能退','保修','质保')): out['policy_applicability']+=1
        elif len(s.get('gold_facts') or [])>1: out['multi_fact_lookup']+=1
        else: out['direct_lookup']+=1
    return dict(out)


def _response_behavior_space(samples: list[dict[str,Any]]) -> dict[str,Any]:
    existing=Counter((s.get('expected_behavior') or {}).get('response_type') for s in samples)
    return {
        'existing_formal_distribution':dict(existing),
        'production_supported':[
            {'response_type':'ANSWER','basis':'normal knowledge/structured/mixed completion'},
            {'response_type':'CLARIFICATION','basis':'query understanding / missing identity or ambiguous product context'},
            {'response_type':'HANDOFF','basis':'verifier/evidence insufficiency, conflict, or high-risk manual escalation'},
            {'response_type':'REFUSAL','basis':'authorization/governance fail-closed behavior'},
            {'response_type':'ERROR','basis':'execution failure semantics; not a desired normal answer'},
        ],
        'formal_clarification_count':sum(bool((s.get('expected_behavior') or {}).get('clarification_required')) for s in samples),
        'formal_handoff_count':sum(bool((s.get('expected_behavior') or {}).get('handoff_required')) for s in samples),
    }


def _semantic_family_space(facts, structured_facts, mixed, safety, coverage):
    existing=Counter(coverage['semantic_family_distribution'])
    available=[]
    def add(fid,category,basis): available.append({'semantic_family_id':fid,'category':category,'basis':basis,'existing_formal_cases':existing.get(fid,0)})
    types={f.fact_type for f in facts if f.benchmark_usable}; st={f.fact_type for f in structured_facts if f.benchmark_usable}
    if 'PRODUCT_SPEC' in types: add('PRODUCT_SPEC_LOOKUP','KNOWLEDGE_QA','source-linked product specification facts')
    if 'FEATURE_OR_INSTRUCTION' in types: add('PRODUCT_FEATURE_OR_USAGE','KNOWLEDGE_QA','manual feature/usage fact space')
    if 'SAFETY_INSTRUCTION' in types: add('PRODUCT_SAFETY_INSTRUCTION','KNOWLEDGE_QA','manual safety instruction fact space')
    if 'RETURN_POLICY' in types: add('RETURN_POLICY_DIRECT','KNOWLEDGE_QA','checked-in after-sales/FAQ return facts')
    if 'WARRANTY_POLICY' in types or 'POLICY' in types: add('WARRANTY_POLICY_DIRECT','KNOWLEDGE_QA','checked-in policy facts')
    if 'TROUBLESHOOTING_STEP' in types: add('TROUBLESHOOT_DIRECT','TROUBLESHOOTING','source-linked troubleshooting facts')
    if 'TROUBLESHOOTING_STEP' in types: add('TROUBLESHOOT_MISSING_CONTEXT','TROUBLESHOOTING','manual troubleshooting where product/model/context is required')
    for sf,fid in [('order.status','ORDER_STATUS_SELF'),('order.order_date','ORDER_PURCHASE_DATE_SELF'),('order.product_id','ORDER_PRODUCT_SELF'),('ticket.status','TICKET_STATUS_SELF'),('warranty.coverage_status','WARRANTY_STATUS_SELF')]:
        if sf in st: add(fid,'PRIVATE_BUSINESS_QUERY',f'production-exposed structured fact {sf}')
    for m in mixed: add(m['mixed_family_id'].upper().replace(':','_').replace('-','_'),'MIXED_KNOWLEDGE_STRUCTURED',m['mixed_family_id'])
    for surf in safety: add('SAFETY_'+surf['attack_surface_id'],'SAFETY_GOVERNANCE',surf['policy_source'])
    return {'existing_semantic_families':dict(existing),'available_source_grounded_families':available,'available_family_count':len(available)}


def _future_split_risks() -> dict[str,Any]:
    return {
        'risks':[
            {'risk':'same source section across splits','severity':'HIGH','reason':'paraphrases of one fact can leak exact evidence semantics'},
            {'risk':'same semantic family + same GoldFact/evidence group across splits','severity':'HIGH','reason':'surface variation is not independent task diversity'},
            {'risk':'same customer/order/ticket/warranty family across splits','severity':'HIGH','reason':'structured entity memorization/leakage'},
            {'risk':'random split by case while same product/manual dominates','severity':'MEDIUM','reason':'overstates product-domain generalization'},
            {'risk':'same policy section across validation/trusted test','severity':'HIGH','reason':'policy applicability variants can share identical Gold'},
        ],
        'recommended_group_split_keys':['document_family','stable section/evidence group','semantic_family_id','product/model family','customer/entity group','policy family'],
        'action':'Do not execute split in Phase D0; use these grouping keys when candidate pool exists.'
    }

def run_dataset_expansion_audit(root: str|Path, output_dir: str|Path) -> dict[str,Any]:
    root=Path(root).resolve(); output=Path(output_dir); output.mkdir(parents=True,exist_ok=True)
    datasets=build_existing_dataset_inventory(root)
    documents, sections=build_document_source_inventory(root)
    structured=build_structured_source_inventory(root)
    facts=extract_atomic_facts(sections)
    structured_facts=build_structured_fact_candidates(root,structured)
    troubleshooting=troubleshooting_space(facts,sections)
    relations=build_relation_inventory(root)
    mixed=build_mixed_combination_inventory(root,facts,structured_facts)
    safety=_safety_surfaces(root)
    capabilities=_capabilities(root,structured)
    samples=_canonical_samples(root)
    coverage=audit_canonical_coverage(samples)
    estimates=estimate_capacity(facts=facts,troubleshooting=troubleshooting,structured_facts=structured_facts,mixed=mixed,safety_surfaces=safety,current_coverage=coverage)
    candidate_plan=candidate_pool_recommendation(estimates)
    rec=candidate_plan['formal_target_recommended']
    candidate_plan['recommended_formal_range']=[round(rec*0.88), round(rec*1.12)]
    matrix=_coverage_matrix(samples,estimates)
    blind=_blind_spots(documents,structured,facts,structured_facts,relations,mixed,samples,safety)
    source_concentration=_source_concentration(samples)
    structured_cardinality=_structured_cardinality(root)
    evidence_complexity=_evidence_complexity(samples)
    reasoning_complexity=_reasoning_complexity(samples)
    response_space=_response_behavior_space(samples)
    semantic_space=_semantic_family_space(facts,structured_facts,mixed,safety,coverage)
    split_risks=_future_split_risks()
    source_reference_validation=_validate_source_references(root,samples,documents,sections)
    response=Counter((s.get('expected_behavior') or {}).get('response_type') for s in samples)
    clarification=sum(bool((s.get('expected_behavior') or {}).get('clarification_required')) for s in samples)
    handoff=sum(bool((s.get('expected_behavior') or {}).get('handoff_required')) for s in samples)
    # Privacy-safe structured concentration: only counts/cardinality, no raw business IDs.
    structured_concentration={k:v for k,v in structured_cardinality.items() if isinstance(v,(int,dict))}
    summary={
        "artifact_version":ARTIFACT_VERSION,
        "existing_formal_canonical_cases":len(samples),
        "development_cases":sum(s.get('split')=='DEVELOPMENT' for s in samples),
        "validation_cases":sum(s.get('split')=='VALIDATION' for s in samples),
        "formal_safety_cases":sum(s.get('category')=='SAFETY_GOVERNANCE' for s in samples),
        "formal_multi_turn_eligible":0,
        "recovery_challenge_ready":False,
        "trusted_test_present":False,
        "effective_case_count":coverage['effective_case_count'],
        "surface_variations":coverage['surface_variations'],
        "semantic_family_count":coverage['semantic_family_count'],
        "document_sources":len(documents),
        "document_sections":sum(d['section_count'] for d in documents),
        "atomic_fact_count":len(facts),
        "benchmark_usable_atomic_facts":sum(f.benchmark_usable for f in facts),
        "structured_fact_types":len(structured_facts),
        "benchmark_usable_structured_fact_types":sum(f.benchmark_usable for f in structured_facts),
        "relation_families":len(relations),
        "mixed_families":len(mixed),
        "safety_attack_surfaces":len(safety),
        "clarification_formal_cases":clarification,
        "handoff_formal_cases":handoff,
        "response_type_distribution":dict(response),
        "recommended_formal_dataset":candidate_plan,
        "new_formal_cases_generated":0,
    }
    artifacts={
        'existing_dataset_inventory.json':datasets,
        'document_source_inventory.json':documents,
        'structured_source_inventory.json':structured,
        'relation_inventory.json':[x.to_state() for x in relations],
        'semantic_family_inventory.json':{**semantic_space,"fingerprints":coverage['fingerprints']},
        'safety_attack_surface_inventory.json':safety,
        'coverage_matrix.json':matrix,
        'coverage_gaps.json':blind,
        'capacity_estimate.json':{"categories":[x.to_state() for x in estimates],"recommended_dataset":candidate_plan},
        'phase_d0_summary.json':summary,
        'production_capability_inventory.json':capabilities,
        'mixed_combination_inventory.json':mixed,
        'troubleshooting_space.json':troubleshooting,
        'source_concentration.json':source_concentration,
        'structured_concentration.json':structured_concentration,
        'evidence_complexity.json':evidence_complexity,
        'reasoning_complexity.json':reasoning_complexity,
        'response_behavior_space.json':response_space,
        'future_split_risks.json':split_risks,
        'source_reference_validation.json':source_reference_validation,
    }
    for name,payload in artifacts.items():
        (output/name).write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
    with (output/'atomic_fact_inventory.jsonl').open('w',encoding='utf-8') as f:
        for fact in facts: f.write(json.dumps(fact.to_state(),ensure_ascii=False,sort_keys=True)+'\n')
    (output/'structured_fact_inventory.json').write_text(json.dumps([x.to_state() for x in structured_facts],ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
    # Stable inventory hash excludes absolute paths/timestamps and hashes generated payloads canonically.
    digest=hashlib.sha256()
    for name in sorted([*artifacts,'atomic_fact_inventory.jsonl','structured_fact_inventory.json']):
        digest.update(name.encode()); digest.update((output/name).read_bytes())
    summary['inventory_hash_sha256']=digest.hexdigest()
    (output/'phase_d0_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
    return {**summary,"coverage_matrix":matrix,"capacity_categories":[x.to_state() for x in estimates],"blind_spots":blind,"troubleshooting":troubleshooting,"structured_cardinality":structured_cardinality}
