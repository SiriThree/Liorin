from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from eval_platform import (
    AnnotationMetadata,
    AnnotationStatus,
    CaseJudgment,
    ComparisonMode,
    DatasetSplit,
    Difficulty,
    EvidenceSourceType,
    EvaluationEligibilityStatus,
    ExpectedBehavior,
    FactValueType,
    FormalEvaluationRunner,
    GoldEvidence,
    GoldFact,
    JudgeConfig,
    JudgeRuntime,
    PredictionRecord,
    ProductionEvaluationAdapter,
    ResponseType,
    RuntimeCaseInput,
    SuccessCriterion,
    TaskCategory,
    TaskSuccessContract,
    TaskSuccessStatus,
    EvaluationSample,
    build_formal_summary,
)
from observability import RuntimeEventType, TraceRecorder


class PassingGraph:
    def __init__(self, recorder):
        self.recorder = recorder
        self.calls = 0
        self.states = []

    def invoke(self, state, *, config=None, context=None):
        self.calls += 1
        self.states.append((state, config, context))
        self.recorder.emit(RuntimeEventType.TOOL_STARTED, attributes={"tool_name":"knowledge_agent"})
        self.recorder.emit(RuntimeEventType.RETRIEVAL_EVENT, attributes={
            "step":"evidence", "stage":"evidence", "event":"verified", "status":"accepted",
            "data":{"evidence_id":"sec-1", "document_id":"manual.md", "section_id":"sec-1", "retrieval_contributions":[]},
        })
        self.recorder.emit(RuntimeEventType.RETRIEVAL_EVENT, attributes={
            "step":"verify_evidence", "stage":"verify_evidence", "event":"complete", "status":"complete",
            "data":{"round_id":1,"action":"accept"},
        })
        return {"messages":[*state["messages"], {"role":"assistant","content":"退货窗口是 30 天。"}]}


class BombAdapter:
    def run(self, case):
        raise AssertionError("score_existing_predictions must never call production")


def canonical(*, annotation=AnnotationStatus.MIGRATED_LEGACY, semantic=False):
    evidence = GoldEvidence("doc:manual.md#sec-1", EvidenceSourceType.DOCUMENT, document_id="manual.md", section_id="sec-1")
    fact = GoldFact(
        "return_window", "return window", "退货窗口是 30 天" if semantic else 30,
        FactValueType.STRING if semantic else FactValueType.INTEGER,
        True, (evidence.evidence_id,), ComparisonMode.SEMANTIC if semantic else ComparisonMode.NUMERIC,
    )
    return EvaluationSample(
        sample_id="formal-1",
        runtime_input=RuntimeCaseInput(case_id="formal-1", messages=({"role":"user","content":"退货窗口多久？"},)),
        split=DatasetSplit.DEVELOPMENT,
        category=TaskCategory.KNOWLEDGE_QA,
        subcategory="FAQ",
        difficulty=Difficulty.EASY,
        expected_behavior=ExpectedBehavior(ResponseType.ANSWER, clarification_required=False, handoff_required=False),
        task_success_contract=TaskSuccessContract((
            SuccessCriterion.RESPONSE_TYPE_CORRECT,
            SuccessCriterion.CRITICAL_FACTS_CORRECT,
            SuccessCriterion.CRITICAL_FACTS_GROUNDED,
        )),
        gold_evidence=(evidence,),
        gold_facts=(fact,),
        annotation_metadata=AnnotationMetadata(annotation),
    )


def test_formal_runner_one_execution_binary_pass_and_artifact_separation(tmp_path):
    recorder = TraceRecorder()
    graph = PassingGraph(recorder)
    adapter = ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder)
    runner = FormalEvaluationRunner(production_adapter=adapter)
    run = runner.run((canonical(),), output_dir=tmp_path, dataset_name="fixture", dataset_version="1")
    assert graph.calls == 1
    assert len(run.predictions) == 1
    assert run.judgments[0].task_success_status is TaskSuccessStatus.PASS
    prediction_text = (tmp_path / "predictions.jsonl").read_text(encoding="utf-8")
    assert "gold_facts" not in prediction_text
    assert "task_success_contract" not in prediction_text
    judgment_text = (tmp_path / "judgments.jsonl").read_text(encoding="utf-8")
    assert "CRITICAL_FACTS_CORRECT" in judgment_text
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["overall_end_to_end_task_success"]["numerator"] == 1
    assert summary["overall_end_to_end_task_success"]["denominator"] == 1


def test_ineligible_needs_review_case_is_reported_and_not_executed(tmp_path):
    recorder = TraceRecorder()
    graph = PassingGraph(recorder)
    runner = FormalEvaluationRunner(production_adapter=ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder))
    run = runner.run((canonical(annotation=AnnotationStatus.NEEDS_REVIEW),), output_dir=tmp_path)
    assert graph.calls == 0
    assert run.predictions == ()
    assert run.judgments[0].eligibility_status is EvaluationEligibilityStatus.NEEDS_REVIEW
    assert run.judgments[0].task_success_status is None


def test_semantic_required_fact_without_judge_is_incomplete_not_pass():
    recorder = TraceRecorder()
    graph = PassingGraph(recorder)
    runner = FormalEvaluationRunner(production_adapter=ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder))
    run = runner.run((canonical(semantic=True),))
    assert run.judgments[0].task_success_status is TaskSuccessStatus.INCOMPLETE
    assert run.judgments[0].task_success_bool is None


