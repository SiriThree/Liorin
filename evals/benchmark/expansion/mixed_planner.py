"""Deterministic Structured + Knowledge source planning for Phase E0."""
from __future__ import annotations
import hashlib,json,sqlite3,re
from collections import Counter,defaultdict
from pathlib import Path
from typing import Any
from retrieval.security import hash_identifier
from .candidate_contracts import CandidateStatus
from .mixed_candidate import MixedCandidate,MixedNecessity
from .source_inventory import build_document_source_inventory

GENERATION_VERSION='mixed-e0-v1'
FAMILY_COUNTS={
 'MIXED_ORDER_RETURN_POLICY':10,
 'MIXED_ORDER_STATUS_POLICY':8,
 'MIXED_ORDER_PRODUCT_MANUAL':18,
 'MIXED_TICKET_TROUBLESHOOTING':8,
 'MIXED_WARRANTY_STATUS_POLICY':8,
 'MIXED_WARRANTY_PRODUCT_MANUAL':16,
}
POLICY_SOURCE='source:policy:after_sales_policy'
POLICY_DOC='after_sales_policy'

def _href(kind:str, raw:str, namespace:str|None=None)->str:
    return f"{kind}:hash:{hash_identifier(raw,namespace=namespace or f'structured:{kind}')}"

def _evidence(kind:str, raw:str, field:str)->str:
    return f"record:{kind}:hash:{hash_identifier(raw,namespace=f'structured:{kind}')}#{field}"

def _token(kind:str, ref:str)->str:
    return f"<{kind.upper()}_REF:{ref.rsplit(':',1)[-1][:8]}>"

def _cid(family:str, entity_ref:str, doc_facts:list[str], structured_fields:list[str], derived:str='')->str:
    material=json.dumps({'family':family,'entity':entity_ref,'doc':doc_facts,'fields':structured_fields,'derived':derived},sort_keys=True,separators=(',',':'))
    return 'MIX-'+hashlib.sha256(material.encode()).hexdigest()[:16].upper()

def _load_facts(root:Path):
    rows=[]
    for line in (root/'artifacts/evaluation/dataset-expansion-d0/atomic_fact_inventory.jsonl').open(encoding='utf-8'):
        x=json.loads(line)
        if x.get('benchmark_usable'): rows.append(x)
    return rows

def _sections(root:Path):
    _,secs=build_document_source_inventory(root)
    return {x['section_id']:x for x in secs}

def _db_rows(root:Path):
    con=sqlite3.connect(root/'data/structured/liorin.db'); con.row_factory=sqlite3.Row
    try:
        customers={r['customer_id']:dict(r) for r in con.execute('select customer_id,tenant_id from customers')}
        products={r['product_id']:dict(r) for r in con.execute('select * from products')}
        orders=[]
        for r in con.execute('''select o.*, x.item_count, i.product_id from orders o join (select order_id,count(*) item_count from order_items group by order_id) x on x.order_id=o.order_id left join order_items i on i.order_id=o.order_id and x.item_count=1 order by o.order_id'''):
            d=dict(r); d.update(customers[d['customer_id']]); orders.append(d)
        tickets=[]
        for r in con.execute('select * from tickets order by ticket_id'):
            d=dict(r); d.update(customers[d['customer_id']]); tickets.append(d)
        warranties=[]
        for r in con.execute('select * from warranty_cases order by case_id'):
            d=dict(r); d.update(customers[d['customer_id']]); warranties.append(d)
        return orders,tickets,warranties,products
    finally: con.close()

def _policy_fact(facts:list[dict], needle:str)->dict:
    hits=[f for f in facts if f['source_id']==POLICY_SOURCE and needle in f['normalized_value']]
    if len(hits)!=1: raise RuntimeError(f'policy fact {needle!r} hits={len(hits)}')
    return hits[0]

def _existing_formal_sections(root:Path)->set[str]:
    # Bridge legacy Hxxx refs to current section ids before collision checks.
    amap=root/'artifacts/evaluation/dataset-expansion-d1/legacy_section_alias_map.json'
    bridge={}
    if amap.exists():
        payload=json.loads(amap.read_text(encoding='utf-8'))
        rows=payload if isinstance(payload,list) else payload.get('mappings') or payload.get('rows') or []
        for x in rows:
            if x.get('current_section_id'): bridge[(x.get('document_id'),x.get('legacy_ref') or x.get('legacy_section_id'))]=x['current_section_id']
    used=set()
    for fn in ('dev_v7_3_canonical_v1.json','validation_v7_3_canonical_v1.json'):
        data=json.loads((root/'evals/benchmark/data/canonical'/fn).read_text(encoding='utf-8'))
        arr=data if isinstance(data,list) else data.get('samples') or data.get('cases') or []
        for c in arr:
            if c.get('category')!='MIXED_KNOWLEDGE_STRUCTURED': continue
            for e in c.get('gold_evidence',[]):
                if e.get('source_type')=='DOCUMENT':
                    key=(e.get('document_id'),e.get('section_id'))
                    used.add(bridge.get(key,e.get('section_id')))
    return {x for x in used if x}

