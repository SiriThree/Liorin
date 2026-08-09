# Phase 6 Final Evaluation System

## 1. Phase 6 Summary

Phase 6 is the convergence stage for the Liorin Evaluation System.

Final status:

```text
Evaluation Platform Engineering: COMPLETE
Formal Quality Evaluation: BLOCKED / NOT RUN
Trusted Test: NOT AVAILABLE
Resume-safe Quality Metrics: NONE
```

The platform, contracts, controlled experiment configuration, regression-gate semantics, CI layering, final-report generation and provenance controls are implemented. No formal quality result is manufactured from fixtures, stub Judges, mocks, unit-test pass counts, historical component scores or legacy lexical proxies.

## 2. Final Evaluation Architecture

```text
Canonical Dataset
        │
        ├──── Hidden Gold
        │
        ▼
RuntimeCaseInput
        ↓
Production Agent
        ↓
ONE Production Execution
        ↓
ONE Trace
        ↓
PredictionRecord
        │
        ├── Binary Task Success
        ├── Evidence Reliability
        ├── Claim Grounding
        ├── Agentic Recovery
        ├── Context / Memory / Artifact
        └── Fail-anywhere Safety
                ↓
           CaseJudgment
                ↓
       Failure Attribution
                ↓
      Controlled Experiments
        ├── Recovery
        ├── Context Strategy
        └── Ablation
                ↓
        Regression Gate
                ↓
        Final Evaluation Report
                ↓
        Resume-safe Metrics
```

Hard invariants remain unchanged:

- ONE case/config execution -> ONE Production execution -> ONE trace -> ONE PredictionRecord.
- Gold never enters Production Runtime.
- Task Success is required-criterion conjunction, not a weighted score.
- Correctness != Grounding.
- Observability failure != Retrieval failure.
- Stored stale memory != Memory contamination.
- Cross-user/cross-tenant selected private data is a Safety signal.
- Final refusal cannot erase earlier unauthorized access.
- Primary failure is the causal root, not the final symptom.

## 3. Evaluation Readiness

Actual `eval_platform doctor` result in the Phase-6 environment:

| Readiness item | Status | Actual result |
|---|---|---|
| production_runtime | BLOCKED | `ModuleNotFoundError: No module named 'langchain'` |
| model_provider | PARTIAL | provider/model/credential not fully live-verified |
| judge_provider | BLOCKED | LangChain/provider/Judge model not available |
| retrieval_backend | NOT_READY | Milvus runtime not verifiable in current container |
| structured_data_backend | PARTIAL | local `data/structured/liorin.db` exists; specialist wiring remains partial |
| memory_backend | PARTIAL | runtime exists; external backend not live-verified |
| artifact_backend | PARTIAL | runtime exists; external backend not live-verified |
| canonical_dataset | READY | 39 fully canonical legacy cases |
| validation_split | READY | 5 canonical validation cases |
| trusted_test_split | NOT_READY | no trusted TEST split |
| recovery_subset | NOT_READY | `COVERAGE_INSUFFICIENT_NEEDS_REVIEW` |
| multi_turn_subset | NOT_READY | 0 formal eligible sessions |
| safety_subset | READY | 3 formal Safety candidates |
| ablation_configs | READY | 11 configs |
| baseline_registry | NOT_READY | 0 promoted baselines |

The system status is `PRODUCTION_BLOCKED`.

## 4. Formal Data Status

Actual canonical counts:

```text
Development canonical: 34
Validation canonical:   5
Total canonical:       39
```

Phase-4 multi-turn:

```text
Candidate sessions: 12
Turns:              29
Formal eligible:     0
Needs review:         9
Missing context Gold: 3
```

Phase-5 Safety:

```text
Formal Gold-eligible single-turn Safety candidates: 3
Representative Safety seed NEEDS_REVIEW:              4
Multi-turn unreviewed Safety sessions:                 3
UNIT_TEST security fixtures:                           8
```

Recovery Challenge remains insufficient/review debt. Historical blind inputs are not upgraded to a trusted Test split.

## 5. Full Liorin Configuration

Formal full-system config:

```text
evals/benchmark/configs/full_liorin.json
```

It records:

- model and embedding identity;
- Dense and BM25 retrieval;
- Metadata direct lookup;
- Structured DB capability;
- RRF/fusion;
- Reranker;
- Parent Expansion;
- Evidence Verifier;
- Supplement/Rewrite/Clarification/Agentic Recovery;
- Context strategy;
- Context budget / retrieval round budget;
- Working Memory / Long-term Memory / Artifact through the full context strategy;
- identity / ACL / Memory / Artifact governance;
- Order Agent structured-tool wiring status.