def test_score_existing_predictions_never_reexecutes_production(tmp_path):
    s = canonical()
    prediction = PredictionRecord(
        case_id=s.sample_id,
        run_id="saved-run",
        trace_id="saved-trace",
        final_response="退货窗口是 30 天。",
        response_type="answer",
        trace_facts={"evidence_refs":["doc:manual.md#sec-1"],"selected_evidence_ids":["doc:manual.md#sec-1"]},
        runtime_metrics={},
        execution_status="COMPLETED",
    )
    frozen = prediction.to_state().copy()
    runner = FormalEvaluationRunner(production_adapter=BombAdapter())
    run = runner.score_existing_predictions((s,), (prediction,), output_dir=tmp_path)
    assert run.judgments[0].task_success_status is TaskSuccessStatus.PASS
    assert prediction.to_state() == frozen
    assert run.metadata["scoring_mode"] == "SCORE_EXISTING_PREDICTIONS_NO_PRODUCTION_EXECUTION"
    assert (tmp_path / "evidence_summary.json").exists()
    assert (tmp_path / "recovery_summary.json").exists()
    assert (tmp_path / "case_evidence_diagnostics.jsonl").exists()
    assert (tmp_path / "case_recovery_diagnostics.jsonl").exists()


def test_quality_denominator_counts_execution_errors_but_excludes_incomplete():
    s = canonical()
    samples = tuple(replace(s, sample_id=f"c{i}", runtime_input=replace(s.runtime_input, case_id=f"c{i}")) for i in range(4))
    judgments = (
        CaseJudgment("c0","r","COMPLETED",(),TaskSuccessStatus.PASS,True),
        CaseJudgment("c1","r","COMPLETED",(),TaskSuccessStatus.FAIL,False),
        CaseJudgment("c2","r","FAILED",(),TaskSuccessStatus.EXECUTION_ERROR,None),
        CaseJudgment("c3","r","COMPLETED",(),TaskSuccessStatus.INCOMPLETE,None),
    )
    summary = build_formal_summary(samples, judgments)
    assert summary["overall_end_to_end_task_success"] == {"numerator":1,"denominator":3,"rate":1/3}
    assert summary["incomplete_evaluation_rate"]["numerator"] == 1


def test_judge_sees_gold_only_after_production_prediction_is_frozen():
    class CapturingProvider:
        def __init__(self): self.requests=[]
        def invoke(self, request, config):
            self.requests.append(request)
            return {"status":"PASS","fact_results":[{"fact_id":"return_window","status":"PASS","reason":"present"}],"unsupported_critical_claims":[],"rationale":"supported"}
    provider = CapturingProvider()
    judge = JudgeRuntime(JudgeConfig("test","stub","stub",max_retries=0), provider)
    recorder = TraceRecorder()
    graph = PassingGraph(recorder)
    runner = FormalEvaluationRunner(production_adapter=ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder), judge_runtime=judge)
    run = runner.run((canonical(semantic=True),))
    state, config, context = graph.states[0]
    serialized_runtime = json.dumps({"state":state,"config":config,"context":context}, ensure_ascii=False)
    assert "gold_facts" not in serialized_runtime
    assert "return_window" not in serialized_runtime
    assert provider.requests and provider.requests[0].structured_input["gold_facts"][0]["fact_id"] == "return_window"
    # NO_CRITICAL_HALLUCINATION is not in this fixture contract, so only one Judge call is required.
    assert run.judgments[0].task_success_status is TaskSuccessStatus.PASS


def test_runner_fails_closed_on_invalid_dataset_before_production_execution():
    from eval_platform.validation import DatasetValidationError
    recorder = TraceRecorder()
    graph = PassingGraph(recorder)
    runner = FormalEvaluationRunner(production_adapter=ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder))
    invalid = replace(canonical(), subcategory="NOT_A_REAL_SUBCATEGORY")
    try:
        runner.run((invalid,))
    except DatasetValidationError:
        pass
    else:
        raise AssertionError("invalid dataset must fail closed")
    assert graph.calls == 0


def test_summary_artifact_includes_dataset_identity_and_category_breakdown(tmp_path):
    recorder = TraceRecorder()
    graph = PassingGraph(recorder)
    runner = FormalEvaluationRunner(production_adapter=ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder))
    runner.run((canonical(),), output_dir=tmp_path, dataset_name="phase2-fixture", dataset_version="v1")
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["run"]["dataset_name"] == "phase2-fixture"
    assert summary["run"]["dataset_version"] == "v1"
    assert summary["run"]["dataset_hash"]
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Dataset: phase2-fixture (v1)" in text
    assert "## By category" in text
    assert "KNOWLEDGE_QA: 1 / 1" in text


def test_high_risk_safety_case_exports_human_review_without_claiming_human_reviewed(tmp_path):
    from eval_platform import SafetyConstraint
    base = canonical()
    safety = replace(
        base,
        category=TaskCategory.SAFETY_GOVERNANCE,
        subcategory="SENSITIVE_DATA",
        safety_constraints=(SafetyConstraint(forbidden_disclosures=("alice@example.com",)),),
    )
    recorder = TraceRecorder()
    graph = PassingGraph(recorder)
    runner = FormalEvaluationRunner(production_adapter=ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder))
    runner.run((safety,), output_dir=tmp_path)
    queue = [json.loads(line) for line in (tmp_path / "human_review_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert queue
    assert all(item["case_id"] == safety.sample_id for item in queue)
    serialized = json.dumps(queue, ensure_ascii=False)
    assert '"reviewed_by": "human"' not in serialized
