from eval_platform.contracts import (
    CriterionJudgment, CriterionStatus, EvaluationMethod, TaskSuccessStatus, SuccessCriterion,
)
from eval_platform.failure_attribution import (
    AttributionEligibilityStatus, FailureCode, FailureDomain, attribute_failure,
)
from eval_platform.report import CaseJudgment, PredictionRecord
from eval_platform.safety import (
    SafetyCaseDiagnostic, SafetyCaseStatus, SafetyCriterionResult, SafetyEligibilityStatus,
    SafetyEvaluationEligibility, SafetySeverity, SafetyViolationStage,
)


def judgment(status=TaskSuccessStatus.FAIL, *criteria):
    return CaseJudgment(
        case_id="c", run_id="r", execution_status="COMPLETED", criterion_judgments=tuple(criteria),
        task_success_status=status, task_success_bool=False if status is TaskSuccessStatus.FAIL else None,
        failed_criteria=tuple(x.criterion for x in criteria if x.status is CriterionStatus.FAIL), trace_id="t",
        rationale="failed",
    )


def cj(criterion, reason="bad"):
    return CriterionJudgment(criterion, CriterionStatus.FAIL, EvaluationMethod.DETERMINISTIC, True, reason)


def pred(error=None):
    return PredictionRecord("c","t","answer","answer",{}, {}, execution_status="FAILED" if error else "COMPLETED", execution_error=error, schema_version="5.0")


def test_routing_is_primary_before_tool_and_answer_consequences():
    j=judgment(TaskSuccessStatus.FAIL, cj(SuccessCriterion.REQUIRED_AGENTS_CORRECT,"wrong route"), cj(SuccessCriterion.REQUIRED_TOOLS_CORRECT,"wrong tool"), cj(SuccessCriterion.CRITICAL_FACTS_CORRECT,"wrong answer"))
    a=attribute_failure(j,pred())
    assert a.primary_failure.failure_code is FailureCode.ROUTING_ERROR
    assert {x.failure_code for x in a.secondary_failures} >= {FailureCode.TOOL_SELECTION_ERROR, FailureCode.ANSWER_CORRECTNESS_ERROR}


def test_zero_tolerance_safety_takes_primary_precedence():
    j=judgment(TaskSuccessStatus.FAIL, cj(SuccessCriterion.CRITICAL_FACTS_CORRECT,"wrong answer"))
    violation=SafetyCriterionResult(
        SuccessCriterion.NO_CROSS_TENANT_DATA, CriterionStatus.FAIL, SafetySeverity.CRITICAL,
        violation_stage=SafetyViolationStage.RETRIEVAL, reason="cross tenant", metadata={}
    )
    s=SafetyCaseDiagnostic("c","r","t",SafetyEvaluationEligibility("c",SafetyEligibilityStatus.ELIGIBLE),(),(violation,),SafetyCaseStatus.FAIL,1,1,False,task_failing_violation=True)
    a=attribute_failure(j,pred(),safety=s)
    assert a.primary_failure.domain is FailureDomain.SAFETY
    assert a.primary_failure.failure_code is FailureCode.SAFETY_VIOLATION


def test_judge_infrastructure_incomplete_is_not_agent_failure():
    j=judgment(TaskSuccessStatus.INCOMPLETE)
    a=attribute_failure(j,pred())
    assert a.eligibility is AttributionEligibilityStatus.EVALUATION_INCOMPLETE
    assert a.primary_failure.failure_code is FailureCode.EVALUATION_INFRASTRUCTURE_ERROR


def test_execution_timeout_is_attributed_to_execution_infra():
    j=judgment(TaskSuccessStatus.EXECUTION_ERROR)
    a=attribute_failure(j,pred("TimeoutError: model call timed out"))
    assert a.primary_failure.failure_code is FailureCode.TIMEOUT


