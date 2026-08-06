"""Unified, JSON-safe evaluation reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ScenarioEvaluationResult:
    scenario_id: str
    output: Mapping[str, Any]
    scores: Mapping[str, float]
    trace: Mapping[str, Any]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    dataset_name: str
    results: tuple[ScenarioEvaluationResult, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def metrics(self) -> dict[str, float]:
        names = {name for result in self.results for name in result.scores}
        return {
            name: sum(result.scores.get(name, 0.0) for result in self.results) / len(self.results)
            for name in sorted(names)
        } if self.results else {}

    @property
    def success_rate(self) -> float:
        return sum(1 for result in self.results if result.error is None) / len(self.results) if self.results else 0.0

    def to_state(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "created_at": self.created_at.isoformat(),
            "scenario_count": len(self.results),
            "success_rate": self.success_rate,
            "metrics": self.metrics,
            "results": [
                {
                    "scenario_id": item.scenario_id,
                    "output": dict(item.output),
                    "scores": dict(item.scores),
                    "trace": dict(item.trace),
                    "error": item.error,
                }
                for item in self.results
            ],
        }
