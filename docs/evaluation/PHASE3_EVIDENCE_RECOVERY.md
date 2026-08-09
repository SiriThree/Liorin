# Phase 3: Evidence Reliability, Claim Grounding and Agentic Recovery Evaluation

## 1. Phase 3 Summary

Phase 3 extends the existing `eval_platform` selected in Phase 0. It does not create a parallel benchmark framework and does not change Canonical Dataset semantics from Phase 1 or binary Task Success semantics from Phase 2.

The implemented evaluation path is:

```text
CanonicalEvaluationSample
  ├─ RuntimeCaseInput -> ONE Production execution -> ONE Trace -> PredictionRecord
  └─ hidden GoldEvidence / GoldFact / TaskSuccessContract
                          ↓
                 frozen PredictionRecord
                          ↓
       Evidence / Claim / First-pass / Recovery evaluation
                          ↓
                   Phase-3 diagnostics
```

All Phase-3 scoring operates on the frozen `PredictionRecord`, Trace facts and Canonical Gold. Evaluators never re-run Retriever, Agent, Tool, DB or Verifier.

Stage status: **PARTIAL**. Contracts, instrumentation, deterministic evaluators, Judge contracts, baseline configuration, report writers and regression tests are implemented. Real Production Support Graph and real LLM Judge runs are blocked by the current environment (`langchain` is not installed; offline dependency resolution also fails because `agentevals` is absent from the cache). Therefore no formal Liorin Evidence/Recovery quality number is reported in this phase.

## 2. Evidence Observability Audit

The audit is based on the actual current Production code, especially `agents/knowledge_agent.py`, `retrieval/evidence_verifier.py`, `retrieval/trace.py`, `tools/database.py`, `agents/order_agent.py`, `observability/trace.py`, and `eval_platform/production_adapter.py`.

| Signal | Status | Actual source / limitation |
|---|---|---|
| retrieval round id | AVAILABLE | retrieval/evidence/verifier trace now carries `round_id` |
| initial retrieval query | PARTIAL | query planning/recovery events expose query data, but the initial retrieval-complete event does not always persist one canonical query string |
| retrieval source | AVAILABLE for document path | evidence contributions/source are projected by `TraceAdapter` |
| retrieved document evidence | AVAILABLE | per-evidence trace contains evidence/document/section IDs and rank metadata |
| selected document evidence | AVAILABLE | frozen as final verifier `accepted_evidence_ids`; explicit legacy fallback only for old predictions |
| stable document identity | AVAILABLE | `doc:<document_id>#<section_id>` |
| document id / section id | AVAILABLE | traced by Knowledge-Agent verifier path |
| structured record type / id / field | PARTIAL | safe SQL tool now emits stable read-only evidence projection, but current Order Agent does not register that tool |
| structured field value | PARTIAL | safe SQL tool trace projection records the already-returned field value; current Order Agent wiring remains a gap |
| tool-result evidence | PARTIAL | `execute_sql_template` is instrumented; not all Production specialist tools expose a unified evidence event |
| verifier input evidence | AVAILABLE for document path | round evidence events plus accepted/excluded IDs; structured specialist path is not equivalent yet |
| verifier output decision | AVAILABLE | `verify_evidence.complete.action` |
| coverage/conflict state | AVAILABLE for document verifier | coverage before/after, missing/covered requirements, conflicts |
| recovery action | AVAILABLE for Knowledge Agent | real `VerificationAction` values are projected from the same trace |
| rewritten query | PARTIAL | rewrite/replan events are captured when present |
| supplement plan | PARTIAL | generated subqueries/new evidence are available; there is no one universal supplement-plan object |
| clarification slot | PARTIAL | captured when Production event exposes the requested slot |
| handoff | AVAILABLE | terminal handoff event/action is traced |
| round latency | PARTIAL | retrieval/recovery events expose available latency; not every verifier step has a dedicated latency |
| round error | PARTIAL | errors are preserved when the Production event carries them |

