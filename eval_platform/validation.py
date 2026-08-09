"""Fail-closed validation for the Phase-1 canonical benchmark dataset."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from eval_platform.contracts import (
    CANONICAL_SCHEMA_VERSION,
    DatasetValidationResult,
    EvidenceSourceType,
    ResponseType,
    SuccessCriterion,
    TaskCategory,
)
from eval_platform.dataset import EvaluationSample


SUBCATEGORIES: dict[TaskCategory, frozenset[str]] = {
    TaskCategory.KNOWLEDGE_QA: frozenset({
        "FAQ", "EXACT_SPEC", "AFTER_SALES_POLICY", "REGION_POLICY", "MULTI_DOCUMENT",
    }),
    TaskCategory.TROUBLESHOOTING: frozenset({
        "DIRECT", "MULTI_STEP", "MISSING_INFORMATION", "AMBIGUOUS_SYMPTOM", "RETRIEVAL_RECOVERY",
    }),
    TaskCategory.PRIVATE_BUSINESS_QUERY: frozenset({"ORDER", "TICKET", "WARRANTY", "CROSS_OBJECT"}),
    TaskCategory.MIXED_KNOWLEDGE_STRUCTURED: frozenset({
        "ORDER_POLICY", "PRODUCT_WARRANTY", "TICKET_MANUAL", "ORDER_REGION_POLICY",
    }),
    TaskCategory.SAFETY_GOVERNANCE: frozenset({
        "TENANT_ISOLATION", "USER_ISOLATION", "SESSION_ISOLATION", "PROMPT_INJECTION",
        "PROMPT_INJECTION_USER", "PROMPT_INJECTION_RETRIEVED_CONTENT", "UNAUTHORIZED_TOOL",
        "UNAUTHORIZED_PRIVATE_QUERY", "SENSITIVE_DATA", "IDENTITY_CONFLICT",
        "MEMORY_CROSS_USER", "MEMORY_CROSS_TENANT", "ARTIFACT_CROSS_USER", "ARTIFACT_CROSS_TENANT",
    }),
}


class DatasetValidationError(ValueError):
    def __init__(self, result: DatasetValidationResult):
        self.result = result
        super().__init__("canonical dataset validation failed: " + "; ".join(result.errors[:10]))


def _validate_sample(sample: EvaluationSample) -> list[str]:
    errors: list[str] = []
    prefix = sample.sample_id
    if sample.schema_version != CANONICAL_SCHEMA_VERSION:
        errors.append(f"{prefix}: unsupported schema_version={sample.schema_version}")
    if sample.subcategory not in SUBCATEGORIES[sample.category]:
        errors.append(f"{prefix}: subcategory {sample.subcategory!r} incompatible with {sample.category.value}")

    behavior = sample.expected_behavior
    required_agents = set(behavior.required_agents)
    forbidden_agents = set(behavior.forbidden_agents)
    required_tools = set(behavior.required_tools)
    forbidden_tools = set(behavior.forbidden_tools)
    if required_agents & forbidden_agents:
        errors.append(f"{prefix}: agent cannot be both required and forbidden: {sorted(required_agents & forbidden_agents)}")
    if required_tools & forbidden_tools:
        errors.append(f"{prefix}: tool cannot be both required and forbidden: {sorted(required_tools & forbidden_tools)}")
    if behavior.clarification_required is True and not behavior.required_clarification_slots:
        errors.append(f"{prefix}: clarification_required=true requires at least one slot")
    if behavior.clarification_required is False and behavior.required_clarification_slots:
        errors.append(f"{prefix}: clarification_required=false cannot define required clarification slots")
    if behavior.handoff_required is False and behavior.handoff_reason:
        errors.append(f"{prefix}: handoff_required=false cannot define handoff_reason")
    if behavior.authorization_required is True and sample.runtime_input.identity is None:
        errors.append(f"{prefix}: authorization-required case must provide production-compatible IdentitySpec")

    criteria = sample.task_success_contract.required_criteria
    conditional = sample.task_success_contract.conditional_criteria
    supported_when = {
        "clarification_required==true", "clarification_required=true",
        "handoff_required==true", "handoff_required=true",
        "authorization_required==true", "authorization_required=true",
    }
    conditional_keys = [(item.criterion, "".join(str(item.when).split()).casefold()) for item in conditional]
    if len(set(conditional_keys)) != len(conditional_keys):
        errors.append(f"{prefix}: duplicate conditional success criterion")
    for criterion, when in conditional_keys:
        if when not in supported_when:
            errors.append(f"{prefix}: unsupported conditional criterion expression {when!r}")
    if not criteria:
        errors.append(f"{prefix}: task_success_contract.required_criteria must not be empty")
    if len(set(criteria)) != len(criteria):
        errors.append(f"{prefix}: duplicate success criterion")
    if SuccessCriterion.REQUIRED_TOOLS_CORRECT in criteria and not behavior.required_tools:
        errors.append(f"{prefix}: REQUIRED_TOOLS_CORRECT requires expected_behavior.required_tools")
    if SuccessCriterion.REQUIRED_AGENTS_CORRECT in criteria and not behavior.required_agents:
        errors.append(f"{prefix}: REQUIRED_AGENTS_CORRECT requires expected_behavior.required_agents")
    if SuccessCriterion.CLARIFICATION_CORRECT in criteria and behavior.clarification_required is not True:
        errors.append(f"{prefix}: CLARIFICATION_CORRECT requires clarification_required=true")
    if SuccessCriterion.HANDOFF_CORRECT in criteria and behavior.handoff_required is not True:
        errors.append(f"{prefix}: HANDOFF_CORRECT requires handoff_required=true")
    if SuccessCriterion.FORBIDDEN_TOOLS_NOT_CALLED in criteria and not (behavior.forbidden_tools or any(item.forbidden_tools for item in sample.safety_constraints)):
        errors.append(f"{prefix}: FORBIDDEN_TOOLS_NOT_CALLED requires an explicit forbidden tool")
    if SuccessCriterion.AUTHORIZATION_CORRECT in criteria and behavior.authorization_required is None:
        errors.append(f"{prefix}: AUTHORIZATION_CORRECT requires authorization_required to be specified")
    if SuccessCriterion.NO_SENSITIVE_DATA_LEAK in criteria and not sample.safety_constraints:
        errors.append(f"{prefix}: NO_SENSITIVE_DATA_LEAK requires explicit safety_constraints")
    phase5_safety = {
        SuccessCriterion.NO_UNAUTHORIZED_RETRIEVAL, SuccessCriterion.NO_UNAUTHORIZED_TOOL_EXECUTION,
        SuccessCriterion.NO_UNAUTHORIZED_SIDE_EFFECT, SuccessCriterion.NO_CROSS_TENANT_DATA,
        SuccessCriterion.NO_CROSS_USER_DATA, SuccessCriterion.NO_CROSS_SESSION_STATE_WHEN_FORBIDDEN,
        SuccessCriterion.NO_UNAUTHORIZED_ARTIFACT_ACCESS, SuccessCriterion.NO_UNAUTHORIZED_MEMORY_ACCESS,
        SuccessCriterion.PROMPT_INJECTION_NOT_FOLLOWED, SuccessCriterion.CORRECT_REFUSAL_OR_HANDOFF,
    }
    if any(c in phase5_safety for c in criteria) and not sample.safety_constraints:
        errors.append(f"{prefix}: Phase-5 safety criteria require explicit safety_constraints")
    if SuccessCriterion.NO_UNAUTHORIZED_TOOL_EXECUTION in criteria and not (behavior.forbidden_tools or any(item.forbidden_tools for item in sample.safety_constraints)):
        errors.append(f"{prefix}: NO_UNAUTHORIZED_TOOL_EXECUTION requires an explicit forbidden tool")
    if SuccessCriterion.CORRECT_REFUSAL_OR_HANDOFF in criteria and behavior.response_type not in {ResponseType.REFUSAL, ResponseType.HANDOFF}:
        errors.append(f"{prefix}: CORRECT_REFUSAL_OR_HANDOFF requires expected REFUSAL or HANDOFF")
    if (SuccessCriterion.CRITICAL_FACTS_CORRECT in criteria or SuccessCriterion.CRITICAL_FACTS_GROUNDED in criteria) and not sample.gold_facts:
        errors.append(f"{prefix}: critical-fact criteria require gold_facts")

    evidence_ids = [e.evidence_id for e in sample.gold_evidence]
    if len(set(evidence_ids)) != len(evidence_ids):
        errors.append(f"{prefix}: duplicate gold evidence_id")
    evidence_id_set = set(evidence_ids)
    for evidence in sample.gold_evidence:
        lowered = evidence.evidence_id.lower().replace(" ", "")
        if lowered.startswith("top_k") or lowered.startswith("top-") or lowered.startswith("rank:"):
            errors.append(f"{prefix}: evidence_id must be stable, not runtime rank: {evidence.evidence_id}")
    for fact in sample.gold_facts:
        if fact.critical and not fact.supporting_evidence_ids:
            errors.append(f"{prefix}: critical fact {fact.fact_id} has no supporting evidence")
        missing = set(fact.supporting_evidence_ids) - evidence_id_set
        if missing:
            errors.append(f"{prefix}: fact {fact.fact_id} references missing evidence {sorted(missing)}")

    if sample.category is TaskCategory.PRIVATE_BUSINESS_QUERY and sample.runtime_input.identity is None:
        errors.append(f"{prefix}: private business query requires identity")
    if sample.category is TaskCategory.SAFETY_GOVERNANCE:
        if not sample.safety_constraints or all(item.is_empty for item in sample.safety_constraints):
            errors.append(f"{prefix}: safety/governance case requires non-empty safety_constraints")
    if sample.category is TaskCategory.MIXED_KNOWLEDGE_STRUCTURED:
        source_types = {item.source_type for item in sample.gold_evidence if item.required}
        if EvidenceSourceType.DOCUMENT not in source_types or EvidenceSourceType.STRUCTURED_DATA not in source_types:
            errors.append(f"{prefix}: mixed case requires >=1 required DOCUMENT and >=1 required STRUCTURED_DATA evidence")

    if SuccessCriterion.NO_UNAUTHORIZED_ACCESS in criteria and not (
        behavior.authorization_required is not None or sample.safety_constraints
    ):
        errors.append(f"{prefix}: NO_UNAUTHORIZED_ACCESS requires authorization expectation or safety constraint")
    return errors


def validate_dataset(
    samples: Sequence[EvaluationSample] | Iterable[EvaluationSample],
    *,
    allow_invalid: bool = False,
) -> DatasetValidationResult:
    materialized = tuple(samples)
    errors: list[str] = []
    ids = [item.sample_id for item in materialized]
    duplicates = sorted(case_id for case_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate case_id(s): {duplicates}")
    for sample in materialized:
        errors.extend(_validate_sample(sample))
    result = DatasetValidationResult(valid=not errors, errors=tuple(errors), case_count=len(materialized))
    if errors and not allow_invalid:
        raise DatasetValidationError(result)
    return result
