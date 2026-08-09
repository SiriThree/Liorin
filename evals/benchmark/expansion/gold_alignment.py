"""D2 Query/TaskPlan <-> GoldFact <-> GoldEvidence alignment checks."""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


def validate_gold_alignment(candidate: Mapping[str, Any], draft: Mapping[str, Any]) -> dict[str, Any]:
    query_fields = list(candidate["query_plan"]["required_fields"])
    candidate_fields = list(candidate["required_structured_fields"])
    fact_fields = [x["source_field_path"] for x in draft["gold_facts_draft"]]
    evidence_fields = [x["field_path"] for x in draft["gold_evidence_draft"]]
    issues: list[str] = []
    if Counter(query_fields) != Counter(candidate_fields):
        issues.append("QUERY_PLAN_CANDIDATE_FIELD_MISMATCH")
    if Counter(candidate_fields) != Counter(fact_fields):
        issues.append("MISSING_OR_EXTRA_GOLD_FACT")
    if Counter(candidate_fields) != Counter(evidence_fields):
        issues.append("MISSING_OR_EXTRA_GOLD_EVIDENCE")
    evidence_ids = {x["evidence_id"] for x in draft["gold_evidence_draft"]}
    for fact in draft["gold_facts_draft"]:
        if not set(fact["supporting_evidence_ids"]).issubset(evidence_ids):
            issues.append(f"UNRESOLVED_FACT_SUPPORT:{fact['fact_id']}")
    status = "aligned" if not issues else "misaligned"
    return {
        "candidate_id": candidate["candidate_id"],
        "semantic_family_id": candidate["semantic_family_id"],
        "query_plan_fields": query_fields,
        "candidate_fields": candidate_fields,
        "gold_fact_fields": fact_fields,
        "gold_evidence_fields": evidence_fields,
        "status": status,
        "issues": sorted(set(issues)),
        "multi_field": len(candidate_fields) > 1,
    }
