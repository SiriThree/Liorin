from eval_platform import (
    AnnotationMetadata, AnnotationStatus, DatasetSplit, Difficulty, EvidenceSourceType,
    ExpectedBehavior, GoldEvidence, ResponseType, RuntimeCaseInput, TaskCategory,
    TaskSuccessContract, EvaluationSample, FirstPassStatus, TaskSuccessStatus,
    CaseJudgment, evaluate_first_pass, build_recovery_trace, aggregate_recovery_metrics,
)
from eval_platform.report import PredictionRecord


def sample():
    g1=GoldEvidence("g1",EvidenceSourceType.DOCUMENT,document_id="m.md",section_id="s1")
    g2=GoldEvidence("g2",EvidenceSourceType.DOCUMENT,document_id="m.md",section_id="s2")
    return EvaluationSample(
        sample_id="r",runtime_input=RuntimeCaseInput(case_id="r",messages=({"role":"user","content":"q"},)),
        split=DatasetSplit.DEVELOPMENT,category=TaskCategory.TROUBLESHOOTING,subcategory="RETRIEVAL_RECOVERY",difficulty=Difficulty.HARD,
        expected_behavior=ExpectedBehavior(ResponseType.ANSWER,clarification_required=False,handoff_required=False,allowed_recovery_actions=("rewrite","supplement","clarify","handoff")),
        task_success_contract=TaskSuccessContract(()),gold_evidence=(g1,g2),annotation_metadata=AnnotationMetadata(AnnotationStatus.MIGRATED_LEGACY),
    )


def pred(*, first_action="rewrite", second=True, auth=False):
    events=[{"event":"verified","status":"accepted","round_id":1,"evidence_id":"e1","stable_ref":"doc:m.md#s1","document_id":"m.md","section_id":"s1","fusion_rank":1}]
    rounds=[{"round_id":1,"action":first_action,"accepted_evidence_ids":["e1"],"new_evidence_ids":["e1"],"budget_before":{},"budget_after":{}}]
    actions=[first_action] if first_action!="accept" else []
    if second:
        events.append({"event":"verified","status":"accepted","round_id":2,"evidence_id":"e2","stable_ref":"doc:m.md#s2","document_id":"m.md","section_id":"s2","fusion_rank":1})
        rounds.append({"round_id":2,"action":"accept","accepted_evidence_ids":["e1","e2"],"new_evidence_ids":["e2"],"budget_before":{},"budget_after":{}})
    return PredictionRecord(case_id="r",trace_id="t",final_response="ok",response_type="answer",trace_facts={
        "evidence_events":events,"verification_rounds":rounds,"first_pass_verifier_action":first_action,"recovery_actions":actions,
        "authorization_decisions":[{"allowed":False}] if auth else [],
    },runtime_metrics={})


def judgment(status=TaskSuccessStatus.PASS):
    return CaseJudgment("r","run","COMPLETED",(),status, True if status is TaskSuccessStatus.PASS else False)


def test_first_pass_missing_evidence_and_rewrite_recovery_success():
    s=sample(); p=pred()
    first=evaluate_first_pass(s,p)
    assert first.status is FirstPassStatus.INSUFFICIENT_EVIDENCE
    assert first.gold_sufficient is False
    trace=build_recovery_trace(s,p,judgment())
    assert trace.recoverable and trace.recovery_rounds==1 and trace.actions==("rewrite",)
    metrics=aggregate_recovery_metrics((trace,))
    assert metrics["first_pass_failure_recovery_rate"]=={"numerator":1,"denominator":1,"rate":1.0}
    assert metrics["success_within_1_round"]["numerator"]==1


def test_first_pass_sufficient_but_recovery_is_false_reject_and_unnecessary():
    s=sample()
    p=pred(first_action="rewrite",second=False)
    # Make all Gold visible in round 1 while verifier still asks rewrite.
    p=PredictionRecord.from_state({**p.to_state(),"trace_facts":{**p.trace_facts,"evidence_events":[
        {"event":"verified","status":"accepted","round_id":1,"evidence_id":"e1","stable_ref":"doc:m.md#s1","document_id":"m.md","section_id":"s1","fusion_rank":1},
        {"event":"verified","status":"accepted","round_id":1,"evidence_id":"e2","stable_ref":"doc:m.md#s2","document_id":"m.md","section_id":"s2","fusion_rank":2},
    ]}})
    first=evaluate_first_pass(s,p)
    assert first.status is FirstPassStatus.SUFFICIENT and first.false_reject
    trace=build_recovery_trace(s,p,judgment())
    assert trace.unnecessary_recovery is True


def test_nonrecoverable_authorization_block_excluded_from_recovery_denominator():
    s=sample()
    s=EvaluationSample.from_dict({**s.to_dict(),"expected_behavior":{**s.to_dict()["expected_behavior"],"authorization_required":True}})
    p=pred(auth=True)
    first=evaluate_first_pass(s,p)
    assert first.status is FirstPassStatus.AUTHORIZATION_BLOCKED
    trace=build_recovery_trace(s,p,judgment(TaskSuccessStatus.FAIL))
    metrics=aggregate_recovery_metrics((trace,))
    assert metrics["first_pass_failure_recovery_rate"]["denominator"]==0


def test_verifier_false_accept_when_gold_missing_but_verifier_accepts():
    s=sample(); p=pred(first_action="accept",second=False)
    first=evaluate_first_pass(s,p)
    assert first.false_accept and first.reason=="VERIFIER_FALSE_ACCEPT"
