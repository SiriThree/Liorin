"""Scenario runner connecting Dataset -> Runtime -> Trace -> Evaluator -> Report."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from eval_platform.dataset import EvaluationDataset, EvaluationScenario
from eval_platform.report import EvaluationReport, ScenarioEvaluationResult
from observability import TraceRecorder, get_default_metrics, get_default_trace_recorder

Evaluator = Callable[[EvaluationScenario, Mapping[str, Any], Mapping[str, Any]], Mapping[str, float] | float]


class EvaluationRunner:
    def __init__(
        self,
        runtime: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        *,
        evaluators: Mapping[str, Evaluator],
        trace_recorder: TraceRecorder | None = None,
    ) -> None:
        self.runtime = runtime
        self.evaluators = dict(evaluators)
        self.trace_recorder = trace_recorder or get_default_trace_recorder()

    def run(self, dataset: EvaluationDataset) -> EvaluationReport:
        results = []
        for scenario in dataset.scenarios:
            identity = scenario.inputs.get("identity_context") or {}
            conversation_id = str(identity.get("conversation_id") or scenario.metadata.get("conversation_id") or f"conversation:{scenario.scenario_id}")
            thread_id = str(identity.get("thread_id") or scenario.metadata.get("thread_id") or f"thread:{scenario.scenario_id}")
            request_id = str(scenario.metadata.get("request_id") or f"eval:{dataset.name}:{scenario.scenario_id}")
            output: Mapping[str, Any] = {}
            error = None
            scores: dict[str, float] = {}
            with self.trace_recorder.trace(
                request_id=request_id,
                conversation_id=conversation_id,
                thread_id=thread_id,
                agent_name=str(scenario.metadata.get("agent_name") or "support_agent"),
            ) as trace:
                try:
                    output = self.runtime(scenario.inputs)
                    for name, evaluator in self.evaluators.items():
                        raw = evaluator(scenario, output, trace.to_state())
                        if isinstance(raw, Mapping):
                            scores.update({str(key): float(value) for key, value in raw.items()})
                        else:
                            scores[name] = float(raw)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            results.append(ScenarioEvaluationResult(
                scenario_id=scenario.scenario_id,
                output=output,
                scores=scores,
                trace=trace.to_state(),
                error=error,
            ))
        report = EvaluationReport(dataset.name, tuple(results))
        metrics = get_default_metrics()
        metrics.set_value("answer_success_rate", report.success_rate)
        for name, value in report.metrics.items():
            metrics.set_value(name, value)
        return report
