"""Phase F0 source validation and hard guards."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from typing import Iterable

from .troubleshooting_candidate import TroubleshootingCandidate, TroubleshootingSourceUnit

BROAD=("相关要点","介绍一下这个部分","有哪些注意事项")
RAW_ID=re.compile(r"\b(?:ORD|TCK|WAR|CUST)-[A-Za-z0-9_-]+\b")


def validate_candidate(c: TroubleshootingCandidate, unit: TroubleshootingSourceUnit, *, source_unit_map: dict[str,TroubleshootingSourceUnit]) -> tuple[bool,list[str]]:
    reasons=[]
    if not unit.benchmark_usable: reasons.append("SOURCE_UNIT_NOT_BENCHMARK_USABLE")
    if not unit.document_id or not unit.section_id: reasons.append("SOURCE_REFERENCE_MISSING")
    if c.product_id != unit.product_id: reasons.append("PRODUCT_RELATION_DRIFT")
    if not c.source_fact_ids or not set(c.source_fact_ids).issubset(set(unit.manual_fact_ids)): reasons.append("SOURCE_FACT_MISMATCH")
    if not set(c.source_section_ids).issubset({unit.section_id}): reasons.append("SOURCE_SECTION_MISMATCH")
    if RAW_ID.search(c.candidate_query): reasons.append("RAW_PRIVATE_ID_LEAKAGE")
    if any(k in c.candidate_query for k in ("<ORDER_REF:","<TICKET_REF:","<WARRANTY_REF:","订单号","工单号","保修单")): reasons.append("MIXED_OR_PRIVATE_SOURCE_REQUIRED")
    if any(x in c.candidate_query for x in BROAD) and len(unit.manual_fact_ids)>1: reasons.append("SCOPE_TOO_BROAD")
    # Product identity must be absent only for product-context clarification cases.
    if c.task_type=="CLARIFICATION_REQUIRED" and "product_name_or_model" in c.hidden_required_context:
        if unit.product_name and unit.product_name in c.candidate_query: reasons.append("MISSING_CONTEXT_LEAKED")
        if c.expected_behavior_draft.get("response_type")!="CLARIFICATION": reasons.append("CLARIFICATION_BEHAVIOR_MISMATCH")
    if c.task_type=="SUFFICIENT_CONTEXT_NO_CLARIFICATION":
        if not unit.product_name or unit.product_name not in c.candidate_query: reasons.append("FALSE_CLARIFICATION_CONTROL_CONTEXT_INCOMPLETE")
        if c.expected_behavior_draft.get("response_type")!="ANSWER": reasons.append("FALSE_CLARIFICATION_CONTROL_WRONG_BEHAVIOR")
    if c.task_type=="ESCALATION_HANDOFF":
        if not unit.escalation_conditions: reasons.append("HANDOFF_NOT_SOURCE_GROUNDED")
        if c.expected_behavior_draft.get("response_type")!="HANDOFF": reasons.append("HANDOFF_BEHAVIOR_MISMATCH")
    if c.recovery_eligibility.observed_first_pass_failure: reasons.append("FAKE_OBSERVED_FIRST_PASS_FAILURE")
    if c.recovery_eligibility.formal_recovery_eligible: reasons.append("FAKE_FORMAL_RECOVERY_ELIGIBILITY")
    if c.recovery_eligibility.recovery_eligible and not c.recovery_eligibility.acceptable_recovery_actions: reasons.append("RECOVERY_ACTION_UNSUPPORTED")
    if not c.required_steps and c.task_type not in {"CLARIFICATION_REQUIRED","ESCALATION_HANDOFF"}: reasons.append("REQUIRED_STEPS_MISSING")
    # Answer leakage: a sufficiently long source action must not appear verbatim in query.
    for step in unit.diagnostic_steps:
        act=re.sub(r"\s+","",step.action)
        if len(act)>=12 and act in re.sub(r"\s+","",c.candidate_query):
            reasons.append("ANSWER_LEAKAGE"); break
    return not reasons, sorted(set(reasons))


def validate_candidates(candidates: Iterable[TroubleshootingCandidate], units: Iterable[TroubleshootingSourceUnit]):
    um={u.source_unit_id:u for u in units}; validated=[]; rejected=[]
    for c in candidates:
        u=um.get(c.source_unit_id)
        if not u:
            reasons=["SOURCE_UNIT_MISSING"]
        else:
            ok,reasons=validate_candidate(c,u,source_unit_map=um)
        if u and ok:
            validated.append(replace(c,status="SOURCE_VALIDATED",rejection_reasons=()))
        else:
            rejected.append(replace(c,status="REJECTED",rejection_reasons=tuple(reasons)))
    return validated,rejected


def effective_signature(c: TroubleshootingCandidate) -> str:
    # Entity identity is intentionally excluded. Behavior and source semantics are retained.
    return "|".join([c.semantic_family_id,c.source_unit_id,c.task_type,",".join(c.hidden_required_context),",".join(c.required_steps),c.recovery_eligibility.recovery_trigger_type or ""])