Stable canonical SHA-256:

```text
bd7889bdad8cb1dcd4336237c85c96f87dc7d3b7140dc4d4852c7c7ff78ce433
```

The hash is calculated from normalized JSON state, not Python `dict repr`.

## 6. Production Feature Switches

New `agents/feature_flags.py` defines the feature contract used by controlled Evaluation:

```text
agentic_recovery_enabled
evidence_verifier_enabled
query_rewrite_enabled
supplement_enabled
clarification_recovery_enabled
reranker_enabled
parent_expansion_enabled
```

Defaults are all enabled and preserve current Production behavior.

The same Production graph consumes these switches. No benchmark-specific Agent copies were created.

Examples of real wiring:

- Verifier disabled: `execute_retrieval` routes directly to answer generation; Verifier does not run.
- Reranker disabled: hybrid retrieval skips coarse/final rerank rather than discarding its metric later.
- Parent Expansion disabled: expansion logic is skipped.
- Recovery/rewrite/supplement/clarification disabled: the real recovery routing no longer executes the disabled action.

## 7. Controlled Ablation Infrastructure

Core module:

```text
eval_platform/ablation.py
```

Types:

```text
FullSystemConfig
AblationConfig
AblationFeature
AblationStudyType
AblationFairnessResult
ControlledAblationRunner
```

Two study forms are supported:

- staged Addition Study;
- Full-minus-one-feature Removal Ablation.

Current generated configurations: **11**.

Removal features:

- Agentic Recovery;
- Evidence Verifier;
- Query Rewrite;
- Supplement;
- Clarification Recovery;
- Reranker;
- Parent Expansion.

Addition configurations build controlled stages without changing the Agent implementation.

## 8. Ablation Fairness

`check_ablation_fairness()` compares canonical flattened config state. Only explicitly declared feature differences are allowed.

Unexpected changes such as model, dataset, retrieval settings, context policy or budget make the experiment invalid.

Formal result comparison is paired by identical case IDs. Execution errors are not silently removed.

## 9. Ablation Results

**NOT RUN.**

Reason: real Production Support Graph is blocked in the current environment.

The repository generates a truthful Phase-6 ablation status artifact with 11 configured experiments and zero formal paired results. Fixture delta tests only prove the aggregation logic and are not promoted as real ablation gains.

## 10. Recovery Experiment

The Phase-3 Full-vs-One-pass experiment remains integrated and can be invoked through the unified CLI. Recovery Challenge Gold is still insufficient/review debt, so formal Recovery experiment results are **NOT RUN**.

## 11. Context / Memory Experiment

Phase-4 strategy infrastructure remains the source of truth:

```text
FULL_HISTORY
SLIDING_WINDOW
SUMMARY_ONLY
LIORIN_CONTEXT
LIORIN_CONTEXT_MEMORY_ARTIFACT
```

With zero formal eligible multi-turn sessions, formal Quality-Cost comparison is **NOT RUN**. Historical `-95.2%` token reduction remains a legacy component diagnostic.

## 12. Safety Evaluation

Phase-5 fail-anywhere semantics remain unchanged. Three formal Safety Gold candidates exist, but no real Production execution occurred in Phase 6. Therefore formal Safety Pass Rate, Critical Violation count and Prompt Injection Resistance are **NOT RUN**.

Even if these three cases become runnable, `n=3` is a smoke/exploratory sample, not a stable Safety benchmark.

## 13. Regression Gate Architecture

Core module:

```text
eval_platform/regression.py
```

Gate families:

1. Contract Gate — Dataset Validation, Gold Isolation, Single Execution, Schema Compatibility and Evaluation contract tests must all pass.
2. Zero-tolerance Safety Gate — real cross-user/tenant/private leakage or unauthorized committed side effects cannot be tolerated.
3. Quality Regression Gate — formal metrics compare against an explicitly promoted baseline and an explicitly frozen tolerance.

Supported threshold semantics:

```text
ABSOLUTE_FLOOR
MAX_REGRESSION_PP
ZERO_TOLERANCE
WARNING_ONLY
```

No global weighted score and no magic `0.8` threshold exists in the formal system.

## 14. Current Gate Status

Actual platform-status gate:

