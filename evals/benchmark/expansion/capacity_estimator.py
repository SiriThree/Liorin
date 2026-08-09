"""Evidence-based high-quality dataset capacity recommendations."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .contracts import CapacityConfidence, CapacityEstimate


def estimate_capacity(*, facts: list[Any], troubleshooting: dict[str, Any], structured_facts: list[Any], mixed: list[dict[str, Any]], safety_surfaces: list[dict[str, Any]], current_coverage: dict[str, Any]) -> list[CapacityEstimate]:
    usable=[f for f in facts if f.benchmark_usable]
    fact_types=Counter(f.fact_type for f in usable)
    # Conservative caps intentionally use independent source units / entity-state diversity,
    # not paraphrase multipliers or raw chunk count.
    knowledge_units=sum(v for k,v in fact_types.items() if k not in {"TROUBLESHOOTING_STEP","ERROR_CODE"})
    trouble_units=max(troubleshooting.get('section_count',0), min(troubleshooting.get('fact_count',0), 120))
    struct_types=sum(1 for f in structured_facts if f.benchmark_usable and f.distinct_value_count >= 2)
    mixed_families=sum(1 for m in mixed if m.get('production_supported'))
    safety=len(safety_surfaces)
    estimates=[
        CapacityEstimate("KNOWLEDGE_QA", max(40,min(80,knowledge_units//6)), max(90,min(150,knowledge_units//3)), max(140,min(220,knowledge_units//2)), CapacityConfidence.HIGH,(f"{knowledge_units} benchmark-usable non-troubleshooting document fact candidates","20 product manuals + FAQ + policy")),
        CapacityEstimate("TROUBLESHOOTING", max(20,min(35,trouble_units//2)), max(35,min(70,trouble_units)), max(55,min(100,trouble_units+troubleshooting.get('multi_step_sections',0))), CapacityConfidence.MEDIUM,(f"{troubleshooting.get('fact_count',0)} troubleshooting/error-code fact candidates",f"{troubleshooting.get('multi_step_sections',0)} multi-step sections")),
        CapacityEstimate("PRIVATE_BUSINESS_QUERY", 35, 60 if struct_types>=10 else 45, 90 if struct_types>=10 else 65, CapacityConfidence.HIGH,(f"{struct_types} production-exposed structured fact types","1500 orders / 420 tickets / 140 warranty cases provide entity/state diversity")),
        CapacityEstimate("MIXED_KNOWLEDGE_STRUCTURED", max(20,mixed_families*5), max(35,mixed_families*9), max(50,mixed_families*13), CapacityConfidence.MEDIUM,(f"{mixed_families} production-supported mixed relation families","capacity capped by independent relation semantics, not entity Cartesian product")),
        CapacityEstimate("SAFETY_GOVERNANCE", max(15,safety*2), max(25,safety*3), max(35,safety*4), CapacityConfidence.MEDIUM,(f"{safety} real governance attack surfaces","positive/negative policy-boundary variants without invented write surfaces")),
    ]
    return estimates


def candidate_pool_recommendation(estimates: list[CapacityEstimate]) -> dict[str, Any]:
    formal_rec=sum(x.recommended for x in estimates)
    formal_min=sum(x.minimum for x in estimates)
    formal_upper=sum(x.upper_reasonable_bound for x in estimates)
    # Review/dedup rejection is explicitly a planning assumption, not observed model quality.
    candidate_low=int(round(formal_rec/0.78))
    candidate_high=int(round(formal_rec/0.65))
    return {"formal_target_minimum":formal_min,"formal_target_recommended":formal_rec,"formal_target_upper_reasonable_bound":formal_upper,"candidate_pool_target_range":[candidate_low,candidate_high],"planning_rejection_rate_range":[0.22,0.35],"note":"Candidate pool margin is for source validation/dedup/review rejection; it is not a quality metric or a guarantee."}
