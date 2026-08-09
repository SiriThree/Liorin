"""Gold-aware first-pass and Agentic Recovery evaluation over frozen traces."""
from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any, Mapping, Sequence

from eval_platform.contracts import (
    EvidenceSourceType,
    FirstPassEvaluation,
    FirstPassStatus,
    RecoveryEvaluationEligibility,
    RecoveryEvaluationEligibilityStatus,
    RecoveryFailureReason,
    RecoveryOutcome,
    RecoveryRound,
    RecoveryTrace,
    SuccessCriterion,
    TaskSuccessStatus,
)
from eval_platform.dataset import EvaluationSample
from eval_platform.evidence import _required_units, _unit_matches, prediction_evidence_refs
from eval_platform.report import CaseJudgment, PredictionRecord


RECOVERY_ACTIONS = {"supplement", "rewrite", "decompose", "relax", "relax_filters", "clarify", "handoff"}
NON_RECOVERABLE_FIRST_PASS = {FirstPassStatus.AUTHORIZATION_BLOCKED, FirstPassStatus.EXECUTION_ERROR}


def _first_round_refs(prediction: PredictionRecord):
    refs = prediction_evidence_refs(prediction)
    round_ids = [r.round_id for r in refs if r.round_id is not None]
    if not round_ids:
        return ()
    first = min(round_ids)
    return tuple(r for r in refs if r.round_id == first)


def _authorization_blocked(prediction: PredictionRecord) -> bool:
    decisions = prediction.trace_facts.get("authorization_decisions") or ()
    return any(isinstance(x, Mapping) and x.get("allowed") is False for x in decisions)


def _first_verification(prediction: PredictionRecord) -> Mapping[str, Any] | None:
    rows = prediction.trace_facts.get("verification_rounds") or ()
    return rows[0] if rows and isinstance(rows[0], Mapping) else None


def evaluate_first_pass(sample: EvaluationSample, prediction: PredictionRecord) -> FirstPassEvaluation:
    action = str(prediction.trace_facts.get("first_pass_verifier_action") or "") or None
    if prediction.execution_status.upper() not in {"COMPLETED", "SUCCESS", "OK"}:
        return FirstPassEvaluation(sample.sample_id, FirstPassStatus.EXECUTION_ERROR, False, action, None, reason="production execution failed")
    first_verification = _first_verification(prediction)
    if first_verification is None:
        return FirstPassEvaluation(sample.sample_id, FirstPassStatus.UNKNOWN, None, action, None, reason="NO_FIRST_PASS_TRACE")
    prod_sufficient = (str(first_verification.get("action") or "").lower() == "accept")
    first_refs = _first_round_refs(prediction)
    units = _required_units(sample.gold_evidence)

    if _authorization_blocked(prediction) and sample.expected_behavior.authorization_required:
        gold_sufficient = False
        status = FirstPassStatus.AUTHORIZATION_BLOCKED
        missing = tuple(name for name, _ in units)
    elif sample.expected_behavior.clarification_required is True and str(first_verification.get("action") or "").lower() == "clarify":
        gold_sufficient = False
        status = FirstPassStatus.MISSING_REQUIRED_SLOT
        missing = tuple(sample.expected_behavior.required_clarification_slots)
    elif any(g.source_type is EvidenceSourceType.STRUCTURED_DATA and g.required for g in sample.gold_evidence) and not any(r.source_type is EvidenceSourceType.STRUCTURED_DATA for r in prediction_evidence_refs(prediction)):
        # We know the Gold requires structured evidence, but Phase-2 production
        # tracing cannot prove whether the specialist actually acquired it.
        return FirstPassEvaluation(
            sample.sample_id,
            FirstPassStatus.UNKNOWN,
            None,
            action,
            prod_sufficient,
            first_pass_evidence_refs=tuple(r.stable_id for r in first_refs),
            reason="OBSERVABILITY_INSUFFICIENT: required structured evidence is not projected into production trace",
        )
    else:
        found = [name for name, unit in units if _unit_matches(unit, first_refs)]
        missing = tuple(name for name, unit in units if not _unit_matches(unit, first_refs))
        gold_sufficient = bool(units) and len(found) == len(units)
        conflicts = first_verification.get("conflicts") or ()
        unresolved = any(isinstance(x, Mapping) and bool(x.get("unresolved")) for x in conflicts)
        if unresolved:
            status = FirstPassStatus.CONFLICT_UNRESOLVED
            gold_sufficient = False
        elif not units:
            # Non-evidence safety/clarification tasks cannot be independently
            # judged as first-pass evidence-sufficient from GoldEvidence.
            status = FirstPassStatus.UNKNOWN
            gold_sufficient = None
        elif gold_sufficient:
            status = FirstPassStatus.SUFFICIENT
        else:
            status = FirstPassStatus.INSUFFICIENT_EVIDENCE

    false_accept = gold_sufficient is False and prod_sufficient is True
    false_reject = gold_sufficient is True and prod_sufficient is False
    return FirstPassEvaluation(
        case_id=sample.sample_id,
        status=status,
        gold_sufficient=gold_sufficient,
        production_verifier_action=str(first_verification.get("action") or "") or action,
        production_verifier_sufficient=prod_sufficient,
        false_accept=false_accept,
        false_reject=false_reject,
        first_pass_evidence_refs=tuple(r.stable_id for r in first_refs),
        missing_required_units=missing,
        reason=(
            "VERIFIER_FALSE_ACCEPT" if false_accept else
            "VERIFIER_FALSE_REJECT" if false_reject else
            "Gold-aware first-pass sufficiency derived from round-1 trace and required Gold evidence"
        ),
    )


