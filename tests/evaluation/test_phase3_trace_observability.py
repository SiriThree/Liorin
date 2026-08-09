from __future__ import annotations

from eval_platform.production_adapter import ProductionEvaluationAdapter, TraceAdapter
from observability import get_default_trace_recorder
from retrieval.trace import trace_event


def test_real_retrieval_trace_bridge_preserves_round_and_structured_evidence_on_one_trace():
    recorder = get_default_trace_recorder()
    request_id = "phase3-trace-bridge-contract"
    with recorder.trace(
        request_id=request_id,
        conversation_id="conversation:p3",
        thread_id="thread:p3",
        agent_name="support_agent",
    ) as trace:
        trace_event(
            "evidence",
            "structured_tool_result",
            status="accepted",
            source="database",
            trace_level="evidence",
            round_id=1,
            evidence_id="record:ticket:TCK-1",
            stable_ref="record:ticket:TCK-1#status",
            record_type="ticket",
            record_id="TCK-1",
            field_path="status",
            observed_value="处理中",
            tool_name="execute_sql_template",
            result_ref="sql-template:ticket_detail:TCK-1",
            selected_for_answer=True,
        )
        trace_event(
            "verify_evidence",
            "complete",
            status="complete",
            round_id=1,
            action="accept",
            accepted_evidence_ids=[],
            excluded_evidence_ids=[],
        )

    facts = TraceAdapter().adapt(trace.to_state())
    assert facts["trace_id"] == request_id
    assert facts["verification_rounds"][0]["round_id"] == 1
    event = facts["evidence_events"][0]
    assert event["stable_ref"] == "record:ticket:TCK-1#status"
    assert event["record_type"] == "ticket"
    assert event["record_id"] == "TCK-1"
    assert event["field_path"] == "status"
    assert event["selected_for_answer"] is True
    assert "record:ticket:TCK-1#status" in facts["selected_evidence_ids"]


def test_one_pass_adapter_uses_same_deployment_loader_with_only_recovery_disabled(monkeypatch):
    calls = []
    sentinel = object()

    def fake_loader(enabled: bool):
        calls.append(enabled)
        return sentinel

    monkeypatch.setattr("eval_platform.production_adapter._load_production_graph_with_recovery", fake_loader)
    adapter = ProductionEvaluationAdapter.for_agentic_recovery(enabled=False)
    assert adapter._graph_instance() is sentinel
    assert calls == [False]