### Selected Evidence semantic freeze

For Phase 3, `selected_evidence` has one formal meaning:

1. document evidence accepted by the **final Evidence Verifier decision** and therefore allowed through the answer gate; plus
2. structured tool-result evidence explicitly marked as already passed into the specialist LLM context.

Raw Dense/BM25/fusion candidates are not the Selected Evidence Precision denominator.

## 3. Structured Evidence Trace

Phase 2 correctly identified that structured evidence was not consistently observable. Phase 3 adds read-only structured evidence instrumentation to the safe fixed-template tool in `tools/database.py`.

After `execute_sql_template` has already performed its one authorized DB read, the returned rows are projected into trace-only evidence events. No additional DB query is executed. A returned field is represented as:

```text
record:<record_type>:<record_id>#<field_path>
```

The trace event records the template/tool, stable result reference and the already-returned value. `TraceAdapter` then projects these events into `EvaluationEvidenceRef` and, because the tool result is directly returned to the specialist LLM context, marks them as selected-for-answer evidence.

### Remaining real Production gap

Current `agents/order_agent.py` still imports and registers:

```text
ORDER_AGENT_BASE_TOOLS = [execute_sql]
```

while `execute_sql` is the legacy arbitrary-SQL entrypoint that intentionally fails closed. The safe `execute_sql_template` exists but is **not registered by the current Order Agent**.

Phase 3 does not change this wiring because replacing a Production business tool would alter Agent behavior rather than merely improve observability. Consequently:

- the structured Evidence contract and instrumentation exist;
- structured Prediction fixtures can be evaluated correctly;
- actual Order/Ticket/Warranty Production evidence remains **PARTIAL / observability-wiring blocked** until the Production specialist is intentionally migrated to the safe template tool in a separate correctness change.

Evaluator code is forbidden from compensating by querying the DB itself.

## 4. Evidence Identity / Matching

`eval_platform.evidence` normalizes Production evidence into `EvaluationEvidenceRef` without creating a second `GoldEvidence` type.

Stable identities:

```text
DOCUMENT   doc:<document_id>#<section_id>
STRUCTURED record:<record_type>:<record_id>#<field_path>
TOOL_RESULT stable result_ref / reviewed alias
```

Matching priority is deterministic:

1. typed stable evidence identity;
2. exact document + section;
3. exact structured record + field;
4. explicitly reviewed stable aliases;
5. explicit parent/child hierarchy metadata;
6. semantic relevance Judge only where deterministic matching cannot answer relevance.

A Phase-3 regression found and fixed a real over-counting bug: a section-scoped Gold requirement could previously match another section from the same document because a broad `document_id` alias intersected. Now a Gold section requires the same section, an explicitly allowed parent hierarchy, an exact stable evidence ID, or a reviewed alias. Likewise, a field-scoped structured requirement cannot be satisfied by another field in the same record.

Alternative evidence uses Phase-1 `alternative_group`; one group is one required unit and can never contribute recall greater than 1.

## 5. Evidence Recall@K

Implemented case-level `Any Required Evidence Recall@K` for K = 1, 3, 5, 10.

Definition for a K:

```text
# eligible cases whose first K ranked observed evidence items contain
  at least one required Gold evidence unit
/
# eligible retrieval cases with rank-aware evidence trace
```

Case diagnostics preserve the boolean per K. Aggregate reports include the formal `@5` summary while other K values remain available case-by-case.

The metric is not emitted for a case whose trace cannot establish the relevant evidence path.

## 6. Required Gold Evidence Recall

Formal definition:

```text
# required Gold evidence units observed in the frozen Production trace
/
# all required Gold evidence units
```

An `alternative_group` contributes one unit regardless of how many approved alternatives are retrieved.

The implementation supports document evidence, structured record/field evidence, multi-evidence tasks and reviewed alternative evidence. Observability absence is not converted into retrieval failure.

## 7. Selected Evidence Precision

