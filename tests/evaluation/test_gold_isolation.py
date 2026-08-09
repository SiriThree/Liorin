from __future__ import annotations

import pytest

from eval_platform import EvaluationSample, ProductionEvaluationAdapter, RuntimeCaseInput
from evals.gold_isolation import assert_no_gold_leak
from observability import TraceRecorder


class NoopGraph:
    def invoke(self, state, *, config=None, context=None):
        return {"messages": [*state["messages"], {"role": "assistant", "content": "ok"}]}


def test_runtime_case_rejects_gold_and_expected_fields():
    with pytest.raises(ValueError, match="gold fields entered runtime packet"):
        RuntimeCaseInput(
            case_id="leak-gold",
            messages=({"role": "user", "content": "q"},),
            metadata={"gold_evidence": ["chunk-1"]},
        )

    with pytest.raises(ValueError, match="gold fields entered runtime packet"):
        RuntimeCaseInput(
            case_id="leak-expected",
            messages=({"role": "user", "content": "q"},),
            config={"expected_answer": "secret"},
        )


def test_evaluation_sample_keeps_gold_outside_runtime_boundary():
    runtime = RuntimeCaseInput(
        case_id="safe-case",
        messages=({"role": "user", "content": "q"},),
    )
    sample = EvaluationSample(
        sample_id="safe-case",
        runtime_input=runtime,
    )

    packet = sample.to_runtime_input().runtime_packet()
    assert_no_gold_leak(packet)
    assert "gold" not in packet
    assert "expected_answer" not in str(packet)


def test_production_adapter_refuses_gold_bearing_sample_object():
    runtime = RuntimeCaseInput(
        case_id="safe-case",
        messages=({"role": "user", "content": "q"},),
    )
    sample = EvaluationSample(sample_id="safe-case", runtime_input=runtime)
    adapter = ProductionEvaluationAdapter(graph=NoopGraph(), trace_recorder=TraceRecorder())

    with pytest.raises(TypeError, match="RuntimeCaseInput only"):
        adapter.run(sample)  # type: ignore[arg-type]
