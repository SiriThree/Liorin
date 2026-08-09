"""Formal binary/conjunctive Task Success aggregation for Phase 2."""
from __future__ import annotations

from collections.abc import Sequence

from eval_platform.contracts import (
    CriterionJudgment,
    CriterionStatus,
    SuccessCriterion,
    TaskSuccessContract,
    TaskSuccessResult,
    TaskSuccessStatus,
)


class TaskSuccessEvaluator:
    """Aggregate required criterion judgments without weights or thresholds."""

    def evaluate(
        self,
        contract: TaskSuccessContract,
        judgments: Sequence[CriterionJudgment],
        *,
        execution_failed: bool = False,
        resolved_required_criteria: Sequence[SuccessCriterion] | None = None,
    ) -> TaskSuccessResult:
        required = tuple(dict.fromkeys(resolved_required_criteria or contract.required_criteria))
        if execution_failed:
            return TaskSuccessResult(
                task_success=TaskSuccessStatus.EXECUTION_ERROR,
                required_criteria_total=len(required),
                required_criteria_passed=0,
                failed_criteria=required,
                reason="production execution failed; counted as task failure in aggregate quality denominator",
            )

        by_criterion = {item.criterion: item for item in judgments if item.required}
        missing = tuple(criterion for criterion in required if criterion not in by_criterion)
        if missing:
            return TaskSuccessResult(
                task_success=TaskSuccessStatus.INCOMPLETE,
                required_criteria_total=len(required),
                required_criteria_passed=sum(
                    1 for criterion in required
                    if criterion in by_criterion and by_criterion[criterion].status is CriterionStatus.PASS
                ),
                incomplete_criteria=missing,
                diagnostic_criteria=tuple(item.criterion for item in judgments if not item.required),
                reason=f"required criterion missing from evaluation registry/output: {[c.value for c in missing]}",
            )

        failed = tuple(c for c in required if by_criterion[c].status is CriterionStatus.FAIL)
        incomplete = tuple(
            c for c in required
            if by_criterion[c].status in {
                CriterionStatus.ERROR,
                CriterionStatus.NOT_EVALUATED,
                CriterionStatus.NOT_APPLICABLE,
            }
        )
        passed_count = sum(1 for c in required if by_criterion[c].status is CriterionStatus.PASS)
        diagnostic = tuple(item.criterion for item in judgments if not item.required)

        if failed:
            return TaskSuccessResult(
                task_success=TaskSuccessStatus.FAIL,
                required_criteria_total=len(required),
                required_criteria_passed=passed_count,
                failed_criteria=failed,
                incomplete_criteria=incomplete,
                diagnostic_criteria=diagnostic,
                reason=f"required criterion failed: {[c.value for c in failed]}",
            )
        if incomplete:
            return TaskSuccessResult(
                task_success=TaskSuccessStatus.INCOMPLETE,
                required_criteria_total=len(required),
                required_criteria_passed=passed_count,
                incomplete_criteria=incomplete,
                diagnostic_criteria=diagnostic,
                reason=f"required criterion not evaluable: {[c.value for c in incomplete]}",
            )
        return TaskSuccessResult(
            task_success=TaskSuccessStatus.PASS,
            required_criteria_total=len(required),
            required_criteria_passed=passed_count,
            diagnostic_criteria=diagnostic,
            reason="all required criteria passed",
        )


__all__ = ["TaskSuccessEvaluator"]
