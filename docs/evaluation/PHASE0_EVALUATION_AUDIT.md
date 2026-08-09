# Phase 0 Evaluation Audit

## 1. Executive Summary

Phase 0 status: **PARTIAL**.

The repository audit confirmed that Liorin had several useful but disconnected evaluation systems and that the historical `end_to_end` benchmark adapter violated the required single-execution contract. Before this phase, one E2E case could execute the Support Graph for the final answer and then execute the Knowledge Agent again to obtain evidence, verifier, and retrieval diagnostics. The resulting prediction could therefore combine facts from two different executions.

Phase 0 removes that defect for the formal legacy `end_to_end` path and freezes the future architecture around the existing `eval_platform` package:

```text
EvaluationSample
    │ owns input + hidden Gold
    ▼
RuntimeCaseInput
    │ explicit Gold-free whitelist
    ▼
ProductionEvaluationAdapter
    ▼
deployments.support_agent_graph.graph
    ▼
ONE production execution
    ▼
ONE AgentExecutionTrace
    ▼
TraceAdapter
    ▼
PredictionRecord
    ▼
Phase 1+ evaluators compare PredictionRecord + Gold
    ▼
CaseJudgment
```

Formal End-to-End Task Success is **not implemented in Phase 0**. No new benchmark score is claimed. The future primary metric remains binary case-dependent End-to-End Task Success.

The local environment cannot execute the real LLM/Milvus production benchmark because the supplied checkout does not include installed LangChain dependencies and offline dependency resolution cannot obtain `agentevals`. Therefore production quality results are **BLOCKED / NOT RUN**, not replaced with mock scores.

---

## 2. Current Evaluation Architecture

### 2.1 Evaluation systems found in the real checkout

The checkout contains all of the following active or historical evaluation surfaces:

```text
evals/benchmark/
eval_platform/
evaluators/
evals/agentic_rag_eval.py
evals/agentic_rag_metrics.py
evals/retrieval_evaluation.py
evals/run_ablations.py
evals/context_compaction_benchmark.py
evals/working_memory_benchmark.py
evals/long_term_memory_benchmark.py
evals/artifact_context_benchmark.py
evals/memory_governance_benchmark.py
evals/production_benchmark.py
evals/annotation_pipeline/
evals/tracemind/
evals/run_ci_eval.py
```

No fourth parallel evaluation framework was created. The existing `eval_platform` abstraction is retained and promoted as the migration target because it already owns `Dataset -> Runtime -> Trace -> Evaluator -> Report` responsibilities.

### 2.2 Historical benchmark architecture

`evals/benchmark/runner.py` dispatches by layer:

```text
query_understanding
routing
retrieval
agent_behavior
answer_generation
end_to_end
```

`evals/benchmark/scoring/scorer.py` computes per-layer `objective_score` values and aggregates them into `macro_objective_score`.

These scores are now explicitly classified as **legacy diagnostics**. They are not End-to-End Task Success.

### 2.3 Existing eval_platform architecture

Before Phase 0, `eval_platform` already supplied:

```text
EvaluationScenario
EvaluationDataset
EvaluationRunner
EvaluationReport
Context / Memory / Artifact / Agent evaluators
```

However:

- `EvaluationScenario` did not type-separate runtime-visible input from Gold;
- `agent_evaluator()` trusted `output["task_success"]` and compared it to expected success;
- `EvaluationReport.success_rate` meant runtime/evaluator execution completion, not task success;
- production E2E did not use `eval_platform` as the single execution boundary.

Phase 0 keeps this package and adds the missing production contracts instead of creating a new root-level framework.

---

## 3. Evaluation Asset Inventory

