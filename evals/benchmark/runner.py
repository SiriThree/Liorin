"""Benchmark runner that calls the production Liorin Agent/RAG stack."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import DEFAULT_MODEL

from .adapters import behavior, end_to_end, retrieval, routing, understanding
from .corpus_registry import BenchmarkCorpusRegistry
from .data_paths import DATASETS, DATASET_TRUST_STATUS
from .scoring import score_predictions


LAYER_ADAPTERS: dict[str, Callable[..., dict[str, Any]]] = {
    "query_understanding": understanding.predict,
    "routing": routing.predict,
    "retrieval": retrieval.predict,
    "agent_behavior": behavior.predict,
    "answer_generation": end_to_end.predict,
    "end_to_end": end_to_end.predict,
}


@dataclass
class BenchmarkRunConfig:
    dataset: str = "validation"
    dataset_path: Path | None = None
    layers: set[str] = field(default_factory=set)
    limit: int | None = None
    output_path: Path = Path("evals/reports/benchmark_predictions.json")
    report_path: Path = Path("evals/reports/benchmark_report.json")
    allow_partial: bool = False
    model: str | None = None
    smoke_per_layer: bool = False


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


class BenchmarkRunner:
    def __init__(self, config: BenchmarkRunConfig):
        self.config = config
        self.registry = BenchmarkCorpusRegistry()

    @property
    def dataset_path(self) -> Path:
        if self.config.dataset_path:
            return self.config.dataset_path
        return DATASETS[self.config.dataset]

    def load_samples(self) -> list[dict[str, Any]]:
        rows = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        if self.config.layers:
            rows = [row for row in rows if row["layer"] in self.config.layers]
        if self.config.smoke_per_layer:
            selected = []
            seen = set()
            for row in rows:
                if row["layer"] in seen:
                    continue
                seen.add(row["layer"])
                selected.append(row)
            rows = selected
        if self.config.limit is not None:
            rows = rows[: self.config.limit]
        return rows

    def run_predictions(self) -> list[dict[str, Any]]:
        rows = []
        for sample in self.load_samples():
            adapter = LAYER_ADAPTERS[sample["layer"]]
            kwargs = {"model": self.config.model}
            if sample["layer"] in {"retrieval", "answer_generation", "end_to_end"}:
                kwargs["registry"] = self.registry
            row = adapter(sample, **kwargs)
            rows.append({"id": row["id"], "prediction": row["prediction"], "diagnostics": row.get("diagnostics", {})})
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return rows

    def _selected_samples_have_gold(self) -> bool:
        samples = self.load_samples()
        return bool(samples) and all(bool(sample.get("gold")) for sample in samples)

    def score(self) -> dict[str, Any]:
        if not self._selected_samples_have_gold():
            raise ValueError(
                "selected dataset has no local Gold; generate predictions only and score in the Gold-custodian environment"
            )
        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": git_commit(),
            "model": self.config.model or DEFAULT_MODEL,
            "dataset": self.config.dataset,
            "dataset_trust_status": DATASET_TRUST_STATUS.get(self.config.dataset, "CUSTOM_UNVERIFIED"),
            "layers": sorted(self.config.layers) if self.config.layers else "all",
        }
        report = score_predictions(
            self.config.output_path,
            self.dataset_path,
            layers=self.config.layers or None,
            allow_partial=self.config.allow_partial,
            run_metadata=metadata,
        )
        self.config.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def run(self) -> dict[str, Any]:
        rows = self.run_predictions()
        if not self._selected_samples_have_gold():
            report = {
                "dataset": str(self.dataset_path),
                "dataset_trust_status": DATASET_TRUST_STATUS.get(self.config.dataset, "CUSTOM_UNVERIFIED"),
                "sample_count": len(self.load_samples()),
                "prediction_count": len(rows),
                "macro_objective_score": None,
                "scoring_status": "PREDICTIONS_ONLY_GOLD_NOT_AVAILABLE",
                "warning": (
                    "No local Gold was available. No benchmark score was computed. "
                    "The historical 'blind' name is not a Phase-0 trust claim."
                ),
            }
            self.config.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report
        return self.score()