def recovery_eligibility(sample: EvaluationSample, prediction: PredictionRecord, first: FirstPassEvaluation) -> RecoveryEvaluationEligibility:
    if first.status is FirstPassStatus.UNKNOWN:
        reason = "NO_FIRST_PASS_TRACE" if first.reason == "NO_FIRST_PASS_TRACE" else first.reason
        return RecoveryEvaluationEligibility(sample.sample_id, RecoveryEvaluationEligibilityStatus.NO_FIRST_PASS_TRACE if reason == "NO_FIRST_PASS_TRACE" else RecoveryEvaluationEligibilityStatus.UNSUPPORTED, (reason,))
    if first.status is FirstPassStatus.SUFFICIENT:
        return RecoveryEvaluationEligibility(sample.sample_id, RecoveryEvaluationEligibilityStatus.NON_RECOVERABLE, ("first pass already sufficient",))
    if first.status in NON_RECOVERABLE_FIRST_PASS:
        return RecoveryEvaluationEligibility(sample.sample_id, RecoveryEvaluationEligibilityStatus.NON_RECOVERABLE, (f"{first.status.value} is not a recoverable retrieval/reasoning miss",))
    if not sample.gold_evidence and first.status is not FirstPassStatus.MISSING_REQUIRED_SLOT:
        return RecoveryEvaluationEligibility(sample.sample_id, RecoveryEvaluationEligibilityStatus.MISSING_GOLD_EVIDENCE, ("recovery task lacks GoldEvidence",))
    if not (prediction.trace_facts.get("verification_rounds") or prediction.trace_facts.get("recovery_actions")):
        return RecoveryEvaluationEligibility(sample.sample_id, RecoveryEvaluationEligibilityStatus.MISSING_RECOVERY_TRACE, ("production trace has no verifier/recovery events",))
    return RecoveryEvaluationEligibility(sample.sample_id, RecoveryEvaluationEligibilityStatus.ELIGIBLE)


def _recovery_rounds(prediction: PredictionRecord) -> tuple[RecoveryRound, ...]:
    verifications = [x for x in (prediction.trace_facts.get("verification_rounds") or ()) if isinstance(x, Mapping)]
    recovery_events = [x for x in (prediction.trace_facts.get("recovery_events") or ()) if isinstance(x, Mapping)]
    rounds: list[RecoveryRound] = []
    # Each non-ACCEPT verifier decision initiates one recovery action. If a new
    # retrieval/verification round exists, attach its new evidence and budget.
    for idx, row in enumerate(verifications):
        action = str(row.get("action") or "").lower()
        if action not in RECOVERY_ACTIONS:
            continue
        next_row = verifications[idx + 1] if idx + 1 < len(verifications) else {}
        event = next((e for e in recovery_events if str(e.get("step") or "") in {
            "rewrite_query" if action == "rewrite" else "targeted_retrieve" if action in {"supplement", "relax", "relax_filters"} else "replan" if action == "decompose" else action
        }), {})
        generated = event.get("generated_subqueries") or row.get("generated_subqueries") or ()
        input_query = None
        rewritten_query = None
        if generated and isinstance(generated[0], Mapping):
            input_query = str(generated[0].get("query") or "") or None
        if action == "rewrite":
            rewritten_query = str(event.get("rewritten_question") or input_query or "") or None
        requested_slot = None
        if action == "clarify":
            requested_slot = str(event.get("requested_slot") or event.get("slot") or "") or None
        rounds.append(RecoveryRound(
            round_index=len(rounds) + 1,
            action=action,
            input_query=input_query,
            rewritten_query=rewritten_query,
            requested_slot=requested_slot,
            new_evidence=tuple(str(x) for x in (next_row.get("new_evidence_ids") or ())),
            verifier_decision=str(next_row.get("action") or "") or None,
            latency_ms=float(event.get("latency_ms")) if isinstance(event.get("latency_ms"), (int, float)) else None,
            error=str(event.get("error") or "") or None,
            budget_before=dict(next_row.get("budget_before") or row.get("budget_before") or {}),
            budget_after=dict(next_row.get("budget_after") or row.get("budget_after") or {}),
        ))
    return tuple(rounds)