| Capability | Actual path | Current purpose | Runtime / trace source | Gold access | Phase 0 decision | Reason |
|---|---|---|---|---|---|---|
| Layered benchmark runner | `evals/benchmark/runner.py` | Dispatch six historical benchmark layers | Mixed component + production adapters | Scorer later reads Gold | **MIGRATE** | Useful runner mechanics, but old layers/objective score are not the future primary architecture |
| Benchmark CLI | `evals/benchmark/cli.py` | Run/smoke/score historical benchmark | Delegates to runner | Indirect | **MIGRATE** | Preserve compatibility, later align flags with canonical runner |
| Production E2E adapter | `evals/benchmark/adapters/end_to_end.py` | E2E and answer-generation prediction | E2E now uses `ProductionEvaluationAdapter`; answer-generation remains Knowledge Agent diagnostic | Runtime path does not read Gold | **MIGRATE** | E2E single-execution defect fixed; legacy prediction schema still needs Phase 1 migration |
| Understanding adapter | `evals/benchmark/adapters/understanding.py` | Component query understanding | Direct Knowledge Agent function | No direct Gold access | **MIGRATE** | Diagnostic layer only |
| Routing adapter | `evals/benchmark/adapters/routing.py` | Component retrieval planning | Direct planner functions | No direct Gold access | **MIGRATE** | Diagnostic layer only |
| Retrieval adapter | `evals/benchmark/adapters/retrieval.py` | Component retrieval | Direct retrieval pipeline | No direct Gold access | **MIGRATE** | Valuable diagnostic, not E2E |
| Behavior adapter | `evals/benchmark/adapters/behavior.py` | Knowledge Agent behavior | Knowledge Agent graph | No direct Gold access | **MIGRATE** | Diagnostic attribution, not primary success |
| Legacy scorer | `evals/benchmark/scoring/scorer.py` | Layer metrics + weighted objective | Prediction + Gold | Yes, evaluator side | **DEPRECATE AS PRIMARY / KEEP DIAGNOSTIC** | `macro_objective_score` is not binary task success |
| Corpus mapping | `evals/benchmark/corpus_registry.py` | Exact production/benchmark chunk mapping | Frozen corpus manifest | No | **KEEP** | Useful evidence-ID bridge |
| v7.3 dev dataset | `evals/benchmark/data/dev_v7_3.json` | Development benchmark | N/A | Contains Gold | **MIGRATE** | Useful migration source for canonical data |
| v7.3 validation dataset | `evals/benchmark/data/validation_v7_3.json` | Validation benchmark | N/A | Contains Gold | **MIGRATE** | Useful migration source; not blind |
| historical blind inputs | `evals/benchmark/data/blind_test_inputs_v7_3.json` | Gold-free prediction inputs | N/A | No local Gold | **DEPRECATE TRUST CLAIM / KEEP FILE** | Historical unseen status cannot be proven from checkout |
| Public corpus/fact registry | `evals/benchmark/corpus/*.json` | Frozen source/gold construction assets | N/A | Evaluation-side | **KEEP** | Needed for evidence evaluation and dataset migration |
| Benchmark JSON schemas | `evals/benchmark/schemas/*.json` | v7.3 sample/prediction validation | N/A | Schema includes evaluation fields | **MIGRATE** | Phase 1 canonical schema replaces/extends them |
| eval platform core | `eval_platform/` | Dataset/runtime/trace/evaluator/report abstraction | Unified `TraceRecorder` | Legacy evaluators see expected | **KEEP + BECOME CORE** | Best existing home for canonical evaluation contracts |
| Gold isolation | `evals/gold_isolation.py` | Runtime leakage checks + run fingerprint helpers | Runtime packet validation | Detects Gold | **KEEP** | Strengthened in Phase 0 |
| LangSmith correctness evaluator | `evaluators/evaluators.py` | LLM-as-Judge + tool count | LangSmith/model | Reference output | **MIGRATE** | Needs versioned prompt/model config/raw judgment/retry contract before formal use |
| Memory governance evaluator | `evaluators/memory_governance.py` | Deterministic memory precision/recall/stale/forgetting | Component outputs | Expected fact IDs | **KEEP AS COMPONENT DIAGNOSTIC** | Clear deterministic semantics |
| Retrieval evaluation scorer | `evals/retrieval_evaluation.py` | Recall/MRR/NDCG/source/evidence diagnostics | Prediction + Gold | Yes | **KEEP AS COMPONENT DIAGNOSTIC** | Useful evidence/retrieval metrics |
| Agentic RAG smoke checks | `evals/agentic_rag_eval.py` | Local protocol/regression assertions | Component functions | Fixture expectations | **MIGRATE TO DIAGNOSTICS** | Not E2E quality |
| Heuristic Agentic RAG metrics | `evals/agentic_rag_metrics.py` | Synthetic/heuristic metrics and ablation fixtures | Local deterministic functions | Embedded fixture expectations | **DEPRECATE AS FORMAL QUALITY** | Useful regression fixture, not canonical production quality |
| Context compaction benchmark | `evals/context_compaction_benchmark.py` | Token/state compaction diagnostic | Context Runtime | Synthetic expectations | **KEEP AS COMPONENT DIAGNOSTIC** | Does not represent E2E answer quality |
| Working memory benchmark | `evals/working_memory_benchmark.py` | Working Memory behavior/cost | Memory runtime | Synthetic expectations | **KEEP AS COMPONENT DIAGNOSTIC** | Component quality only |
| Long-term memory benchmark | `evals/long_term_memory_benchmark.py` | Memory retrieval/persistence diagnostic | Memory runtime | Synthetic expectations | **KEEP AS COMPONENT DIAGNOSTIC** | Component quality only |
| Artifact benchmark | `evals/artifact_context_benchmark.py` | Artifact reference/context savings | Artifact runtime | Synthetic expectations | **KEEP AS COMPONENT DIAGNOSTIC** | Component quality/cost only |
| Memory governance benchmark | `evals/memory_governance_benchmark.py` | Governance memory behavior | Governance/memory runtime | Synthetic expected state | **KEEP AS COMPONENT DIAGNOSTIC** | Governance diagnostic only |
| Production benchmark | `evals/production_benchmark.py` | Deterministic infra/runtime load/failure benchmark | Context/Memory/Artifact/storage | No E2E Gold | **KEEP AS COMPONENT DIAGNOSTIC** | Explicitly not Agent answer quality |
| Ablation runner | `evals/run_ablations.py`, `evals/ablation.py` | Component configuration comparison | Caller-provided evaluator | Depends on evaluator | **MIGRATE** | Phase 6+ should use canonical splits/run metadata |
| Annotation pipeline | `evals/annotation_pipeline/`, `evals/scripts/` | Multi-agent annotation/reviewed Gold export | Annotation model backends | Yes, data-authoring side | **KEEP / MIGRATE OUTPUT** | Valuable curation pipeline; canonical schema target changes in Phase 1 |
| Historical TraceMind CSVs | `evals/tracemind/` | Previous benchmark artifacts | Historical | Mixed | **DEPRECATE / MIGRATION INPUT ONLY** | Not current canonical benchmark |
| CI evaluation gate | `evals/run_ci_eval.py` | Historical offline smoke gate | Benchmark smoke + local protocol smoke | Indirect | **MIGRATE** | Cannot be future release gate until E2E binary contract exists |
| Existing reports | `evals/benchmark/reports/`, `evals/*report*.json` | Historical outputs | Historical | N/A | **KEEP AS LEGACY ARTIFACT** | Must not be presented as new Phase 0 metrics |

