from __future__ import annotations
from collections import Counter,defaultdict
from typing import Iterable
from .mixed_candidate import MixedCandidate

def mixed_dedup_report(candidates:Iterable[MixedCandidate], existing_formal:list[dict])->dict:
    rows=list(candidates); counts=Counter(c.dedup_signature for c in rows)
    low=sum(n-1 for n in counts.values() if n>1)
    # Existing formal all map to legacy ticket-manual family; candidate generator avoids their exact current sections.
    existing_sections={s for x in existing_formal for s in x.get('current_document_sections',[])}
    collisions=[]
    for c in rows:
        hit=sorted(existing_sections.intersection(c.document_section_refs))
        if hit and c.mixed_family_id=='MIXED_TICKET_TROUBLESHOOTING': collisions.append({'candidate_id':c.candidate_id,'sections':hit,'type':'EXISTING_FORMAL_SECTION_COLLISION'})
    return {'exact_candidate_id_duplicates':len(rows)-len({c.candidate_id for c in rows}),'same_reasoning_signature_excess':low,'existing_formal_collisions':collisions,'existing_formal_duplicate_count':len(collisions)}
