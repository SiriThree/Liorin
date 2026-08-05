# Liorin Agentic RAG Benchmark Integration

This directory contains the public v7.3 benchmark assets and production adapters.

Quick smoke:

```bash
uv run python -m evals.benchmark.cli smoke
```

Validation run:

```bash
uv run python -m evals.benchmark.cli run --dataset validation --report evals/reports/benchmark_validation_report.json
```

Generate predictions for blind inputs without gold:

```bash
uv run python -m evals.benchmark.cli run --dataset blind --predictions evals/reports/blind_predictions.json --allow-partial
```

`fact_coverage_proxy` is a deterministic lexical grounding proxy. It must not be reported as answer correctness without a locked judge or human review protocol.