**DELETE decisions in Phase 0: none.** No asset met the required “new system fully covers it + imports migrated + tests passing + no historical artifact dependency” bar.

---

## 4. Production Agent Execution Chain

### 4.1 Deployment entry

Actual production graph construction starts in:

```text
deployments/support_agent_graph.py
```

The module first calls:

```text
production.bootstrap.bootstrap_production_runtime()
```

That bootstrap wires the default Memory/Artifact backends, optional Redis/local cache, retry/circuit-breaker wrappers, context cache and metrics exporter. It then constructs:

```text
order_agent = create_order_agent(...)
knowledge_agent = create_knowledge_agent(...)
graph = create_support_agent(order_agent=..., knowledge_agent=...)
```

### 4.2 Real support graph

`agents/support_workflow.py` builds:

```text
START
  ↓
query_router
  ├─ identity required → verify_customer → collect_email / supervisor_agent
  └─ general request   → supervisor_agent
```

`query_router` also resolves runtime identity and synchronizes Working Memory / Long-term Memory lifecycle state through `_with_working_memory()`.

### 4.3 Supervisor

`agents/conversation_supervisor.py` creates the customer-facing ReAct-style supervisor. It:

- builds bounded model context through `ContextRuntime`;
- can call `order_agent` and `knowledge_agent` as tools;
- wraps specialist calls with timeout/retry/tool observability;
- returns the final customer-facing answer.

### 4.4 Knowledge Agent

`agents/knowledge_agent.py` builds the actual Agentic RAG state graph:

```text
understand_query
  ↓ / clarification
plan_retrieval
  ↓
execute_retrieval
  ↓
verify_evidence
  ├─ ACCEPT        → generate_answer
  ├─ SUPPLEMENT    → targeted_retrieve → execute_retrieval
  ├─ REWRITE       → rewrite_query → execute_retrieval
  ├─ DECOMPOSE     → replan → execute_retrieval
  ├─ RELAX_FILTERS → targeted_retrieve → execute_retrieval
  ├─ CLARIFY       → clarification
  └─ HANDOFF       → handoff

generate_answer
  ↓
verify_answer
  ├─ ACCEPT      → finalize_answer
  ├─ REWRITE     → generate_answer
  ├─ SUPPLEMENT  → targeted_retrieve
  └─ HANDOFF     → handoff
```

Retrieval uses production ACL/filtering and evidence verification from `retrieval/` rather than benchmark-specific logic.

### 4.5 Order Agent

`agents/order_agent.py` is a structured-data specialist using the real SQLite database tool and a read-only SQL prompt boundary. It is called through the supervisor tool boundary.

### 4.6 Context / Memory / Artifact / Governance / Trace wiring status

