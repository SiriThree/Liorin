"""Source, relation, necessity and leakage validation for Phase E0 Mixed candidates."""
from __future__ import annotations
import json,re,sqlite3
from pathlib import Path
from .candidate_contracts import CandidateStatus
from .mixed_candidate import MixedCandidate

RAW_IDS=re.compile(r'\b(?:ORD|TCK|WAR|CUST)-\d{4}-?\d*\b|\bCUST-\d+\b',re.I)

def validate_mixed_candidate(root:str|Path,c:MixedCandidate)->MixedCandidate:
    root=Path(root); reasons=list(c.rejection_reasons)
    if not c.mixed_necessity.structured_source_required or c.mixed_necessity.without_structured_complete: reasons.append('STRUCTURED_SOURCE_UNNECESSARY')
    if not c.mixed_necessity.document_source_required or c.mixed_necessity.without_document_complete: reasons.append('DOCUMENT_SOURCE_UNNECESSARY')
    if not any(x.startswith('record:') for x in c.candidate_evidence_refs): reasons.append('MISSING_STRUCTURED_EVIDENCE')
    if not any(x.startswith('doc:') for x in c.candidate_evidence_refs): reasons.append('MISSING_DOCUMENT_EVIDENCE')
    if RAW_IDS.search(c.candidate_query): reasons.append('RAW_PRIVATE_ID_LEAKAGE')
    if c.product_ref and c.mixed_mode=='ENTITY_TO_KNOWLEDGE_ROUTING':
        if c.product_ref in c.candidate_query: reasons.append('PRODUCT_ROUTING_FACT_LEAKED')
        with sqlite3.connect(root/'data/structured/liorin.db') as _con:
            _row=_con.execute('select name from products where product_id=?',(c.product_ref,)).fetchone()
        if _row and str(_row[0]) in c.candidate_query: reasons.append('PRODUCT_ROUTING_FACT_LEAKED')
    if any(x in c.candidate_query for x in ('美国','中国大陆','欧盟','地区政策')): reasons.append('UNSUPPORTED_REGION_SEMANTICS')
    if c.mixed_family_id=='MIXED_ORDER_RETURN_POLICY':
        if 'UNSUPPORTED_TEMPORAL_BASIS_DELIVERY_DATE_REQUIRED' not in reasons: reasons.append('UNSUPPORTED_TEMPORAL_BASIS_DELIVERY_DATE_REQUIRED')
        if 'TIME_DRIFT_WITHOUT_FROZEN_REFERENCE_DATE' not in reasons: reasons.append('TIME_DRIFT_WITHOUT_FROZEN_REFERENCE_DATE')
    # Verify structured row exists from privacy-safe hash.
    table={'order':'orders','ticket':'tickets','warranty':'warranty_cases'}[c.structured_record_type]
    idfield={'order':'order_id','ticket':'ticket_id','warranty':'case_id'}[c.structured_record_type]
    from retrieval.security import hash_identifier
    digest=c.structured_entity_ref.rsplit(':',1)[-1]
    with sqlite3.connect(root/'data/structured/liorin.db') as con:
        ids=[str(r[0]) for r in con.execute(f'select {idfield} from {table}')]
    if not any(hash_identifier(x,namespace=f'structured:{c.structured_record_type}')==digest for x in ids): reasons.append('STRUCTURED_SOURCE_MISSING')
    # Verify current document sections/facts are source-linked.
    facts={}
    for line in (root/'artifacts/evaluation/dataset-expansion-d0/atomic_fact_inventory.jsonl').open(encoding='utf-8'):
        x=json.loads(line); facts[x['fact_id']]=x
    for fid in c.document_fact_refs:
        f=facts.get(fid)
        if not f or f.get('source_id')!=c.document_source_id or f.get('section_id') not in c.document_section_refs: reasons.append('DOCUMENT_RELATION_INVALID')
    c.rejection_reasons=sorted(set(reasons))
    c.status=CandidateStatus.REJECTED if c.rejection_reasons else CandidateStatus.SOURCE_VALIDATED
    if c.status==CandidateStatus.SOURCE_VALIDATED:
        c.quality_flags.extend(['SOURCE_VALID','BOTH_SOURCES_REQUIRED','PRODUCTION_ARCHITECTURALLY_SUPPORTED','CURRENT_STABLE_DOCUMENT_IDENTITY'])
    return c
