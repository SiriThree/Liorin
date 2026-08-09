from __future__ import annotations

from eval_platform import (
    CriterionJudgment,
    CriterionStatus,
    EvaluationMethod,
    SuccessCriterion,
    TaskSuccessContract,
    TaskSuccessEvaluator,
    TaskSuccessStatus,
)


def j(criterion, status):
    return CriterionJudgment(
        criterion=criterion,
        status=status,
        evaluation_method=EvaluationMethod.DETERMINISTIC,
        required=True,
        reason="fixture",
    )


def test_all_required_pass_means_task_pass():
    contract = TaskSuccessContract((SuccessCriterion.RESPONSE_TYPE_CORRECT, SuccessCriterion.CRITICAL_FACTS_CORRECT))
    result = TaskSuccessEvaluator().evaluate(contract, (
        j(SuccessCriterion.RESPONSE_TYPE_CORRECT, CriterionStatus.PASS),
        j(SuccessCriterion.CRITICAL_FACTS_CORRECT, CriterionStatus.PASS),
    ))
    assert result.task_success is TaskSuccessStatus.PASS
    assert result.task_success_bool is True


def test_one_required_fail_means_task_fail_without_weighting():
    contract = TaskSuccessContract((SuccessCriterion.RESPONSE_TYPE_CORRECT, SuccessCriterion.CRITICAL_FACTS_CORRECT))
    result = TaskSuccessEvaluator().evaluate(contract, (
        j(SuccessCriterion.RESPONSE_TYPE_CORRECT, CriterionStatus.PASS),
        j(SuccessCriterion.CRITICAL_FACTS_CORRECT, CriterionStatus.FAIL),
    ))
    assert result.task_success is TaskSuccessStatus.FAIL
    assert result.task_success_bool is False
    assert result.failed_criteria == (SuccessCriterion.CRITICAL_FACTS_CORRECT,)


def test_required_error_is_incomplete_not_pass_or_agent_fail():
    contract = TaskSuccessContract((SuccessCriterion.CRITICAL_FACTS_CORRECT,))
    result = TaskSuccessEvaluator().evaluate(contract, (
        j(SuccessCriterion.CRITICAL_FACTS_CORRECT, CriterionStatus.ERROR),
    ))
    assert result.task_success is TaskSuccessStatus.INCOMPLETE
    assert result.task_success_bool is None


def test_production_execution_error_is_separate_status_but_aggregate_failure():
    contract = TaskSuccessContract((SuccessCriterion.RESPONSE_TYPE_CORRECT,))
    result = TaskSuccessEvaluator().evaluate(contract, (), execution_failed=True)
    assert result.task_success is TaskSuccessStatus.EXECUTION_ERROR
    assert result.task_success_bool is None


def test_required_not_applicable_is_incomplete_not_silently_passed():
    contract = TaskSuccessContract((SuccessCriterion.REQUIRED_TOOLS_CORRECT,))
    result = TaskSuccessEvaluator().evaluate(contract, (
        j(SuccessCriterion.REQUIRED_TOOLS_CORRECT, CriterionStatus.NOT_APPLICABLE),
    ))
    assert result.task_success is TaskSuccessStatus.INCOMPLETE
    assert result.task_success_bool is None
