# Phase 1 Canonical Dataset, Gold Schema, and Task Success Contract

## 1. Phase 1 Summary

Phase 1 status: **PARTIAL**.

The Evaluation data layer is implemented and validated, but the supplied execution environment still cannot import the real deployment graph because the declared `langchain` dependency is not installed. Therefore no real Production Agent smoke run, LLM Judge, or formal End-to-End Task Success metric is claimed in this phase.

Phase 1 refines the existing Phase-0 `eval_platform` contracts rather than creating a parallel framework. The stable invariant remains:

```text
ONE CASE
  -> ONE PRODUCTION EXECUTION
  -> ONE TRACE
  -> ONE PREDICTION RECORD
```

The canonical data flow is now:

```text
EvaluationSample / CanonicalEvaluationSample
  | owns runtime input + hidden Gold
  |-- RuntimeCaseInput ------------------------------> ProductionEvaluationAdapter
  |                                                    -> Production Agent
  |                                                    -> PredictionRecord
  |
  `-- ExpectedBehavior / TaskSuccessContract /
      GoldEvidence / GoldFact / SafetyConstraint ----> Phase-2 Evaluators
                                                        -> CaseJudgment
```

`CanonicalEvaluationSample` is a semantic alias of the existing `EvaluationSample`; it is **not** a second sample implementation.

No weighted Task Success, official Task Success score, LLM Judge result, recovery rate, context quality-cost metric, or ablation result was produced in Phase 1.

---

## 2. Canonical Dataset Architecture

The unified core remains `eval_platform/`:

```text
eval_platform/
├── contracts.py          # strong Gold/dataset enums and dataclasses
├── dataset.py            # single canonical sample + RuntimeCaseInput + JSON/JSONL/hash/manifest
├── validation.py         # fail-closed canonical dataset validator
├── migration.py          # conservative v7.3 legacy migration
├── seed_cases.py         # source-grounded schema coverage seed cases
├── production_adapter.py # Phase-0 one-execution runtime boundary
├── evaluators.py         # legacy/component evaluators; formal Phase-2 task evaluators not added here yet
├── report.py
└── runner.py
```

Canonical generated assets live under the existing benchmark data tree rather than a new framework:

```text
evals/benchmark/data/canonical/
├── dev_v7_3_canonical_v1.json
├── dev_v7_3_canonical_v1.manifest.json
├── validation_v7_3_canonical_v1.json
├── validation_v7_3_canonical_v1.manifest.json
├── representative_seed_v1.json
├── representative_seed_v1.jsonl
├── representative_seed_v1.manifest.json
├── phase1_legacy_migration_report.json
├── phase1_legacy_review_queue.json
├── phase1_non_v73_migration_status.jsonl
├── phase1_legacy_asset_inventory.json
├── split_trust_v1.json
└── phase1_asset_summary.json
```

The deterministic asset builder is:

```text
evals/scripts/build_phase1_canonical_assets.py
```

---

## 3. Task Taxonomy

`eval_platform.contracts.TaskCategory` defines exactly five primary categories:

```text
KNOWLEDGE_QA
TROUBLESHOOTING
PRIVATE_BUSINESS_QUERY
MIXED_KNOWLEDGE_STRUCTURED
SAFETY_GOVERNANCE
```

The old six benchmark layers (`query_understanding`, `routing`, `retrieval`, `agent_behavior`, `answer_generation`, `end_to_end`) are not canonical task categories. They remain legacy diagnostic dimensions/migration metadata.

Supported subcategories are validated by `eval_platform.validation.SUBCATEGORIES`:

| Category | Supported subcategories |
|---|---|
| `KNOWLEDGE_QA` | `FAQ`, `EXACT_SPEC`, `AFTER_SALES_POLICY`, `REGION_POLICY`, `MULTI_DOCUMENT` |
| `TROUBLESHOOTING` | `DIRECT`, `MULTI_STEP`, `MISSING_INFORMATION`, `AMBIGUOUS_SYMPTOM`, `RETRIEVAL_RECOVERY` |
| `PRIVATE_BUSINESS_QUERY` | `ORDER`, `TICKET`, `WARRANTY`, `CROSS_OBJECT` |
| `MIXED_KNOWLEDGE_STRUCTURED` | `ORDER_POLICY`, `PRODUCT_WARRANTY`, `TICKET_MANUAL`, `ORDER_REGION_POLICY` |
| `SAFETY_GOVERNANCE` | `TENANT_ISOLATION`, `USER_ISOLATION`, `PROMPT_INJECTION`, `UNAUTHORIZED_TOOL`, `SENSITIVE_DATA` |

`MIXED_KNOWLEDGE_STRUCTURED` is first-class. The validator rejects a mixed case unless its required Gold contains at least one `DOCUMENT` evidence and one `STRUCTURED_DATA` evidence.

---

## 4. CanonicalEvaluationSample Schema

The canonical class is the Phase-0 `EvaluationSample` refined in `eval_platform/dataset.py`:

```text
case_id / sample_id
schema_version
split: DatasetSplit
category: TaskCategory
subcategory
difficulty: Difficulty
tags
input: RuntimeCaseInput
expected_behavior: ExpectedBehavior
task_success_contract: TaskSuccessContract
gold_evidence: tuple[GoldEvidence, ...]
gold_facts: tuple[GoldFact, ...]
safety_constraints: tuple[SafetyConstraint, ...]
annotation_metadata: AnnotationMetadata
source_metadata: SourceMetadata
```

`CanonicalEvaluationSample = EvaluationSample` is an alias, so Phase 1 does not introduce `CanonicalSampleV2`, `BenchmarkCase2`, or another parallel record hierarchy.

Canonical schema version:

```text
1.0
```

`DatasetSplit` is strong typed:

```text
DEVELOPMENT
VALIDATION
TEST
```

A filename containing `blind` is not a valid split value and cannot grant test trust.

Unknown-field policy is **fail closed** for the canonical object, runtime input, identity, expected behavior, task success contract, conditional criteria, GoldEvidence, GoldFact, SafetyConstraint, annotation metadata, and source metadata. `config`, `context`, `metadata`, and evidence `metadata` remain intentionally extensible mappings.

---

## 5. RuntimeCaseInput Boundary

`RuntimeCaseInput` is the only Evaluation input accepted by `ProductionEvaluationAdapter`.

Runtime-visible fields are:

```text
case_id
query
messages
identity
config
context
metadata
```

It cannot contain:

```text
expected_behavior
task_success_contract
gold_evidence
gold_facts
safety_constraints
expected_answer
expected_source
required_keywords
required_atomic_facts
...
```

`RuntimeCaseInput.runtime_packet()` calls `assert_no_gold_leak()` recursively.

Identity uses `IdentitySpec`, whose five core identifiers map one-to-one to production `identity.IdentityContext`:

```text
tenant_id
user_id
conversation_id
thread_id
session_id
```

If an identity mapping is supplied, Phase 1 no longer invents a missing `tenant_id` or `user_id` merely to make a benchmark case valid. Conversation/thread/session IDs may be deterministically allocated as execution identifiers when a real tenant/user principal is supplied.

A key migration finding is that legacy `input.identity_verified=true` is **not** a real input accepted by the Production Support Graph. Current `agents/support_workflow.py` verifies a customer from runtime conversation/email and database state. Therefore that old flag is not promoted into Canonical Gold or runtime authorization state.

---

## 6. ExpectedBehavior Schema

`ExpectedBehavior` explicitly models expected system behavior:

```text
response_type: ResponseType
required_agents
allowed_agents
forbidden_agents
required_tools
allowed_tools
forbidden_tools
clarification_required: bool | None
required_clarification_slots
handoff_required: bool | None
handoff_reason
authorization_required: bool | None
allowed_recovery_actions
forbidden_recovery_actions
```

`ResponseType` is:

```text
ANSWER
CLARIFICATION
HANDOFF
REFUSAL
ERROR
```

`clarification_required` and `handoff_required` deliberately support `True`, `False`, and `None` so legacy unknown state is not silently converted into a negative Gold label.

---

## 7. TaskSuccessContract

`TaskSuccessContract` is a strong, conjunctive contract. It stores:

```text
required_criteria: tuple[SuccessCriterion, ...]
conditional_criteria: tuple[ConditionalSuccessCriterion, ...]
```

Current `SuccessCriterion` values are:

```text
RESPONSE_TYPE_CORRECT
REQUIRED_AGENTS_CORRECT
REQUIRED_TOOLS_CORRECT
FORBIDDEN_TOOLS_NOT_CALLED
CRITICAL_FACTS_CORRECT
CRITICAL_FACTS_GROUNDED
CLARIFICATION_CORRECT
HANDOFF_CORRECT
AUTHORIZATION_CORRECT
NO_UNAUTHORIZED_ACCESS
NO_SENSITIVE_DATA_LEAK
NO_CRITICAL_HALLUCINATION
```

Future Phase-2 semantics are binary:

```text
for every required criterion:
    criterion must PASS

