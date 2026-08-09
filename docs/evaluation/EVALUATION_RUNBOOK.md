# Liorin Evaluation Runbook

## 1. Purpose

The only formal Evaluation entry point is:

```bash
python -m eval_platform.cli
```

Legacy `evals/benchmark/cli.py` and `evals/run_ci_eval.py` are compatibility / diagnostic entry points only. They must not be used to produce formal Task Success or release decisions.

## 2. Status semantics

- `PASS` / `FAIL`: an evaluation or gate actually ran and reached a result.
- `BLOCKED`: a required dependency, model, Gold asset, baseline, or runtime capability is unavailable.
- `NOT RUN`: no formal execution was performed. This is not PASS.
- `INCOMPLETE`: Production ran but required evaluator/Judge work could not complete.
- `NOT_APPLICABLE`: the metric/gate does not apply to the selected dataset or contract.

Never replace a blocked Production/Judge dependency with a mock and then report formal quality.

## 3. Environment prerequisites

Formal Production evaluation requires the repository's runtime dependencies plus the actual configured services used by the selected cases. At minimum check:

- Python compatible with `pyproject.toml`;
- LangChain / LangGraph runtime dependencies;
- real model provider and credential;
- `LIORIN_MODEL`;
- `LIORIN_JUDGE_MODEL` when semantic Judge criteria are required;
- Milvus/index for document retrieval cases;
- structured data backend for private/mixed cases;
- configured Memory/Artifact backend when the experiment requires them.

The doctor is read-only and never installs dependencies:

```bash
python -m eval_platform.cli doctor --root . --output readiness.json

# Also perform live provider/backend checks once dependencies and credentials exist:
python -m eval_platform.cli doctor --root . --live --output readiness-live.json
```

Do not continue to a formal run if required readiness is `BLOCKED` or `NOT_READY`.

## 4. Dataset validation

Canonical validation:

```bash
python -m eval_platform.cli validate \
  --dataset evals/benchmark/data/canonical/validation_v7_3_canonical_v1.json \
  --split VALIDATION
```

Validation is fail-closed. Invalid cases are not silently skipped.

Current split trust remains:

- Development: usable for development/debugging.
- Validation: canonical validation data.
- Trusted Test: **not present**.
- Historical blind inputs: historical/unverified, not a trusted test set.

## 5. One-case smoke

After `doctor` is READY, run one formal case before any large run:

```bash
python -m eval_platform.cli run \
  --dataset evals/benchmark/data/canonical/validation_v7_3_canonical_v1.json \
  --split VALIDATION \
  --limit 1 \
  --config evals/benchmark/configs/phase6_formal_evaluation.example.json \
  --output artifacts/evaluation/smoke
```

Verify that one selected case creates one Production execution, one trace and one PredictionRecord.

## 6. Development and validation

Small development first:

```bash
python -m eval_platform.cli run \
  --dataset evals/benchmark/data/canonical/dev_v7_3_canonical_v1.json \
  --split DEVELOPMENT \
  --limit 5 \
  --config evals/benchmark/configs/phase6_formal_evaluation.example.json \
  --output artifacts/evaluation/dev-smoke
```

Formal validation only after the smoke is stable:

```bash
python -m eval_platform.cli run \
  --dataset evals/benchmark/data/canonical/validation_v7_3_canonical_v1.json \
  --split VALIDATION \
  --config evals/benchmark/configs/phase6_formal_evaluation.example.json \
  --output artifacts/evaluation/formal-validation
```

Because no trusted TEST split exists, never label this result “test accuracy” or “blind test”.

## 7. Judge

Semantic criteria use the existing versioned JudgeRuntime. The Phase-6 example config obtains the model from `LIORIN_JUDGE_MODEL`.

Judge failures do not become PASS. A required criterion Judge failure yields `INCOMPLETE`/evaluation infrastructure error according to the Phase-2 contract.

To rescore frozen predictions with an updated Judge/evaluator:

```bash
python -m eval_platform.cli score-existing-predictions \
  --dataset evals/benchmark/data/canonical/validation_v7_3_canonical_v1.json \
  --predictions artifacts/evaluation/formal-validation/predictions.jsonl \
  --config evals/benchmark/configs/phase6_formal_evaluation.example.json \
  --output artifacts/evaluation/formal-validation-rescore
```

This must not invoke Production again.

## 8. Recovery experiment

Recovery experiment reuses the same Production graph and disables Agentic Recovery through a controlled feature configuration:

```bash
python -m eval_platform.cli experiment recovery \
  --dataset <canonical-dataset> \
  --config evals/benchmark/configs/phase6_formal_evaluation.example.json \
  --output artifacts/evaluation/recovery-experiment
```