```text
Contract Gate: PASS
Zero-tolerance Safety: BLOCKED (no current formal Safety metric)
Task Success quality gate: BLOCKED
Grounded Claim Rate gate: BLOCKED
Recovery Rate gate: BLOCKED
```

A missing current metric is not PASS.

## 15. Baseline Registry

Registry:

```text
artifacts/evaluation/baseline_registry.json
```

Current promoted baseline count: **0**.

A baseline can be promoted only through the explicit `promote-baseline` command and only if:

- run validity is `VALID`;
- dataset is formal eligible;
- required metrics exist;
- critical Safety violations are zero;
- dataset/config/run fingerprint is present.

The latest run is never automatically promoted and a falling score cannot update the baseline to make CI green.

## 16. Run Validity

Phase-6 regression infrastructure freezes:

```text
VALID
PARTIAL
INVALID_CONFIG
INSUFFICIENT_DATA
DEPENDENCY_BLOCKED
JUDGE_INCOMPLETE
OBSERVABILITY_INSUFFICIENT
```

Only `VALID` runs may become baselines.

Formal summaries also expose run validity based on eligible cases and incomplete required evaluation.

## 17. Unified CLI

Unique formal entry point:

```text
python -m eval_platform.cli
```

It now covers:

```text
validate
run
score-existing-predictions
judge
report
experiment context
experiment recovery
ablation
safety
attribute-failures
doctor
gate
promote-baseline
final-report
```

Normal formal `run` consumes the full `production.features` configuration, not only the old recovery boolean.

`evals/benchmark/cli.py` remains deprecated legacy diagnostic compatibility only.

## 18. CI Convergence

### PR Contract Gate

`.github/workflows/eval-regression.yml`

Runs canonical validation plus Evaluation tests without requiring an external LLM. It explicitly states that external quality evaluation is skipped, not passed via a mock.

The old:

```text
evals/run_ci_eval.py --threshold 0.8
```

workflow path has been removed.

### Scheduled Formal Evaluation

`.github/workflows/formal-evaluation.yml`

Requires real external dependencies and uses:

```text
evals/benchmark/configs/phase6_formal_evaluation.example.json
```

with `LIORIN_JUDGE_MODEL`. Readiness failures block formal evaluation; no mock fallback exists.

### Manual Release Evaluation

`.github/workflows/release-evaluation.yml`

Refuses silent skip of required formal dependencies and emits formal artifacts when execution is available.

## 19. Dependency Convergence

Repository search found no current source/test import of `agentevals` or `openevals`. They have been removed from Production main dependencies and moved to:

```toml
[project.optional-dependencies]
legacy-evaluation = [
  "agentevals>=0.0.9",
  "openevals>=0.0.9",
]
```

This prevents a legacy Evaluation package from being conceptually required by Production runtime.

The current `uv.lock` could not be regenerated offline. After removing those packages from main dependencies, offline resolution now fails on missing cached `httpx` and stale lock resolution state. The lock is intentionally not hand-edited/faked; it must be refreshed in a networked environment.

## 20. Legacy Evaluation Convergence

### KEEP

- `eval_platform/` unified formal Core;
- Canonical dataset and Gold Isolation;
- Annotation pipeline/review assets;
- component benchmark implementations when correctly labeled diagnostic;
- historical artifacts needed for audit/migration.

### MIGRATE — completed in Phase 6

- PR CI from fixed legacy macro threshold -> unified contract gate;
- scheduled/release evaluation -> unified CLI;
- README formal evaluation instructions -> `eval_platform.cli`;
- `agentevals/openevals` -> optional legacy evaluation extra;
- formal feature configuration -> stable `FULL_LIORIN` and ablation configs.

### DEPRECATE

- `evals/benchmark/cli.py` as a formal entry point;
- old layer macro objective as a North Star;
- `fact_coverage_proxy` as correctness;
- `evals/run_ci_eval.py` as a formal release gate;
- legacy LangSmith/benchmark scores as formal quality.

### DELETE

**0 files.** Compatibility assets are retained because historical artifacts/docs/imports still need auditability. Deletion is not done just for cleanliness.

## 21. Legacy Metric Semantics

The following are never permitted on the final quality homepage or as Resume-safe quality metrics:

```text
macro_objective_score
legacy_macro_objective_score
fact_coverage_proxy
historical -95.2% context token reduction
old component benchmark success rates
unit-test pass counts
```

They may remain under Diagnostics / Legacy Appendix with explicit semantics.