def test_context_loss_can_be_primary_before_answer_error():
    j=judgment(TaskSuccessStatus.FAIL, cj(SuccessCriterion.CRITICAL_FACTS_CORRECT,"wrong answer"))
    a=attribute_failure(j,pred(),context_diagnostics={"context_required_fact_dropped":"product_model FR-200 dropped"})
    assert a.primary_failure.failure_code is FailureCode.CONTEXT_REQUIRED_FACT_DROPPED


def test_memory_contamination_can_be_primary_before_answer_error():
    j=judgment(TaskSuccessStatus.FAIL, cj(SuccessCriterion.CRITICAL_FACTS_CORRECT,"wrong answer"))
    a=attribute_failure(j,pred(),context_diagnostics={"memory_contamination":"superseded FR-100 selected"})
    assert a.primary_failure.failure_code is FailureCode.MEMORY_CONTAMINATION


def test_artifact_resolution_failure_can_precede_answer_error():
    j=judgment(TaskSuccessStatus.FAIL, cj(SuccessCriterion.CRITICAL_FACTS_CORRECT,"wrong answer"))
    a=attribute_failure(j,pred(),context_diagnostics={"artifact_not_resolved":"artifact ref missing"})
    assert a.primary_failure.failure_code is FailureCode.ARTIFACT_NOT_RESOLVED


def test_retrieval_miss_precedes_verifier_and_hallucination():
    from eval_platform.contracts import EvidenceCaseDiagnostic, EvidenceEvaluationEligibility, EvidenceEvaluationEligibilityStatus
    evidence=EvidenceCaseDiagnostic(
        case_id="c", trace_id="t", eligibility=EvidenceEvaluationEligibility("c",EvidenceEvaluationEligibilityStatus.ELIGIBLE),
        any_required_evidence_recall_at_k={5:False}, required_gold_evidence_recall_numerator=0,
        required_gold_evidence_recall_denominator=1, selected_evidence_precision_numerator=0,
        selected_evidence_precision_denominator=0, selected_evidence_precision_complete=True,
        missing_required_units=("gold-policy",),
    )
    j=judgment(TaskSuccessStatus.FAIL, cj(SuccessCriterion.NO_CRITICAL_HALLUCINATION,"hallucinated"))
    a=attribute_failure(j,pred(),evidence=evidence)
    assert a.primary_failure.failure_code is FailureCode.RETRIEVAL_MISS
    assert FailureCode.HALLUCINATION in {x.failure_code for x in a.secondary_failures}


def test_retrieved_but_not_selected_is_not_called_retrieval_miss():
    from eval_platform.contracts import EvidenceCaseDiagnostic, EvidenceEvaluationEligibility, EvidenceEvaluationEligibilityStatus, EvaluationEvidenceRef, EvidenceSourceType
    got=EvaluationEvidenceRef(stable_id="doc:d#s",source_type=EvidenceSourceType.DOCUMENT,document_id="d",section_id="s")
    other=EvaluationEvidenceRef(stable_id="doc:d#other",source_type=EvidenceSourceType.DOCUMENT,document_id="d",section_id="other",selected=True)
    evidence=EvidenceCaseDiagnostic(
        case_id="c", trace_id="t", eligibility=EvidenceEvaluationEligibility("c",EvidenceEvaluationEligibilityStatus.ELIGIBLE),
        any_required_evidence_recall_at_k={5:True}, required_gold_evidence_recall_numerator=1,
        required_gold_evidence_recall_denominator=1, selected_evidence_precision_numerator=0,
        selected_evidence_precision_denominator=1, selected_evidence_precision_complete=True,
        retrieved_evidence=(got,), selected_evidence=(other,), missing_required_units=(),
    )
    # Criterion fails because required grounding was lost after retrieval.
    j=judgment(TaskSuccessStatus.FAIL, cj(SuccessCriterion.CRITICAL_FACTS_GROUNDED,"gold evidence not selected"))
    a=attribute_failure(j,pred(),evidence=evidence)
    assert a.primary_failure.failure_code in {FailureCode.RERANK_ERROR, FailureCode.GROUNDING_ERROR}
    assert a.primary_failure.failure_code is not FailureCode.RETRIEVAL_MISS
