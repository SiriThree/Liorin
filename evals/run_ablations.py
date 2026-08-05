"""CLI for the ten production-component ablations.

Pass ``--evaluator package.module:function`` where the function accepts one
``AblationConfig`` and returns per-sample metric rows.  The evaluator is responsible
for invoking the existing production Planner/Retriever/Verifier graph, not a parallel
implementation.  ``--local-bm25-report`` is a limited current-environment mode: it
runs only the measured BM25-only row and explicitly marks the other nine unavailable.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Callable

from evals.ablation import AblationConfig, AblationUnavailable, run_ablations


def _load_evaluator(path: str) -> Callable[[AblationConfig], list[dict[str, float]]]:
    module_name, separator, function_name = path.partition(":")
    if not separator:
        raise ValueError("evaluator must use package.module:function syntax")
    callback = getattr(importlib.import_module(module_name), function_name)
    if not callable(callback):
        raise TypeError("evaluator is not callable")
    return callback


def _local_bm25_evaluator(report_path: Path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = [item["scores"] for item in report.get("details", [])]
    runtime = report.get("runtime_metrics", {})
    for row in rows:
        row["latency_ms"] = float(runtime.get("p50_latency_ms", 0.0))
        row["token_cost"] = 0.0
        row["external_dependency_calls"] = 0.0

    def evaluate(config: AblationConfig) -> list[dict[str, float]]:
        if config.name == "bm25_only":
            return [dict(item) for item in rows]
        requirements = []
        if config.dense:
            requirements.append("real Milvus/embedding runtime")
        if config.reranker:
            requirements.append("real CrossEncoder runtime")
        if config.verifier or config.query_planner:
            requirements.append("real LangGraph/LLM runtime")
        raise AblationUnavailable(
            "current environment cannot execute this configuration: " + ", ".join(requirements or ["production graph runtime"])
        )

    return evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--evaluator")
    group.add_argument("--local-bm25-report")
    parser.add_argument("--primary-metric", default="ndcg@10")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    evaluator = (
        _load_evaluator(args.evaluator)
        if args.evaluator
        else _local_bm25_evaluator(Path(args.local_bm25_report))
    )
    result = run_ablations(evaluator, primary_metric=args.primary_metric, repetitions=args.repetitions)
    result["claim_scope"] = "production_component_ablation"
    result["unavailable_scores_are_not_imputed"] = True
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: row["status"] for name, row in result["results"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
