from __future__ import annotations
from collections import Counter,defaultdict
from typing import Any

def distributions(rows:list[dict[str,Any]])->dict[str,Any]:
    valid=[r for r in rows if r['status']=='POLICY_VALIDATED']
    return {
      'surface':dict(Counter(r['surface_id'] for r in valid)),
      'scenario_type':dict(Counter(r['scenario_type'] for r in valid)),
      'difficulty':dict(Counter(r['difficulty'] for r in valid)),
      'expected_action':dict(Counter(r['expected_security_action'] for r in valid)),
      'attack_vector':dict(Counter(r['attack_vector'] for r in valid)),
    }

def authorization_matrix(rows:list[dict[str,Any]])->list[dict[str,Any]]:
    valid=[r for r in rows if r['status']=='POLICY_VALIDATED']
    seen=set(); out=[]
    for r in valid:
      key=(r['surface_id'],r['ownership_relation'],r['permission_relation'],r['expected_security_action'])
      if key in seen: continue
      seen.add(key); out.append({'surface_id':key[0],'identity_or_ownership_relation':key[1],'permission_relation':key[2],'expected_security_action':key[3]})
    return sorted(out,key=lambda x:(x['surface_id'],x['identity_or_ownership_relation'],x['permission_relation']))

def forbidden_report(rows:list[dict[str,Any]])->dict[str,int]:
    c=Counter()
    for r in rows:
      if r['status']=='POLICY_VALIDATED': c.update(r['forbidden_behaviors'])
    return dict(c.most_common())
