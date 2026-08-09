from __future__ import annotations

import ast
from importlib.util import find_spec
from pathlib import Path

import pytest

from eval_platform.readiness import ReadinessStatus, build_evaluation_readiness

ROOT = Path(__file__).resolve().parents[2]


def _module_available(name: str) -> bool:
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def test_order_agent_uses_only_safe_template_tool_and_no_sql_prompt_contract():
    source = (ROOT / "agents" / "order_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tools.database":
            imported.update(alias.name for alias in node.names)
    assert "execute_sql_template" in imported
    assert "execute_sql" not in imported
    assert "ORDER_AGENT_BASE_TOOLS = [execute_sql_template]" in source
    assert "不要生成、拼接或输出 SQL" in source
    assert "state_schema\": state_schema or OrderAgentState" in source


def test_supervisor_forwards_hidden_verified_identity_to_order_specialist():
    source = (ROOT / "agents" / "conversation_supervisor.py").read_text(encoding="utf-8")
    assert "def call_order_agent(query: str, runtime: ToolRuntime)" in source
    assert 'nested_state["identity_context"] = identity.to_state()' in source
    assert 'nested_state["tenant_id"] = identity.tenant_id' in source
    assert 'nested_state["customer_id"]' in source
    assert 'nested_state["structured_permissions"]' in source
    # Identity is runtime state, not model-visible tool arguments.
    assert "def call_order_agent(query: str, tenant_id" not in source
    assert "def call_order_agent(query: str, customer_id" not in source


def test_customer_verification_is_parameterized_and_tenant_bound():
    source = (ROOT / "agents" / "support_workflow.py").read_text(encoding="utf-8")
    assert "lookup_customer_by_email(email)" in source
    assert "customer_tenant_id" in source
    assert "customer_tenant_id) != str(tenant_id)" in source
    assert "structured:read:self" not in source  # capability constant comes from tools.database
    assert "db._execute(" not in source
    assert "SELECT customer_id, name FROM customers WHERE email =" not in source


def test_phase7_doctor_checks_real_local_structured_backend_and_dataset():
    readiness = build_evaluation_readiness(ROOT)
    items = readiness.by_name()
    assert items["structured_data_backend"].status is ReadinessStatus.READY
    assert items["canonical_dataset"].details["case_count"] == 39
    assert items["validation_split"].details["case_count"] == 5
    assert items["safety_subset"].details["eligible_cases"] == 3
    assert items["multi_turn_subset"].status is ReadinessStatus.NOT_READY
    assert items["recovery_subset"].status is ReadinessStatus.NOT_READY


def test_real_production_import_integration_when_dependencies_are_available():
    required = ["langchain", "langchain_core", "langgraph", "pymilvus"]
    missing = [name for name in required if not _module_available(name)]
    if missing:
        pytest.skip(f"real Production dependencies unavailable: {missing}")
    import deployments.support_agent_graph as deployment
    assert deployment.graph is not None
    assert deployment.build_graph() is not None


def test_real_judge_provider_import_integration_when_langchain_is_available():
    if not _module_available("langchain"):
        pytest.skip("real Judge provider dependency unavailable: langchain")
    from langchain.chat_models import init_chat_model
    assert callable(init_chat_model)


def test_hashed_structured_trace_identity_matches_canonical_gold_without_exposing_record_id():
    from eval_platform.contracts import EvaluationEvidenceRef, EvidenceSourceType, GoldEvidence
    from eval_platform.evidence import evidence_matches
    from retrieval.security import hash_identifier

    raw_id = "ORD-2024-00321"
    hashed_id = f"hash:{hash_identifier(raw_id, namespace='structured:order')}"
    gold = GoldEvidence(
        evidence_id="gold-order-date",
        source_type=EvidenceSourceType.STRUCTURED_DATA,
        record_type="order",
        record_id=raw_id,
        field_path="order_date",
    )
    actual = EvaluationEvidenceRef(
        stable_id=f"record:order:{hashed_id}#order_date",
        source_type=EvidenceSourceType.STRUCTURED_DATA,
        record_type="order",
        record_id=hashed_id,
        field_path="order_date",
    )
    assert raw_id not in actual.stable_id
    assert evidence_matches(gold, actual)