| Capability | Status | Actual wiring |
|---|---|---|
| Context Runtime | **WIRED** | Supervisor dynamic prompt and bounded model messages |
| Working Memory | **WIRED** | `support_workflow._with_working_memory()` |
| Long-term Memory | **WIRED** | `_LONG_TERM_MEMORY_RUNTIME.promote_from_state()` + Context Runtime retrieval |
| Artifact Registry | **WIRED at infrastructure/runtime level** | Production bootstrap installs default registry; artifact events use unified recorder when called |
| Retrieval ACL | **WIRED** | `RetrievalPrincipal`, filter validation, `document_matches_filters`, DB ownership checks |
| Evidence Verifier | **WIRED** | `verify_evidence()` in Knowledge Agent graph |
| Recovery loop | **WIRED** | supplement/rewrite/decompose/relax/clarify/handoff graph branches |
| Unified execution trace | **PARTIAL before Phase 0; improved in Phase 0** | Supervisor/tool/context/memory/artifact recorder existed; retrieval trace used a separate sink and worker-thread context was not propagated |
| Full model-call accounting | **PARTIAL** | Supervisor model calls emit unified `MODEL_CALL`; query classification / all specialist model calls are not yet guaranteed to emit the same event contract |
| Full nested SQL tool accounting | **PARTIAL** | Supervisor `order_agent` invocation is observed; nested SQL tool calls are not yet normalized into the Phase-0 TraceAdapter contract |

---

## 5. Multi-Execution / E2E Consistency Audit

### 5.1 Defect confirmed

The original `evals/benchmark/adapters/end_to_end.py` did the following for an `end_to_end` sample:

```text
Execution A
create_support_agent(...).invoke(...)
→ support_graph_answer

Execution B
create_knowledge_agent(...).invoke(state)
(or manual understand/plan/retrieve/grade/generate/verify/finalize fallback)
→ evidences / verification action / retry_count / trace_events

Prediction
answer from A when available
+ diagnostics/decision/evidence from B
```

This is the exact defect:

```text
P0 ARCHITECTURAL DEFECT:
MULTI_EXECUTION_PREDICTION_ASSEMBLY
```

Consequences:

- final answer and cited evidence could come from different executions;
- retrieval rounds could describe a request that did not produce the final answer;
- verifier/recovery actions could be unrelated to the Support Graph answer;
- a Support Graph failure could be hidden by the second Knowledge Agent execution;
- latency described the second chain rather than the complete production request.

### 5.2 Fix

`end_to_end` now delegates to:

```text
eval_platform.production_adapter.ProductionEvaluationAdapter
```

That adapter lazily loads:

```text
deployments.support_agent_graph.graph
```

and invokes it exactly once.

If the production execution fails, the adapter returns a `PredictionRecord` with:

```text
execution_status = FAILED
execution_error = <real error>
final_response = ""
```

It does **not** run a Knowledge Agent/retrieval/verifier fallback.

`answer_generation` is intentionally left as a direct Knowledge Agent component diagnostic and is labeled as such.

### 5.3 Trace consistency instrumentation

A second production observability issue was found while fixing single execution: specialist tools use `execute_with_timeout()`, which runs the specialist in a `ThreadPoolExecutor`. Python `ContextVar` values do not automatically propagate to that worker. Therefore retrieval events generated inside the Knowledge Agent could not reliably attach to the parent Support Graph trace.

Phase 0 adds trace-only propagation:

```text
TraceRecorder.bind(existing_trace)
```

`invoke_observed_tool()` binds only the existing trace inside the timeout worker. It does not alter Agent state, prompt, runtime config, retrieval parameters, retry policy, or Gold visibility.

`retrieval.trace.trace_event()` now mirrors its already-sanitized event into the current unified trace as `RETRIEVAL_EVENT`. The original retrieval `TRACE_SINK` remains intact for compatibility.

Workflow identity/routing decisions are also emitted as read-only `WORKFLOW_DECISION` / `AUTHORIZATION_DECISION` events.

---

## 6. Gold Leakage Audit

### 6.1 Historical flow

The historical benchmark runner loads full rows containing:

```text
input
gold
metadata
```

and passes the full sample object to component adapters. Current adapter implementations mostly read only `sample["input"]`, but the type boundary did not prevent future code from reading Gold and passing it into the runtime.

The scorer correctly reads Gold only after predictions have been generated.

### 6.2 New boundary

Phase 0 freezes:

```text
EvaluationSample
├── runtime_input: RuntimeCaseInput
└── gold: hidden evaluation requirements
```

Only this transition is valid:

```text
EvaluationSample.to_runtime_input()
    ↓
RuntimeCaseInput
    ↓
ProductionEvaluationAdapter.run()
```

