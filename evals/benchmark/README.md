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

## Phase 0 evaluation semantics

The v7.3 layered benchmark is now a **legacy diagnostic surface**, not the source
of formal End-to-End Task Success. In particular:

- `macro_objective_score` is a legacy aggregate and must not be reported as E2E Task Success;
- `fact_coverage_proxy` is lexical-only, not Answer Correctness or Groundedness;
- the `end_to_end` adapter uses one production graph execution and one trace;
- `blind_test_inputs_v7_3.json` is retained by historical filename but Phase 0
  classifies it as `HISTORICAL_BLIND_INPUTS_UNVERIFIED` because historical
  unseen/tuning status cannot be proven from the checkout;
- Gold-free datasets are predictions-only locally and are not scored without a
  separate Gold-custodian artifact.

See `docs/evaluation/PHASE0_EVALUATION_AUDIT.md` for the migration contract.

## Phase 2 formal Task Success

Formal binary End-to-End Task Success is now owned by `eval_platform` and the
Canonical Dataset contracts. Use `python -m eval_platform.cli ...` for formal
validation/run/rescoring. The historical `evals.benchmark.cli` remains a
**legacy diagnostic** entry point only: its `macro_objective_score`,
`objective_score`, and `fact_coverage_proxy` must not be reported as formal
Task Success.

Formal scoring preserves `predictions.jsonl` separately from
`judgments.jsonl`; rescoring saved predictions does not invoke the Production
Agent again. See `docs/evaluation/PHASE2_E2E_TASK_SUCCESS.md`.

## Phase 3 evidence/recovery migration

Formal Evidence Reliability and Agentic Recovery metrics no longer come from the legacy layer/objective scorer or `evals/retrieval_evaluation.py`. The canonical definitions live in `eval_platform.evidence`, `eval_platform.recovery`, and `eval_platform.phase3_report` and operate only on Canonical Gold plus a frozen `PredictionRecord` from one Production execution.

Legacy `recall@K`, `evidence_coverage`, retrieval objective scores, and retry diagnostics remain **LEGACY DIAGNOSTIC** for compatibility. They are not aliases for `Required Gold Evidence Recall`, `Selected Evidence Precision`, `Grounded Claim Rate`, or `First-pass Failure Recovery Rate`.

## Phase 5 safety/failure-attribution migration

Formal Safety / Governance evaluation is owned by `eval_platform.safety` and
uses **fail-anywhere** semantics over the frozen Production trace. A final
refusal never erases an earlier unauthorized retrieval, private-data access,
forbidden tool execution, cross-identity Memory/Artifact access, or committed
side effect. Safety criteria remain criterion-level and are never combined into
a weighted `safety_score`.

Unified failure attribution is owned by `eval_platform.failure_attribution`.
It consumes the existing Task judgment plus Evidence/Recovery/Context/Safety
diagnostics and records versioned primary/secondary causal failures. If the
trace cannot establish the cause, the result remains
`OBSERVABILITY_INSUFFICIENT`; the evaluator does not re-run the Agent, Retriever,
Tool, DB, Memory, Artifact resolver, or Governance policy to fill the gap.

Use `python -m eval_platform.cli safety ...` and
`python -m eval_platform.cli attribute-failures ...` on canonical data and
saved predictions. Security fixtures under `evals/benchmark/data/security/`
are test/calibration assets and are **not** formal Production Safety scores.
See `docs/evaluation/PHASE5_SAFETY_FAILURE_ATTRIBUTION.md`.

## Phase 6 final convergence

The formal Evaluation System has converged on `python -m eval_platform.cli`.
Use `eval_platform doctor` before any real run; controlled ablation, regression
gates, explicit baseline promotion, final reports, and resume-safe metric
provenance are all owned by `eval_platform`.

`evals.benchmark.cli` is retained only for historical diagnostics and migration
compatibility. It must never be used as a formal release gate or a source of
resume quality metrics. The current Phase-6 report explicitly separates
Evaluation Platform engineering status from real-model Formal Quality status.

See:

- `docs/evaluation/PHASE6_FINAL_EVALUATION_SYSTEM.md`
- `docs/evaluation/EVALUATION_RUNBOOK.md`
- `docs/evaluation/FINAL_EVALUATION_REPORT.md`
- `docs/evaluation/RESUME_SAFE_METRICS.md`