if ANY required criterion FAILS:
    End-to-End Task Success = FAIL
else:
    End-to-End Task Success = PASS
```

There is no weight field and no threshold field. Diagnostic scores may be added by evaluators later, but cannot define Task Success.

Phase 1 **does not execute** this contract to produce an Overall Task Success number.

---

## 8. GoldEvidence Schema

`GoldEvidence` supports:

```text
evidence_id
source_type
required
alternative_group
document_id
section_id
record_type
record_id
field_path
expected_value
authority
effective_from
effective_to
metadata
```

`EvidenceSourceType` currently supports only evidence sources justified by the real system:

```text
DOCUMENT
STRUCTURED_DATA
TOOL_RESULT
```

Memory and Artifact were deliberately **not** automatically added as authoritative Gold evidence sources merely because Liorin has memory/artifact systems.

Document evidence uses stable logical source identifiers such as:

```text
doc:<source_file>#<chunk_id>
```

Structured evidence uses stable business-record identifiers such as:

```text
record:order:<order_id>
record:ticket:<ticket_id>
record:warranty:<case_id>
```

No Gold references `top_k=3`, “fifth chunk”, or another runtime rank.

Multi-evidence is represented by multiple `GoldEvidence` objects. Equivalent manually-approved alternatives can share `alternative_group`; a serialization test proves this field survives round-trip. Phase 2 must implement the group semantics and must not auto-expand alternative Gold from semantic similarity.

---

## 9. GoldFact Schema

`GoldFact` contains:

```text
fact_id
description
normalized_value
value_type
critical
supporting_evidence_ids
comparison_mode
```

Supported `value_type` values include string, integer, float, boolean, date, datetime, enum, and JSON. Comparison modes include exact, normalized exact, numeric, date, and semantic.

A critical GoldFact must reference existing GoldEvidence IDs; the validator rejects missing support.

Legacy `required_keywords` are **not GoldFact**. They remain lexical legacy annotations unless separately reviewed and migrated. The migration tests explicitly assert that `required_keywords` are not auto-promoted.

---

## 10. SafetyConstraint Schema

`SafetyConstraint` can express case-specific Gold requirements without copying production governance policy into the dataset:

```text
tenant_boundary
user_ownership
required_permissions
forbidden_resources
forbidden_tools
forbidden_disclosures
expected_authorization_behavior
```

Canonical safety cases are invalid if they have no non-empty safety constraint.

The representative safety seed set is grounded in real repository attack surfaces / identity relationships and covers:

```text
TENANT_ISOLATION
USER_ISOLATION
UNAUTHORIZED_TOOL
PROMPT_INJECTION
```

No new production capability was created just to make these cases exist.

---

## 11. Split Trust Model

Trust is explicit in `DatasetManifest.trust_level` and in:

```text
evals/benchmark/data/canonical/split_trust_v1.json
```

Current trust is:

| Legacy asset | Trust |
|---|---|
| `dev_v7_3.json` | `DEVELOPMENT` |
| `validation_v7_3.json` | `VALIDATION` |
| `blind_test_inputs_v7_3.json` | `HISTORICAL_UNVERIFIED` |

Formal result:

```text
NO TRUSTED TEST SPLIT YET
```

There is no evidence in the supplied checkout proving independent Gold custody, zero historical tuning exposure, and human review for the historical blind inputs. The word `blind` in the filename is ignored for trust assignment.

---

## 12. Dataset Validator

`eval_platform/validation.py` is fail closed by default:

```python
validate_dataset(samples)
# raises DatasetValidationError if invalid
```

Migration diagnostics can use:

```python
validate_dataset(samples, allow_invalid=True)
```

The validator currently enforces:

- unique case IDs;
- supported schema version;
- valid strong-typed split/category/difficulty values;
- category/subcategory compatibility;
- required/forbidden agent conflicts;
- required/forbidden tool conflicts;
- clarification-required implies at least one required slot;
- clarification false cannot carry required slots;
- handoff false cannot carry a handoff reason;
- authorization-required cases require production-compatible identity;
- non-empty TaskSuccessContract;
- no duplicate required criteria;
- criterion/ExpectedBehavior compatibility;
- forbidden-tool criterion requires an explicit forbidden tool;
- authorization criterion requires an explicit authorization expectation;
- sensitive-data-leak criterion requires explicit safety constraints;
- critical fact criteria require GoldFacts;
- unique stable evidence IDs;
- critical GoldFacts require support evidence;
- all supporting evidence references exist;
- Private Business Query requires identity;
- Safety/Governance requires non-empty SafetyConstraint;
- Mixed Knowledge + Structured requires required `DOCUMENT` + `STRUCTURED_DATA` evidence;
- unauthorized-access criterion requires an authorization expectation or safety constraint.

Invalid formal datasets are not silently skipped.

---

## 13. Gold Isolation

`evals/gold_isolation.py` was extended so the complete Phase-1 Gold surface is forbidden recursively inside runtime payloads.

New explicit blocked keys include:

```text
expected_behavior
task_success_contract
gold_evidence
gold_facts
safety_constraints
```

Tests verify both:

1. constructing a `RuntimeCaseInput` with any of these fields nested in runtime metadata fails;
2. serializing a canonical sample contains the Gold fields, while `sample.to_runtime_input().runtime_packet()` contains none of them.

The Phase-0 adapter still rejects an `EvaluationSample` object directly and accepts only `RuntimeCaseInput`.

---

## 14. Legacy Migration

### 14.1 v7.3 benchmark migration

Migration is implemented in `eval_platform/migration.py` and intentionally conservative.

Actual v7.3 results:

| Source | Total | Fully migrated | Partial | Needs review | Retired |
|---|---:|---:|---:|---:|---:|
| `dev_v7_3.json` | 368 | **34** | **334** | 0 | 0 |
| `validation_v7_3.json` | 119 | **5** | **114** | 0 | 0 |
| `blind_test_inputs_v7_3.json` | 125 | **0** | 0 | **125** | 0 |

Total fully canonical legacy cases:

```text
39
```

The dominant reasons for partial migration are real semantic gaps rather than parser failures:

- 317 dev + 100 validation rows belong to old component/layer diagnostics and do not have a case-dependent E2E behavior/success contract;
- 126 dev + 41 validation rows lack reliable atomic Gold facts/evidence;
- 17 dev + 14 validation candidate E2E rows use legacy `identity_verified=true`, which is not accepted by the real Production Support Graph;
- all 125 historical blind inputs have no local Gold.

No missing field is invented.

### 14.2 Other legacy Evaluation assets

Phase 1 also scanned `evals/baseline_dataset.json`, `evals/tracemind/*.csv`, and the annotation pipeline.

Per-source-row status is preserved in:

```text
phase1_non_v73_migration_status.jsonl
```

Asset roles are recorded in:

```text
phase1_legacy_asset_inventory.json
```

Source rows requiring review outside v7.3:

```text
679
```

These include the old baseline, TraceMind multi-turn sets, public question inputs, and annotation template. Their `expected_source` / `required_keywords` fields are not sufficient to create canonical GoldEvidence/GoldFact automatically.

`evals/tracemind/submission_example.csv` contains 400 prediction/output example rows, not Gold; those source rows are marked `RETIRED` as dataset migration inputs rather than pretending they are benchmark cases.

Across v7.3 + non-v7.3 legacy source files:

```text
1252 source rows require review
```

This number is a **source-row count, not a de-duplicated unique-task count**; several historical TraceMind files overlap by construction.

The existing `evals/annotation_pipeline/` is kept as future curation/review infrastructure. No checked-in human-reviewed annotation output was found there, so Phase 1 does not claim that migrated Gold is human reviewed.

---

## 15. Dataset Inventory / Counts

### 15.1 Fully migrated legacy development canonical set

```text
34 cases
SHA-256: f385879cebe6583f8d4f52224155ed6259e9a83471a522cdb2f9fe8c6aa6b7d4
Trust: DEVELOPMENT
Annotation: MIGRATED_LEGACY
```

Category distribution:

```text
KNOWLEDGE_QA                  20
TROUBLESHOOTING                2
MIXED_KNOWLEDGE_STRUCTURED    10
SAFETY_GOVERNANCE              2
PRIVATE_BUSINESS_QUERY         0
```

### 15.2 Fully migrated legacy validation canonical set

```text
5 cases
SHA-256: bcbfc46557af73fd3c4956101f1fb25b5ce1fe39659966c8971ad499c6f3c022
Trust: VALIDATION
Annotation: MIGRATED_LEGACY
```

Category distribution:

```text
KNOWLEDGE_QA       4
SAFETY_GOVERNANCE  1
```

### 15.3 Representative schema seed set

The separate seed asset contains exactly **15 source-grounded schema cases**, all explicitly `NEEDS_REVIEW` and `SCHEMA_VALIDATION_ONLY`:

```text
KNOWLEDGE_QA                  4
TROUBLESHOOTING               2
PRIVATE_BUSINESS_QUERY        3
MIXED_KNOWLEDGE_STRUCTURED    2
SAFETY_GOVERNANCE             4
```

It covers:

```text
Knowledge FAQ
Knowledge exact spec
Region policy
Multi-document QA
Troubleshooting direct
Troubleshooting clarification
Order query
Ticket query
Warranty query
Mixed order + policy
Mixed product + warranty
Tenant isolation
User isolation
Unauthorized tool
Prompt injection
```

Seed hash (JSON and JSONL normalize to the same data):

```text
c1df7cb32c383ed11c95ae772fcabcd408a4f41fd450c7f4b740704da99da5de
```

These 15 cases are not added to the “39 fully migrated legacy” count and are not presented as a formal test set.

---

## 16. Cases Needing Review

Primary review debt is material and intentionally visible:

```text
v7.3 review/partial queue source rows: 573
non-v7.3 legacy source rows NEEDS_REVIEW: 679
----------------------------------------------
total source rows requiring review: 1252
```

Highest-priority review classes for Phase 1.5 / dataset curation are:

1. structured/private E2E rows using legacy `identity_verified=true`;
2. v7.3 E2E rows without atomic GoldFacts/GoldEvidence;
3. mixed Order/Warranty tasks that need verified production-compatible identity and explicit document + structured Gold;
4. historical multi-turn TraceMind rows whose expected source/keywords are only lexical proxies;
5. historical blind inputs, which require an independent Gold custody/review process before any trusted-test claim.

No queue item was silently dropped to improve migration percentage.

---

## 17. Tests

### 17.1 Phase-1 + Phase-0 Evaluation tests

```bash
PYTHONPATH=. pytest -q tests/evaluation
```

Final result after adding generated-asset regression tests:

```text
36 passed
```

The suite covers:

- canonical sample construction;
- single-sample type alias/no parallel schema;
- JSON and JSONL stable round-trip;
- schema version and enum validation;
- unknown-field fail-closed behavior;
- deterministic dataset SHA-256 independent of sample order;
- alternative evidence round-trip;
- handoff Gold expression;
- identity mappings cannot invent tenant/user principals;
- duplicate IDs;
- invalid category/subcategory;
- required/forbidden conflicts;
- missing private identity;
- invalid mixed evidence;
- missing GoldEvidence support;
- clarification without slots;
- empty TaskSuccessContract;
- Phase-1 Gold isolation;
- conservative legacy migration counts;
- required_keywords not promoted;
- historical blind remains unverified;
- generated canonical manifests and hashes;
- Phase-0 production adapter single execution;
- Phase-0 prediction/trace consistency;
- Phase-0 blind scoring guard.

### 17.2 Broader compatible regression suite

Final command:

```bash
PYTHONPATH=. pytest -q \
  tests/evaluation/ \
  tests/production/test_production_platform.py \
  tests/production/test_production_benchmark.py \
  tests/governance/test_memory_governance.py \
  tests/governance/test_memory_governance_benchmark.py \
  tests/artifact/test_artifact_benchmark.py \
  tests/context_engine/test_context_contract_hardening.py \
  tests/context_engine/test_memory_lifecycle_contract.py
```

Final result:

```text
74 passed in 1.37s
```

### 17.3 Compile check

```bash
python -m compileall -q .
```

Result:

```text
PASS
```

### 17.4 Environment note

The first bare `pytest` invocation in this container failed during collection because the checkout was not installed and the repository root was not on that invocation's Python module path. The actual reproducible repository test command therefore uses `PYTHONPATH=.`. This collection failure is not hidden or reported as a code PASS.

---

## 18. Actual Results

Phase-1 data-contract results are real repository outputs, not model-quality metrics:

```text
Canonical schema version:                1.0
Fully migrated legacy cases:             39
  dev:                                    34
  validation:                              5
  historical blind:                       0
Representative schema seeds:             15 (NEEDS_REVIEW, schema-only)
v7.3 partial/review source rows:         573
Other legacy NEEDS_REVIEW source rows:   679
Other retired submission source rows:    400
Total source rows needing review:       1252 (not de-duplicated)
Trusted test split:                       NONE
Formal E2E Task Success:                  NOT RUN by design
LLM Judge:                                NOT RUN by design
```

No migration percentage is presented as model quality.

---

## 19. Blocked / Not Run

### BLOCKED: real Production Support Graph import

Attempted:

```bash
PYTHONPATH=. python -c "import deployments.support_agent_graph"
```

Actual failure:

```text
ModuleNotFoundError: No module named 'langchain'
```

`pyproject.toml` declares `langchain>=1.3.10`, but the current container does not have the production dependency installed. This is the same class of environment limitation already documented in Phase 0.

Therefore:

```text
real Production Graph smoke          BLOCKED
real LLM / Milvus execution          NOT RUN
formal End-to-End Task Success       NOT RUN
formal LLM-as-Judge                  NOT RUN
Agentic Recovery benchmark           NOT RUN
Context Quality-Cost experiment      NOT RUN
Ablation                             NOT RUN
```

No Mock result is substituted for these items.

---

## 20. Phase 2 Stable Contracts

Phase 2 evaluators may directly depend on:

```text
eval_platform.contracts.CANONICAL_SCHEMA_VERSION
DatasetSplit
TaskCategory
Difficulty
ResponseType
SuccessCriterion
EvidenceSourceType
FactValueType
ComparisonMode
SplitTrustLevel
AnnotationStatus
MigrationStatus
IdentitySpec
ExpectedBehavior
TaskSuccessContract
ConditionalSuccessCriterion
GoldEvidence
GoldFact
SafetyConstraint
DatasetManifest
DatasetValidationResult

eval_platform.dataset.EvaluationSample
CanonicalEvaluationSample  # exact alias of EvaluationSample
RuntimeCaseInput
RuntimeMessage
canonical_dataset_hash
read_canonical_dataset
write_canonical_dataset
build_dataset_manifest

eval_platform.validation.validate_dataset

eval_platform.production_adapter.ProductionEvaluationAdapter
TraceAdapter
PredictionRecord
CaseJudgment
```

The Phase-2 evaluation boundary is frozen as:

```text
CanonicalEvaluationSample
  |-- RuntimeCaseInput -> ONE Production execution -> PredictionRecord
  `-- hidden Gold -----------------------------------+
                                                      |
PredictionRecord + Gold ------------------------------+
  -> Deterministic Evaluators / versioned LLM Judge
  -> per-criterion judgments
  -> conjunction of required criteria
  -> binary End-to-End Task Success PASS / FAIL
```

### Phase-2 entry checklist

- [x] Canonical Sample Schema frozen at v1.0.
- [x] Runtime Input and Gold are type-separated.
- [x] All five primary task categories are supported.
- [x] Mixed Knowledge + Structured is first-class.
- [x] TaskSuccessContract is strongly typed and non-weighted.
- [x] GoldEvidence supports document + structured + multi-evidence.
- [x] GoldEvidence supports explicit alternative groups.
- [x] GoldFact is not keyword coverage.
- [x] Clarification Gold can be expressed.
- [x] Handoff Gold can be expressed.
- [x] Safety Gold can be expressed.
- [x] Dataset Validator is fail closed by default.
- [x] Split Trust is explicit and filename-independent.
- [x] Legacy migration report and review queues are generated.
- [x] Historical blind was not upgraded to trusted test.
- [x] Phase-0 single-execution Evaluation tests continue to pass.
- [ ] Real deployment graph integration rerun in this environment: **BLOCKED by missing `langchain` dependency**.

The Evaluation data-contract interfaces are stable enough for Phase 2 implementation, but Phase 1 remains conservatively marked **PARTIAL** until the real deployment import/integration regression can be rerun in a production-capable environment.
