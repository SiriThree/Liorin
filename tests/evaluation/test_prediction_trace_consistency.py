from __future__ import annotations

from eval_platform import ProductionEvaluationAdapter, RuntimeCaseInput
from observability import RuntimeEventType, TraceRecorder, invoke_observed_tool


class TraceRichGraph:
    def __init__(self, recorder: TraceRecorder):
        self.recorder = recorder
        self.calls = 0

    def invoke(self, state, *, config=None, context=None):
        self.calls += 1

        def specialist_operation():
            # This runs in invoke_observed_tool's timeout worker. Phase 0 trace
            # binding must keep the event on the parent production trace.
            self.recorder.emit(
                RuntimeEventType.RETRIEVAL_EVENT,
                attributes={
                    "step": "evidence",
                    "stage": "evidence",
                    "event": "verified",
                    "status": "accepted",
                    "data": {"evidence_id": "chunk-7", "retrieval_contributions": []},
                },
            )
            self.recorder.emit(
                RuntimeEventType.RETRIEVAL_EVENT,
                attributes={
                    "step": "verify_evidence",
                    "stage": "verify_evidence",
                    "event": "complete",
                    "status": "complete",
                    "data": {"round_id": 1, "action": "accept"},
                },
            )
            return "specialist answer"

        invoke_observed_tool(
            "knowledge_agent",
            specialist_operation,
            timeout_seconds=1.0,
            input_preview="question",
        )
        return {"messages": [*state["messages"], {"role": "assistant", "content": "final answer"}]}


def test_prediction_diagnostics_are_derived_from_same_trace_as_final_answer():
    recorder = TraceRecorder()
    graph = TraceRichGraph(recorder)
    adapter = ProductionEvaluationAdapter(graph=graph, trace_recorder=recorder)
    case = RuntimeCaseInput(
        case_id="trace-case",
        messages=({"role": "user", "content": "question"},),
    )

    record = adapter.run(case)

    assert graph.calls == 1
    assert len(recorder.traces()) == 1
    trace = recorder.get(record.trace_id)
    assert trace is not None
    event_request_ids = {event.request_id for event in trace.events}
    assert event_request_ids == {record.trace_id}
    assert record.trace_facts["trace_id"] == record.trace_id
    assert record.trace_facts["selected_evidence_ids"] == ["chunk-7"]
    assert record.trace_facts["verifier_actions"] == ["accept"]
    assert record.trace_facts["retrieval_rounds"] == 1
    assert record.trace_facts["tool_names"] == ["knowledge_agent"]
    assert record.final_response == "final answer"