def _manual_fact_pool(facts, sections, product_id, existing_sections, *, prefer_trouble=False):
    doc_prefix=f'source:manual:{product_id}_'
    rows=[f for f in facts if f['source_id'].startswith(doc_prefix) and f['section_id'] not in existing_sections and f.get('ambiguity')=='LOW']
    bad_titles={'警告','目录','内容','前言','使用说明书','用户手册','产品介绍','请阅读本手册','关于本手册'}
    good=[]
    for f in rows:
        raw_title=(sections.get(f['section_id']) or {}).get('title','').strip()
        title=re.sub(r'^[■●·•\-*\s]+','',raw_title)
        title=re.sub(r'^\d+(?:[.、)])\s*','',title).strip()
        product_name=(sections.get(f['section_id']) or {}).get('product_name') or ''
        if len(title)<3 or title in bad_titles or len(title)>55 or title.endswith('手册') or (product_name and product_name in title): continue
        rank=0
        if prefer_trouble and f['fact_type'] in {'TROUBLESHOOTING_STEP','ERROR_CODE'}: rank-=20
        elif f['fact_type']=='TROUBLESHOOTING_STEP': rank-=10
        elif f['fact_type'] in {'FEATURE_OR_INSTRUCTION','COMPATIBILITY','PRODUCT_SPEC'}: rank-=6
        elif f['fact_type']=='SAFETY_INSTRUCTION': rank-=2
        else: rank+=5
        good.append((rank, f['section_id'], f['fact_id'], f))
    return [x[-1] for x in sorted(good)]

