from __future__ import annotations

from eval_platform import ProductionEvaluationAdapter, RuntimeCaseInput
from observability import RuntimeEventType, TraceRecorder


class FakeProductionGraph:
    def __init__(self, recorder: TraceRecorder):
        self.recorder = recorder
        self.calls = 0
        self.invocations = []

    def invoke(self, state, *, config=None, context=None):
        self.calls += 1
        self.invocations.append((state, config, context))
        self.recorder.emit(
            RuntimeEventType.WORKFLOW_DECISION,
            attributes={"stage": "query_router", "action": "supervisor_agent"},
        )
        self.recorder.emit(
            RuntimeEventType.TOOL_STARTED,
            attributes={"tool_name": "knowledge_agent"},
        )
        return {"messages": [*state["messages"], {"role": "assistant", "content": "grounded answer"}]}


def test_production_adapter_invokes_one_graph_once_and_returns_one_trace():
    recorder = TraceRecorder()
    graph = FakeProductionGraph(recorder)
    adapter = ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder)
    case = RuntimeCaseInput(
        case_id="case-1",
        messages=({"role": "user", "content": "question"},),
        identity={"tenant_id": "tenant:a", "user_id": "user:a"},
    )

    record = adapter.run(case)

    assert graph.calls == 1
    assert record.final_response == "grounded answer"
    assert record.execution_status == "COMPLETED"
    assert record.trace_id == record.trace_facts["trace_id"]
    assert record.trace_facts["tool_names"] == ["knowledge_agent"]
    assert len(recorder.traces()) == 1
    _, config, _ = graph.invocations[0]
    assert config["configurable"]["tenant_id"] == "tenant:a"
    assert config["configurable"]["user_id"] == "user:a"
