from __future__ import annotations
import json
import pytest
from pydantic import ValidationError

from retrieval.budget import RetrievalBudget
from retrieval.protocols import (
    QueryUnderstanding, RetrievalPlan, RetrievalSubquery, RetrievalResponse,
    RetrievalStatus, RetrievalError, VerificationDecision, VerificationAction,
    RetrievalPrincipal,
)


def roundtrip(model):
    return type(model).model_validate_json(json.dumps(model.to_state(), ensure_ascii=False))


def test_query_understanding_multi_requirement_roundtrip():
    value = QueryUnderstanding(original_query="AX-300 出现 E502，是否可以免费维修，大概多久修好？", normalized_query="AX-300 E502 故障 免费维修条件 维修周期", language="zh", intent="repair", task_type="troubleshooting_warranty", product_name="AX", product_models=["AX-300"], error_codes=["E502"], requirements=["解释 E502 的故障含义", "判断是否满足免费维修条件", "给出预计维修周期"], confidence=.91)
    restored = roundtrip(value)
    assert restored.requirements == value.requirements
    assert restored.product_models == ["AX-300"]


def test_retrieval_plan_multi_subquery_roundtrip():
    plan = RetrievalPlan(strategy="decomposed", original_requirements=["故障", "质保"], subqueries=[RetrievalSubquery(subquery_id="fault", query="AX-300 E502", source="manual", required_evidence=["故障含义"], priority=90, reason="故障手册"), RetrievalSubquery(subquery_id="warranty", query="AX-300 免费维修", source="policy", required_evidence=["免费维修条件"], priority=80, reason="质保政策")])
    restored = roundtrip(plan)
    assert [x.subquery_id for x in restored.subqueries] == ["fault", "warranty"]


def test_retrieval_response_distinguishes_failure_modes():
    no_results = RetrievalResponse(status=RetrievalStatus.NO_RESULTS)
    timeout = RetrievalResponse(status=RetrievalStatus.TIMEOUT, errors=[RetrievalError(stage="dense", error_type="TimeoutError", message="timeout", retryable=True, dependency="milvus")])
    dep = RetrievalResponse(status=RetrievalStatus.DEPENDENCY_ERROR, errors=[RetrievalError(stage="dense", error_type="ConnectionError", message="down", retryable=True, dependency="milvus")])
    assert len({no_results.status, timeout.status, dep.status}) == 3
    with pytest.raises(ValidationError):
        RetrievalResponse(status=RetrievalStatus.TIMEOUT)


@pytest.mark.parametrize("action", list(VerificationAction))
def test_verification_actions_are_valid(action):
    kwargs = {}
    if action == VerificationAction.CLARIFY: kwargs["clarification_question"] = "请补充型号"
    if action == VerificationAction.HANDOFF: kwargs["handoff_reason"] = "权限不足"
    assert VerificationDecision(action=action, **kwargs).action == action


def test_verification_action_contracts():
    with pytest.raises(ValidationError): VerificationDecision(action=VerificationAction.CLARIFY)
    with pytest.raises(ValidationError): VerificationDecision(action=VerificationAction.HANDOFF)


def test_principal_tenant_and_auth_behavior():
    anonymous = RetrievalPrincipal(user_id="", tenant_id="", authenticated=False)
    assert not anonymous.can_retrieve
    with pytest.raises(ValidationError): RetrievalPrincipal(user_id="u1", tenant_id="", authenticated=True)
    assert RetrievalPrincipal(user_id="u1", tenant_id="t1", authenticated=True).can_retrieve


def test_checkpoint_json_roundtrip_preserves_agentic_state():
    budget = RetrievalBudget(max_dense_queries=6, max_sparse_queries=8).start()
    assert budget.reserve_dense(); assert budget.reserve_sparse(); assert budget.reserve_context(321)
    state = {
        "retry_count": 2,
        "budget_snapshot": budget.to_state(),
        "retrieval_plan_v2": RetrievalPlan(subqueries=[RetrievalSubquery(subquery_id="sq-1", query="q", source="manual")]).to_state(),
        "verification_decision": VerificationDecision(action=VerificationAction.SUPPLEMENT, reason="missing").to_state(),
    }
    checkpoint_json = json.dumps(state)
    restored = json.loads(checkpoint_json)
    restored_budget = RetrievalBudget.from_state(restored["budget_snapshot"])
    assert restored["retry_count"] == 2
    assert restored_budget.dense_queries_used == 1
    assert restored_budget.sparse_queries_used == 1
    assert restored_budget.context_chars_used == 321
    assert RetrievalPlan.from_legacy(restored).subqueries[0].subquery_id == "sq-1"
    assert VerificationDecision.from_legacy(restored).action == VerificationAction.SUPPLEMENT


def test_legacy_knowledge_state_compatibility():
    legacy = {"original_question":"AX-300 E502", "rewritten_question":"AX-300 E502 故障", "product_model":"AX-300", "error_code":"E502", "requirements":["解释故障"], "retrieval_plan":[{"query":"E502", "source":"manual", "filters":{}, "purpose":"查故障", "execution":"parallel"}], "verification_action":"retrieve_more"}
    assert QueryUnderstanding.from_legacy(legacy).error_codes == ["E502"]
    assert RetrievalPlan.from_legacy(legacy).subqueries[0].source == "manual"
    assert VerificationDecision.from_legacy(legacy).action == VerificationAction.SUPPLEMENT


def test_benchmark_adapter_uses_production_nodes():
    from pathlib import Path
    source = Path("evals/benchmark/adapters/retrieval.py").read_text(encoding="utf-8")
    assert "from agents.knowledge_agent import execute_retrieval, plan_retrieval, understand_query" in source
    assert "state.update(understand_query" in source
    assert "state.update(plan_retrieval" in source
    assert "execute_retrieval(state)" in source
