"""Reporting helpers for Phase F0."""
from __future__ import annotations
from collections import Counter,defaultdict
from typing import Iterable
from .troubleshooting_candidate import TroubleshootingCandidate,TroubleshootingSourceUnit
from .troubleshooting_validation import effective_signature


def behavior_distribution(rows):
    c=Counter()
    for r in rows:
        for x in r.behavior_labels: c[x]+=1
    return dict(sorted(c.items()))


def concentration(rows, units):
    um={u.source_unit_id:u for u in units}; docs=Counter(); secs=Counter(); sus=Counter(); symptoms=Counter()
    for r in rows:
        u=um[r.source_unit_id]; docs[u.document_id]+=1; secs[u.section_id]+=1; sus[u.source_unit_id]+=1; symptoms[u.symptom_family]+=1
    n=max(1,len(rows))
    return {"cases_per_document":dict(docs),"cases_per_section":dict(secs),"cases_per_source_unit":dict(sus),"cases_per_symptom_family":dict(symptoms),
            "max_per_document":max(docs.values(),default=0),"max_per_section":max(secs.values(),default=0),"max_per_source_unit":max(sus.values(),default=0),
            "section_concentration_warning": any(v/n>0.10 for v in secs.values())}


def effective_diversity(rows):
    sig=Counter(effective_signature(x) for x in rows)
    return {"source_validated":len(rows),"effective_semantic_units":len(sig),"semantic_duplicate_excess":sum(v-1 for v in sig.values() if v>1),
            "scenario_families":len({x.scenario_family_id for x in rows}),"procedure_families":len({x.procedure_family_id for x in rows}),"surface_variations":0}
