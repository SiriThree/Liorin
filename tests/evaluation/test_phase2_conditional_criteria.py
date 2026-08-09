from __future__ import annotations

from eval_platform import (
    AnnotationMetadata,
    AnnotationStatus,
    ConditionalSuccessCriterion,
    DatasetSplit,
    Difficulty,
    ExpectedBehavior,
    EvaluationSample,
    ResponseType,
    RuntimeCaseInput,
    SuccessCriterion,
    TaskCategory,
    TaskSuccessContract,
)
from eval_platform.criteria import resolve_conditional_criteria
from eval_platform.validation import DatasetValidationError, validate_dataset


def make_sample(*, clarification_required=True, when="clarification_required == true"):
    return EvaluationSample(
        sample_id="conditional-1",
        runtime_input=RuntimeCaseInput(case_id="conditional-1", messages=({"role":"user","content":"q"},)),
        split=DatasetSplit.DEVELOPMENT,
        category=TaskCategory.TROUBLESHOOTING,
        subcategory="MISSING_INFORMATION",
        difficulty=Difficulty.MEDIUM,
        expected_behavior=ExpectedBehavior(
            ResponseType.CLARIFICATION if clarification_required else ResponseType.ANSWER,
            clarification_required=clarification_required,
            required_clarification_slots=("product_model",) if clarification_required else (),
            handoff_required=False,
        ),
        task_success_contract=TaskSuccessContract(
            (SuccessCriterion.RESPONSE_TYPE_CORRECT,),
            (ConditionalSuccessCriterion(SuccessCriterion.CLARIFICATION_CORRECT, when),),
        ),
        annotation_metadata=AnnotationMetadata(AnnotationStatus.MIGRATED_LEGACY),
    )


def test_conditional_criterion_activates_only_when_condition_is_true():
    active = make_sample(clarification_required=True)
    inactive = make_sample(clarification_required=False)
    assert resolve_conditional_criteria(active) == (SuccessCriterion.CLARIFICATION_CORRECT,)
    assert resolve_conditional_criteria(inactive) == ()


def test_unknown_conditional_expression_fails_dataset_validation_closed():
    sample = make_sample(when="mystery_runtime_flag == true")
    try:
        validate_dataset((sample,))
    except DatasetValidationError as exc:
        assert "unsupported conditional criterion expression" in str(exc)
    else:
        raise AssertionError("unsupported conditional expression must fail validation")
