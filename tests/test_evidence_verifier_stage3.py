from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import types

import pytest

# This audit environment lacks LangChain/LangGraph.  Interface stubs exercise
# Liorin's production verifier/routing code without claiming real framework,
# model, Milvus or checkpoint-backend integration.
try:
    from langchain_core.documents import Document  # type: ignore
except (ModuleNotFoundError, ImportError):
    langchain_core = types.ModuleType("langchain_core")
    documents = types.ModuleType("langchain_core.documents")

    class Document:
        def __init__(self, page_content: str, metadata: dict | None = None):
            self.page_content = page_content
            self.metadata = metadata or {}

    documents.Document = Document
    langchain_core.documents = documents
    langchain_core.__path__ = []
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.documents"] = documents

# Another test module may already have installed a minimal langchain_core stub.
# Ensure the message interface exists regardless of collection/import order.
if "langchain_core.messages" not in sys.modules:
    messages = types.ModuleType("langchain_core.messages")

    class BaseMessage:
        def __init__(self, content: str = "", **kwargs):
            self.content = content

    class AIMessage(BaseMessage):
        pass

    class HumanMessage(BaseMessage):
        pass

    messages.AIMessage = AIMessage
    messages.HumanMessage = HumanMessage
    sys.modules["langchain_core.messages"] = messages
    core = sys.modules.get("langchain_core")
    if core is not None:
        core.messages = messages

if "langchain" not in sys.modules:
    langchain = types.ModuleType("langchain")
    chat_models = types.ModuleType("langchain.chat_models")
    agents_mod = types.ModuleType("langchain.agents")
    middleware_mod = types.ModuleType("langchain.agents.middleware")

    class FakeModel:
        def with_structured_output(self, schema):
            return self
        def invoke(self, messages):
            raise RuntimeError("model unavailable in isolated audit")

    chat_models.init_chat_model = lambda *args, **kwargs: FakeModel()
    agents_mod.create_agent = lambda *args, **kwargs: FakeModel()
    middleware_mod.ModelRequest = type("ModelRequest", (), {})
    middleware_mod.dynamic_prompt = lambda fn: fn
    langchain.chat_models = chat_models
    langchain.agents = agents_mod
    sys.modules["langchain"] = langchain
    sys.modules["langchain.chat_models"] = chat_models
    sys.modules["langchain.agents"] = agents_mod
    sys.modules["langchain.agents.middleware"] = middleware_mod

if "langgraph" not in sys.modules:
    langgraph = types.ModuleType("langgraph")
    graph_mod = types.ModuleType("langgraph.graph")
    message_mod = types.ModuleType("langgraph.graph.message")
    checkpoint_mod = types.ModuleType("langgraph.checkpoint")
    memory_mod = types.ModuleType("langgraph.checkpoint.memory")

    class MemorySaver:
        pass

    class StateGraph:
        def __init__(self, *args, **kwargs):
            self.nodes = {}
            self.edges = []
            self.conditional_edges = {}
            self.entry_point = None
        def add_node(self, name, fn):
            self.nodes[name] = fn
        def add_edge(self, source, target):
            self.edges.append((source, target))
        def add_conditional_edges(self, source, router, mapping):
            self.conditional_edges[source] = (router, mapping)
        def set_entry_point(self, name):
            self.entry_point = name
        def compile(self, **kwargs):
            self.compile_kwargs = kwargs
            return self

    graph_mod.END = "__END__"
    graph_mod.StateGraph = StateGraph
    message_mod.add_messages = lambda left, right: [*(left or []), *(right or [])]
    memory_mod.MemorySaver = MemorySaver
    langgraph.graph = graph_mod
    checkpoint_mod.memory = memory_mod
    sys.modules["langgraph"] = langgraph
    sys.modules["langgraph.graph"] = graph_mod
    sys.modules["langgraph.graph.message"] = message_mod
    sys.modules["langgraph.checkpoint"] = checkpoint_mod
    sys.modules["langgraph.checkpoint.memory"] = memory_mod

if "tools" not in sys.modules:
    tools = types.ModuleType("tools")
    tools.search_manuals = lambda *args, **kwargs: []
    tools.search_support_policies = lambda *args, **kwargs: []
    tools_documents = types.ModuleType("tools.documents")
    tools_documents.get_vectorstore = lambda: (_ for _ in ()).throw(RuntimeError("no vectorstore"))
    tools_documents.search_manuals = tools.search_manuals
    tools_documents.search_support_policies = tools.search_support_policies
    sys.modules["tools"] = tools
    sys.modules["tools.documents"] = tools_documents

