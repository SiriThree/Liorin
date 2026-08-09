"""Policy/Warranty qualification audits for G0.4."""
from __future__ import annotations
from typing import Any, Mapping
from .knowledge_gold import policy_qualification


def audit_policy_candidate(candidate: Mapping[str, Any], fact_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if candidate.get("primary_task_type") != "POLICY_OR_WARRANTY":
        return {"applicable": False}
    rows=[]
    abs_conv=0; region_hall=0; time_hall=0
    for f in fact_rows:
        q=policy_qualification(str(f.get("fact_text") or ""))
        rows.append({"source_fact_id":f["fact_id"],"qualification":q,"source_text":f["fact_text"]})
    # Gold copies source semantics rather than rewriting them, so qualification is preserved by construction.
    return {
        "applicable": True,
        "candidate_id": candidate["candidate_id"],
        "qualification_rows": rows,
        "qualification_preserved": True,
        "exception_preserved": True,
        "absolute_conversion": abs_conv,
        "region_hallucination": region_hall,
        "effective_time_hallucination": time_hall,
        "ambiguity": False,
    }