Formal denominator:

```text
all evidence actually passed into the Verifier / Answer path
```

Relevant selected evidence can be classified as:

- `GOLD_MATCH`
- `SEMANTICALLY_RELEVANT`
- `IRRELEVANT`
- `NOT_EVALUATED`

A selected item that is not annotated Gold is **not automatically irrelevant**. If a real semantic relevance Judge is unavailable it becomes `NOT_EVALUATED`, making precision incomplete rather than artificially low or high.

Empty selected evidence has an explicit zero-denominator / not-evaluable semantic.

## 8. Claim Schema

Phase 3 adds `AnswerClaim` with:

```text
claim_id
text
critical
claim_type
normalized_subject
normalized_predicate
normalized_value
source_span
gold_fact_ids
```

Claim extraction is intentionally separate from answer correctness. It does not decide whether the answer is globally good.

## 9. Claim Extraction

Phase-2 `JudgeRuntime` is reused. A new versioned prompt exists:

```text
claim_extraction_v1
```

Input is limited to the user task and final answer. Output is structured `claims[]`.

If no real Judge is available, semantic claim extraction is incomplete/NOT RUN; the system does not substitute keyword splitting and call it claim-level grounding.

## 10. Claim-Evidence Entailment

New versioned prompt:

```text
claim_evidence_entailment_v1
```

The Judge sees only the claim and candidate evidence (and task query where needed), and returns one of:

```text
SUPPORTED
UNSUPPORTED
CONTRADICTED
NOT_VERIFIABLE
```

Structured facts with stable record/field evidence are eligible for deterministic support checks before an LLM is used.

A separate `selected_evidence_relevance_v1` prompt handles non-Gold selected evidence relevance.

## 11. Grounded Claim Rate

Formal definition:

```text
SUPPORTED critical claims
/
all verifiable critical claims
```

`NOT_VERIFIABLE` claims are excluded from this denominator and reported separately.

Also reported:

```text
Unsupported Critical Claim Rate
Contradicted Critical Claim Count
Not-verifiable Critical Claim Count
```

No formal Grounded Claim Rate is produced from stubs or keyword proxy output.

## 12. Correctness vs Grounding

Phase 2 `CRITICAL_FACTS_CORRECT` remains independent from Phase-3 grounding.

Examples preserved by the contracts:

```text
fact happens to be correct + evidence absent
=> correctness may PASS; grounding does not PASS

relevant evidence is present + answer misreads it
=> evidence source present; correctness can FAIL
```

Evidence presence is therefore never renamed `Grounded Answer`.

## 13. First-pass Boundary

The Production-aligned boundary is frozen as:

```text
initial query / plan
  -> first retrieval/tool acquisition
  -> first observed evidence
  -> first Evidence Verifier decision
  -> FIRST-PASS BOUNDARY
  -> any supplement/rewrite/decompose/relax/clarify/handoff recovery
```

This is an evidence sufficiency boundary before recovery, not “the first final answer was wrong.”

## 14. FirstPassStatus

Strongly typed statuses:

```text
SUFFICIENT
INSUFFICIENT_EVIDENCE
MISSING_STRUCTURED_DATA
MISSING_REQUIRED_SLOT
CONFLICT_UNRESOLVED
STALE_EVIDENCE
VERIFIER_REJECTED
AUTHORIZATION_BLOCKED
EXECUTION_ERROR
UNKNOWN
```

The current evaluator uses only states that can be proven from available Gold and frozen trace. Missing structured observability produces `UNKNOWN / OBSERVABILITY_INSUFFICIENT`; it is not a retrieval miss.

## 15. Gold-aware First-pass Evaluation

`eval_platform.recovery.evaluate_first_pass()` compares:

```text
round-1 Production evidence + Canonical Gold
```

and independently decides whether first-pass evidence was sufficient.

It also records the Production Verifier's first action and normalized sufficient/recover decision. This makes verifier correctness independently measurable without trusting the Production Verifier as Gold.

