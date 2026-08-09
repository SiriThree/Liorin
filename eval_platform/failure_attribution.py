"""Versioned deterministic failure attribution over frozen evaluation artifacts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from eval_platform.contracts import (
    ClaimGroundingDiagnostic,
    CriterionStatus,
    EvidenceCaseDiagnostic,
    RecoveryTrace,
    RecoveryFailureReason,
    SuccessCriterion,
    TaskSuccessStatus,
)
from eval_platform.report import CaseJudgment, PredictionRecord
from eval_platform.safety import SafetyCaseDiagnostic, SafetyCaseStatus

FAILURE_TAXONOMY_VERSION = "1.0"
ATTRIBUTION_POLICY_VERSION = "earliest_causal_fail_anywhere_v1"


class FailureDomain(StrEnum):
    INPUT = "INPUT"
    IDENTITY = "IDENTITY"
    UNDERSTANDING = "UNDERSTANDING"
    ROUTING = "ROUTING"
    AUTHORIZATION = "AUTHORIZATION"
    RETRIEVAL = "RETRIEVAL"
    RERANK = "RERANK"
    VERIFIER = "VERIFIER"
    RECOVERY = "RECOVERY"
    TOOL = "TOOL"
    CONTEXT = "CONTEXT"
    MEMORY = "MEMORY"
    ARTIFACT = "ARTIFACT"
    ANSWER = "ANSWER"
    GROUNDING = "GROUNDING"
    SAFETY = "SAFETY"
    EXECUTION = "EXECUTION"
    EVALUATION = "EVALUATION"
    OBSERVABILITY = "OBSERVABILITY"


class FailureStage(StrEnum):
    INPUT = "INPUT"
    IDENTITY = "IDENTITY"
    UNDERSTANDING = "UNDERSTANDING"
    ROUTING = "ROUTING"
    AUTHORIZATION = "AUTHORIZATION"
    RETRIEVAL = "RETRIEVAL"
    RERANK = "RERANK"
    EVIDENCE_VERIFICATION = "EVIDENCE_VERIFICATION"
    RECOVERY = "RECOVERY"
    TOOL = "TOOL"
    CONTEXT = "CONTEXT"
    MEMORY = "MEMORY"
    ARTIFACT = "ARTIFACT"
    ANSWER_GENERATION = "ANSWER_GENERATION"
    GROUNDING = "GROUNDING"
    SAFETY = "SAFETY"
    EXECUTION_INFRA = "EXECUTION_INFRA"
    EVALUATION_INFRA = "EVALUATION_INFRA"
    UNKNOWN = "UNKNOWN"


class FailureCode(StrEnum):
    UNDERSTANDING_ERROR = "UNDERSTANDING_ERROR"
    ROUTING_ERROR = "ROUTING_ERROR"
    IDENTITY_ERROR = "IDENTITY_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    RERANK_ERROR = "RERANK_ERROR"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    VERIFIER_FALSE_ACCEPT = "VERIFIER_FALSE_ACCEPT"
    VERIFIER_FALSE_REJECT = "VERIFIER_FALSE_REJECT"
    QUERY_REWRITE_FAILURE = "QUERY_REWRITE_FAILURE"
    SUPPLEMENT_FAILURE = "SUPPLEMENT_FAILURE"
    DECOMPOSITION_FAILURE = "DECOMPOSITION_FAILURE"
    RELAX_FILTER_FAILURE = "RELAX_FILTER_FAILURE"
    CLARIFICATION_FAILURE = "CLARIFICATION_FAILURE"
    OVER_CLARIFICATION = "OVER_CLARIFICATION"
    HANDOFF_FAILURE = "HANDOFF_FAILURE"
    TOOL_SELECTION_ERROR = "TOOL_SELECTION_ERROR"
    TOOL_ARGUMENT_ERROR = "TOOL_ARGUMENT_ERROR"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    STRUCTURED_DATA_ERROR = "STRUCTURED_DATA_ERROR"
    ANSWER_CORRECTNESS_ERROR = "ANSWER_CORRECTNESS_ERROR"
    GROUNDING_ERROR = "GROUNDING_ERROR"
    HALLUCINATION = "HALLUCINATION"
    CITATION_ERROR = "CITATION_ERROR"
    CONTEXT_REQUIRED_FACT_DROPPED = "CONTEXT_REQUIRED_FACT_DROPPED"
    CONTEXT_BUDGET_EXHAUSTED = "CONTEXT_BUDGET_EXHAUSTED"
    SUMMARY_LOST_REQUIRED_FACT = "SUMMARY_LOST_REQUIRED_FACT"
    SUMMARY_HALLUCINATION = "SUMMARY_HALLUCINATION"
    MEMORY_NOT_WRITTEN = "MEMORY_NOT_WRITTEN"
    MEMORY_NOT_RETRIEVED = "MEMORY_NOT_RETRIEVED"
    MEMORY_NOT_SELECTED = "MEMORY_NOT_SELECTED"
    MEMORY_STALE = "MEMORY_STALE"
    MEMORY_CONTAMINATION = "MEMORY_CONTAMINATION"
    ARTIFACT_NOT_REGISTERED = "ARTIFACT_NOT_REGISTERED"
    ARTIFACT_NOT_RESOLVED = "ARTIFACT_NOT_RESOLVED"
    ARTIFACT_WRONG_IDENTITY = "ARTIFACT_WRONG_IDENTITY"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    PROMPT_INJECTION_FAILURE = "PROMPT_INJECTION_FAILURE"
    PII_LEAKAGE = "PII_LEAKAGE"
    TIMEOUT = "TIMEOUT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    OBSERVABILITY_INSUFFICIENT = "OBSERVABILITY_INSUFFICIENT"
    EVALUATION_INFRASTRUCTURE_ERROR = "EVALUATION_INFRASTRUCTURE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AttributionEligibilityStatus(StrEnum):
    ATTRIBUTABLE = "ATTRIBUTABLE"
    PARTIALLY_ATTRIBUTABLE = "PARTIALLY_ATTRIBUTABLE"
    OBSERVABILITY_INSUFFICIENT = "OBSERVABILITY_INSUFFICIENT"
    EVALUATION_INCOMPLETE = "EVALUATION_INCOMPLETE"
    NOT_FAILED = "NOT_FAILED"


_STAGE_ORDER = {
    FailureStage.INPUT: 0,
    FailureStage.IDENTITY: 1,
    FailureStage.UNDERSTANDING: 2,
    FailureStage.ROUTING: 3,
    FailureStage.AUTHORIZATION: 4,
    FailureStage.RETRIEVAL: 5,
    FailureStage.RERANK: 6,
    FailureStage.EVIDENCE_VERIFICATION: 7,
    FailureStage.RECOVERY: 8,
    FailureStage.TOOL: 9,
    FailureStage.CONTEXT: 10,
    FailureStage.MEMORY: 11,
    FailureStage.ARTIFACT: 12,
    FailureStage.ANSWER_GENERATION: 13,
    FailureStage.GROUNDING: 14,
    FailureStage.SAFETY: 15,
    FailureStage.EXECUTION_INFRA: 16,
    FailureStage.EVALUATION_INFRA: 17,
    FailureStage.UNKNOWN: 99,
}


@dataclass(frozen=True, slots=True)
class FailureEvidence:
    failure_code: FailureCode
    domain: FailureDomain
    primary: bool
    stage: FailureStage
    reason: str
    criterion_refs: tuple[str, ...] = ()
    trace_event_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    judge_refs: tuple[str, ...] = ()
    confidence: float = 1.0
    deterministic: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        return {
            "failure_code": self.failure_code.value,
            "domain": self.domain.value,
            "primary": self.primary,
            "stage": self.stage.value,
            "reason": self.reason,
            "criterion_refs": list(self.criterion_refs),
            "trace_event_refs": list(self.trace_event_refs),
            "evidence_refs": list(self.evidence_refs),
            "judge_refs": list(self.judge_refs),
            "confidence": self.confidence,
            "deterministic": self.deterministic,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CaseFailureAttribution:
    case_id: str
    run_id: str | None
    trace_id: str | None
    task_success_status: TaskSuccessStatus | None
    eligibility: AttributionEligibilityStatus
    primary_failure: FailureEvidence | None
    secondary_failures: tuple[FailureEvidence, ...]
    causal_explanation: str
    failure_taxonomy_version: str = FAILURE_TAXONOMY_VERSION
    attribution_policy_version: str = ATTRIBUTION_POLICY_VERSION

    @property
    def all_failures(self) -> tuple[FailureEvidence, ...]:
        return tuple(x for x in ((self.primary_failure,) + self.secondary_failures) if x is not None)

    def to_state(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "task_success_status": self.task_success_status.value if self.task_success_status else None,
            "eligibility": self.eligibility.value,
            "primary_failure": self.primary_failure.to_state() if self.primary_failure else None,
            "secondary_failures": [x.to_state() for x in self.secondary_failures],
            "causal_explanation": self.causal_explanation,
            "failure_taxonomy_version": self.failure_taxonomy_version,
            "attribution_policy_version": self.attribution_policy_version,
        }


def _failure(code: FailureCode, domain: FailureDomain, stage: FailureStage, reason: str, **kwargs: Any) -> FailureEvidence:
    return FailureEvidence(code, domain, False, stage, reason, **kwargs)


def _criterion_failures(judgment: CaseJudgment) -> list[FailureEvidence]:
    rows: list[FailureEvidence] = []
    for item in judgment.criterion_judgments:
        if item.status is not CriterionStatus.FAIL:
            continue
        criterion = item.criterion
        mapping = {
            SuccessCriterion.REQUIRED_AGENTS_CORRECT: (FailureCode.ROUTING_ERROR, FailureDomain.ROUTING, FailureStage.ROUTING),
            SuccessCriterion.REQUIRED_TOOLS_CORRECT: (FailureCode.TOOL_SELECTION_ERROR, FailureDomain.TOOL, FailureStage.TOOL),
            SuccessCriterion.FORBIDDEN_TOOLS_NOT_CALLED: (FailureCode.TOOL_SELECTION_ERROR, FailureDomain.TOOL, FailureStage.TOOL),
            SuccessCriterion.AUTHORIZATION_CORRECT: (FailureCode.AUTHORIZATION_ERROR, FailureDomain.AUTHORIZATION, FailureStage.AUTHORIZATION),
            SuccessCriterion.CLARIFICATION_CORRECT: (FailureCode.CLARIFICATION_FAILURE, FailureDomain.RECOVERY, FailureStage.RECOVERY),
            SuccessCriterion.HANDOFF_CORRECT: (FailureCode.HANDOFF_FAILURE, FailureDomain.RECOVERY, FailureStage.RECOVERY),
            SuccessCriterion.CRITICAL_FACTS_CORRECT: (FailureCode.ANSWER_CORRECTNESS_ERROR, FailureDomain.ANSWER, FailureStage.ANSWER_GENERATION),
            SuccessCriterion.CRITICAL_FACTS_GROUNDED: (FailureCode.GROUNDING_ERROR, FailureDomain.GROUNDING, FailureStage.GROUNDING),
            SuccessCriterion.NO_CRITICAL_HALLUCINATION: (FailureCode.HALLUCINATION, FailureDomain.ANSWER, FailureStage.ANSWER_GENERATION),
            SuccessCriterion.NO_SENSITIVE_DATA_LEAK: (FailureCode.PII_LEAKAGE, FailureDomain.SAFETY, FailureStage.SAFETY),
            SuccessCriterion.NO_UNAUTHORIZED_ACCESS: (FailureCode.SAFETY_VIOLATION, FailureDomain.SAFETY, FailureStage.SAFETY),
            SuccessCriterion.NO_UNAUTHORIZED_RETRIEVAL: (FailureCode.SAFETY_VIOLATION, FailureDomain.SAFETY, FailureStage.RETRIEVAL),
            SuccessCriterion.NO_UNAUTHORIZED_TOOL_EXECUTION: (FailureCode.SAFETY_VIOLATION, FailureDomain.SAFETY, FailureStage.TOOL),
            SuccessCriterion.NO_UNAUTHORIZED_SIDE_EFFECT: (FailureCode.SAFETY_VIOLATION, FailureDomain.SAFETY, FailureStage.TOOL),
            SuccessCriterion.NO_CROSS_TENANT_DATA: (FailureCode.SAFETY_VIOLATION, FailureDomain.SAFETY, FailureStage.SAFETY),
            SuccessCriterion.NO_CROSS_USER_DATA: (FailureCode.SAFETY_VIOLATION, FailureDomain.SAFETY, FailureStage.SAFETY),
            SuccessCriterion.NO_UNAUTHORIZED_MEMORY_ACCESS: (FailureCode.MEMORY_CONTAMINATION, FailureDomain.MEMORY, FailureStage.MEMORY),
            SuccessCriterion.NO_UNAUTHORIZED_ARTIFACT_ACCESS: (FailureCode.ARTIFACT_WRONG_IDENTITY, FailureDomain.ARTIFACT, FailureStage.ARTIFACT),
            SuccessCriterion.PROMPT_INJECTION_NOT_FOLLOWED: (FailureCode.PROMPT_INJECTION_FAILURE, FailureDomain.SAFETY, FailureStage.INPUT),
        }
        if criterion not in mapping:
            continue
        code, domain, stage = mapping[criterion]
        rows.append(_failure(
            code, domain, stage, item.reason,
            criterion_refs=(criterion.value,), trace_event_refs=tuple(item.trace_refs),
            evidence_refs=tuple(item.evidence_refs), judge_refs=tuple(x for x in (item.judge_record_id,) if x),
            deterministic=item.evaluation_method.value != "LLM_JUDGE",
        ))
    return rows


def _diagnostic_failures(
    evidence: EvidenceCaseDiagnostic | None,
    grounding: ClaimGroundingDiagnostic | None,
    recovery: RecoveryTrace | None,
    safety: SafetyCaseDiagnostic | None,
) -> list[FailureEvidence]:
    rows: list[FailureEvidence] = []
    if evidence is not None:
        if evidence.eligibility.status.value in {"OBSERVABILITY_INSUFFICIENT", "UNSUPPORTED_PREDICTION_VERSION"}:
            rows.append(_failure(FailureCode.OBSERVABILITY_INSUFFICIENT, FailureDomain.OBSERVABILITY, FailureStage.UNKNOWN, "; ".join(evidence.eligibility.reasons)))
        elif evidence.required_gold_evidence_recall_denominator and evidence.required_gold_evidence_recall_numerator < evidence.required_gold_evidence_recall_denominator:
            # Distinguish raw retrieval miss from selection/rerank failure.
            retrieved = {x.stable_id for x in evidence.retrieved_evidence}
            selected = {x.stable_id for x in evidence.selected_evidence}
            if evidence.missing_required_units:
                rows.append(_failure(FailureCode.RETRIEVAL_MISS, FailureDomain.RETRIEVAL, FailureStage.RETRIEVAL, f"required evidence units missing: {list(evidence.missing_required_units)}", evidence_refs=tuple(sorted(retrieved))))
            elif retrieved and selected != retrieved:
                rows.append(_failure(FailureCode.RERANK_ERROR, FailureDomain.RERANK, FailureStage.RERANK, "required evidence was retrieved but not preserved in selected evidence", evidence_refs=tuple(sorted(selected))))
    if grounding is not None:
        if grounding.contradicted_critical_claims:
            rows.append(_failure(FailureCode.HALLUCINATION, FailureDomain.ANSWER, FailureStage.GROUNDING, f"{grounding.contradicted_critical_claims} critical claim(s) contradicted evidence"))
        if grounding.unsupported_critical_claims:
            rows.append(_failure(FailureCode.GROUNDING_ERROR, FailureDomain.GROUNDING, FailureStage.GROUNDING, f"{grounding.unsupported_critical_claims} unsupported critical claim(s)"))
        if not grounding.complete:
            rows.append(_failure(FailureCode.OBSERVABILITY_INSUFFICIENT, FailureDomain.OBSERVABILITY, FailureStage.GROUNDING, grounding.reason or "claim grounding incomplete"))
    if recovery is not None:
        fp = recovery.first_pass
        if fp.false_accept:
            rows.append(_failure(FailureCode.VERIFIER_FALSE_ACCEPT, FailureDomain.VERIFIER, FailureStage.EVIDENCE_VERIFICATION, fp.reason))
        if fp.false_reject:
            rows.append(_failure(FailureCode.VERIFIER_FALSE_REJECT, FailureDomain.VERIFIER, FailureStage.EVIDENCE_VERIFICATION, fp.reason))
        if recovery.failure_reason:
            mapping = {
                RecoveryFailureReason.RETRIEVAL_MISS: (FailureCode.RETRIEVAL_MISS, FailureDomain.RETRIEVAL),
                RecoveryFailureReason.QUERY_REWRITE_INEFFECTIVE: (FailureCode.QUERY_REWRITE_FAILURE, FailureDomain.RECOVERY),
                RecoveryFailureReason.SUPPLEMENT_INEFFECTIVE: (FailureCode.SUPPLEMENT_FAILURE, FailureDomain.RECOVERY),
                RecoveryFailureReason.WRONG_CLARIFICATION: (FailureCode.CLARIFICATION_FAILURE, FailureDomain.RECOVERY),
                RecoveryFailureReason.OVER_CLARIFICATION: (FailureCode.OVER_CLARIFICATION, FailureDomain.RECOVERY),
                RecoveryFailureReason.BUDGET_EXHAUSTED: (FailureCode.BUDGET_EXHAUSTED, FailureDomain.RECOVERY),
                RecoveryFailureReason.TOOL_ERROR: (FailureCode.TOOL_EXECUTION_ERROR, FailureDomain.TOOL),
                RecoveryFailureReason.AUTHORIZATION_BLOCKED: (FailureCode.AUTHORIZATION_ERROR, FailureDomain.AUTHORIZATION),
                RecoveryFailureReason.GROUNDING_FAILURE: (FailureCode.GROUNDING_ERROR, FailureDomain.GROUNDING),
                RecoveryFailureReason.ANSWER_FAILURE: (FailureCode.ANSWER_CORRECTNESS_ERROR, FailureDomain.ANSWER),
                RecoveryFailureReason.OBSERVABILITY_INSUFFICIENT: (FailureCode.OBSERVABILITY_INSUFFICIENT, FailureDomain.OBSERVABILITY),
            }
            code_domain = mapping.get(recovery.failure_reason)
            if code_domain:
                code, domain = code_domain
                stage = FailureStage.RECOVERY if domain is FailureDomain.RECOVERY else FailureStage[domain.value] if domain.value in FailureStage.__members__ else FailureStage.UNKNOWN
                rows.append(_failure(code, domain, stage, f"recovery outcome: {recovery.failure_reason.value}"))
    if safety is not None:
        for violation in safety.violations:
            code = FailureCode.PROMPT_INJECTION_FAILURE if violation.criterion is SuccessCriterion.PROMPT_INJECTION_NOT_FOLLOWED else FailureCode.PII_LEAKAGE if violation.criterion is SuccessCriterion.NO_SENSITIVE_DATA_LEAK else FailureCode.SAFETY_VIOLATION
            rows.append(_failure(
                code, FailureDomain.SAFETY, FailureStage.SAFETY, violation.reason,
                criterion_refs=(violation.criterion.value,), trace_event_refs=violation.trace_event_ids,
                evidence_refs=tuple(x for x in (violation.resource_ref,) if x),
                metadata={"zero_tolerance": violation.criterion.value in {"NO_CROSS_TENANT_DATA", "NO_CROSS_USER_DATA", "NO_UNAUTHORIZED_SIDE_EFFECT", "NO_UNAUTHORIZED_ARTIFACT_ACCESS", "NO_UNAUTHORIZED_MEMORY_ACCESS"}},
            ))
    return rows


def _dedupe(rows: Sequence[FailureEvidence]) -> list[FailureEvidence]:
    result: list[FailureEvidence] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (row.failure_code, row.stage, row.reason)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def attribute_failure(
    judgment: CaseJudgment,
    prediction: PredictionRecord | None,
    *,
    evidence: EvidenceCaseDiagnostic | None = None,
    grounding: ClaimGroundingDiagnostic | None = None,
    recovery: RecoveryTrace | None = None,
    safety: SafetyCaseDiagnostic | None = None,
    context_diagnostics: Mapping[str, Any] | None = None,
) -> CaseFailureAttribution:
    status = judgment.task_success_status
    if status is TaskSuccessStatus.PASS:
        return CaseFailureAttribution(judgment.case_id, judgment.run_id, judgment.trace_id, status, AttributionEligibilityStatus.NOT_FAILED, None, (), "task passed; no failure attribution")
    if status is TaskSuccessStatus.INCOMPLETE:
        item = _failure(FailureCode.EVALUATION_INFRASTRUCTURE_ERROR, FailureDomain.EVALUATION, FailureStage.EVALUATION_INFRA, judgment.rationale or "evaluation incomplete")
        primary = FailureEvidence(**{**asdict(item), "primary": True})
        return CaseFailureAttribution(judgment.case_id, judgment.run_id, judgment.trace_id, status, AttributionEligibilityStatus.EVALUATION_INCOMPLETE, primary, (), primary.reason)
    if status is TaskSuccessStatus.EXECUTION_ERROR:
        error = (prediction.execution_error if prediction else None) or judgment.rationale or "production execution failed"
        code = FailureCode.TIMEOUT if "timeout" in error.casefold() else FailureCode.INTERNAL_ERROR
        item = _failure(code, FailureDomain.EXECUTION, FailureStage.EXECUTION_INFRA, error)
        primary = FailureEvidence(**{**asdict(item), "primary": True})
        return CaseFailureAttribution(judgment.case_id, judgment.run_id, judgment.trace_id, status, AttributionEligibilityStatus.ATTRIBUTABLE, primary, (), primary.reason)

    rows = _criterion_failures(judgment)
    rows.extend(_diagnostic_failures(evidence, grounding, recovery, safety))
    context = dict(context_diagnostics or {})
    for code_name, reason in (
        ("CONTEXT_REQUIRED_FACT_DROPPED", context.get("context_required_fact_dropped")),
        ("CONTEXT_BUDGET_EXHAUSTED", context.get("context_budget_exhausted")),
        ("SUMMARY_LOST_REQUIRED_FACT", context.get("summary_lost_required_fact")),
        ("MEMORY_CONTAMINATION", context.get("memory_contamination")),
        ("ARTIFACT_NOT_RESOLVED", context.get("artifact_not_resolved")),
    ):
        if reason:
            code = FailureCode(code_name)
            if code_name.startswith("CONTEXT") or code_name.startswith("SUMMARY"):
                domain, stage = FailureDomain.CONTEXT, FailureStage.CONTEXT
            elif code_name.startswith("MEMORY"):
                domain, stage = FailureDomain.MEMORY, FailureStage.MEMORY
            else:
                domain, stage = FailureDomain.ARTIFACT, FailureStage.ARTIFACT
            rows.append(_failure(code, domain, stage, str(reason)))
    rows = _dedupe(rows)
    if not rows:
        obs = _failure(FailureCode.OBSERVABILITY_INSUFFICIENT, FailureDomain.OBSERVABILITY, FailureStage.UNKNOWN, "Task failed but frozen diagnostics do not support a reliable causal attribution", confidence=0.0)
        primary = FailureEvidence(**{**asdict(obs), "primary": True})
        return CaseFailureAttribution(judgment.case_id, judgment.run_id, judgment.trace_id, status, AttributionEligibilityStatus.OBSERVABILITY_INSUFFICIENT, primary, (), primary.reason)

    # Critical safety violations are unacceptable system behavior and take primary
    # precedence. Otherwise use the earliest causal stage supported by diagnostics.
    safety_critical = [x for x in rows if x.domain is FailureDomain.SAFETY and bool(x.metadata.get("zero_tolerance"))]
    if safety_critical:
        chosen = safety_critical[0]
    else:
        chosen = sorted(rows, key=lambda x: (_STAGE_ORDER.get(x.stage, 99), 0 if x.deterministic else 1))[0]
    primary = FailureEvidence(**{**asdict(chosen), "primary": True})
    secondary = tuple(x for x in rows if x is not chosen)
    partial = any(x.failure_code is FailureCode.OBSERVABILITY_INSUFFICIENT for x in rows)
    eligibility = AttributionEligibilityStatus.PARTIALLY_ATTRIBUTABLE if partial else AttributionEligibilityStatus.ATTRIBUTABLE
    return CaseFailureAttribution(
        judgment.case_id, judgment.run_id, judgment.trace_id, status, eligibility,
        primary, secondary,
        f"primary={primary.failure_code.value} at {primary.stage.value}; selected by {ATTRIBUTION_POLICY_VERSION}",
    )


def aggregate_failure_attribution(rows: Sequence[CaseFailureAttribution], *, total_cases: int | None = None) -> dict[str, Any]:
    failed = [x for x in rows if x.task_success_status in {TaskSuccessStatus.FAIL, TaskSuccessStatus.EXECUTION_ERROR}]
    attributable = [x for x in failed if x.eligibility is AttributionEligibilityStatus.ATTRIBUTABLE]
    partial = [x for x in failed if x.eligibility is AttributionEligibilityStatus.PARTIALLY_ATTRIBUTABLE]
    obs = [x for x in failed if x.eligibility is AttributionEligibilityStatus.OBSERVABILITY_INSUFFICIENT]
    denominator = len(failed)
    from collections import Counter
    domains = Counter(x.primary_failure.domain.value for x in failed if x.primary_failure)
    codes = Counter(x.primary_failure.failure_code.value for x in failed if x.primary_failure)
    overall = total_cases if total_cases is not None else len(rows)
    return {
        "failure_taxonomy_version": FAILURE_TAXONOMY_VERSION,
        "attribution_policy_version": ATTRIBUTION_POLICY_VERSION,
        "failed_cases": denominator,
        "attribution_coverage": {"numerator": len(attributable), "denominator": denominator, "rate": len(attributable)/denominator if denominator else None},
        "partially_attributable": len(partial),
        "observability_insufficient": len(obs),
        "primary_domains": {
            key: {"count": count, "share_of_failures": count/denominator if denominator else None, "rate_overall_cases": count/overall if overall else None}
            for key, count in domains.most_common()
        },
        "primary_codes": {
            key: {"count": count, "share_of_failures": count/denominator if denominator else None, "rate_overall_cases": count/overall if overall else None}
            for key, count in codes.most_common()
        },
    }


__all__ = [
    "FAILURE_TAXONOMY_VERSION", "ATTRIBUTION_POLICY_VERSION", "FailureDomain", "FailureStage", "FailureCode",
    "AttributionEligibilityStatus", "FailureEvidence", "CaseFailureAttribution", "attribute_failure",
    "aggregate_failure_attribution",
]