Only run formal recovery metrics when the Recovery Challenge subset is eligible. Current repository readiness says it is not yet ready.

## 9. Context strategy experiment

```bash
python -m eval_platform.cli experiment context \
  --dataset evals/benchmark/data/canonical/phase4_multi_turn_candidates_v1.json \
  --strategies FULL_HISTORY,SLIDING_WINDOW,SUMMARY_ONLY,LIORIN_CONTEXT,LIORIN_CONTEXT_MEMORY_ARTIFACT \
  --output artifacts/evaluation/context-experiment
```

Formal Quality-Cost comparison requires reviewed/eligible multi-turn sessions and paired session IDs. Current candidates are not formal benchmark data.

## 10. Safety

Score saved predictions against Safety Gold and the frozen fail-anywhere trace:

```bash
python -m eval_platform.cli safety \
  --dataset <canonical-safety-dataset> \
  --predictions <predictions.jsonl> \
  --category SAFETY_GOVERNANCE \
  --output artifacts/evaluation/safety
```

A final refusal does not erase an earlier unauthorized read, tool execution, side effect, Memory access or Artifact access.

## 11. Failure attribution

```bash
python -m eval_platform.cli attribute-failures \
  --dataset <canonical-dataset> \
  --predictions <predictions.jsonl> \
  --output artifacts/evaluation/failure-analysis
```

Attribution consumes frozen Prediction/Trace + Gold + prior diagnostics. It does not re-query DB, Retriever, Tool or Agent.

## 12. Controlled ablation

The full Production feature configuration is:

```text
evals/benchmark/configs/full_liorin.json
```

Ablation definitions are under:

```text
evals/benchmark/configs/ablation/
```

Example:

```bash
python -m eval_platform.cli ablation \
  --dataset evals/benchmark/data/canonical/validation_v7_3_canonical_v1.json \
  --split VALIDATION \
  --ablation-config evals/benchmark/configs/ablation/full_minus_evidence_verifier.json \
  --config evals/benchmark/configs/phase6_formal_evaluation.example.json \
  --output artifacts/evaluation/ablation-no-verifier
```

Ablations must use the same case IDs and may differ only in declared feature switches. An unexpected model, prompt, top-k, dataset or budget change invalidates the comparison.

## 13. Final report

Generate the current system/readiness report:

```bash
python -m eval_platform.cli final-report \
  --root . \
  --output artifacts/evaluation/final
```

A blocked metric remains visible as `NOT RUN` rather than disappearing from the report.

## 14. Regression gate

The registry is explicit and does not auto-drift:

```text
artifacts/evaluation/baseline_registry.json
```

Evaluate a real current run descriptor:

```bash
python -m eval_platform.cli gate \
  --current <real-current-run.json> \
  --registry artifacts/evaluation/baseline_registry.json \
  --baseline-name formal_validation \
  --output artifacts/evaluation/gate
```

Contract gates can run without an LLM. Zero-tolerance Safety requires an actual Safety metric. Quality regression requires a promoted real baseline plus an explicitly frozen tolerance; missing baselines/tolerances are `BLOCKED`, not PASS.

## 15. Promote a baseline

Promotion is always explicit:

```bash
python -m eval_platform.cli promote-baseline \
  --run <valid-real-run-descriptor.json> \
  --registry artifacts/evaluation/baseline_registry.json \
  --baseline-name formal_validation
```

Promotion rejects:

- non-`VALID` runs;
- non-formal datasets;
- missing required metrics;
- any critical Safety violation;
- missing dataset/config/run fingerprint.

Never automatically promote the latest CI result.

## 16. CI layers

- PR CI: contract/schema/Gold Isolation/single-execution/evaluator/zero-tolerance fixture regression; no expensive external LLM requirement.
- Scheduled Formal Evaluation: real validation execution with external dependencies; blocked if credentials/runtime are not ready.
- Manual Release Evaluation: must not silently skip required formal evaluation.

Workflows:

```text
.github/workflows/eval-regression.yml
.github/workflows/formal-evaluation.yml
.github/workflows/release-evaluation.yml
```

## 17. Interpreting legacy evaluation

`evals/benchmark/` remains for legacy diagnostics, migration compatibility and retained component assets. `legacy_macro_objective_score`, lexical `fact_coverage_proxy`, historical component token reduction, and legacy component benchmark values are not formal End-to-End quality metrics.

Resume quality metrics must come only from:

```text
docs/evaluation/RESUME_SAFE_METRICS.md
```


## 16. Production Hardening prerequisite

Before the first formal run, follow `docs/production/PHASE7_PRODUCTION_HARDENING.md`. In particular, the Support Graph import, real model, required retrieval backend and real Judge must be available. The safe structured business tool is template-based and principal-bound; do not re-enable the legacy arbitrary-SQL entry point.
