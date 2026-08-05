"""Reproducible 10-configuration Agentic RAG ablation runner."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from random import Random
import statistics
from typing import Any, Callable


@dataclass(frozen=True)
class AblationConfig:
    name: str
    dense: bool = True
    bm25: bool = True
    fusion: bool = True
    reranker: bool = True
    parent_expansion: bool = True
    verifier: bool = True
    verifier_loop: bool = True
    query_planner: bool = True


ABLATIONS = (
    AblationConfig("dense_only", bm25=False, fusion=False, reranker=False, parent_expansion=False, verifier=False, verifier_loop=False, query_planner=False),
    AblationConfig("bm25_only", dense=False, fusion=False, reranker=False, parent_expansion=False, verifier=False, verifier_loop=False, query_planner=False),
    AblationConfig("dense_bm25", fusion=False, reranker=False, parent_expansion=False, verifier=False, verifier_loop=False, query_planner=False),
    AblationConfig("hybrid_fusion", reranker=False, parent_expansion=False, verifier=False, verifier_loop=False, query_planner=False),
    AblationConfig("hybrid_reranker", parent_expansion=False, verifier=False, verifier_loop=False, query_planner=False),
    AblationConfig("hybrid_parent_expansion", verifier=False, verifier_loop=False, query_planner=False),
    AblationConfig("hybrid_verifier", verifier_loop=False, query_planner=False),
    AblationConfig("hybrid_verifier_loop", query_planner=False),
    AblationConfig("hybrid_query_planner", verifier=False, verifier_loop=False),
    AblationConfig("full_agentic_rag"),
)


class AblationUnavailable(RuntimeError):
    """Raised when a configuration cannot run without a missing real dependency."""


def _bootstrap_ci(differences: list[float], *, seed: int = 20260805, samples: int = 1000) -> tuple[float, float]:
    if not differences:
        return 0.0, 0.0
    rng = Random(seed)
    means = []
    for _ in range(samples):
        draw = [differences[rng.randrange(len(differences))] for _ in differences]
        means.append(statistics.mean(draw))
    ordered = sorted(means)
    return ordered[int(0.025 * (len(ordered) - 1))], ordered[int(0.975 * (len(ordered) - 1))]


def run_ablations(
    evaluate: Callable[[AblationConfig], list[dict[str, float]]],
    *,
    primary_metric: str = "ndcg@10",
    repetitions: int = 3,
) -> dict[str, Any]:
    """Run all configurations without inventing scores for unavailable dependencies.

    The evaluator must call the production components selected by ``AblationConfig``.
    Missing Milvus/model/graph dependencies should raise ``AblationUnavailable``;
    the result records ``not_run`` instead of converting the failure to zero.
    """
    results: dict[str, Any] = {}
    baseline_rows: list[dict[str, float]] | None = None
    previous_rows: list[dict[str, float]] | None = None
    previous_name: str | None = None
    for config in ABLATIONS:
        try:
            repetitions_rows = [evaluate(config) for _ in range(repetitions)]
        except AblationUnavailable as exc:
            results[config.name] = {
                "config": asdict(config),
                "status": "not_run",
                "reason": str(exc),
                "primary_metric": primary_metric,
                "repetitions": 0,
            }
            previous_name = config.name
            previous_rows = None
            continue
        per_run = [statistics.mean(row.get(primary_metric, 0.0) for row in rows) if rows else 0.0 for rows in repetitions_rows]
        flattened = repetitions_rows[0] if repetitions_rows else []
        if config.name == "dense_only":
            baseline_rows = flattened
        metric_names = sorted({key for rows in repetitions_rows for row in rows for key in row})
        metric_runs = {
            metric: [statistics.mean(row.get(metric, 0.0) for row in rows) if rows else 0.0 for rows in repetitions_rows]
            for metric in metric_names
        }
        vs_dense: list[float] = []
        if baseline_rows is not None and len(baseline_rows) == len(flattened):
            vs_dense = [row.get(primary_metric, 0.0) - base.get(primary_metric, 0.0) for row, base in zip(flattened, baseline_rows)]
        vs_previous: list[float] = []
        if previous_rows is not None and len(previous_rows) == len(flattened):
            vs_previous = [row.get(primary_metric, 0.0) - base.get(primary_metric, 0.0) for row, base in zip(flattened, previous_rows)]
        dense_ci = _bootstrap_ci(vs_dense)
        previous_ci = _bootstrap_ci(vs_previous)
        results[config.name] = {
            "config": asdict(config),
            "status": "completed",
            "primary_metric": primary_metric,
            "mean": statistics.mean(per_run),
            "stddev": statistics.pstdev(per_run) if len(per_run) > 1 else 0.0,
            "metric_means": {key: statistics.mean(values) for key, values in metric_runs.items()},
            "metric_stddev": {key: statistics.pstdev(values) if len(values) > 1 else 0.0 for key, values in metric_runs.items()},
            "repetitions": repetitions,
            "paired_delta_vs_dense_only": statistics.mean(vs_dense) if vs_dense else None,
            "paired_bootstrap_95_ci_vs_dense_only": list(dense_ci) if vs_dense else None,
            "previous_configuration": previous_name,
            "paired_delta_vs_previous": statistics.mean(vs_previous) if vs_previous else None,
            "paired_bootstrap_95_ci_vs_previous": list(previous_ci) if vs_previous else None,
            "stable_direction_vs_previous": bool(vs_previous) and (previous_ci[0] > 0 or previous_ci[1] < 0),
        }
        # Retain Stage-4's original key for existing consumers.
        results[config.name]["paired_bootstrap_95_ci"] = list(dense_ci) if vs_dense else [0.0, 0.0]
        results[config.name]["stable_direction"] = bool(vs_dense) and (dense_ci[0] > 0 or dense_ci[1] < 0)
        previous_rows = flattened
        previous_name = config.name
    return {"primary_metric": primary_metric, "results": results}