`ProductionEvaluationAdapter` refuses `EvaluationSample` or arbitrary Gold-bearing mappings. It accepts `RuntimeCaseInput` only.

### 6.3 Runtime packet whitelist

`RuntimeCaseInput` explicitly owns only:

```text
case_id
messages
identity
config
context
metadata
```

Before construction and before graph invocation, the packet is checked by `assert_no_gold_leak()`.

Phase 0 expanded forbidden runtime names to cover historical and future leakage patterns, including:

```text
gold
reviewed_gold*
qrels
expected_answer
expected_source(s)
expected_agent
expected_tool(s)
expected_route
expected_action
expected_response_type
required_atomic_facts
required_keywords
gold_evidence
gold_fact(s)
forbidden_sources
outdated_sources
```

### 6.4 Static audit result

Current runtime-facing benchmark adapters contain no direct Gold field reads. Gold references are found in evaluator/scoring code, which is the correct side of the boundary.

### 6.5 Remaining risk

Legacy `EvaluationScenario.inputs` remains an unrestricted mapping for component/backwards-compatible evaluation. It must not become the Phase 1 production E2E input contract. Formal E2E must use `RuntimeCaseInput`.

---

## 7. Dataset Split / Blind Contamination Audit

### 7.1 Actual files and counts

| Split/file | Cases | Local Gold | Layer distribution |
|---|---:|---|---|
| `dev_v7_3.json` | 368 | 368/368 | retrieval 129, answer_generation 62, understanding 58, E2E 51, routing 41, behavior 27 |
| `validation_v7_3.json` | 119 | 119/119 | retrieval 55, E2E 19, understanding 17, routing 15, behavior 9, answer_generation 4 |
| `blind_test_inputs_v7_3.json` | 125 | 0/125 | retrieval 47, understanding 25, E2E 19, routing 16, behavior 14, answer_generation 4 |

SHA-256 at audit time:

```text
dev        5f7251b90b60f556a84fc643809800d6a358901e7bcb77a09a28ffe1e89d2439
validation c980ada94f11b94a01f174bed8612cda4ca44db0c79bc779e73528d7e3e24973
blind      ec2b7770f3e0fdaf1a773add0dabc45eecc656c55ea73637d204c0490079b67f
```

### 7.2 Mechanical cross-split checks

For the supplied files:

```text
ID overlap:             0 across all split pairs
exact question overlap: 0 across all split pairs
surface_template overlap: 0 across all split pairs
```

This supports mechanical separation, but it does not prove historical blindness.

### 7.3 Blind trust conclusion

The repository contains `BLIND_TEST_PROTOCOL.md`, and the public blind input file correctly contains no Gold. However, the supplied ZIP has no `.git` history, no private Gold-custodian artifact, and no auditable record proving that these 125 inputs were never examined during prior prompt/rule/retriever tuning.

Therefore:

```text
dev        → DEVELOPMENT
validation → VALIDATION
blind      → HISTORICAL_BLIND_INPUTS_UNVERIFIED
```

The filename is retained for backwards compatibility. Phase 0 does **not** treat it as a trustworthy blind/test result source.

### 7.4 Blind scoring bug fixed

Historically, `BenchmarkRunner.run()` always called `score()` after generating predictions. With `blind_test_inputs_v7_3.json`, that meant the scorer could run even though the rows had no Gold.

Phase 0 now enforces:

```text
No local Gold
→ predictions only
→ macro_objective_score = null
→ scoring_status = PREDICTIONS_ONLY_GOLD_NOT_AVAILABLE
```

Explicit scoring also rejects any selected sample without Gold.

---

## 8. Metric Semantic Audit

### 8.1 Primary metric status

**No formal primary metric is computed in Phase 0.**

The frozen future primary metric is:

```text
End-to-End Task Success = binary PASS / FAIL
```

with a case-dependent success contract. It will be implemented in Phase 1+.

### 8.2 Metric classification

