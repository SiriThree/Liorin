from __future__ import annotations
from collections import Counter,defaultdict

def distributions(rows):
    fam=Counter(x.mixed_family_id for x in rows); mode=Counter(x.mixed_mode for x in rows); reason=Counter(r for x in rows for r in x.rejection_reasons)
    docs=Counter(x.document_source_id for x in rows); sections=Counter(s for x in rows for s in x.document_section_refs); facts=Counter(f for x in rows for f in x.document_fact_refs)
    ents=Counter(x.structured_entity_ref for x in rows); products=Counter(x.product_ref for x in rows if x.product_ref); tenants=Counter(x.tenant_group_ref for x in rows); customers=Counter(x.customer_group_ref for x in rows)
    state=defaultdict(Counter)
    for x in rows: state[x.mixed_family_id][x.source_entity_state]+=1
    return {'family':dict(fam),'mode':dict(mode),'rejections':dict(reason),'documents':dict(docs),'sections':dict(sections),'facts':dict(facts),'entities':dict(ents),'products':dict(products),'tenants':dict(tenants),'customers':dict(customers),'states':{k:dict(v) for k,v in state.items()}}