## 16. Production Verifier Evaluation

Phase 3 records:

```text
True Accept
False Accept
True Reject
False Reject
```

Definitions:

```text
Gold-aware insufficient + Production ACCEPT
=> VERIFIER_FALSE_ACCEPT

Gold-aware sufficient + Production recovery action
=> VERIFIER_FALSE_REJECT
```

Diagnostics include sufficiency precision/recall, false accept rate and false reject rate. They are not North-Star metrics.

## 17. Recovery Eligibility

`RecoveryEvaluationEligibilityStatus`:

```text
ELIGIBLE
NO_FIRST_PASS_TRACE
MISSING_GOLD_EVIDENCE
MISSING_RECOVERY_TRACE
NON_RECOVERABLE
NEEDS_REVIEW
UNSUPPORTED
```

Authorization blocks and execution errors do not enter the formal recoverable-failure denominator. Observability gaps are not silently skipped or reclassified as Agent failure.

## 18. RecoveryTrace

Each recovery case has a typed `RecoveryTrace` derived only from the one frozen Prediction/Trace:

```text
case_id
first_pass
eligibility
rounds[]
  round_index
  action
  input_query
  rewritten_query
  requested_slot
  new_evidence
  verifier_decision
  latency
  error
  budget_before / budget_after
final_task_success
outcome
failure_reason
```

Actual current Production recovery actions are derived from `VerificationAction` and include:

```text
SUPPLEMENT
REWRITE
DECOMPOSE
RELAX_FILTERS
CLARIFY
HANDOFF
```

Phase-3 evaluator aliases only reflect these real actions; it does not invent a new Production action vocabulary.

## 19. First-pass Failure Recovery Rate

Formal denominator is frozen as:

```text
# recoverable Gold-aware first-pass failures that finally reach formal Task Success PASS
/
# all recoverable Gold-aware first-pass failures
```

Non-recoverable authorization blocks are excluded from that denominator.

A separate raw outcome diagnostic can report final success across all first-pass failures, but it is not named the formal recovery rate.

## 20. Recovery Rounds / Budget

Reported for observable recoverable cases:

```text
Average Recovery Rounds
P50
P95
Max
Success within 1 Round
Success within 2 Rounds
```

Production budgets are read from trace snapshots. The evaluator does not alter them. Current Knowledge Agent constants still include:

```text
MAX_RETRIEVAL_RETRIES = 2
MAX_VERIFICATION_RETRIES = 1
```

and the existing `RetrievalBudget` remains the production source of runtime retrieval budgets.

## 21. Recovery Action Distribution

Aggregate output keeps case-level recovery rate separate from action-level diagnostics and reports:

```text
action count
success by action
```

A case may contain multiple actions; therefore action counts are not used as the recovery denominator.

## 22. Recovery Failure Reasons

Phase-3 typed taxonomy includes:

```text
RETRIEVAL_MISS
STRUCTURED_DATA_MISSING
QUERY_REWRITE_INEFFECTIVE
SUPPLEMENT_INEFFECTIVE
WRONG_CLARIFICATION
OVER_CLARIFICATION
VERIFIER_FALSE_ACCEPT
VERIFIER_FALSE_REJECT
CONFLICT_UNRESOLVED
STALE_EVIDENCE
BUDGET_EXHAUSTED
TOOL_ERROR
AUTHORIZATION_BLOCKED
GROUNDING_FAILURE
ANSWER_FAILURE
OBSERVABILITY_INSUFFICIENT
UNKNOWN
```

This is intentionally narrower than a future global Phase-5 failure taxonomy.

## 23. One-pass Baseline

No `simple_rag_baseline.py` or copied retrieval stack was created.

The existing Production Knowledge Agent gained one configuration-only switch:

```text
create_knowledge_agent(..., recovery_enabled=True)
```

The deployment entry now exposes:

```text
build_graph(agentic_recovery_enabled=True|False)
```

