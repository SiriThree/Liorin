"""Evaluation helpers for Liorin.

Optional LangChain/LangSmith evaluators remain available when their dependencies
are installed. Deterministic Memory evaluators are dependency-free.
"""
from evaluators.memory_governance import (
    MemoryEvaluationCase,
    MemoryEvaluationReport,
    evaluate_memory_cases,
    memory_evaluator,
)

try:
    from evaluators.evaluators import correctness_evaluator, count_total_tool_calls_evaluator
except ModuleNotFoundError:  # local governance tests do not require LangChain
    correctness_evaluator = None
    count_total_tool_calls_evaluator = None

__all__ = [
    "MemoryEvaluationCase",
    "MemoryEvaluationReport",
    "correctness_evaluator",
    "count_total_tool_calls_evaluator",
    "evaluate_memory_cases",
    "memory_evaluator",
]
