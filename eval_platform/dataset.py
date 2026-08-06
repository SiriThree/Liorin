"""Unified evaluation dataset contracts over existing Liorin benchmarks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class EvaluationScenario:
    scenario_id: str
    inputs: Mapping[str, Any]
    expected: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.scenario_id).strip():
            raise ValueError("scenario_id must not be empty")


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    name: str
    scenarios: tuple[EvaluationScenario, ...]

    @classmethod
    def from_iterable(cls, name: str, scenarios: Iterable[EvaluationScenario]) -> "EvaluationDataset":
        materialized = tuple(scenarios)
        if not materialized:
            raise ValueError("evaluation dataset must contain scenarios")
        return cls(name=name, scenarios=materialized)