def _outcome(prediction: PredictionRecord, judgment: CaseJudgment) -> RecoveryOutcome:
    if judgment.task_success_status is TaskSuccessStatus.INCOMPLETE:
        return RecoveryOutcome.INCOMPLETE_EVALUATION
    if judgment.task_success_status is not TaskSuccessStatus.PASS:
        return RecoveryOutcome.FINAL_TASK_FAILED
    response_type = str(prediction.response_type or "").upper()
    actions = {str(x).lower() for x in prediction.trace_facts.get("recovery_actions") or ()}
    if "HANDOFF" in response_type or "handoff" in actions:
        return RecoveryOutcome.RESOLVED_BY_HANDOFF
    if "CLARIFICATION" in response_type or "clarify" in actions:
        return RecoveryOutcome.RESOLVED_BY_CLARIFICATION
    if "REFUSAL" in response_type:
        return RecoveryOutcome.SAFELY_ABSTAINED
    return RecoveryOutcome.RESOLVED_BY_ANSWER


def _failure_reason(first: FirstPassEvaluation, rounds: Sequence[RecoveryRound], judgment: CaseJudgment) -> RecoveryFailureReason | None:
    if judgment.task_success_status is TaskSuccessStatus.PASS:
        return None
    if first.false_accept:
        return RecoveryFailureReason.VERIFIER_FALSE_ACCEPT
    if first.false_reject:
        return RecoveryFailureReason.VERIFIER_FALSE_REJECT
    if first.status is FirstPassStatus.AUTHORIZATION_BLOCKED:
        return RecoveryFailureReason.AUTHORIZATION_BLOCKED
    if first.status is FirstPassStatus.CONFLICT_UNRESOLVED:
        return RecoveryFailureReason.CONFLICT_UNRESOLVED
    actions = [r.action for r in rounds]
    if "rewrite" in actions:
        return RecoveryFailureReason.QUERY_REWRITE_INEFFECTIVE
    if "supplement" in actions or "relax" in actions or "relax_filters" in actions:
        return RecoveryFailureReason.SUPPLEMENT_INEFFECTIVE
    if "clarify" in actions:
        return RecoveryFailureReason.WRONG_CLARIFICATION
    failed = set(judgment.failed_criteria)
    if SuccessCriterion.CRITICAL_FACTS_GROUNDED in failed:
        return RecoveryFailureReason.GROUNDING_FAILURE
    if SuccessCriterion.CRITICAL_FACTS_CORRECT in failed or SuccessCriterion.NO_CRITICAL_HALLUCINATION in failed:
        return RecoveryFailureReason.ANSWER_FAILURE
    return RecoveryFailureReason.RETRIEVAL_MISS if first.status is FirstPassStatus.INSUFFICIENT_EVIDENCE else RecoveryFailureReason.UNKNOWN


def build_recovery_trace(sample: EvaluationSample, prediction: PredictionRecord, judgment: CaseJudgment) -> RecoveryTrace:
    first = evaluate_first_pass(sample, prediction)
    eligibility = recovery_eligibility(sample, prediction, first)
    rounds = _recovery_rounds(prediction)
    actions = tuple(r.action for r in rounds if r.action)
    unnecessary = first.status is FirstPassStatus.SUFFICIENT and bool(actions)
    recoverable = first.status not in NON_RECOVERABLE_FIRST_PASS and first.status not in {FirstPassStatus.SUFFICIENT, FirstPassStatus.UNKNOWN}
    return RecoveryTrace(
        case_id=sample.sample_id,
        trace_id=prediction.trace_id,
        eligibility=eligibility,
        first_pass=first,
        rounds=rounds,
        actions=actions,
        recoverable=recoverable,
        final_task_success=judgment.task_success_status,
        outcome=_outcome(prediction, judgment),
        failure_reason=_failure_reason(first, rounds, judgment),
        recovery_rounds=len(rounds),
        unnecessary_recovery=unnecessary,
    )