Default `graph` still builds with recovery enabled, preserving Production behavior.

The `ONE_PASS_BASELINE` uses the same deployment graph construction, model initialization, retriever, verifier, prompts, answer nodes, identity and governance. Only the post-first-verifier recovery route is disabled. If first-pass verifier accepts, the normal answer path is used; if it does not accept, the recovery-disabled baseline terminates safely instead of running a second retrieval/rewrite/decompose/clarification loop.

Example configs:

```text
evals/benchmark/configs/phase3_full_agentic.example.json
evals/benchmark/configs/phase3_one_pass_baseline.example.json
```

The unified CLI consumes `production.agentic_recovery_enabled` through the existing `ProductionEvaluationAdapter`; this is an executable configuration, not documentation-only metadata.

## 24. Full vs Baseline Protocol

Fairness constraints are frozen:

```text
same Canonical dataset / case IDs
same model
same embedding
same corpus/index
same retriever configuration
same identity
same prompts
same Production code
```

The intended core difference is only Agentic Recovery enabled/disabled.

Real Full-vs-One-pass Task Success and absolute gain are **NOT RUN** in this environment because the Production graph cannot currently import.

## 25. Metric Denominators

- Required Gold Evidence Recall: required evidence units found / all required units.
- Any Required Evidence Recall@5: eligible rank-aware cases with at least one required evidence in top 5 / all such eligible cases.
- Selected Evidence Precision: relevant selected evidence / all selected evidence; unresolved semantic relevance makes the metric incomplete rather than guessed.
- Grounded Claim Rate: supported critical claims / all verifiable critical claims; NOT_VERIFIABLE excluded and reported.
- First-pass Failure Rate: Gold-aware insufficient first passes / cases with sufficient first-pass observability.
- First-pass Failure Recovery Rate: recoverable first-pass failures ending Task Success PASS / all recoverable first-pass failures.
- Unnecessary Recovery Rate: Gold-aware sufficient first passes that still perform a recovery action / all Gold-aware sufficient first passes.

All aggregate outputs retain numerator and denominator.

## 26. Artifact / Report Format

A formal Phase-2 run or `score-existing-predictions` now additionally writes:

```text
evidence_summary.json
evidence_summary.md
recovery_summary.json
recovery_summary.md
phase3_summary.json
case_evidence_diagnostics.jsonl
case_claim_grounding.jsonl
case_recovery_diagnostics.jsonl
```

Existing Phase-2 artifacts remain physically separate:

```text
predictions.jsonl
judgments.jsonl
evaluation_run.json
summary.json
summary.md
```

Phase-3 rescoring never mutates `predictions.jsonl` and never invokes Production.

Prediction schema is now `3.0`; older Phase-2 predictions deserialize as `2.0`. Metrics that can be supported from old stable evidence refs may still run, while missing round/verifier trace is explicitly reported as unavailable instead of triggering a Production rerun.

## 27. Dataset Inventory / Eligibility

Generated by:

```text
evals/scripts/build_phase3_evaluation_inventory.py
```

Artifact:

```text
evals/benchmark/data/canonical/phase3_evaluation_inventory.json
```

Actual Canonical data-readiness counts (not quality metrics):

| Asset | Cases | Cases with GoldEvidence | Required Document Evidence | Required Structured Evidence |
|---|---:|---:|---:|---:|
| legacy dev | 34 | 34 | 35 evidence units / 34 cases | 10 evidence units / 10 cases |
| legacy validation | 5 | 5 | 5 evidence units / 5 cases | 0 |
| representative seed | 15 | 10 | 8 evidence units / 7 cases | 5 evidence units / 5 cases |

Thus all **39 formal legacy canonical cases** contain GoldEvidence, and **10** formally migrated dev cases require structured evidence.

The 15 representative seed cases remain `NEEDS_REVIEW` and are not formal benchmark results.

### Recovery challenge coverage