## 22. Final Evaluation Report

Generated:

```text
docs/evaluation/FINAL_EVALUATION_REPORT.md
artifacts/evaluation/phase6-platform-status/final_evaluation_report.json
artifacts/evaluation/phase6-platform-status/FINAL_EVALUATION_REPORT.md
```

The report intentionally displays `NOT RUN` for missing formal metrics rather than hiding them.

## 23. Resume-safe Metrics

Generated:

```text
docs/evaluation/RESUME_SAFE_METRICS.md
```

Current result:

```text
SAFE_TO_USE QUALITY METRICS:
NONE
```

Engineering test counts and legacy diagnostic values are listed separately and are not allowed to masquerade as Agent quality.

## 24. Reproducibility

### Dataset hashes

```text
Development:
f385879cebe6583f8d4f52224155ed6259e9a83471a522cdb2f9fe8c6aa6b7d4

Validation:
bcbfc46557af73fd3c4956101f1fb25b5ce1fe39659966c8971ad499c6f3c022
```

### Full config hash

```text
bd7889bdad8cb1dcd4336237c85c96f87dc7d3b7140dc4d4852c7c7ff78ce433
```

### Source archive hash

```text
93cd4cd452598bbcfe64aefbb95c22773d4c882cfc9a98b1f8ae025cf53e577c
```

Because the delivered source archive contains no trustworthy `.git`, `git_commit=null` is preserved instead of fabricated.

Run manifest:

```text
artifacts/evaluation/phase6-platform-status/run_manifest.json
```

## 25. Engineering Regression

Actual commands/results:

```text
PYTHONPATH=. pytest -q tests/evaluation
158 passed

PYTHONPATH=. pytest -q tests
370 passed

PYTHONPATH=. python -m compileall -q .
PASS
```

These are engineering regression results only.

## 26. Production / Judge Status

Actual Production import:

```text
ModuleNotFoundError: No module named 'langchain'
```

Actual real Judge import:

```text
ModuleNotFoundError: No module named 'langchain'
```

Therefore:

```text
Production E2E: BLOCKED
Real Judge: BLOCKED
Formal Validation: NOT RUN
Ablation: NOT RUN
Context Strategy: NOT RUN
Recovery Experiment: NOT RUN
Safety Formal Run: NOT RUN
```

## 27. Carry-over Production Gap

The structured business-query Tool gap remains intentionally unmodified:

```text
safe execute_sql_template exists
Order Agent remains wired to fail-closed execute_sql
```

This is a Production hardening/functionality wiring issue, not an Evaluation cleanup task. It remains visible in the final limitations and full-system config.

## 28. Evaluation Debt

Machine-readable debt:

```text
artifacts/evaluation/phase6-platform-status/evaluation_debt.json
```

Outstanding items include:

- restore Production dependencies/runtime;
- restore real Judge and calibrate it;
- create/independently hold a trusted Test split;
- review multi-turn sessions and context Gold;
- complete Recovery Challenge Gold;
- expand formal Safety data;
- harden structured business-query Production Tool wiring;
- regenerate `uv.lock` in a networked environment;
- establish and explicitly promote a real baseline.

## 29. Final Formal Metric Status

| Metric | Status |
|---|---|
| End-to-End Task Success | NOT RUN |
| Required Gold Evidence Recall | NOT RUN |
| Grounded Claim Rate | NOT RUN |
| First-pass Failure Recovery Rate | NOT RUN |
| Safety Pass Rate | NOT RUN |
| Context Avg/P95 Input Tokens | NOT RUN |
| Token Reduction vs Full History | NOT RUN |
| Context Task Success Delta | NOT RUN |
| Memory Contamination Rate | NOT RUN |
| Failure Attribution Coverage | NOT RUN |
| Controlled Ablation Delta | NOT RUN |

## 30. Final Conclusion

Phase 6 completes the **Evaluation Platform engineering convergence**, not the real-model benchmark execution.

The platform now enforces a provenance chain:

```text
Metric
→ Dataset
→ Gold
→ Prediction
→ Trace
→ Judgment
→ Run ID
→ Config
```

Only a real, formally eligible, fully traceable run may become a promoted baseline or a `SAFE_TO_USE` resume metric.

At the current environment boundary, the truthful final answer is:

```text
Evaluation Architecture: COMPLETE
Formal Evaluation: BLOCKED / NOT RUN
Resume-safe Quality Metrics: NONE
```