def _percentile(values: Sequence[int], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def aggregate_recovery_metrics(traces: Sequence[RecoveryTrace]) -> dict[str, Any]:
    observed = [t for t in traces if t.first_pass.gold_sufficient is not None]
    failures = [t for t in observed if t.first_pass.gold_sufficient is False]
    recoverable = [t for t in failures if t.recoverable and t.eligibility.eligible]
    recovered = [t for t in recoverable if t.final_task_success is TaskSuccessStatus.PASS]
    rounds = [t.recovery_rounds for t in recoverable]
    unnecessary_candidates = [t for t in observed if t.first_pass.gold_sufficient is True]
    action_counts = Counter(action for t in traces for action in t.actions)
    action_success = Counter(action for t in traces if t.final_task_success is TaskSuccessStatus.PASS for action in set(t.actions))
    false_accept = sum(t.first_pass.false_accept for t in observed)
    false_reject = sum(t.first_pass.false_reject for t in observed)
    verifier_accept = [t for t in observed if t.first_pass.production_verifier_sufficient is True]
    gold_sufficient = [t for t in observed if t.first_pass.gold_sufficient is True]
    true_accept = sum(t.first_pass.gold_sufficient is True and t.first_pass.production_verifier_sufficient is True for t in observed)
    return {
        "first_pass_failure_rate": {
            "numerator": len(failures), "denominator": len(observed), "rate": len(failures) / len(observed) if observed else None,
        },
        "first_pass_failure_recovery_rate": {
            "numerator": len(recovered), "denominator": len(recoverable), "rate": len(recovered) / len(recoverable) if recoverable else None,
        },
        "raw_first_pass_failure_outcome": {
            "numerator": sum(t.final_task_success is TaskSuccessStatus.PASS for t in failures),
            "denominator": len(failures),
            "rate": sum(t.final_task_success is TaskSuccessStatus.PASS for t in failures) / len(failures) if failures else None,
        },
        "average_recovery_rounds": sum(rounds) / len(rounds) if rounds else None,
        "recovery_rounds_p50": _percentile(rounds, 0.50),
        "recovery_rounds_p95": _percentile(rounds, 0.95),
        "recovery_rounds_max": max(rounds) if rounds else None,
        "success_within_1_round": {
            "numerator": sum(t.final_task_success is TaskSuccessStatus.PASS and t.recovery_rounds <= 1 for t in recoverable),
            "denominator": len(recoverable),
            "rate": sum(t.final_task_success is TaskSuccessStatus.PASS and t.recovery_rounds <= 1 for t in recoverable) / len(recoverable) if recoverable else None,
        },
        "success_within_2_rounds": {
            "numerator": sum(t.final_task_success is TaskSuccessStatus.PASS and t.recovery_rounds <= 2 for t in recoverable),
            "denominator": len(recoverable),
            "rate": sum(t.final_task_success is TaskSuccessStatus.PASS and t.recovery_rounds <= 2 for t in recoverable) / len(recoverable) if recoverable else None,
        },
        "unnecessary_recovery_rate": {
            "numerator": sum(t.unnecessary_recovery for t in unnecessary_candidates),
            "denominator": len(unnecessary_candidates),
            "rate": sum(t.unnecessary_recovery for t in unnecessary_candidates) / len(unnecessary_candidates) if unnecessary_candidates else None,
        },
        "recovery_action_distribution": dict(sorted(action_counts.items())),
        "recovery_success_by_action": {
            action: {"numerator": action_success[action], "denominator": count, "rate": action_success[action] / count if count else None}
            for action, count in sorted(action_counts.items())
        },
        "failure_reasons": dict(sorted(Counter(t.failure_reason.value for t in traces if t.failure_reason).items())),
        "verifier": {
            "true_accept": true_accept,
            "false_accept": false_accept,
            "false_reject": false_reject,
            "true_reject": sum(t.first_pass.gold_sufficient is False and t.first_pass.production_verifier_sufficient is False for t in observed),
            "sufficiency_precision": true_accept / len(verifier_accept) if verifier_accept else None,
            "sufficiency_recall": true_accept / len(gold_sufficient) if gold_sufficient else None,
            "false_accept_rate": false_accept / len(failures) if failures else None,
            "false_reject_rate": false_reject / len(gold_sufficient) if gold_sufficient else None,
        },
    }