Current formal Canonical data does not contain an independently reviewed, explicit first-pass-insufficiency condition for a certified Recovery Challenge subset. Therefore:

```text
Recovery Challenge Dataset Coverage Insufficient
status = COVERAGE_INSUFFICIENT_NEEDS_REVIEW
```

No synthetic 100-case recovery benchmark was auto-generated.

## 28. Legacy Retrieval Evaluator Migration

`evals/retrieval_evaluation.py`, `evals/agentic_rag_metrics.py`, and the legacy layered benchmark continue to exist for compatibility/component regression.

`evals/retrieval_evaluation.py` is now explicitly marked:

```text
LEGACY_DIAGNOSTIC_MIGRATE_TO_EVAL_PLATFORM_EVIDENCE
```

Historical names such as:

```text
recall@K
evidence_coverage
retrieval objective
retry success
```

are not aliases for the Phase-3 formal metrics. Formal definitions live in `eval_platform.evidence`, `eval_platform.recovery`, and `eval_platform.phase3_report`.

## 29. Judge Calibration

Added:

```text
evals/benchmark/data/calibration/phase3_claim_grounding_calibration_v1.json
```

It contains referenced fixtures for:

```text
exact support
paraphrase support
partial support
unsupported
contradicted
structured fact support
multiple-evidence synthesis
irrelevant evidence
```

References are carefully constructed fixtures, not Judge self-grading. `load_phase3_claim_calibration()` validates IDs, kinds, expected labels and provenance.

Real calibration quality is **NOT RUN** because the real Judge provider cannot import in the current environment. Stub providers are used only for infrastructure/evaluator tests.

## 30. Code Changes Made in Phase 3

### New evaluation modules

```text
eval_platform/evidence.py
eval_platform/recovery.py
eval_platform/phase3_report.py
```

### Extended existing Evaluation Core

```text
eval_platform/contracts.py
eval_platform/judge.py
eval_platform/report.py
eval_platform/runner.py
eval_platform/production_adapter.py
eval_platform/calibration.py
eval_platform/cli.py
eval_platform/__init__.py
```

### Read-only Production instrumentation / baseline configuration

```text
retrieval/observability.py
agents/knowledge_agent.py
deployments/support_agent_graph.py
tools/database.py
```

No Production prompt, retrieval ranking algorithm, verifier decision policy, memory policy or governance policy was changed.

### Data/config assets

```text
evals/benchmark/configs/phase3_full_agentic.example.json
evals/benchmark/configs/phase3_one_pass_baseline.example.json
evals/benchmark/data/calibration/phase3_claim_grounding_calibration_v1.json
evals/benchmark/data/canonical/phase3_evaluation_inventory.json
evals/scripts/build_phase3_evaluation_inventory.py
```

### Legacy compatibility documentation

```text
evals/retrieval_evaluation.py
evals/benchmark/README.md
```

### Added / expanded tests

```text
tests/evaluation/test_phase3_evidence_reliability.py
tests/evaluation/test_phase3_claim_grounding.py
tests/evaluation/test_phase3_first_pass_recovery.py
tests/evaluation/test_phase3_trace_observability.py
tests/evaluation/test_phase3_judge_calibration.py
tests/evaluation/test_phase3_inventory_and_baseline.py
tests/evaluation/test_phase2_formal_runner.py   # score-existing artifact regression extended
```

## 31. Tests / Actual Results

### Phase 3 + Phase 0/1/2 Evaluation regression

```bash
PYTHONPATH=. pytest -q tests/evaluation
```

Actual:

```text
94 passed in 0.71s
```

This includes the Phase-0 single-execution and Gold-isolation regressions, Phase-1 Schema/Validator/Migration regressions, Phase-2 TaskSuccess/Judge regressions, and Phase-3 Evidence/Grounding/Recovery tests.

### Broader compatibility regression

