from __future__ import annotations
from collections import defaultdict
from typing import Any

def dedup_report(rows:list[dict[str,Any]])->dict[str,Any]:
    valid=[r for r in rows if r['status']=='POLICY_VALIDATED']
    q=defaultdict(list); sig=defaultdict(list)
    for r in valid:
      q[' '.join(r['candidate_query'].casefold().split())].append(r['candidate_id'])
      sig[r['dedup_signature']].append(r['candidate_id'])
    return {'exact_or_normalized_query_duplicate_groups':{k:v for k,v in q.items() if len(v)>1},'semantic_duplicate_groups':{k:v for k,v in sig.items() if len(v)>1},'semantic_duplicate_excess':sum(len(v)-1 for v in sig.values() if len(v)>1)}
