from eval_platform import (
    AnnotationMetadata, AnnotationStatus, ComparisonMode, DatasetSplit, Difficulty,
    EvidenceSourceType, ExpectedBehavior, FactValueType, GoldEvidence, GoldFact,
    ResponseType, RuntimeCaseInput, TaskCategory, TaskSuccessContract, EvaluationSample,
    ClaimSupportStatus, evaluate_claim_grounding, evaluate_evidence_case,
)
from eval_platform.judge import JudgeConfig, JudgeRuntime
from eval_platform.report import PredictionRecord


def fixture():
    evidence=GoldEvidence("g1",EvidenceSourceType.DOCUMENT,document_id="m.md",section_id="s1")
    fact=GoldFact("window","window",30,FactValueType.INTEGER,True,("g1",),ComparisonMode.NUMERIC)
    sample=EvaluationSample(
        sample_id="claim-case",runtime_input=RuntimeCaseInput(case_id="claim-case",messages=({"role":"user","content":"退货多久？"},)),
        split=DatasetSplit.DEVELOPMENT,category=TaskCategory.KNOWLEDGE_QA,subcategory="FAQ",difficulty=Difficulty.EASY,
        expected_behavior=ExpectedBehavior(ResponseType.ANSWER,clarification_required=False,handoff_required=False),
        task_success_contract=TaskSuccessContract(()),gold_evidence=(evidence,),gold_facts=(fact,),annotation_metadata=AnnotationMetadata(AnnotationStatus.MIGRATED_LEGACY),
    )
    pred=PredictionRecord(case_id="claim-case",trace_id="t",final_response="退货窗口为30天。",response_type="answer",trace_facts={
        "evidence_events":[{"event":"verified","status":"accepted","round_id":1,"evidence_id":"e1","stable_ref":"doc:m.md#s1","document_id":"m.md","section_id":"s1","content_preview":"标准退货窗口为30天。","fusion_rank":1}],
        "selected_evidence_ids":["e1"],"verification_rounds":[{"round_id":1,"action":"accept","accepted_evidence_ids":["e1"]}]
    },runtime_metrics={})
    return sample,pred


class ClaimProvider:
    def __init__(self, entailment="SUPPORTED"): self.entailment=entailment
    def invoke(self, request, config):
        if request.prompt_version=="claim_extraction_v1":
            return {"claims":[{"claim_id":"c1","text":"退货窗口为30天","critical":True,"claim_type":"POLICY","normalized_subject":"return","normalized_predicate":"window","normalized_value":30,"source_span":"退货窗口为30天","gold_fact_id":"window"}],"rationale":"atomic"}
        if request.prompt_version=="claim_evidence_entailment_v1":
            return {"entailment_status":self.entailment,"rationale":"fixture entailment"}
        raise AssertionError(request.prompt_version)


def test_grounded_claim_rate_supported_and_not_verifiable_policy():
    sample,pred=fixture()
    evidence=evaluate_evidence_case(sample,pred)
    judge=JudgeRuntime(JudgeConfig("c","stub","stub",max_retries=0),ClaimProvider("SUPPORTED"))
    row=evaluate_claim_grounding(sample,pred,evidence,judge=judge)
    assert row.grounded_claim_numerator==1 and row.grounded_claim_denominator==1
    assert row.supports[0].status is ClaimSupportStatus.SUPPORTED
    no_judge=evaluate_claim_grounding(sample,pred,evidence,judge=None)
    assert no_judge.complete is False and no_judge.grounded_claim_denominator==0


def test_claim_entailment_contradicted_is_not_grounded():
    sample,pred=fixture()
    evidence=evaluate_evidence_case(sample,pred)
    judge=JudgeRuntime(JudgeConfig("c","stub","stub",max_retries=0),ClaimProvider("CONTRADICTED"))
    row=evaluate_claim_grounding(sample,pred,evidence,judge=judge)
    assert row.contradicted_critical_claims==1
    assert row.grounded_claim_numerator==0 and row.grounded_claim_denominator==1
