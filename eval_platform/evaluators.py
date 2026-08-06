"""Built-in deterministic evaluators over existing Liorin runtime outputs.

These functions adapt Context, Memory, Artifact and Agent signals to the
unified :mod:`eval_platform` runner. They do not replace existing evaluators;
they provide a common invocation contract for them.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from eval_platform.dataset import EvaluationScenario
from evaluators.memory_governance import MemoryEvaluationCase, evaluate_memory_cases


def _as_set(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset((value,))
    return frozenset(str(item) for item in value)


def context_evaluator(
    scenario: EvaluationScenario,
    output: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> Mapping[str, float]:
    expected = scenario.expected
    before = float(output.get("context_tokens_before", expected.get("context_tokens_before", 0)) or 0)
    after = float(output.get("context_tokens_after", output.get("context_tokens", 0)) or 0)
    state_preserved = bool(output.get("state_preserved", expected.get("state_preserved", True)))
    reduction = 1.0 - after / before if before > 0 else 0.0
    return {
        "context_token_reduction": max(0.0, min(1.0, reduction)),
        "context_state_preservation": 1.0 if state_preserved else 0.0,
    }


def memory_evaluator(
    scenario: EvaluationScenario,
    output: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> Mapping[str, float]:
    report = evaluate_memory_cases((
        MemoryEvaluationCase(
            expected_fact_ids=_as_set(scenario.expected.get("memory_fact_ids")),
            retrieved_fact_ids=_as_set(output.get("memory_fact_ids")),
            expired_fact_ids=_as_set(scenario.expected.get("expired_fact_ids")),
            deleted_fact_ids=_as_set(scenario.expected.get("deleted_fact_ids")),
        ),
    ))
    return {
        "memory_precision": report.memory_precision,
        "memory_recall": report.memory_recall,
        "wrong_injection_rate": report.wrong_injection_rate,
        "stale_memory_rate": report.stale_memory_rate,
        "forgetting_accuracy": report.forgetting_accuracy,
    }


def artifact_evaluator(
    scenario: EvaluationScenario,
    output: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> Mapping[str, float]:
    expected_ids = _as_set(scenario.expected.get("artifact_ids"))
    referenced_ids = _as_set(output.get("artifact_ids"))
    expected_recovery = bool(scenario.expected.get("artifact_recovery", True))
    recovered = bool(output.get("artifact_recovery", False))
    correctness = len(expected_ids & referenced_ids) / len(expected_ids) if expected_ids else 1.0
    return {
        "artifact_reference_correctness": correctness,
        "artifact_recovery_success": 1.0 if recovered == expected_recovery else 0.0,
    }


def agent_evaluator(
    scenario: EvaluationScenario,
    output: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> Mapping[str, float]:
    expected = scenario.expected
    task_success = bool(output.get("task_success", False))
    expected_success = bool(expected.get("task_success", True))
    expected_tools = _as_set(expected.get("tool_names"))
    actual_tools = _as_set(output.get("tool_names"))
    tool_correctness = len(expected_tools & actual_tools) / len(expected_tools) if expected_tools else 1.0
    expected_fallback = bool(expected.get("fallback", False))
    actual_fallback = bool(output.get("fallback", False))
    return {
        "task_success": 1.0 if task_success == expected_success else 0.0,
        "tool_correctness": tool_correctness,
        "fallback_quality": 1.0 if actual_fallback == expected_fallback else 0.0,
    }


BUILTIN_EVALUATORS = {
    "context": context_evaluator,
    "memory": memory_evaluator,
    "artifact": artifact_evaluator,
    "agent": agent_evaluator,
}

__all__ = [
    "BUILTIN_EVALUATORS",
    "agent_evaluator",
    "artifact_evaluator",
    "context_evaluator",
    "memory_evaluator",
]
