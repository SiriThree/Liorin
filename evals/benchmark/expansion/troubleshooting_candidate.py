"""Phase F0 troubleshooting candidate construction contracts.

Construction-only types. They are not CanonicalEvaluationSample and are never
used as Production predictions or Formal Gold.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RequiredContextDraft:
    context_field: str
    required: bool
    reason: str
    source_support: tuple[str, ...] = ()
    can_be_user_provided: bool = True
    can_be_structured_resolved: bool = False
    can_be_inferred: bool = False
    safe_to_infer: bool = False

    def to_state(self) -> dict[str, Any]:
        d = asdict(self); d["source_support"] = list(self.source_support); return d


@dataclass(frozen=True)
class TroubleshootingStepDraft:
    step_id: str
    action: str
    precondition: str | None = None
    postcondition: str | None = None
    order_required: bool = False
    safety_critical: bool = False
    terminal: bool = False
    escalation: bool = False
    source_fact_id: str | None = None

    def to_state(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class TroubleshootingSourceUnit:
    source_unit_id: str
    document_id: str
    section_id: str
    product_id: str | None
    product_name: str | None
    symptom: str
    symptom_family: str
    error_code: str | None
    required_context: tuple[RequiredContextDraft, ...]
    diagnostic_steps: tuple[TroubleshootingStepDraft, ...]
    conditional_branches: tuple[dict[str, Any], ...]
    safety_prerequisites: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    escalation_conditions: tuple[str, ...]
    manual_fact_ids: tuple[str, ...]
    source_text_refs: tuple[str, ...]
    step_order: str
    benchmark_usable: bool
    quality_flags: tuple[str, ...] = ()

    def to_state(self) -> dict[str, Any]:
        d=asdict(self)
        d["required_context"]=[x.to_state() for x in self.required_context]
        d["diagnostic_steps"]=[x.to_state() for x in self.diagnostic_steps]
        for k in ("conditional_branches","safety_prerequisites","stop_conditions","escalation_conditions","manual_fact_ids","source_text_refs","quality_flags"):
            d[k]=list(d[k])
        return d


@dataclass(frozen=True)
class RecoveryEligibilityDraft:
    recovery_eligible: bool
    recovery_trigger_type: str | None
    trigger_condition: str | None
    acceptable_recovery_actions: tuple[str, ...]
    unacceptable_recovery_actions: tuple[str, ...]
    success_after_recovery_contract: str | None
    observed_first_pass_failure: bool = False
    formal_recovery_eligible: bool = False
    recovery_risk_signals: tuple[str, ...] = ()

    def to_state(self) -> dict[str, Any]:
        d=asdict(self)
        for k in ("acceptable_recovery_actions","unacceptable_recovery_actions","recovery_risk_signals"):
            d[k]=list(d[k])
        return d


@dataclass(frozen=True)
class TroubleshootingCandidate:
    candidate_id: str
    status: str
    source_unit_id: str
    product_id: str | None
    product_name: str | None
    semantic_family_id: str
    task_type: str
    behavior_labels: tuple[str, ...]
    symptom: str
    user_known_context: tuple[str, ...]
    hidden_required_context: tuple[str, ...]
    expected_behavior_draft: dict[str, Any]
    required_steps: tuple[str, ...]
    conditional_logic: tuple[str, ...]
    safety_requirements: tuple[str, ...]
    escalation_condition: str | None
    recovery_eligibility: RecoveryEligibilityDraft
    candidate_query: str
    source_fact_ids: tuple[str, ...]
    source_section_ids: tuple[str, ...]
    difficulty: str
    procedure_family_id: str
    scenario_family_id: str
    split_group_keys: dict[str, str]
    dedup_signature: str
    quality_flags: tuple[str, ...] = ()
    rejection_reasons: tuple[str, ...] = ()

    def to_state(self) -> dict[str, Any]:
        d=asdict(self)
        for k in ("behavior_labels","user_known_context","hidden_required_context","required_steps","conditional_logic","safety_requirements","source_fact_ids","source_section_ids","quality_flags","rejection_reasons"):
            d[k]=list(d[k])
        d["recovery_eligibility"]=self.recovery_eligibility.to_state()
        return d
