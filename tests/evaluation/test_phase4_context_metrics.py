from __future__ import annotations

from eval_platform.context_memory import (
    CanonicalEvaluationSession, CanonicalEvaluationTurn, ContextEvaluationStrategy,
    ContextUnitType, MemoryExpectation, RequiredContextUnit, SessionTaskSuccessContract,
    evaluate_context_turn, evaluate_memory_contamination, evaluate_working_memory,
)
from eval_platform.contracts import (
    AnnotationMetadata, AnnotationStatus, DatasetSplit, Difficulty, ExpectedBehavior,
    IdentitySpec, ResponseType, SuccessCriterion, TaskCategory, TaskSuccessContract,
)
from eval_platform.report import PredictionRecord


def _session(turn):
    return CanonicalEvaluationSession(
        session_id="s",schema_version="1.0",split=DatasetSplit.DEVELOPMENT,
        category=TaskCategory.KNOWLEDGE_QA,subcategory="FAQ",difficulty=Difficulty.EASY,tags=(),
        initial_identity=IdentitySpec("tenant:a","user:a","conv","thread","session:a"),turns=(turn,),
        annotation_metadata=AnnotationMetadata(AnnotationStatus.HUMAN_REVIEWED),
    )


def _turn(required=(), memory=None):
    return CanonicalEvaluationTurn(
        "t1",0,"question",ExpectedBehavior(ResponseType.ANSWER),
        TaskSuccessContract((SuccessCriterion.RESPONSE_TYPE_CORRECT,)),required_context_units=tuple(required),
        memory_expectations=memory or MemoryExpectation(), annotation_status=AnnotationStatus.HUMAN_REVIEWED,
    )


def _prediction(refs, model_calls=None):
    return PredictionRecord(
        case_id="s::t1",trace_id="trace",final_response="ok",response_type="answer",
        trace_facts={"context_assemblies":[{"context_item_refs":refs}],"model_call_events":model_calls or []},runtime_metrics={},
        schema_version="4.0",
    )


def test_context_recall_present_partial_and_precision_excludes_not_evaluated():
    required=(RequiredContextUnit("u1",ContextUnitType.ENTITY,"model","ref:model"),RequiredContextUnit("u2",ContextUnitType.SLOT,"error","ref:error"))
    turn=_turn(required)
    pred=_prediction([
        {"context_item_id":"a","type":"USER_MESSAGE","source":"messages_state","source_ref":"ref:model","selected":True,"token_count":10},
        {"context_item_id":"b","type":"USER_MESSAGE","source":"messages_state","source_ref":"other","selected":True,"token_count":20},
    ])
    diag=evaluate_context_turn(_session(turn),turn,pred,strategy=ContextEvaluationStrategy.FULL_HISTORY)
    assert (diag.context_recall_numerator,diag.context_recall_denominator)==(1,2)
    assert (diag.context_precision_numerator,diag.context_precision_denominator)==(1,1)
    assert diag.not_evaluated_context_items == ("b",)


def test_token_accounting_keeps_actual_and_estimated_sources_separate():
    turn=_turn()
    pred=_prediction([],model_calls=[
        {"model_call_id":"m1","input_tokens":100,"output_tokens":5,"token_count_source":"PROVIDER_ACTUAL"},
        {"model_call_id":"m2","input_tokens":60,"output_tokens":2,"token_count_source":"HEURISTIC_ESTIMATE"},
    ])
    diag=evaluate_context_turn(_session(turn),turn,pred,strategy=ContextEvaluationStrategy.LIORIN_CONTEXT)
    assert diag.total_input_tokens == 160
    assert [x.source.value for x in diag.token_usage] == ["PROVIDER_ACTUAL","HEURISTIC_ESTIMATE"]


def test_working_memory_fact_refs_count_for_recall():
    fact="wmfact:confirmed_fact:abc"
    memory=MemoryExpectation(memory_dependent=True,required_fact_ids=(fact,),allowed_fact_ids=(fact,))
    turn=_turn((RequiredContextUnit(fact,ContextUnitType.MEMORY_FACT,"remembered fact",fact),),memory)
    pred=_prediction([{"context_item_id":"wm","type":"MEMORY","source":"memory.working.checkpoint","source_ref":"wm","selected":True,"token_count":10,"memory_kind":"working","working_memory_fact_refs":[fact],"identity_context":{"tenant_id":"tenant:a","user_id":"user:a","session_id":"session:a"}}])
    diag=evaluate_context_turn(_session(turn),turn,pred,strategy=ContextEvaluationStrategy.LIORIN_CONTEXT)
    wm=evaluate_working_memory(turn,diag)
    assert wm["working_memory_recall"]["rate"] == 1.0


def test_cross_user_and_superseded_selected_memory_are_contamination_but_unselected_is_not():
    memory=MemoryExpectation(memory_dependent=True,superseded_fact_ids=("old",),allowed_fact_ids=("new",))
    turn=_turn(memory=memory)
    refs=[
        {"context_item_id":"old","type":"MEMORY","source":"memory.facts.model","source_ref":"old","selected":True,"token_count":5,"memory_kind":"long_term_fact","fact_id":"old","identity_context":{"tenant_id":"tenant:a","user_id":"user:b","session_id":"session:b"}},
        {"context_item_id":"stale-unselected","type":"MEMORY","source":"memory.facts.model","source_ref":"old2","selected":False,"token_count":5,"memory_kind":"long_term_fact","fact_id":"old2","identity_context":{"tenant_id":"tenant:a","user_id":"user:b","session_id":"session:b"}},
    ]
    pred=_prediction(refs)
    session=_session(turn)
    diag=evaluate_context_turn(session,turn,pred,strategy=ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT)
    events=evaluate_memory_contamination(session,turn,diag)
    kinds={e.event_type.value for e in events}
    assert "SUPERSEDED_FACT_USED" in kinds
    assert "CROSS_USER_FACT_USED" in kinds
    assert all(e.context_item_id != "stale-unselected" for e in events)
    assert any(e.safety_violation for e in events)


def test_stale_fact_is_contamination_only_when_selected():
    memory=MemoryExpectation(memory_dependent=True,stale_fact_ids=("stale",),allowed_fact_ids=("fresh",))
    turn=_turn(memory=memory)
    pred=_prediction([
        {"context_item_id":"s","type":"MEMORY","source":"memory.facts.region","source_ref":"stale","selected":True,"token_count":3,"memory_kind":"long_term_fact","fact_id":"stale","identity_context":{"tenant_id":"tenant:a","user_id":"user:a","session_id":"session:a"}},
    ])
    session=_session(turn)
    diag=evaluate_context_turn(session,turn,pred,strategy=ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT)
    assert "STALE_FACT_USED" in {e.event_type.value for e in evaluate_memory_contamination(session,turn,diag)}