| Metric / signal | What it actually measures | Phase 0 class | Final report? | Resume claim? |
|---|---|---|---|---|
| `macro_objective_score` | Mean of heterogeneous per-layer weighted objective scores | **INVALID/MISLEADING AS PRIMARY** | Legacy appendix only | **No** as Task Success |
| layer `objective_score` | Layer-specific weighted aggregate | **DIAGNOSTIC** | Yes, labeled legacy | Not as E2E |
| `fact_coverage_proxy` | Anchor/number/character-overlap lexical coverage | **PROXY_ONLY** | Diagnostic only | **No** as correctness/groundedness |
| retrieval `recall@K` | Gold relevant evidence retrieved in top K | **DIAGNOSTIC** | Yes | Yes if dataset/split clearly stated |
| MRR / NDCG / MAP | Ranking quality against qrels | **DIAGNOSTIC** | Yes | Yes if real retrieval run |
| source accuracy / source recall | Required source-type overlap | **DIAGNOSTIC** | Yes | Not as answer correctness |
| routing/action/tool accuracy | Match against expected route/tool/action | **DIAGNOSTIC** | Yes | Not as E2E success |
| response-type accuracy | Expected answer/clarification/handoff type | **DIAGNOSTIC** | Yes | Not alone |
| old `eval_platform.agent_evaluator.task_success` | Whether runtime self-reported boolean matches expected boolean | **PROXY_ONLY / SELF-REPORTED SIGNAL** | No as E2E | **No** |
| `self_reported_task_success_match` | Renamed historical signal above | **PROXY_ONLY** | Diagnostic only | No |
| `EvaluationReport.success_rate` | Scenario runtime/evaluator completed without exception | **DIAGNOSTIC EXECUTION RELIABILITY** | Yes with explicit semantics | Not Task Success |
| `context_token_reduction` | Before/after context token reduction | **DIAGNOSTIC EFFICIENCY** | Yes | Yes with success/quality counter-metric |
| context state preservation | Component-preservation signal | **DIAGNOSTIC** | Yes | Not alone |
| memory precision/recall | Retrieved MemoryFact overlap against expected facts | **DIAGNOSTIC** | Yes | Yes as memory subsystem metric |
| stale/wrong memory rates | Invalid memory injection behavior | **DIAGNOSTIC SAFETY** | Yes | Yes with test contract |
| artifact reference/recovery metrics | Artifact subsystem reference/recovery behavior | **DIAGNOSTIC** | Yes | Yes as subsystem metric |
| `unsafe_action_avoidance` in legacy scorer | Keyword absence for a small list of risky completion phrases | **PROXY_ONLY** | Diagnostic only | **No** as Safety Pass Rate |
| latency/model/tool/retrieval counts | Runtime efficiency facts | **DIAGNOSTIC** | Yes | Yes if traced from real execution |

### 8.3 Code-level semantic changes

Phase 0 made the following ambiguity reductions:

- `macro_objective_score` remains for compatibility but report metadata now says `LEGACY_DIAGNOSTIC_DEPRECATED_AS_PRIMARY`;
- scorer report says `primary_metric_status = NOT_DEFINED_IN_PHASE0`;
- `fact_coverage_proxy` explicitly says lexical proxy, not Answer Correctness;
- built-in Agent evaluator now emits `self_reported_task_success_match`, not `task_success`;
- `EvaluationReport` exposes `execution_success_rate`; legacy `success_rate` remains an alias with explicit semantics;
- metrics registry now records `evaluation_execution_success_rate` from the legacy runner instead of labeling it `answer_success_rate`.

---

## 9. KEEP / MIGRATE / DEPRECATE / DELETE Matrix

### KEEP

```text
eval_platform/                         as future core
evals/gold_isolation.py
evals/benchmark/corpus_registry.py
evals/retrieval_evaluation.py          component diagnostic
evaluators/memory_governance.py        component diagnostic
Context/Memory/Artifact/Production benchmarks
annotation pipeline
unified observability / trace infrastructure
```

### MIGRATE

```text
evals/benchmark/runner.py
evals/benchmark/cli.py
evals/benchmark/adapters/*
evals/benchmark/schemas/*
dev/validation v7.3 datasets
evaluators/evaluators.py               formal Judge contract not yet sufficient
evals/run_ablations.py
evals/run_ci_eval.py
evals/agentic_rag_eval.py
annotation reviewed-Gold export schema
```

### DEPRECATE

```text
macro_objective_score as primary metric
objective-score thresholding as task success
fact_coverage_proxy as answer correctness
eval_platform self-reported task_success as formal success
EvaluationReport.success_rate name as semantic primary
historical blind filename as proof of blindness
evals/agentic_rag_metrics.py as formal production quality
legacy TraceMind CSVs as formal current benchmark
old E2E scorer interpretation
```

### DELETE

```text
NONE in Phase 0
```

---

## 10. Target Evaluation Architecture

Phase 0 freezes the following architecture:

