# Liorin Final Evaluation Report

## Executive Summary

**Evaluation Platform Engineering: COMPLETE**  
**Formal Quality Evaluation: BLOCKED / NOT RUN**  
**Trusted Test Split: NO**  
**Resume-safe Quality Metrics: NONE**

The Phase 0–6 Evaluation Platform is implemented and regression-tested. Production Hardening Phase 7 additionally completed the safe Structured Business Tool wiring (principal-bound allow-listed templates, tenant/customer ownership checks, hidden runtime identity propagation and stable hashed structured-evidence refs). However, the current execution environment still cannot import the real Production Support Graph or the real Judge because the runtime dependency/lock layer is blocked. Formal quality values are therefore not manufactured from fixtures, stubs, legacy metrics, unit tests or component benchmarks.

## Evaluation Status

| Item | Status | Current fact |
|---|---|---|
| Production Runtime | BLOCKED | current Python lacks LangChain/LangGraph/Milvus runtime; Support Graph import stops at `langchain` |
| Model Provider | PARTIAL | provider/model/credential not live-verified in this environment |
| Judge Provider | BLOCKED | LangChain + real Judge model/provider unavailable |
| Canonical Dataset | READY | 39 fully canonical legacy cases |
| Validation | READY | 5 canonical validation cases |
| Trusted Test | NOT READY | no trusted test split |
| Recovery subset | NOT READY | `COVERAGE_INSUFFICIENT_NEEDS_REVIEW` |
| Multi-turn subset | NOT READY | 0 formal eligible sessions |
| Safety subset | READY for smoke | 3 Gold-eligible single-turn candidates |
| Ablation configs | READY | 11 controlled configs |
| Promoted baseline | NOT READY | baseline registry empty |

## Dataset Scope

- Development canonical: **34 cases**.
- Validation canonical: **5 cases**.
- Total fully canonical legacy: **39 cases**.
- Safety formal candidate: **3 cases**.
- Phase-4 multi-turn candidates: **12 sessions / 29 turns**.
- Formal eligible multi-turn sessions: **0**.
- Recovery Challenge: **not formally ready**.
- Trusted TEST: **NO**.

## Core Formal Metrics

| Metric | Result |
|---|---|
| End-to-End Task Success | **NOT RUN** |
| Required Gold Evidence Recall | **NOT RUN** |
| Grounded Claim Rate | **NOT RUN** |
| First-pass Failure Recovery Rate | **NOT RUN** |
| Safety Pass Rate | **NOT RUN** |
| Full History vs Liorin Avg Input Token Reduction | **NOT RUN** |
| Full History vs Liorin Task Success Delta | **NOT RUN** |

No value in this table is replaced by a fixture result.

## End-to-End Task Success

Formal Task Success remains the single North Star and keeps the Phase-2 definition: all required case criteria must pass; Production execution errors are user-visible task failures; evaluation-infrastructure failures are incomplete and reported separately. No formal Production run occurred in the current environment, so numerator and denominator do not exist yet.

## Evidence Reliability / Grounding

Phase-3 Evidence Recall, Required Gold Evidence Recall, Selected Evidence Precision and claim-level Grounded Claim Rate remain implemented and rescorable from frozen predictions. They were not run against real Production predictions in Phase 6.

## Agentic Recovery

The Full-vs-One-pass infrastructure and recovery metrics remain available, but the reviewed Recovery Challenge subset is still insufficient. Therefore First-pass Failure Recovery Rate and recovery gain are **NOT RUN**.

## Context / Memory Quality-Cost

Five context strategies are wired to the same Production ContextRuntime. The 12 candidate multi-turn sessions remain unreviewed/incomplete for formal Gold, leaving **0 formal eligible sessions**. Historical `-95.2%` component token reduction is not reused here. Formal paired Token Reduction, Task Success Delta, Groundedness Delta and Memory Contamination Rate are **NOT RUN**.

## Safety / Governance

Fail-anywhere Safety, resource-identity tracing, Memory/Artifact safety linkage, Prompt Injection contracts and zero-tolerance signals are implemented. Three formal single-turn Safety Gold candidates exist, but real Production execution is blocked. Formal Safety Pass Rate, Prompt Injection Resistance and Critical Violation counts are **NOT RUN**.

## Failure Attribution

Phase-5 causal Primary/Secondary Failure attribution is implemented and can rescore frozen predictions. With no Phase-6 real Production run, formal Failure Attribution Coverage and production failure distribution are **NOT RUN**.

## Controlled Ablation

`FULL_LIORIN` and 11 addition/removal configurations are implemented with stable fingerprints and fairness checking. Ablated features are disabled in the real Production graph wiring rather than ignored by the evaluator. No real paired ablation was executed because Production is blocked, so all ablation deltas are **NOT RUN**.

## Regression Gate

Current platform-status gate:

- Contract Gate: **PASS** based on actual repository regression tests and preserved contracts.
- Zero-tolerance Safety Gate: **BLOCKED**, because there is no current formal Safety run.
- Task Success regression: **BLOCKED**, no promoted real baseline/current metric.
- Grounded Claim Rate regression: **BLOCKED**.
- Recovery Rate regression: **BLOCKED**.

There is no invented `0.8` or `0.85` formal threshold.

## Engineering Regression

These are engineering validation results, not Agent quality metrics:

- Full `tests/`: **377 passed / 2 integration skips**.
- `tests/evaluation`: **163 passed / 2 integration skips**.
- `compileall`: **PASS**.

## Reproducibility

- Full system config: `evals/benchmark/configs/full_liorin.json`.
- Full system config hash: `bd7889bdad8cb1dcd4336237c85c96f87dc7d3b7140dc4d4852c7c7ff78ce433`.
- Validation dataset hash: `bcbfc46557af73fd3c4956101f1fb25b5ce1fe39659966c8971ad499c6f3c022`.
- Development dataset hash: `f385879cebe6583f8d4f52224155ed6259e9a83471a522cdb2f9fe8c6aa6b7d4`.
- Source Phase-6 archive hash for Phase 7: `e2f4c74b5087eac10016d8d84248b1c1dbe09f0f9996f348f50dc1bb5aa8566a`.
- Git commit: `null` because the supplied archive has no trustworthy `.git` history.

## Limitations / Evaluation Debt

1. Current environment lacks `langchain`, blocking Production and Judge execution.
2. Offline `uv` lock refresh is blocked by cache availability; the stale lock must be regenerated in a networked environment.
3. No trusted TEST split.
4. Recovery Challenge Gold remains insufficient/review debt.
5. 12 multi-turn candidates are not formal eligible; 0 formal sessions currently enter Context Quality-Cost metrics.
6. Safety formal sample is only 3 cases and would be exploratory even if run.
7. Safe `execute_sql_template` is now wired into Order Agent with trusted identity/capability propagation and owner checks; **code-level wiring is hardened**, but the real Support Graph structured smoke is still BLOCKED by runtime dependencies.
8. No real formal run has been promoted as a regression baseline.

## Resume-safe Metrics

**NONE.** See `RESUME_SAFE_METRICS.md` for provenance rules and explicitly excluded legacy/engineering numbers.
