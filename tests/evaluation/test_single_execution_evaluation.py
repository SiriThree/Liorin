from __future__ import annotations

from eval_platform import ProductionEvaluationAdapter, RuntimeCaseInput
from observability import TraceRecorder


class FailingProductionGraph:
    def __init__(self):
        self.calls = 0

    def invoke(self, state, *, config=None, context=None):
        self.calls += 1
        raise RuntimeError("production graph failed")


def test_failed_production_execution_is_not_masked_by_second_execution():
    graph = FailingProductionGraph()
    recorder = TraceRecorder()
    adapter = ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder)
    case = RuntimeCaseInput(
        case_id="case-fail",
        messages=({"role": "user", "content": "question"},),
    )

    record = adapter.run(case)

    assert graph.calls == 1
    assert len(recorder.traces()) == 1
    assert record.execution_status == "FAILED"
    assert record.response_type == "error"
    assert record.final_response == ""
    assert "production graph failed" in (record.execution_error or "")