```text
Canonical Evaluation Sample                 [Phase 1]
│
├── RuntimeCaseInput  ───────────────────────────────┐
│   query/messages/conversation/identity/config      │ Gold isolation
│                                                    │
└── Gold                                             │
    expected behavior/evidence/facts/safety          │
                                                     ▼
                                          ProductionEvaluationAdapter
                                                     │
                                                     ▼
                                deployments.support_agent_graph.graph
                                                     │
                                                     ▼
                                          ONE Production Execution
                                                     │
                                                     ▼
                                          ONE AgentExecutionTrace
                                                     │
                                                     ▼
                                                TraceAdapter
                                                     │
                                                     ▼
                                             PredictionRecord
                                                     │
                    ┌────────────────────────────────┼─────────────────────────────┐
                    ▼                                ▼                             ▼
              Task Evaluator                 Evidence Evaluator              Safety Evaluator
                    │                                │                             │
                    └────────────────────────────────┼─────────────────────────────┘
                                                     ▼
                                              CaseJudgment
                                                     │
                                                     ▼
                                      Failure Attribution / Report
```

Component diagnostics remain parallel **consumers of the same canonical cases/subsets where appropriate**, but they do not feed a weighted score into Task Success.

---

## 11. Stable Contracts for Phase 1

### `EvaluationSample`

Evaluation-layer owner of:

```text
sample_id
runtime_input
gold
metadata
```

Production code must never receive this object directly.

### `RuntimeCaseInput`

Only production-visible evaluation input. Phase 0 fields:

```text
case_id
messages
identity
config
context
metadata
```

It enforces Gold leakage validation.

### `PredictionRecord`

Generated from exactly one production execution:

```text
case_id
trace_id
final_response
response_type
trace_facts
runtime_metrics
execution_status
execution_error
```

It contains no Gold judgment.

### `CaseJudgment`

Evaluator-side result contract reserved for Phase 1:

```text
case_id
passed
contract
diagnostics
rationale
```

### `EvaluationRun`

Run-level envelope for predictions, judgments and run metadata. Phase 1 should extend this with dataset version, split, git commit, config fingerprint, model versions and judge versions rather than create another run abstraction.

---

## 12. Code Changes Made in Phase 0

### Evaluation core

- `eval_platform/dataset.py`
  - added `RuntimeCaseInput`;
  - added `EvaluationSample`;
  - retained legacy `EvaluationScenario`.
- `eval_platform/report.py`
  - added `PredictionRecord`, `CaseJudgment`, `EvaluationRun`;
  - clarified execution success semantics.
- `eval_platform/production_adapter.py` **new**
  - added `ProductionEvaluationAdapter`;
  - added read-only `TraceAdapter`;
  - added `PredictionDraft`;
  - uses `deployments.support_agent_graph.graph` lazily;
  - one graph invocation only.
- `eval_platform/__init__.py`
  - exports the Phase-0 stable contracts.
- `eval_platform/evaluators.py`
  - renamed self-reported success signal.
- `eval_platform/runner.py`
  - no longer exports runtime completion as `answer_success_rate`.

### Gold isolation

- `evals/gold_isolation.py`
  - expanded forbidden runtime Gold/expected keys.

### Production trace consistency

- `observability/events.py`
  - added `RETRIEVAL_EVENT`, `WORKFLOW_DECISION`, `AUTHORIZATION_DECISION`.
- `observability/trace.py`
  - added `TraceRecorder.bind()` for trace-only worker propagation.
- `observability/instrumentation.py`
  - specialist timeout worker inherits the existing execution trace only.
- `retrieval/trace.py`
  - mirrors sanitized retrieval/verifier/evidence events into current execution trace.
- `agents/support_workflow.py`
  - emits read-only workflow/identity decisions.

### Legacy benchmark migration

- `evals/benchmark/adapters/end_to_end.py`
  - removed multi-execution E2E assembly;
  - E2E now calls `ProductionEvaluationAdapter` once;
  - answer generation remains labeled component diagnostic.
- `evals/benchmark/data_paths.py`
  - added split trust status.
- `evals/benchmark/runner.py`
  - no-Gold dataset becomes predictions-only;
  - run metadata includes split trust status.
- `evals/benchmark/scoring/scorer.py`
  - refuses scoring rows without Gold;
  - labels legacy metric semantics.
- `evals/benchmark/cli.py`
  - CLI output labels macro objective as legacy.
- `evals/tests/test_benchmark_integration.py`
  - updates the E2E adapter contract test.

### New Phase-0 regression tests

```text
tests/evaluation/test_production_evaluation_adapter.py
tests/evaluation/test_single_execution_evaluation.py
tests/evaluation/test_gold_isolation.py
tests/evaluation/test_prediction_trace_consistency.py
tests/evaluation/test_blind_scoring_guard.py
```

---

## 13. Tests Run

### 13.1 Phase-0 and compatible component tests

Command:

```bash
python -m pytest -q \
  tests/evaluation \
  tests/production/test_production_platform.py \
  tests/production/test_production_benchmark.py \
  tests/governance/test_memory_governance.py \
  tests/governance/test_memory_governance_benchmark.py \
  tests/artifact/test_artifact_benchmark.py \
  tests/context_engine/test_context_contract_hardening.py \
  tests/context_engine/test_memory_lifecycle_contract.py
```

