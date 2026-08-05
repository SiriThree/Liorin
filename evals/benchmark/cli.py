"""CLI for the versioned Liorin Agentic RAG benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import BenchmarkRunConfig, BenchmarkRunner


def parse_layers(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Generate predictions with production adapters and score them.")
    run.add_argument("--dataset", choices=["dev", "validation", "blind"], default="validation")
    run.add_argument("--dataset-path", type=Path)
    run.add_argument("--layers", default="")
    run.add_argument("--limit", type=int)
    run.add_argument("--predictions", type=Path, default=Path("evals/reports/benchmark_predictions.json"))
    run.add_argument("--report", type=Path, default=Path("evals/reports/benchmark_report.json"))
    run.add_argument("--allow-partial", action="store_true")
    run.add_argument("--model")

    smoke = sub.add_parser("smoke", help="Run one local sample per layer.")
    smoke.add_argument("--report", type=Path, default=Path("evals/reports/benchmark_smoke_report.json"))

    score = sub.add_parser("score", help="Score an existing prediction file.")
    score.add_argument("predictions", type=Path)
    score.add_argument("--dataset-path", type=Path, required=True)
    score.add_argument("--layers", default="")
    score.add_argument("--allow-partial", action="store_true")
    score.add_argument("--report", type=Path, default=Path("evals/reports/benchmark_score_report.json"))

    args = parser.parse_args()
    if args.command == "score":
        from .scoring import score_predictions

        report = score_predictions(args.predictions, args.dataset_path, layers=parse_layers(args.layers) or None, allow_partial=args.allow_partial)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        config = BenchmarkRunConfig(
            dataset="validation" if args.command == "smoke" else args.dataset,
            dataset_path=None if args.command == "smoke" else args.dataset_path,
            layers=parse_layers("") if args.command == "smoke" else parse_layers(args.layers),
            limit=None if args.command == "smoke" else args.limit,
            output_path=Path("evals/reports/benchmark_smoke_predictions.json") if args.command == "smoke" else args.predictions,
            report_path=args.report,
            allow_partial=True if args.command == "smoke" else args.allow_partial,
            model=args.model if args.command == "run" else None,
            smoke_per_layer=args.command == "smoke",
        )
        report = BenchmarkRunner(config).run()
    print(json.dumps({"macro_objective_score": report["macro_objective_score"], "sample_count": report["sample_count"], "report": str(args.report)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
