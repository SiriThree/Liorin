"""Deterministic Memory governance evaluation integrated with Liorin evaluators."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class MemoryEvaluationCase:
    expected_fact_ids: frozenset[str]
    retrieved_fact_ids: frozenset[str]
    expired_fact_ids: frozenset[str] = frozenset()
    deleted_fact_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class MemoryEvaluationReport:
    memory_precision: float
    memory_recall: float
    wrong_injection_rate: float
    stale_memory_rate: float
    forgetting_accuracy: float
    expected_count: int
    retrieved_count: int

    def to_state(self) -> dict[str, float | int]:
        return {
            "memory_precision": self.memory_precision,
            "memory_recall": self.memory_recall,
            "wrong_injection_rate": self.wrong_injection_rate,
            "stale_memory_rate": self.stale_memory_rate,
            "forgetting_accuracy": self.forgetting_accuracy,
            "expected_count": self.expected_count,
            "retrieved_count": self.retrieved_count,
        }


def evaluate_memory_cases(cases: Iterable[MemoryEvaluationCase]) -> MemoryEvaluationReport:
    true_positive = 0
    expected_total = 0
    retrieved_total = 0
    wrong_total = 0
    stale_total = 0
    deleted_expected = 0
    deleted_retrieved = 0

    for case in cases:
        expected = set(case.expected_fact_ids)
        retrieved = set(case.retrieved_fact_ids)
        expired = set(case.expired_fact_ids)
        deleted = set(case.deleted_fact_ids)
        true_positive += len(expected & retrieved)
        expected_total += len(expected)
        retrieved_total += len(retrieved)
        wrong_total += len(retrieved - expected)
        stale_total += len(retrieved & expired)
        deleted_expected += len(deleted)
        deleted_retrieved += len(retrieved & deleted)

    precision = true_positive / retrieved_total if retrieved_total else (1.0 if expected_total == 0 else 0.0)
    recall = true_positive / expected_total if expected_total else 1.0
    wrong_rate = wrong_total / retrieved_total if retrieved_total else 0.0
    stale_rate = stale_total / retrieved_total if retrieved_total else 0.0
    forgetting = 1.0 - (deleted_retrieved / deleted_expected) if deleted_expected else 1.0
    return MemoryEvaluationReport(
        memory_precision=precision,
        memory_recall=recall,
        wrong_injection_rate=wrong_rate,
        stale_memory_rate=stale_rate,
        forgetting_accuracy=forgetting,
        expected_count=expected_total,
        retrieved_count=retrieved_total,
    )


def memory_evaluator(*, expected_fact_ids, retrieved_fact_ids, expired_fact_ids=(), deleted_fact_ids=()):
    """LangSmith-compatible evaluator result without requiring an LLM judge."""
    report = evaluate_memory_cases([
        MemoryEvaluationCase(
            expected_fact_ids=frozenset(expected_fact_ids),
            retrieved_fact_ids=frozenset(retrieved_fact_ids),
            expired_fact_ids=frozenset(expired_fact_ids),
            deleted_fact_ids=frozenset(deleted_fact_ids),
        )
    ])
    return {
        "key": "memory_governance",
        "score": report.memory_precision,
        "comment": report.to_state(),
    }


__all__ = [
    "MemoryEvaluationCase",
    "MemoryEvaluationReport",
    "evaluate_memory_cases",
    "memory_evaluator",
]
