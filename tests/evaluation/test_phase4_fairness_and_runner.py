from __future__ import annotations

from dataclasses import replace

from eval_platform.context_memory import check_strategy_fairness, ContextEvaluationStrategy, ContextStrategyConfig
from eval_platform.multi_turn_seed import build_phase4_candidate_sessions
from eval_platform.production_adapter import ProductionEvaluationAdapter
from eval_platform.report import PredictionRecord
from eval_platform.runner import ContextStrategyExperimentRunner


def test_strategy_fairness_rejects_model_drift_but_allows_context_policy_diff():
    ok,errors=check_strategy_fairness([
        {"model":"m","retriever":"r","context_strategy":"FULL_HISTORY"},
        {"model":"m","retriever":"r","context_strategy":"LIORIN_CONTEXT"},
    ])
    assert ok and not errors
    ok,errors=check_strategy_fairness([
        {"model":"m1","context_strategy":"FULL_HISTORY"},
        {"model":"m2","context_strategy":"LIORIN_CONTEXT"},
    ])
    assert not ok and "non-context config drift: model" in errors


def test_context_strategy_factory_is_top_level_checkpointed_without_changing_default_graph(monkeypatch):
    seen={}
    class Graph:
        pass
    def fake_loader(enabled,*,use_checkpointer=False):
        seen.update(enabled=enabled,use_checkpointer=use_checkpointer)
        return Graph()
    import eval_platform.production_adapter as module
    monkeypatch.setattr(module,"_load_production_graph_with_recovery",fake_loader)
    adapter=ProductionEvaluationAdapter.for_context_strategy()
    assert isinstance(adapter._graph_instance(),Graph)
    assert seen == {"enabled":True,"use_checkpointer":True}


def test_unreviewed_sessions_are_not_executed_by_experiment_runner():
    calls=[]
    class Adapter:
        def run(self,case):
            calls.append(case.case_id)
            raise AssertionError("unreviewed session must not execute Production")
    runner=ContextStrategyExperimentRunner(adapter_factory=lambda cfg:Adapter())
    result=runner.run(build_phase4_candidate_sessions(),strategies=[ContextEvaluationStrategy.FULL_HISTORY])
    assert calls == []
    assert result.results == ()
    assert result.metadata["dataset"]["eligible_sessions"] == 0


def test_eligible_session_executes_exactly_once_per_strategy_turn():
    from eval_platform.context_memory import CanonicalEvaluationSession, CanonicalEvaluationTurn, SessionTaskSuccessContract
    from eval_platform.contracts import AnnotationMetadata, AnnotationStatus, DatasetSplit, Difficulty, ExpectedBehavior, IdentitySpec, ResponseType, SuccessCriterion, TaskCategory, TaskSuccessContract
    calls=[]
    turns=tuple(CanonicalEvaluationTurn(
        f"t{i}",i-1,f"q{i}",ExpectedBehavior(ResponseType.ANSWER),
        TaskSuccessContract((SuccessCriterion.RESPONSE_TYPE_CORRECT,)),annotation_status=AnnotationStatus.HUMAN_REVIEWED,
    ) for i in (1,2))
    session=CanonicalEvaluationSession(
        "eligible","1.0",DatasetSplit.DEVELOPMENT,TaskCategory.KNOWLEDGE_QA,"FAQ",Difficulty.EASY,(),
        IdentitySpec("tenant","user","conversation","thread","session"),turns,
        annotation_metadata=AnnotationMetadata(AnnotationStatus.HUMAN_REVIEWED),
        session_success_contract=SessionTaskSuccessContract(required_terminal_turn_pass=True),
    )
    class Adapter:
        def __init__(self,strategy): self.strategy=strategy
        def run(self,case):
            calls.append((self.strategy,case.case_id))
            return PredictionRecord(case.case_id,f"trace:{self.strategy}:{case.case_id}","answer","answer",{
                "context_assemblies":[{"context_item_refs":[]}],"model_call_events":[],"tool_names":[],"agent_names":[]
            },{},schema_version="4.0")
    runner=ContextStrategyExperimentRunner(adapter_factory=lambda cfg:Adapter(cfg.strategy.value))
    result=runner.run([session],strategies=[ContextEvaluationStrategy.FULL_HISTORY,ContextEvaluationStrategy.LIORIN_CONTEXT])
    assert len(calls)==4
    assert len(set(calls))==4
    assert len(result.results)==2
    assert all(row.session_success_status.value=="PASS" for row in result.results)