```bash
PYTHONPATH=. pytest -q \
  tests/evaluation \
  tests/production/test_production_platform.py \
  tests/production/test_production_benchmark.py \
  tests/governance/test_memory_governance.py \
  tests/governance/test_memory_governance_benchmark.py \
  tests/artifact/test_artifact_benchmark.py \
  tests/context_engine/test_context_contract_hardening.py \
  tests/context_engine/test_memory_lifecycle_contract.py
```

Actual:

```text
132 passed in 1.53s
```

### Compile

```bash
PYTHONPATH=. python -m compileall -q .
```

Actual: `PASS`.

These pass counts are code/contract regressions, **not** Agent quality metrics.

## 32. Production / Judge Status, Blocked Items and Phase 4 Entry

### Production Support Graph

Rechecked in this Phase:

```bash
PYTHONPATH=. python -c "import deployments.support_agent_graph"
```

Actual:

```text
ModuleNotFoundError: No module named 'langchain'
```

Status:

```text
Production E2E smoke = BLOCKED
real Evidence Recall = NOT RUN
real First-pass Failure Rate = NOT RUN
real Recovery Rate = NOT RUN
Full vs One-pass = NOT RUN
```

### Real Judge

Rechecked:

```text
from langchain.chat_models import init_chat_model
```

Actual:

```text
ModuleNotFoundError: No module named 'langchain'
```

Status:

```text
real Claim Extraction Judge = BLOCKED / NOT RUN
real Claim-Evidence Entailment Judge = BLOCKED / NOT RUN
real Grounded Claim Rate = NOT RUN
real Judge calibration quality = NOT RUN
```

### Offline dependency attempt

```bash
uv sync --offline
```

Actual result: failed because `agentevals>=0.0.9` is not present in the local cache while network access is disabled. No mock Production run was substituted.

### Remaining risks / data review debt

1. Current `order_agent` still registers fail-closed legacy `execute_sql`, not the safe `execute_sql_template`; structured Production business queries therefore require a separate Production correctness/wiring change.
2. Structured evidence instrumentation exists but cannot claim real Order/Ticket/Warranty observability until the safe tool is actually on the Production specialist path.
3. Initial retrieval query and some recovery/latency details are still partial in the trace contract.
4. Real semantic Selected Evidence relevance, Claim Extraction and entailment require a real Judge.
5. No trusted TEST split exists.
6. No formally reviewed Recovery Challenge subset exists yet; current coverage is explicitly insufficient.
7. Full-vs-One-pass gain is not known and must not be assumed positive.

### Phase 4 stable interfaces

Phase 4 can directly depend on:

```text
EvaluationEvidenceRef
EvidenceEvaluationEligibility
EvidenceItemRelevance
EvidenceCaseDiagnostic
AnswerClaim
ClaimSupport
ClaimGroundingDiagnostic
FirstPassStatus
FirstPassEvaluation
RecoveryEvaluationEligibility
RecoveryRound
RecoveryTrace
RecoveryFailureReason
RecoveryOutcome

evidence_matches
prediction_evidence_refs
evaluate_evidence_case
evaluate_claim_grounding
aggregate_evidence_metrics
aggregate_grounding_metrics

evaluate_first_pass
recovery_eligibility
build_recovery_trace
aggregate_recovery_metrics

evaluate_phase3
build_phase3_summary
write_phase3_artifacts

claim_extraction_v1
claim_evidence_entailment_v1
selected_evidence_relevance_v1

ProductionEvaluationAdapter.for_agentic_recovery(...)
build_graph(agentic_recovery_enabled=...)
```

The following Phase-3 invariants are frozen for Phase 4:

```text
ONE CASE -> ONE Production execution -> ONE Trace -> ONE PredictionRecord
Evidence/Recovery rescoring never triggers Production execution
Observability failure != retrieval failure
Correctness != grounding
Task Success remains the North Star and is not recombined with Evidence/Recovery into a weighted score
```

Phase 4 may now build Context / Memory Quality-Cost experiments on these frozen Task/Evidence/Recovery diagnostics without redefining them.
