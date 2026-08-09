"""Distribution/concentration summaries for D1 candidates."""
from __future__ import annotations

from collections import Counter
from typing import Any
from .candidate_contracts import CandidateStatus, PrivateBusinessCandidate


def build_distribution(candidates: list[PrivateBusinessCandidate]) -> dict[str,Any]:
    retained=[c for c in candidates if c.status is CandidateStatus.SOURCE_VALIDATED]
    domain=Counter(c.record_type for c in retained); family=Counter(c.semantic_family_id for c in retained)
    state={
        "order_status": Counter(c.state_attributes.get("status") for c in retained if c.record_type=="order"),
        "ticket_status": Counter(c.state_attributes.get("status") for c in retained if c.record_type=="ticket"),
        "warranty_status": Counter(c.state_attributes.get("status") for c in retained if c.record_type=="warranty"),
        "warranty_coverage_status": Counter(c.state_attributes.get("coverage_status") for c in retained if c.record_type=="warranty"),
    }
    fields=Counter(f"{c.record_type}.{f}" for c in retained for f in c.required_structured_fields)
    combos=Counter(f"{c.record_type}:"+"+".join(sorted(c.required_structured_fields)) for c in retained)
    customers=Counter(c.customer_group_ref for c in retained); entities=Counter(c.source_entity_ref for c in retained)
    products=Counter(c.product_ref for c in retained if c.product_ref); tenants=Counter(c.tenant_group_ref for c in retained)
    difficulty=Counter(c.difficulty for c in retained)
    sampling=Counter(c.sampling_reason or "UNSPECIFIED" for c in retained)
    return {
        "domain_distribution":dict(domain),"semantic_family_distribution":dict(family),
        "state_distribution":{k:dict(v) for k,v in state.items()},"difficulty_distribution":dict(difficulty),"sampling_reason_distribution":dict(sampling),"field_distribution":dict(fields),"field_combination_distribution":dict(combos),
        "unique_customers":len(customers),"unique_entities":len(entities),"unique_products":len(products),"unique_tenants":len(tenants),"product_resolved_candidates":sum(products.values()),
        "unique_customer_ratio": (len(customers)/len(retained) if retained else None),"unique_entity_ratio":(len(entities)/len(retained) if retained else None),
        "max_per_customer":max(customers.values(),default=0),"max_per_entity":max(entities.values(),default=0),"max_per_product":max(products.values(),default=0),"max_per_tenant":max(tenants.values(),default=0),"max_per_semantic_family":max(family.values(),default=0),
        "tenant_concentration_ratio":(max(tenants.values(),default=0)/len(retained) if retained else None),"product_concentration_ratio":(max(products.values(),default=0)/sum(products.values()) if products else None),
    }