def _base_candidate(*,family,mode,record_type,row,raw_id,structured_fields,doc_source,doc_facts,relation,query,reasoning,derived,product_id,source_state,quality=None,rejections=None)->MixedCandidate:
    eref=_href('warranty' if record_type=='warranty' else record_type,raw_id)
    srefs=tuple(_evidence(record_type,raw_id,f) for f in structured_fields)
    dsecs=tuple(dict.fromkeys(f['section_id'] for f in doc_facts))
    drefs=tuple(f"doc:{f['document_id']}#{f['section_id']}" for f in doc_facts)
    doc_ids=tuple(f['fact_id'] for f in doc_facts)
    necessity=MixedNecessity(True,True,
      'The private structured record supplies a required business fact/entity not present in the query.',
      'The checked-in knowledge source supplies the rule/instruction required to complete the task.',False,False)
    outcome=(derived or {}).get('result','') if derived else ''
    sig=hashlib.sha256(json.dumps({'f':family,'sf':list(structured_fields),'sv':[str(row.get(x)) for x in structured_fields],'df':list(doc_ids),'r':list(reasoning),'o':outcome},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    cid=_cid(family,eref,list(doc_ids),list(structured_fields),outcome)
    customer=str(row['customer_id']); tenant=str(row['tenant_id'])
    return MixedCandidate(candidate_id=cid,status=CandidateStatus.CANDIDATE,construction_schema_version='mixed-candidate-1.0',mixed_family_id=family,mixed_mode=mode,semantic_family_id=family,structured_record_type=record_type,structured_entity_ref=eref,structured_fact_refs=srefs,document_source_id=doc_source,document_section_refs=dsecs,document_fact_refs=doc_ids,relation_path=relation,mixed_necessity=necessity,reasoning_type=tuple(reasoning),derived_fact_draft=derived,expected_response_type_draft='ANSWER',candidate_query=query,candidate_evidence_refs=srefs+drefs,production_capability_refs=('private_structured_read','knowledge_retrieval','support_graph_mixed_architecture'),split_group_keys={'semantic_family_group':family,'customer_group':_href('customer',customer,'customer'),'entity_group':eref,'product_group':product_id or 'NONE','tenant_group':_href('tenant',tenant,'tenant'),'document_group':doc_source},dedup_signature=sig,source_entity_state=source_state,product_ref=product_id,customer_group_ref=_href('customer',customer,'customer'),tenant_group_ref=_href('tenant',tenant,'tenant'),document_fact_type=doc_facts[0]['fact_type'] if doc_facts else None,quality_flags=list(quality or []),rejection_reasons=list(rejections or []))

def generate_mixed_candidates(root:str|Path)->list[MixedCandidate]:
    root=Path(root); facts=_load_facts(root); secs=_sections(root); existing_sections=_existing_formal_sections(root)
    orders,tickets,warranties,products=_db_rows(root)
    out=[]; used=defaultdict(set); customer_counts=Counter(); tenant_counts=Counter(); product_counts=Counter()
    # F1: explicit raw attempts, deliberately rejected later: policy basis is delivery/sign-off date, not order_date.
    ret=_policy_fact(facts,'已签收商品通常需要在 7 天内')
    for row in [r for r in orders if r['status']=='Delivered'][:FAMILY_COUNTS['MIXED_ORDER_RETURN_POLICY']]:
        raw=row['order_id']; ref=_href('order',raw); tok=_token('order',ref)
        out.append(_base_candidate(family='MIXED_ORDER_RETURN_POLICY',mode='POLICY_APPLICATION',record_type='order',row=row,raw_id=raw,structured_fields=['order_date'],doc_source=POLICY_SOURCE,doc_facts=[ret],relation='order -> after_sales_policy',query=f'订单 {tok} 按售后政策现在还能申请退货吗？',reasoning=['POLICY_APPLICATION','TEMPORAL_COMPARISON'],derived={'inputs':['order.order_date',ret['fact_id']],'rule':'POLICY_USES_SIGNED/DELIVERY_DATE_NOT_ORDER_DATE','result':'UNDETERMINED','comparison_operation':'UNSUPPORTED_TEMPORAL_BASIS'},product_id=row.get('product_id'),source_state=row['status']))
    # F2: order status + cancellation policy, balanced across the four real states.
    pf={'Processing':_policy_fact(facts,'Processing` 状态订单可以进入取消资格检查'),'Shipped':_policy_fact(facts,'Shipped` 或 `Delivered'),'Delivered':_policy_fact(facts,'Shipped` 或 `Delivered'),'Cancelled':_policy_fact(facts,'Cancelled` 状态订单只能解释原因')}
    desired=['Processing','Shipped','Cancelled','Delivered']*2
    for state in desired:
        row=next(r for r in orders if r['status']==state and r['order_id'] not in used['order'])
        used['order'].add(row['order_id']); raw=row['order_id']; ref=_href('order',raw); tok=_token('order',ref)
        outcome={'Processing':'ELIGIBILITY_CHECK_ALLOWED','Shipped':'DIRECT_CANCEL_NOT_ALLOWED_USE_RETURN_REFUND','Delivered':'DIRECT_CANCEL_NOT_ALLOWED_USE_RETURN_REFUND','Cancelled':'DO_NOT_REPEAT_CANCEL'}[state]
        out.append(_base_candidate(family='MIXED_ORDER_STATUS_POLICY',mode='POLICY_APPLICATION',record_type='order',row=row,raw_id=raw,structured_fields=['status'],doc_source=POLICY_SOURCE,doc_facts=[pf[state]],relation='order -> after_sales_policy',query=f'订单 {tok} 现在还能直接取消吗？请结合当前订单状态和售后政策说明下一步。',reasoning=['POLICY_APPLICATION','CONDITIONAL_APPLICATION'],derived={'inputs':['order.status',pf[state]['fact_id']],'rule':'after_sales_policy/order_cancellation','result':outcome,'comparison_operation':'ENUM_RULE'},product_id=row.get('product_id'),source_state=state,quality=['RARE_STATE_COVERAGE'] if state!='Delivered' else []))
    # Helpers for routing families. Prioritize D0-uncovered product manuals 17-20, then all others.
    product_order=['LIO-PROD-017','LIO-PROD-018','LIO-PROD-019','LIO-PROD-020']+[f'LIO-PROD-{i:03d}' for i in range(1,17)]
    def route_family(family,record_type,rows,count,relation,prefer_trouble=False,product_sequence=None):
        selected=0; fact_use=Counter(); ent_used=used[record_type]
        for pid in (product_sequence or product_order)*3:
            if selected>=count: break
            pool=_manual_fact_pool(facts,secs,pid,existing_sections,prefer_trouble=prefer_trouble)
            if not pool: continue
            # Choose a fact not yet used in this family when possible.
            fact=next((f for f in pool if fact_use[f['fact_id']]==0),pool[0])
            candidates=[r for r in rows if r.get('product_id')==pid and ({'order':'order_id','ticket':'ticket_id','warranty':'case_id'}[record_type] not in ent_used)]
            if record_type=='order': candidates=[r for r in candidates if int(r.get('item_count') or 0)==1]
            if not candidates: continue
            candidates.sort(key=lambda r:(customer_counts[r['customer_id']],tenant_counts[r['tenant_id']],product_counts[pid],str(r[{'order':'order_id','ticket':'ticket_id','warranty':'case_id'}[record_type]])))
            row=candidates[0]; raw=str(row[{'order':'order_id','ticket':'ticket_id','warranty':'case_id'}[record_type]])
            ent_used.add(raw); customer_counts[row['customer_id']]+=1; tenant_counts[row['tenant_id']]+=1; product_counts[pid]+=1; fact_use[fact['fact_id']]+=1
            ref=_href(record_type,raw); tok=_token(record_type,ref); title=(secs.get(fact['section_id']) or {}).get('title','相关操作').strip(); title=re.sub(r'^[■●·•\-*\s]+','',title); title=re.sub(r'^\d+(?:[.、)])\s*','',title).strip()
            if record_type=='ticket':
                query=f'工单 {tok} 里没有写产品型号。请先确认对应产品，再根据该产品手册说明“{title}”相关的排查或处理方法。'
            elif record_type=='warranty':
                query=f'保修案例 {tok} 对应的是哪类产品不用单独告诉我；请根据它实际对应的产品手册，说明“{title}”相关的使用或处理要点。'
            else:
                query=f'订单 {tok} 里的设备具体型号我不记得了。请先从订单确认产品，再根据对应手册说明“{title}”相关的使用或处理要点。'
            out.append(_base_candidate(family=family,mode='ENTITY_TO_KNOWLEDGE_ROUTING',record_type=record_type,row=row,raw_id=raw,structured_fields=['product_id'],doc_source=fact['source_id'],doc_facts=[fact],relation=relation,query=query,reasoning=['ENTITY_RESOLUTION','SOURCE_ROUTING'],derived={'inputs':[f'{record_type}.product_id',fact['fact_id']],'rule':'structured product identity selects the applicable checked-in manual','result':'ROUTE_TO_MATCHED_PRODUCT_MANUAL','comparison_operation':'EXACT_RELATION'},product_id=pid,source_state=row.get('status') or row.get('coverage_status')))
            selected+=1
        if selected<count: raise RuntimeError(f'{family}: only {selected}/{count} source routes')
    route_family('MIXED_ORDER_PRODUCT_MANUAL','order',orders,FAMILY_COUNTS['MIXED_ORDER_PRODUCT_MANUAL'],'order -> order_items -> product -> manual')
    route_family('MIXED_TICKET_TROUBLESHOOTING','ticket',tickets,FAMILY_COUNTS['MIXED_TICKET_TROUBLESHOOTING'],'ticket -> product -> manual',prefer_trouble=True,product_sequence=['LIO-PROD-015','LIO-PROD-016','LIO-PROD-017','LIO-PROD-018','LIO-PROD-019','LIO-PROD-020','LIO-PROD-001','LIO-PROD-002']+[f'LIO-PROD-{i:03d}' for i in range(3,15)])
    # F5: warranty state + policy coverage semantics. Both are explicit answer components.
    cov=_policy_fact(facts,'保修覆盖通常包括制造缺陷'); excl=_policy_fact(facts,'进水、跌落、私拆')
    desired_cov=['expired','in_warranty']*4
    for target_cov in desired_cov:
        choices=[r for r in warranties if r['coverage_status']==target_cov and r['case_id'] not in used['warranty']]
        choices.sort(key=lambda r:(customer_counts[r['customer_id']],tenant_counts[r['tenant_id']],product_counts[r['product_id']],r['case_id']))
        if not choices: raise RuntimeError(f'no warranty source for coverage_status={target_cov}')
        row=choices[0]; raw=row['case_id']
        used['warranty'].add(raw); customer_counts[row['customer_id']]+=1; tenant_counts[row['tenant_id']]+=1; product_counts[row['product_id']]+=1
        ref=_href('warranty',raw); tok=_token('warranty',ref)
        out.append(_base_candidate(family='MIXED_WARRANTY_STATUS_POLICY',mode='CROSS_SOURCE_SYNTHESIS',record_type='warranty',row=row,raw_id=raw,structured_fields=['coverage_status'],doc_source=POLICY_SOURCE,doc_facts=[cov,excl],relation='warranty -> after_sales_policy',query=f'保修案例 {tok} 当前是否还在保修范围？同时按售后政策说明标准保修通常覆盖哪些问题、哪些情况通常不覆盖。',reasoning=['MULTI_SOURCE_SYNTHESIS'],derived={'inputs':['warranty.coverage_status',cov['fact_id'],excl['fact_id']],'rule':'report current structured coverage state plus policy coverage/exclusion semantics','result':f'{target_cov.upper()}_PLUS_POLICY_INTERPRETATION','comparison_operation':'SYNTHESIS'},product_id=row['product_id'],source_state=row['coverage_status']))
    route_family('MIXED_WARRANTY_PRODUCT_MANUAL','warranty',warranties,FAMILY_COUNTS['MIXED_WARRANTY_PRODUCT_MANUAL'],'warranty -> product -> manual')
    return out
