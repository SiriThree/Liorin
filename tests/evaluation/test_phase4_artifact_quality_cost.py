from __future__ import annotations

from eval_platform.context_memory import (
    ArtifactExpectation, CanonicalEvaluationSession, CanonicalEvaluationTurn,
    ContextEvaluationStrategy, ContextTurnDiagnostic, SessionStrategyResult,
    SessionTaskSuccessStatus, TokenCountSource, TokenUsageRecord,
    aggregate_context_strategy, evaluate_artifacts, paired_quality_cost, quality_cost_frontier,
)
from eval_platform.contracts import (
    AnnotationMetadata, AnnotationStatus, DatasetSplit, Difficulty, ExpectedBehavior,
    IdentitySpec, ResponseType, SuccessCriterion, TaskCategory, TaskSuccessContract,
)
from eval_platform.report import PredictionRecord
from eval_platform.context_memory import ContextUnitObservation


def _session(expectation=ArtifactExpectation()):
    turn=CanonicalEvaluationTurn(
        "t",0,"q",ExpectedBehavior(ResponseType.ANSWER),TaskSuccessContract((SuccessCriterion.RESPONSE_TYPE_CORRECT,)),
        artifact_expectations=expectation,annotation_status=AnnotationStatus.HUMAN_REVIEWED,
    )
    return CanonicalEvaluationSession(
        "s","1.0",DatasetSplit.DEVELOPMENT,TaskCategory.KNOWLEDGE_QA,"FAQ",Difficulty.EASY,(),
        IdentitySpec("tenant","user","conv","thread","session"),(turn,),
        annotation_metadata=AnnotationMetadata(AnnotationStatus.HUMAN_REVIEWED),
    ),turn


def _diag(strategy,tokens,artifact=False):
    obs=()
    if artifact:
        obs=(ContextUnitObservation("a","ARTIFACT_REFERENCE","artifact","artifact:1",True,12,artifact_id="artifact:1"),)
    return ContextTurnDiagnostic("s","t",strategy,"trace",0,0,0,0,(TokenUsageRecord("m",tokens,source=TokenCountSource.PROVIDER_ACTUAL),),obs)


def _result(strategy,tokens,status=SessionTaskSuccessStatus.PASS):
    return SessionStrategyResult("s",strategy,(),(),(_diag(strategy,tokens),),(),(),status,0,{"memory_dependent_turns":0})


def test_artifact_correct_reuse_and_missing_are_distinct():
    session,turn=_session(ArtifactExpectation(required_artifact_ids=("artifact:1",)))
    good=evaluate_artifacts(session,turn,_diag(ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT,100,artifact=True))
    bad=evaluate_artifacts(session,turn,_diag(ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT,100,artifact=False))
    assert good[0].status.value == "CORRECT_REUSE"
    assert bad[0].status.value == "MISSING"


def test_paired_quality_cost_uses_same_session_and_percentage_points():
    rows=[_result(ContextEvaluationStrategy.FULL_HISTORY,1000),_result(ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT,400)]
    paired=paired_quality_cost(rows)
    item=paired[ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT.value]
    assert item["paired_sessions"] == 1
    assert item["token_reduction"] == 0.6
    assert item["task_success_delta_percentage_points"] == 0.0


def test_quality_cost_frontier_has_no_weighted_score():
    summary=aggregate_context_strategy([
        _result(ContextEvaluationStrategy.FULL_HISTORY,1000),
        _result(ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT,400),
    ])
    frontier=quality_cost_frontier(summary)
    assert frontier["no_weighted_quality_cost_score"] is True
    assert ContextEvaluationStrategy.FULL_HISTORY.value in frontier["dominated_by"]


def test_artifact_origin_wrong_identity_is_not_correct_reuse():
    session,turn=_session(ArtifactExpectation(required_artifact_ids=("artifact:1",),identity_scoped=True))
    diag=ContextTurnDiagnostic("s","t",ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT,"trace",0,0,0,0,(),(
        ContextUnitObservation("a","ARTIFACT_REFERENCE","artifact","artifact:1",True,12,artifact_id="artifact:1",identity_scope={"tenant_id":"other","user_id":"user"}),
    ))
    result=evaluate_artifacts(session,turn,diag)
    assert result[0].status.value == "WRONG_IDENTITY"