Actual result:

```text
45 passed in 1.04s
```

### 13.2 Syntax compilation

Command:

```bash
python -m compileall -q .
```

Actual result:

```text
PASS
```

### 13.3 Original evaluation/Agent integration baseline attempt

Command attempted before modification:

```bash
python -m pytest -q \
  evals/tests/test_benchmark_integration.py \
  tests/test_agentic_rag_protocols.py \
  tests/test_retrieval_execution_stage2.py \
  tests/test_enterprise_governance_stage4.py
```

Actual result:

```text
ERROR during collection
ModuleNotFoundError: No module named 'langchain_core'
```

### 13.4 Offline dependency restore attempt

Command:

```bash
uv sync --offline
```

Actual result:

```text
FAILED
agentevals was not present in the local package cache
network access was disabled
```

---

## 14. Actual Results

These results are **engineering regression results**, not Agent quality benchmark scores:

```text
Phase-0 contract/component test subset: 45 PASS
Python compileall: PASS
Single-execution regression: PASS
Gold-isolation regression: PASS
Prediction/trace consistency regression: PASS
Production deterministic component benchmark test: PASS
```

No formal E2E Task Success, Recovery Rate, Safety Pass Rate, Grounded Claim Rate, or Context Quality-Cost benchmark was generated in Phase 0.

---

## 15. Blocked / Not Run

### BLOCKED: real production Agent smoke

Reason:

```text
langchain_core and the rest of the LLM stack are not installed in the execution environment
```

Offline installation was also blocked because required packages were absent from cache.

Therefore the following are **NOT RUN** in this environment:

```text
real Support Graph LLM invocation
real Milvus retrieval smoke
real model-provider call
real E2E benchmark score
LLM-as-Judge
full Agent/retrieval/governance integration suite that imports LangChain
```

No deterministic/mock result is substituted for those production results.

---

## 16. Remaining Risks

1. **Formal Task Success does not yet exist.** Phase 1 must implement category-specific binary contracts.
2. **Trace model-call count is incomplete.** Supervisor model calls are observed, but query classification and all specialist model calls are not yet guaranteed to use one normalized `MODEL_CALL` event.
3. **Nested Order Agent SQL trace is incomplete.** Supervisor `order_agent` tool use is visible; nested SQL tool semantics need normalization before formal tool-call metrics.
4. **Legacy component adapters still receive a full historical sample object.** The formal E2E runtime boundary is safe, but Phase 1 should migrate all canonical loaders to construct `EvaluationSample` explicitly.
5. **Legacy scorer still exists.** It is labeled diagnostic but can still be called on dev/validation for historical comparisons.
6. **Blind historical validity is unprovable from the supplied checkout.** A new controlled test split/version is required for a trustworthy blind result.
7. **LLM Judge contract is not production-ready.** Existing correctness evaluator has a prompt/schema but does not yet persist all required model/version/retry/raw-judgment metadata in the new run contract.
8. **No git commit is available in the ZIP.** Run provenance can only report `unversioned-checkout` until executed in a real Git checkout.
9. **Production API itself does not yet expose one explicit request-id contract for the whole graph invocation.** The production evaluation adapter creates a trustworthy parent execution trace; API-level trace propagation can be hardened later without changing the Evaluation contract.

---

## 17. Phase 1 Entry Conditions

| Entry condition | Status |
|---|---|
| Evaluation Asset Inventory complete | **YES** |
| Production Evaluation Entry identified | **YES** — `deployments.support_agent_graph.graph` via thin adapter |
| ONE CASE -> ONE EXECUTION principle frozen | **YES** |
| Historical E2E double execution eliminated | **YES for formal legacy end_to_end path** |
| Gold Isolation Boundary frozen | **YES** |
| Old metric semantics classified | **YES** |
| Blind/test trust status made explicit | **YES** |
| `eval_platform` future role decided | **YES — become/migrate into Evaluation Core** |
| `evals/benchmark` future role decided | **YES — legacy runner + diagnostics, migrate E2E to canonical contracts** |
| Component benchmark future role decided | **YES — Component Diagnostics** |
| Phase 1 can implement Canonical Dataset Schema | **YES** |
| Real production integration smoke executed in this environment | **NO — BLOCKED by missing dependencies** |

Because the real LLM/Milvus production smoke is blocked, Phase 0 is reported as **PARTIAL**, not COMPLETE. The architectural entry contracts required for Phase 1 are nevertheless frozen and covered by local regression tests.
