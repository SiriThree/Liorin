from dataclasses import replace

from eval_platform import (
    AnnotationMetadata, AnnotationStatus, ComparisonMode, DatasetSplit, Difficulty,
    EvidenceEvaluationEligibilityStatus, EvidenceRelevanceStatus, EvidenceSourceType,
    ExpectedBehavior, FactValueType, GoldEvidence, GoldFact, ResponseType,
    RuntimeCaseInput, TaskCategory, TaskSuccessContract, EvaluationSample,
    evaluate_evidence_case,
)
from eval_platform.judge import JudgeConfig, JudgeRuntime
from eval_platform.report import PredictionRecord


def sample(*gold):
    facts = tuple(
        GoldFact(f"f{i}", f"fact {i}", "x", FactValueType.STRING, True, (g.evidence_id,), ComparisonMode.NORMALIZED_EXACT)
        for i, g in enumerate(gold, 1)
    )
    return EvaluationSample(
        sample_id="evidence-case",
        runtime_input=RuntimeCaseInput(case_id="evidence-case", messages=({"role":"user","content":"question"},)),
        split=DatasetSplit.DEVELOPMENT,
        category=TaskCategory.KNOWLEDGE_QA,
        subcategory="FAQ",
        difficulty=Difficulty.EASY,
        expected_behavior=ExpectedBehavior(ResponseType.ANSWER, clarification_required=False, handoff_required=False),
        task_success_contract=TaskSuccessContract(()),
        gold_evidence=tuple(gold),
        gold_facts=facts,
        annotation_metadata=AnnotationMetadata(AnnotationStatus.MIGRATED_LEGACY),
    )


def doc(eid, doc, sec, *, required=True, group=None, metadata=None):
    return GoldEvidence(eid, EvidenceSourceType.DOCUMENT, required=required, alternative_group=group, document_id=doc, section_id=sec, metadata=metadata or {})


def pred(events, selected=()):
    return PredictionRecord(
        case_id="evidence-case", trace_id="trace-1", final_response="answer", response_type="answer",
        trace_facts={"prediction_schema_version":"3.0", "evidence_events":events, "selected_evidence_ids":list(selected), "verification_rounds":[{"round_id":1,"action":"accept","accepted_evidence_ids":list(selected)}]},
        runtime_metrics={}, execution_status="COMPLETED",
    )


def ev(eid, doc, sec, rank, *, status="accepted", round_id=1, requirements=()):
    return {"event":"verified","status":status,"round_id":round_id,"evidence_id":eid,"stable_ref":f"doc:{doc}#{sec}","document_id":doc,"section_id":sec,"fusion_rank":rank,"requirement_coverage":list(requirements)}


def test_required_recall_all_partial_none_and_duplicate_do_not_inflate():
    g1, g2 = doc("g1","m.md","s1"), doc("g2","m.md","s2")
    s = sample(g1,g2)
    all_row = evaluate_evidence_case(s, pred([ev("r1","m.md","s1",1),ev("r2","m.md","s2",2),ev("dup","m.md","s1",3)], ("r1","r2")))
    assert (all_row.required_gold_evidence_recall_numerator, all_row.required_gold_evidence_recall_denominator) == (2,2)
    partial = evaluate_evidence_case(s, pred([ev("r1","m.md","s1",1)], ("r1",)))
    assert (partial.required_gold_evidence_recall_numerator, partial.required_gold_evidence_recall_denominator) == (1,2)
    none = evaluate_evidence_case(s, pred([ev("x","other.md","x",1)], ("x",)))
    assert none.required_gold_evidence_recall_numerator == 0


def test_alternative_group_counts_as_one_required_unit_and_recall_never_exceeds_one():
    a = doc("a","m.md","s1",group="policy")
    b = doc("b","faq.md","f1",group="policy")
    s = sample(a,b)
    row = evaluate_evidence_case(s, pred([ev("ra","m.md","s1",1),ev("rb","faq.md","f1",2)], ("ra","rb")))
    assert (row.required_gold_evidence_recall_numerator,row.required_gold_evidence_recall_denominator)==(1,1)


def test_parent_section_match_requires_explicit_hierarchy_metadata():
    g = doc("child","m.md","child",metadata={"allowed_parent_refs":["doc:m.md#chapter-1"]})
    row = evaluate_evidence_case(sample(g), pred([ev("parent","m.md","chapter-1",1)], ("parent",)))
    assert row.required_gold_evidence_recall_numerator == 1


def test_structured_gold_without_structured_trace_is_observability_insufficient_not_retrieval_miss():
    g = GoldEvidence("order-date", EvidenceSourceType.STRUCTURED_DATA, record_type="order", record_id="ORD1", field_path="order_date")
    row = evaluate_evidence_case(sample(g), pred([ev("policy","m.md","s1",1)], ("policy",)))
    assert row.eligibility.status is EvidenceEvaluationEligibilityStatus.OBSERVABILITY_INSUFFICIENT


def test_structured_field_matches_stable_record_ref():
    g = GoldEvidence("order-date", EvidenceSourceType.STRUCTURED_DATA, record_type="order", record_id="ORD1", field_path="order_date")
    events=[{"event":"verified","status":"accepted","round_id":1,"evidence_id":"db1","stable_ref":"record:order:ORD1#order_date","record_type":"order","record_id":"ORD1","field_path":"order_date","fusion_rank":1}]
    row = evaluate_evidence_case(sample(g), pred(events,("db1",)))
    assert row.eligibility.eligible
    assert row.required_gold_evidence_recall_numerator == 1


class RelevanceProvider:
    def invoke(self, request, config):
        stable = request.structured_input["selected_evidence"]["stable_id"]
        return {"status":"PASS" if "helpful" in stable else "FAIL", "rationale":"fixture"}


def test_selected_precision_does_not_treat_non_gold_as_irrelevant_without_judge():
    g = doc("g","m.md","s1")
    events=[ev("gold","m.md","s1",1),ev("helpful","extra.md","helpful",2),ev("noise","noise.md","noise",3)]
    no_judge = evaluate_evidence_case(sample(g), pred(events,("gold","helpful","noise")))
    assert no_judge.selected_evidence_precision_complete is False
    assert any(x.status is EvidenceRelevanceStatus.NOT_EVALUATED for x in no_judge.selected_relevance)
    judge=JudgeRuntime(JudgeConfig("r","stub","stub",max_retries=0),RelevanceProvider())
    judged = evaluate_evidence_case(sample(g), pred(events,("gold","helpful","noise")), judge=judge)
    assert judged.selected_evidence_precision_complete is True
    assert (judged.selected_evidence_precision_numerator,judged.selected_evidence_precision_denominator)==(2,3)


def test_empty_selected_precision_has_zero_denominator_not_fake_perfect_score():
    g=doc("g","m.md","s1")
    row=evaluate_evidence_case(sample(g), pred([ev("g","m.md","s1",1)], ()))
    assert row.selected_evidence_precision_denominator == 0