from retrieval.budget import RetrievalBudget
from retrieval.evidence_verifier import subquery_signature, verify_evidence
from retrieval.protocols import (
    EvidenceAudit,
    QueryUnderstanding,
    RetrievalPlan,
    RetrievalPrincipal,
    RetrievalResponse,
    RetrievalStatus,
    RetrievalSubquery,
    VerificationAction,
    VerificationDecision,
)

NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def principal() -> RetrievalPrincipal:
    return RetrievalPrincipal(
        user_id="support-1",
        tenant_id="tenant-1",
        roles=["support"],
        groups=["support"],
        permissions=["knowledge:read", "classification:confidential:read"],
        authenticated=True,
        region="CN",
    )


def evidence(
    eid: str,
    text: str,
    source: str,
    *,
    region: str = "CN",
    active: bool = True,
    version: str = "v2",
    effective_from: str | None = "2026-01-01",
    effective_to: str | None = None,
    section_id: str | None = None,
    content_sha256: str | None = None,
    authority: str | None = None,
    **metadata,
) -> dict:
    md = {
        "document_id": f"doc-{eid}",
        "section_id": section_id or f"sec-{eid}",
        "chunk_id": eid,
        "tenant_id": "tenant-1",
        "allowed_user_ids": [],
        "allowed_groups": [],
        "required_permissions": [],
        "classification": "public",
        "acl_identity_public": True,
        "active": active,
        "source": source,
        "doc_type": source,
        "source_file": f"{source}.md",
        "region": region,
        "product_model": "AX-300",
        "product_models": ["AX-300"],
        "version": version,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    if content_sha256:
        md["content_sha256"] = content_sha256
    if authority:
        md["authority"] = authority
    md.update(metadata)
    return {
        "document": Document(page_content=text, metadata=md),
        "source_type": source,
        "source": source,
        "citation_id": eid,
        "authority": authority,
        "contributions": [],
        "trace": [],
    }


def understanding(requirements: list[str], *, region: str | None = "CN", product: bool = True):
    return QueryUnderstanding(
        original_query="AX-300 E502 是否免费维修，大概多久修好？",
        normalized_query="AX-300 E502 故障含义 免费维修条件 维修周期",
        product_models=["AX-300"] if product else [],
        error_codes=["E502"],
        region=region,
        requirements=requirements,
    )


def plan(requirements: list[str], *, max_rounds: int = 3, broad: bool = False):
    subqueries = [
        RetrievalSubquery(
            subquery_id="broad" if broad else f"sq-{index}",
            query="AX-300 E502" if broad else requirement,
            source="all" if broad else "manual",
            required_evidence=[] if broad else [requirement],
        )
        for index, requirement in enumerate(requirements, start=1)
    ]
    if broad:
        subqueries = subqueries[:1]
    return RetrievalPlan(
        strategy="broad" if broad else "decomposed",
        subqueries=subqueries,
        max_rounds=max_rounds,
        original_requirements=requirements,
    )


def response(evidences: list[dict], status: RetrievalStatus = RetrievalStatus.SUCCESS):
    kwargs = {"status": status, "evidences": evidences}
    if status in {RetrievalStatus.TIMEOUT, RetrievalStatus.DEPENDENCY_ERROR}:
        from retrieval.protocols import RetrievalError
        kwargs["errors"] = [RetrievalError(stage="retrieval", error_type=str(status), message="failed")]
    return RetrievalResponse(**kwargs)


def test_single_requirement_sufficient_accepts():
    reqs = ["解释 E502 的故障含义"]
    rows = [evidence("E1", "错误码 E502 表示温度传感器异常，需要检查传感器连接。", "manual")]
    result = verify_evidence(understanding(reqs), plan(reqs), response(rows), rows, principal(), now=NOW)
    assert result.decision.action == VerificationAction.ACCEPT
    assert result.audit.requirement_coverages[0].covered
    assert result.audit.requirement_coverages[0].authority_sufficient


def test_multi_requirement_partial_coverage_targets_supplement():
    reqs = ["解释 E502 的故障含义", "判断是否满足免费维修条件", "给出预计维修周期"]
    rows = [evidence("E1", "错误码 E502 表示温度传感器异常。", "manual")]
    result = verify_evidence(understanding(reqs), plan(reqs), response(rows), rows, principal(), now=NOW)
    assert result.decision.action == VerificationAction.SUPPLEMENT
    assert result.decision.missing_requirements == reqs[1:]
    assert {q.source for q in result.decision.next_subqueries} == {"policy", "ticket_history"}
    assert all(reqs[0] not in q.query for q in result.decision.next_subqueries)


def test_targeted_supplement_then_accepts_with_old_and_new_evidence():
    reqs = ["解释 E502 的故障含义", "判断是否满足免费维修条件"]
    old = [evidence("E1", "错误码 E502 表示温度传感器异常。", "manual")]
    first = verify_evidence(understanding(reqs), plan(reqs), response(old), old, principal(), now=NOW)
    assert first.decision.action == VerificationAction.SUPPLEMENT
    policy = evidence(
        "E2",
        "AX-300 在保修期内且属于非人为损坏时支持免费维修。",
        "policy",
        policy_id="P-WARRANTY",
    )
    combined = [*old, policy]
    second_plan = RetrievalPlan(
        strategy="targeted_supplement",
        subqueries=first.decision.next_subqueries,
        max_rounds=3,
        original_requirements=reqs,
    )
    second = verify_evidence(
        understanding(reqs), second_plan, response(combined), combined, principal(), retry_count=1, now=NOW
    )
    assert second.decision.action == VerificationAction.ACCEPT
    assert second.audit.coverage_score == 1.0


def test_missing_product_model_clarifies():
    reqs = ["解释 E502 的故障含义"]
    result = verify_evidence(understanding(reqs, product=False), plan(reqs), RetrievalResponse(status="no_results"), [], principal(), now=NOW)
    assert result.decision.action == VerificationAction.CLARIFY
    assert "型号" in result.decision.clarification_question


def test_expired_policy_conflict_prefers_current_policy():
    reqs = ["判断是否满足免费维修条件"]
    old = evidence(
        "E-old", "AX-300 不支持免费维修。", "policy", version="v1", effective_from="2024-01-01",
        effective_to="2025-12-31", policy_id="P1", conflict_key="free_repair", conflict_value="no",
    )
    current = evidence(
        "E-new", "AX-300 在保修期内非人为损坏支持免费维修。", "policy", version="v2",
        policy_id="P1", conflict_key="free_repair", conflict_value="yes",
    )
    result = verify_evidence(understanding(reqs), plan(reqs), response([old, current]), [old, current], principal(), now=NOW)
    assert result.decision.action == VerificationAction.ACCEPT
    conflict = result.audit.conflicts[0]
    assert conflict.preferred_evidence_id == "E-new"
    assert conflict.unresolved is False
    assert "current valid" in conflict.resolution_reason


def test_same_authority_current_policy_conflict_handoffs():
    reqs = ["判断是否满足免费维修条件"]
    yes = evidence("E1", "AX-300 支持免费维修。", "policy", policy_id="P1", conflict_key="free_repair", conflict_value="yes")
    no = evidence("E2", "AX-300 不支持免费维修。", "policy", policy_id="P2", conflict_key="free_repair", conflict_value="no")
    result = verify_evidence(understanding(reqs), plan(reqs), response([yes, no]), [yes, no], principal(), now=NOW)
    assert result.decision.action == VerificationAction.HANDOFF
    assert result.audit.unresolved_high_risk_conflicts
    assert result.decision.unresolved_conflict_ids


def test_historical_ticket_cannot_override_current_policy():
    reqs = ["判断是否满足免费维修条件"]
    policy = evidence("P", "保修期内非人为损坏支持免费维修。", "policy", conflict_key="free_repair", conflict_value="yes")
    ticket = evidence("T", "历史工单曾拒绝免费维修。", "ticket_history", conflict_key="free_repair", conflict_value="no")
    result = verify_evidence(understanding(reqs), plan(reqs), response([policy, ticket]), [policy, ticket], principal(), now=NOW)
    assert result.decision.action == VerificationAction.ACCEPT
    conflict = result.audit.conflicts[0]
    assert conflict.preferred_evidence_id == "P"
    assert "policy authority overrides historical ticket" in conflict.resolution_reason


def test_region_mismatch_never_accepts():
    reqs = ["判断是否满足免费维修条件"]
    us = evidence("US", "保修期内支持免费维修。", "policy", region="US")
    result = verify_evidence(understanding(reqs, region="CN"), plan(reqs), response([us]), [us], principal(), now=NOW)
    assert result.decision.action != VerificationAction.ACCEPT
    validity = result.audit.evidence_validity[0]
    assert not validity.region_compatible


def test_duplicate_chunk_does_not_inflate_coverage():
    reqs = ["解释 E502 的故障含义", "判断是否满足免费维修条件"]
    a = evidence("E1", "错误码 E502 表示温度传感器异常。", "manual", content_sha256="same")
    b = evidence("E2", "错误码 E502 表示温度传感器异常。", "manual", content_sha256="same")
    result = verify_evidence(understanding(reqs), plan(reqs), response([a, b]), [a, b], principal(), now=NOW)
    assert result.audit.coverage_score == 0.5
    assert len(result.audit.duplicate_groups) == 1
    assert len(result.audit.requirement_coverages[0].evidence_ids) == 1


def test_max_rounds_handoffs_deterministically():
    reqs = ["解释 E502 的故障含义"]
    result = verify_evidence(
        understanding(reqs), plan(reqs, max_rounds=2), RetrievalResponse(status="no_results"), [], principal(), retry_count=1, now=NOW
    )
    assert result.decision.action == VerificationAction.HANDOFF
    assert "最大检索轮次" in result.decision.handoff_reason


def test_budget_exhaustion_handoffs_not_loops():
    reqs = ["解释 E502 的故障含义"]
    result = verify_evidence(
        understanding(reqs), plan(reqs), RetrievalResponse(status="budget_exhausted"), [], principal(), now=NOW
    )
    assert result.decision.action == VerificationAction.HANDOFF
    assert result.decision.next_subqueries == []


def test_production_route_and_answer_gate_block_failed_verifier(monkeypatch):
    from agents import knowledge_agent as ka

    decision = VerificationDecision(
        action="supplement",
        reason="missing policy",
        missing_requirements=["免费维修条件"],
        next_subqueries=[RetrievalSubquery(subquery_id="target", query="AX-300 免费维修条件", source="policy")],
    )
    assert ka.route_after_grade({"verification_decision": decision.to_state()}) == "targeted_retrieve"
    called = {"llm": False}
    monkeypatch.setattr(ka, "_llm", lambda *args, **kwargs: called.update(llm=True))
    blocked = ka.generate_answer({
        "verification_decision": decision.to_state(),
        "evidence_audit": EvidenceAudit().to_state(),
        "principal": principal().to_state(),
    })
    assert blocked["answer_gate_passed"] is False
    assert called["llm"] is False


def test_checkpoint_roundtrip_continues_correct_round_and_route():
    from agents import knowledge_agent as ka

    budget = RetrievalBudget(max_sparse_queries=4).start()
    assert budget.reserve_sparse()
    decision = VerificationDecision(
        action="supplement",
        reason="missing",
        missing_requirements=["维修周期"],
        next_subqueries=[RetrievalSubquery(subquery_id="r2", query="AX-300 维修周期", source="ticket_history")],
    )
    state = {
        "retry_count": 1,
        "budget_snapshot": budget.to_state(),
        "verification_decision": decision.to_state(),
        "verification_rounds": [{"round_id": 1, "trigger": "initial_retrieval"}],
        "executed_query_signatures": [subquery_signature(RetrievalSubquery(subquery_id="r1", query="AX-300 E502", source="manual"))],
    }
    restored = json.loads(json.dumps(state))
    assert restored["retry_count"] == 1
    assert RetrievalBudget.from_state(restored["budget_snapshot"]).sparse_queries_used == 1
    assert restored["verification_rounds"][0]["round_id"] == 1
    assert ka.route_after_grade(restored) == "targeted_retrieve"
    update = ka.plan_supplemental_retrieval(restored)
    assert update["retry_count"] == 2
    assert update["retrieval_plan"][0]["query"] == "AX-300 维修周期"


def test_production_graph_contains_all_verification_routes():
    from agents.knowledge_agent import create_knowledge_agent

    graph = create_knowledge_agent(use_checkpointer=False)
    assert "verify_evidence" in graph.nodes
    if hasattr(graph, "edges"):
        assert ("execute_retrieval", "verify_evidence") in graph.edges
        _, mapping = graph.conditional_edges["verify_evidence"]
    else:
        graph_repr = repr(graph.get_graph())
        assert "execute_retrieval" in graph_repr and "verify_evidence" in graph_repr
        branch_specs = graph.builder.branches["verify_evidence"]
        mapping = next(iter(branch_specs.values())).ends
    assert set(mapping) == {
        "generate_answer", "targeted_retrieve", "rewrite_query", "replan", "clarification", "handoff"
    }


def test_benchmark_uses_production_graph_and_scores_verification_action():
    behavior = Path("evals/benchmark/adapters/behavior.py").read_text(encoding="utf-8")
    end_to_end = Path("evals/benchmark/adapters/end_to_end.py").read_text(encoding="utf-8")
    scorer = Path("evals/benchmark/scoring/scorer.py").read_text(encoding="utf-8")
    assert "create_knowledge_agent" in behavior
    assert "create_knowledge_agent" in end_to_end
    assert "verification_action_accuracy" in scorer


def test_resolved_conflict_excludes_superseded_evidence_from_answer_set():
    reqs = ["判断是否满足免费维修条件"]
    old = evidence(
        "old-active", "AX-300 不支持免费维修。", "policy",
        version="v1", policy_id="P1", conflict_key="free_repair", conflict_value="no",
    )
    current = evidence(
        "new-active", "AX-300 在保修期内非人为损坏支持免费维修。", "policy",
        version="v2", policy_id="P1", conflict_key="free_repair", conflict_value="yes",
    )
    result = verify_evidence(
        understanding(reqs), plan(reqs), response([old, current]), [old, current], principal(), now=NOW
    )
    assert result.decision.action == VerificationAction.ACCEPT
    assert result.audit.accepted_evidence_ids == ["new-active"]
    assert "old-active" in result.audit.excluded_evidence_ids


def test_distinct_chunks_in_same_section_can_cover_different_requirements():
    reqs = ["解释 E502 的故障含义", "给出预计维修周期"]
    fault = evidence(
        "fault", "错误码 E502 表示温度传感器异常。", "manual", section_id="same-section"
    )
    duration = evidence(
        "duration", "该型号平均维修周期为 3 个工作日。", "ticket_history", section_id="same-section"
    )
    result = verify_evidence(
        understanding(reqs), plan(reqs), response([fault, duration]), [fault, duration], principal(), now=NOW
    )
    assert result.decision.action == VerificationAction.ACCEPT
    assert result.audit.duplicate_groups == []
    assert result.audit.coverage_score == 1.0


def test_product_version_mismatch_blocks_accept():
    reqs = ["给出适用产品版本的操作步骤"]
    query = understanding(reqs)
    query.product_version = "V3"
    row = evidence(
        "manual-v2", "复位步骤：长按复位键五秒。", "manual", product_version="V2"
    )
    result = verify_evidence(query, plan(reqs), response([row]), [row], principal(), now=NOW)
    assert result.decision.action != VerificationAction.ACCEPT
    assert result.audit.evidence_validity[0].product_version_compatible is False


def test_missing_verification_decision_routes_to_safe_handoff():
    from agents import knowledge_agent as ka
    assert ka.route_after_grade({}) == "handoff"
    assert ka.route_after_verify({}) == "handoff"


def test_rule_fallback_decomposes_multi_requirement_question():
    from agents import knowledge_agent as ka
    rows = ka._heuristic_requirements("AX-300 出现 E502，是否可以免费维修，大概多久修好？", ["E502"])
    assert len(rows) == 3
    assert any("故障" in item for item in rows)
    assert any("免费维修" in item for item in rows)
    assert any("维修周期" in item for item in rows)


def test_benchmark_adapter_invokes_production_graph_and_scores_action(monkeypatch):
    from evals.benchmark.adapters import behavior
    from evals.benchmark.scoring.scorer import score_row

    called = {"invoke": 0}

    class FakeGraph:
        def invoke(self, state):
            called["invoke"] += 1
            assert state["principal"]["region"] == "CN"
            return {
                "verification_decision": VerificationDecision(
                    action="supplement",
                    reason="missing policy evidence",
                    missing_requirements=["免费维修条件"],
                    next_subqueries=[
                        RetrievalSubquery(
                            subquery_id="bench-sq",
                            query="AX-300 免费维修条件",
                            source="policy",
                        )
                    ],
                ).to_state(),
                "verification_rounds": [{"round_id": 1}],
                "evidence_audit": {"requirement_coverages": [], "conflicts": [], "coverage_score": 0.5, "method": "rules"},
            }

    monkeypatch.setattr(behavior, "create_knowledge_agent", lambda **kwargs: FakeGraph())
    row = behavior.predict({"id": "BEH-stage3", "input": {"question": "AX-300 是否免费维修？"}})
    assert called["invoke"] == 1
    assert row["prediction"]["verification_action"] == "supplement"
    scores = score_row(
        {
            "layer": "agent_behavior",
            "gold": {
                "expected_action": "retrieve_more",
                "expected_verification_action": "supplement",
                "reason_codes": ["missing policy evidence"],
                "required_clarification_slots": [],
                "required_supplemental_sources": ["policy"],
                "max_retrieval_rounds": 2,
            },
        },
        row["prediction"],
    )
    assert scores["verification_action_accuracy"] == 1.0


def test_retrieval_response_document_is_checkpoint_safe():
    row = evidence("checkpoint-doc", "错误码 E502 表示传感器异常。", "manual")
    payload = response([row]).to_state()
    encoded = json.dumps(payload, ensure_ascii=False)
    restored = json.loads(encoded)
    assert restored["evidences"][0]["document"]["page_content"].startswith("错误码 E502")
    assert restored["evidences"][0]["document"]["metadata"]["chunk_id"] == "checkpoint-doc"


def test_json_checkpointed_evidence_can_resume_production_verification():
    from agents import knowledge_agent as ka

    reqs = ["解释 E502 的故障含义"]
    row = evidence("resume-e1", "错误码 E502 表示温度传感器异常。", "manual")
    understanding_state = understanding(reqs).to_state()
    plan_state = plan(reqs).to_state()
    response_state = response([row]).to_state()
    checkpoint = json.loads(json.dumps({
        "query_understanding": understanding_state,
        "retrieval_plan_v2": plan_state,
        "retrieval_response": response_state,
        "evidences": response_state["evidences"],
        "principal": principal().to_state(),
        "retry_count": 0,
        "trace_events": [],
        "requirements": reqs,
    }, ensure_ascii=False))
    update = ka.grade_evidence(checkpoint)
    assert update["verification_action"] == "accept"
    assert update["evidence_audit"]["coverage_score"] == 1.0
    assert update["verified_evidences"][0]["document"].metadata["chunk_id"] == "resume-e1"


def test_different_current_policy_ids_do_not_use_unrelated_version_order():
    reqs = ["判断是否满足免费维修条件"]
    one = evidence(
        "policy-a", "AX-300 支持免费维修。", "policy", version="v1",
        policy_id="P-A", conflict_group="warranty", conflict_key="free_repair", conflict_value="yes",
    )
    other = evidence(
        "policy-b", "AX-300 不支持免费维修。", "policy", version="v9",
        policy_id="P-B", conflict_group="warranty", conflict_key="free_repair", conflict_value="no",
    )
    result = verify_evidence(understanding(reqs), plan(reqs), response([one, other]), [one, other], principal(), now=NOW)
    assert result.decision.action == VerificationAction.HANDOFF
    assert result.audit.conflicts[0].preferred_evidence_id is None


def test_conflict_group_scopes_identical_conflict_keys():
    reqs = ["判断是否满足免费维修条件"]
    consumer = evidence(
        "consumer", "消费者版本支持免费维修。", "policy",
        policy_id="P-C", conflict_group="consumer", conflict_key="free_repair", conflict_value="yes",
    )
    enterprise = evidence(
        "enterprise", "企业版本不支持免费维修。", "policy",
        policy_id="P-E", conflict_group="enterprise", conflict_key="free_repair", conflict_value="no",
    )
    result = verify_evidence(
        understanding(reqs), plan(reqs), response([consumer, enterprise]), [consumer, enterprise], principal(), now=NOW
    )
    assert result.audit.conflicts == []


def test_only_expired_conflicting_policies_request_new_evidence_not_conflict_handoff():
    reqs = ["判断是否满足免费维修条件"]
    a = evidence(
        "expired-a", "AX-300 支持免费维修。", "policy", effective_to="2025-01-01",
        policy_id="P-A", conflict_key="free_repair", conflict_value="yes",
    )
    b = evidence(
        "expired-b", "AX-300 不支持免费维修。", "policy", effective_to="2025-01-01",
        policy_id="P-B", conflict_key="free_repair", conflict_value="no",
    )
    result = verify_evidence(understanding(reqs), plan(reqs), response([a, b]), [a, b], principal(), now=NOW)
    assert result.audit.unresolved_high_risk_conflicts is False
    assert result.decision.action in {VerificationAction.REWRITE, VerificationAction.SUPPLEMENT}


def test_multi_requirement_broad_plan_decomposes_when_nothing_is_covered():
    reqs = ["解释 E502 的故障含义", "判断是否满足免费维修条件"]
    result = verify_evidence(
        understanding(reqs), plan(reqs, broad=True), RetrievalResponse(status="no_results"), [], principal(), now=NOW
    )
    assert result.decision.action == VerificationAction.DECOMPOSE
    assert {item.required_evidence[0] for item in result.decision.next_subqueries} == set(reqs)


def test_single_clear_requirement_rewrites_when_initial_query_retrieves_nothing():
    reqs = ["解释 E502 的故障含义"]
    result = verify_evidence(
        understanding(reqs), plan(reqs), RetrievalResponse(status="no_results"), [], principal(), now=NOW
    )
    assert result.decision.action == VerificationAction.REWRITE
    assert result.decision.next_subqueries[0].required_evidence == reqs


def test_safe_non_acl_filter_can_be_relaxed_but_region_cannot():
    reqs = ["解释 E502 的故障含义"]
    strict_plan = RetrievalPlan(
        strategy="strict",
        subqueries=[RetrievalSubquery(
            subquery_id="strict-sq", query="AX-300 E502", source="manual",
            filters={"doc_type": "repair_manual", "region": "CN", "tenant_id": "tenant-1"},
            required_evidence=reqs,
        )],
        max_rounds=3,
        original_requirements=reqs,
    )
    result = verify_evidence(
        understanding(reqs), strict_plan, RetrievalResponse(status="no_results"), [], principal(), now=NOW
    )
    assert result.decision.action == VerificationAction.RELAX_FILTERS
    assert result.decision.filters_to_relax == ["doc_type"]
    assert "region" not in result.decision.filters_to_relax
    assert "tenant_id" not in result.decision.filters_to_relax


def test_repeated_targeted_signature_exits_instead_of_looping():
    reqs = ["解释 E502 的故障含义"]
    first = verify_evidence(
        understanding(reqs), plan(reqs), RetrievalResponse(status="no_results"), [], principal(), now=NOW
    )
    signatures = {subquery_signature(item) for item in first.decision.next_subqueries}
    second = verify_evidence(
        understanding(reqs), plan(reqs), RetrievalResponse(status="no_results"), [], principal(),
        executed_signatures=signatures, now=NOW,
    )
    assert second.decision.action == VerificationAction.HANDOFF
    assert second.decision.next_subqueries == []


def test_policy_without_effective_metadata_is_not_accepted_as_current():
    reqs = ["判断是否满足免费维修条件"]
    row = evidence(
        "undated-policy", "保修期内非人为损坏支持免费维修。", "policy",
        effective_from=None, effective_to=None, policy_id="P-undated",
    )
    result = verify_evidence(understanding(reqs), plan(reqs), response([row]), [row], principal(), now=NOW)
    assert result.decision.action != VerificationAction.ACCEPT
    assert result.audit.evidence_validity[0].temporal_information_complete is False
    assert result.audit.requirement_coverages[0].validity_sufficient is False


def test_policy_without_region_metadata_is_not_accepted_for_region_specific_requirement():
    reqs = ["判断是否满足免费维修条件"]
    row = evidence("no-region", "保修期内支持免费维修。", "policy", policy_id="P-no-region")
    row["document"].metadata.pop("region", None)
    result = verify_evidence(understanding(reqs), plan(reqs), response([row]), [row], principal(), now=NOW)
    assert result.decision.action != VerificationAction.ACCEPT
    assert result.audit.evidence_validity[0].region_information_complete is False


def test_low_authority_faq_cannot_establish_warranty_eligibility():
    reqs = ["判断是否满足免费维修条件"]
    row = evidence("faq-low", "常见问答称可能支持免费维修。", "faq")
    result = verify_evidence(understanding(reqs), plan(reqs), response([row]), [row], principal(), now=NOW)
    assert result.decision.action != VerificationAction.ACCEPT
    coverage = result.audit.requirement_coverages[0]
    assert coverage.authority_required is True
    assert coverage.authority_sufficient is False


def test_product_specific_requirement_needs_product_metadata_on_evidence():
    reqs = ["解释 E502 的故障含义"]
    row = evidence("generic-manual", "错误码 E502 表示温度传感器异常。", "manual")
    md = row["document"].metadata
    md.pop("product_model", None)
    md.pop("product_models", None)
    md.pop("product_id", None)
    md.pop("product_name", None)
    result = verify_evidence(understanding(reqs), plan(reqs), response([row]), [row], principal(), now=NOW)
    assert result.decision.action != VerificationAction.ACCEPT
    assert result.audit.evidence_validity[0].product_information_complete is False


def test_verifier_internal_failure_routes_to_handoff_not_answer(monkeypatch):
    from agents import knowledge_agent as ka

    monkeypatch.setattr(ka, "verify_evidence", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bad policy config")))
    reqs = ["解释 E502 的故障含义"]
    state = {
        "query_understanding": understanding(reqs).to_state(),
        "retrieval_plan_v2": plan(reqs).to_state(),
        "retrieval_response": response([evidence("err-e1", "错误码 E502 表示传感器异常。", "manual")]).to_state(),
        "evidences": [evidence("err-e1", "错误码 E502 表示传感器异常。", "manual")],
        "principal": principal().to_state(),
        "requirements": reqs,
        "trace_events": [],
    }
    update = ka.grade_evidence(state)
    assert update["verification_action"] == "handoff"
    assert update["verification_errors"][0]["stage"] == "evidence_verifier"
    assert ka.route_after_grade(update) == "handoff"


def test_verification_round_records_trigger_coverage_and_budget_change():
    from agents import knowledge_agent as ka

    reqs = ["解释 E502 的故障含义"]
    row = evidence("round-e1", "错误码 E502 表示温度传感器异常。", "manual")
    state = {
        "query_understanding": understanding(reqs).to_state(),
        "retrieval_plan_v2": plan(reqs).to_state(),
        "retrieval_response": response([row]).to_state(),
        "evidences": [row],
        "principal": principal().to_state(),
        "requirements": reqs,
        "retry_count": 1,
        "verification_action": "supplement",
        "coverage_score": 0.0,
        "last_new_evidence_ids": ["round-e1"],
        "last_retrieval_budget_before": {"sparse_queries_used": 1},
        "last_retrieval_budget_after": {"sparse_queries_used": 2},
        "trace_events": [],
    }
    update = ka.grade_evidence(state)
    record = update["verification_rounds"][-1]
    assert record["round_id"] == 2
    assert record["trigger"] == "supplement_retrieval"
    assert record["new_evidence_ids"] == ["round-e1"]
    assert record["coverage_before"] == 0.0
    assert record["coverage_after"] == 1.0
    assert record["coverage_change"] == 1.0
    assert record["budget_before"]["sparse_queries_used"] == 1
    assert record["budget_after"]["sparse_queries_used"] == 2


def test_safe_handoff_labels_covered_missing_and_human_reason():
    from agents import knowledge_agent as ka

    audit = EvidenceAudit(
        requirement_coverages=[
            {
                "requirement_id": "req-1", "requirement": "解释故障含义", "covered": True,
                "evidence_ids": ["partial-e1"], "confidence": 0.9,
                "authority_sufficient": True, "validity_sufficient": True,
            },
            {
                "requirement_id": "req-2", "requirement": "判断免费维修条件", "covered": False,
                "evidence_ids": [], "confidence": 0.0,
            },
        ],
        accepted_evidence_ids=["partial-e1"],
        coverage_score=0.5,
    )
    decision = VerificationDecision(
        action="handoff", reason="missing policy", missing_requirements=["判断免费维修条件"],
        handoff_reason="需要人工核对当前政策", partial_answer_allowed=True,
    )
    row = evidence("partial-e1", "错误码 E502 表示传感器异常。", "manual")
    update = ka.handoff({
        "verification_decision": decision.to_state(),
        "evidence_audit": audit.to_state(),
        "verified_evidences": [row],
        "trace_events": [],
    })
    assert "已取得可靠证据的部分" in update["answer"]
    assert "仍缺少可靠证据的部分" in update["answer"]
    assert "转人工原因" in update["answer"]
